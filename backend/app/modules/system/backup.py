"""Backup, retention, restore test and full restore.

Layout under the data folder::

    backups/db/boms_<UTC stamp>_<kind>.dump            pg_dump -Fc
    backups/db/boms_<UTC stamp>_<kind>.manifest.json   checksums + row counts at dump time
    backups/files/<aa>/<bb>/<sha256>                   content-addressed mirror of files/
    backups/archive/boms_<...>.zip                     optional AES-256 archive

The row counts are taken inside the same snapshot that pg_dump uses
(``pg_export_snapshot`` + ``pg_dump --snapshot``), so the restore test can
compare them exactly.
"""

import json
import logging
import os
import random
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import VERSION, get_config
from app.core.db import get_engine, new_session
from app.core.errors import AppError
from app.core.files import copy_verified, iter_store, sha256_file, store_relpath
from app.core.secrets import get_secret
from app.core.time import utcnow
from app.modules.events import service as events
from app.modules.system import settings
from app.modules.system.models import BackupRun

log = logging.getLogger("boms.backup")

APP_SCHEMAS = ("sys", "ref", "core", "outreach", "tender", "ops", "fin", "compliance", "analytics")
DUMP_RE = re.compile(r"^boms_(\d{8}T\d{9}Z)_(nightly|manual|pre_update)\.dump$")
RESTORE_SAMPLE_SIZE = 20
KEEP_DAILY, KEEP_WEEKLY, KEEP_MONTHLY = 7, 4, 12


class BackupError(AppError):
    status = 500


# ---- helpers -----------------------------------------------------------------

def pg_tool(name: str) -> str:
    bin_dir = get_config().pg_bin_dir
    exe = name + (".exe" if os.name == "nt" else "")
    return str(Path(bin_dir) / exe) if bin_dir else name


def _pg_args(database: str) -> list[str]:
    config = get_config()
    return ["-h", config.db_host, "-p", str(config.db_port), "-U", config.db_user, "-d", database]


def _pg_env() -> dict[str, str]:
    return {**os.environ, "PGPASSWORD": get_secret("db_password"), "PGCONNECT_TIMEOUT": "10"}


def _run(cmd: list[str], what: str) -> None:
    proc = subprocess.run(cmd, env=_pg_env(), capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-2000:]
        raise BackupError(f"{what}_failed", f"{what} failed (exit {proc.returncode}): {tail}")


def stamp_of(name: str) -> datetime | None:
    match = DUMP_RE.match(name)
    if not match:
        return None
    raw = match.group(1)
    return datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(microsecond=int(raw[15:18]) * 1000, tzinfo=UTC)


def _new_dump_name(kind: str) -> str:
    now = utcnow()
    return f"boms_{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{kind}.dump"


def manifest_path(dump: Path) -> Path:
    return dump.with_name(dump.name.removesuffix(".dump") + ".manifest.json")


def table_counts(conn) -> dict[str, int]:
    tables = conn.execute(
        text("SELECT schemaname || '.' || tablename FROM pg_tables WHERE schemaname = ANY(:s) ORDER BY 1"),
        {"s": list(APP_SCHEMAS)},
    ).scalars().all()
    return {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}


def mirror_files(src: Path, dst: Path) -> dict:
    """Copy content-addressed files missing from ``dst``. Returns counts and problems."""
    copied, copied_bytes, problems = 0, 0, []
    for sha, path in iter_store(src):
        target = dst / store_relpath(sha)
        if target.exists():
            continue
        try:
            size = copy_verified(path, target, sha)
        except ValueError:
            problems.append(f"checksum mismatch in source: {store_relpath(sha)}")
            continue
        copied += 1
        copied_bytes += size
    return {"copied": copied, "bytes": copied_bytes, "problems": problems}


def select_retained(stamps: list[datetime], daily: int = KEEP_DAILY, weekly: int = KEEP_WEEKLY,
                    monthly: int = KEEP_MONTHLY) -> set[datetime]:
    """Newest dump of each of the last ``daily`` days, ``weekly`` ISO weeks and ``monthly`` months.

    Buckets are in local time. The newest dump is always kept.
    """
    ordered = sorted(stamps, reverse=True)
    keep: set[datetime] = set(ordered[:1])
    for bucket, limit in (
        (lambda t: t.astimezone().date(), daily),
        (lambda t: t.astimezone().isocalendar()[:2], weekly),
        (lambda t: (t.astimezone().year, t.astimezone().month), monthly),
    ):
        seen = set()
        for stamp in ordered:
            key = bucket(stamp)
            if key in seen:
                continue
            if len(seen) == limit:
                break
            seen.add(key)
            keep.add(stamp)
    return keep


def apply_retention(db_dir: Path, protected: set[str]) -> list[str]:
    """Delete dumps (and manifests) outside the retention set. ``protected`` names are never deleted."""
    dumps = {stamp_of(p.name): p for p in db_dir.glob("boms_*.dump") if stamp_of(p.name)}
    keep = select_retained(list(dumps))
    deleted = []
    for stamp, path in dumps.items():
        if stamp in keep or path.name in protected:
            continue
        path.unlink(missing_ok=True)
        manifest_path(path).unlink(missing_ok=True)
        deleted.append(path.name)
    return sorted(deleted)


def _latest_successful_dump(db: Session) -> str | None:
    path = db.scalar(
        select(BackupRun.db_dump_path).where(BackupRun.status == "succeeded")
        .order_by(BackupRun.started_at.desc()).limit(1)
    )
    return Path(path).name if path else None


# ---- backup ------------------------------------------------------------------

def run_backup(kind: str = "manual", source: str = "worker", actor: str | None = None) -> uuid.UUID:
    if kind not in ("nightly", "manual", "pre_update"):
        raise ValueError(f"invalid backup kind {kind}")
    with new_session() as db:
        run = BackupRun(kind=kind, details={})
        db.add(run)
        db.flush()
        events.record(db, "backup_run", run.id, "start", {"kind": kind}, source, actor=actor)
        db.commit()
        run_id = run.id
    try:
        _do_backup(run_id, kind, source, actor)
    except Exception as exc:
        log.exception("backup %s failed", run_id)
        message = exc.message if isinstance(exc, AppError) else f"{type(exc).__name__}: {exc}"
        with new_session() as db:
            run = db.get(BackupRun, run_id)
            run.status = "failed"
            run.finished_at = utcnow()
            run.details = {**run.details, "error": message}
            events.record(db, "backup_run", run_id, "failed", {"kind": kind, "error": message}, source, actor=actor)
            db.commit()
        raise
    return run_id


def _do_backup(run_id: uuid.UUID, kind: str, source: str, actor: str | None) -> None:
    config = get_config()
    db_dir = config.backups_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    dump = db_dir / _new_dump_name(kind)
    partial = dump.with_name(dump.name + ".partial")

    # 1. dump + row counts from one snapshot
    with get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            snapshot = conn.execute(text("SELECT pg_export_snapshot()")).scalar()
            counts = table_counts(conn)
            revision = conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar()
            try:
                _run([pg_tool("pg_dump"), "-Fc", *_pg_args(config.db_name), "--snapshot", snapshot,
                      "-f", str(partial)], "pg_dump")
            except Exception:
                partial.unlink(missing_ok=True)
                raise
    partial.replace(dump)
    dump_sha = sha256_file(dump)
    dump_bytes = dump.stat().st_size

    manifest = {
        "format": 1,
        "dump": dump.name,
        "sha256": dump_sha,
        "bytes": dump_bytes,
        "kind": kind,
        "created_at": utcnow().isoformat(),
        "app_version": VERSION,
        "alembic_revision": revision,
        "row_counts": counts,
    }
    manifest_path(dump).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # 2. mirror files
    mirror = mirror_files(config.files_dir, config.backups_dir / "files")
    details: dict = {"files_problems": mirror["problems"]}

    with new_session() as db:
        run = db.get(BackupRun, run_id)
        run.db_dump_path = str(dump)
        run.db_dump_sha256 = dump_sha
        run.db_dump_bytes = dump_bytes
        run.files_copied = mirror["copied"]
        run.files_bytes = mirror["bytes"]
        db.commit()
        previous_success = _latest_successful_dump(db)
        secondary_path = settings.get(db, "backup.secondary_path")
        archive_enabled = settings.get(db, "backup.archive_enabled")
        archive_dir = settings.get(db, "backup.archive_path")

    protected = {dump.name} | ({previous_success} if previous_success else set())

    # 3. secondary destination
    secondary_status, secondary_reason = _secondary(secondary_path, dump, protected)
    details["secondary_reason"] = secondary_reason

    # 4. encrypted archive
    if archive_enabled:
        details["archive"] = _archive(Path(archive_dir) if archive_dir else config.backups_dir / "archive", dump)
    else:
        details["archive"] = {"status": "disabled"}

    # 5. retention
    details["retention_deleted"] = apply_retention(db_dir, protected)
    if details["archive"].get("status") == "ok":
        _prune_archives(Path(details["archive"]["path"]).parent, db_dir)

    with new_session() as db:
        run = db.get(BackupRun, run_id)
        run.secondary_status = secondary_status
        run.status = "succeeded"
        run.finished_at = utcnow()
        run.details = details
        events.record(db, "backup_run", run_id, "succeeded", {
            "kind": kind, "dump": dump.name, "bytes": dump_bytes, "files_copied": mirror["copied"],
            "secondary_status": secondary_status, "archive": details["archive"].get("status"),
            "retention_deleted": len(details["retention_deleted"]),
        }, source, actor=actor)
        db.commit()


def _secondary(path: str | None, dump: Path, protected: set[str]) -> tuple[str, str | None]:
    if not path:
        return "disabled", None
    root = Path(path)
    if not root.is_dir():
        return "skipped", f"destination not available: {path}"
    try:
        (root / "db").mkdir(exist_ok=True)
        sha = sha256_file(dump)
        copy_verified(dump, root / "db" / dump.name, sha)
        shutil.copyfile(manifest_path(dump), manifest_path(root / "db" / dump.name))
        mirror = mirror_files(get_config().files_dir, root / "files")
        apply_retention(root / "db", protected)
    except OSError as exc:
        return "failed", f"{type(exc).__name__}: {exc}"
    if mirror["problems"]:
        return "failed", "; ".join(mirror["problems"][:5])
    return "ok", None


def _archive(dest: Path, dump: Path) -> dict:
    import pyzipper

    password = get_secret("archive_password", required=False)
    if not password:
        return {"status": "skipped", "reason": "archive password not set"}
    try:
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / (dump.name.removesuffix(".dump") + ".zip")
        partial = target.with_name(target.name + ".partial")
        files = [{"sha256": sha, "path": store_relpath(sha), "bytes": p.stat().st_size}
                 for sha, p in iter_store(get_config().backups_dir / "files")]
        with pyzipper.AESZipFile(partial, "w", compression=pyzipper.ZIP_STORED) as zf:
            zf.setpassword(password.encode())
            zf.setencryption(pyzipper.WZ_AES, nbits=256)
            zf.write(dump, dump.name)
            zf.write(manifest_path(dump), manifest_path(dump).name)
            zf.writestr("files-manifest.json", json.dumps(files, indent=1))
        partial.replace(target)
    except OSError as exc:
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
    return {"status": "ok", "path": str(target)}


def _prune_archives(archive_dir: Path, db_dir: Path) -> None:
    kept = {p.name.removesuffix(".dump") for p in db_dir.glob("boms_*.dump")}
    for zip_path in archive_dir.glob("boms_*.zip"):
        if zip_path.name.removesuffix(".zip") not in kept:
            zip_path.unlink(missing_ok=True)


# ---- restore test ------------------------------------------------------------

def restore_db_name() -> str:
    return f"{get_config().db_name}_restore_test"


def _admin_engine():
    """App-role connection in autocommit mode, for CREATE/DROP DATABASE."""
    return get_engine().execution_options(isolation_level="AUTOCOMMIT")


def _pick_run(db: Session, run_id: uuid.UUID | None) -> BackupRun:
    if run_id:
        run = db.get(BackupRun, run_id)
        if run is None or run.status != "succeeded":
            raise AppError("no_backup", "Backup run not found or not successful", status=404)
        return run
    for run in db.scalars(select(BackupRun).where(BackupRun.status == "succeeded")
                          .order_by(BackupRun.started_at.desc())):
        if run.db_dump_path and Path(run.db_dump_path).exists():
            return run
    raise AppError("no_backup", "No successful backup with a dump file exists", status=404)


def restore_test(run_id: uuid.UUID | None = None, source: str = "worker", actor: str | None = None) -> dict:
    config = get_config()
    with new_session() as db:
        run = _pick_run(db, run_id)
        run_id, dump, expected_sha = run.id, Path(run.db_dump_path), run.db_dump_sha256

    failures: list[str] = []
    details: dict = {"dump": dump.name}
    temp_db = restore_db_name()

    if sha256_file(dump) != expected_sha:
        failures.append(f"dump checksum mismatch: {dump.name}")
    try:
        manifest = json.loads(manifest_path(dump).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        manifest = None
        failures.append(f"manifest unreadable: {exc}")

    if not failures:
        with _admin_engine().connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{temp_db}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{temp_db}" TEMPLATE template0 ENCODING \'UTF8\''))
        try:
            _run([pg_tool("pg_restore"), *_pg_args(temp_db), "--exit-on-error", "--no-owner", str(dump)],
                 "pg_restore")
            engine = create_engine(config.db_url(temp_db))
            try:
                with engine.connect() as conn:
                    restored = table_counts(conn)
                    shas = conn.execute(text("SELECT sha256 FROM core.document")).scalars().all() \
                        if "core.document" in restored else []
            finally:
                engine.dispose()

            mismatched = {t: {"expected": n, "restored": restored.get(t)}
                          for t, n in manifest["row_counts"].items() if restored.get(t) != n}
            if mismatched:
                failures.append("row counts differ: " + ", ".join(sorted(mismatched)))
            details["tables_checked"] = len(manifest["row_counts"])
            details["row_count_mismatches"] = mismatched

            files_dir = config.backups_dir / "files"
            missing = [store_relpath(s) for s in shas if not (files_dir / store_relpath(s)).exists()]
            present = [s for s in shas if (files_dir / store_relpath(s)).exists()]
            sample = random.sample(present, min(RESTORE_SAMPLE_SIZE, len(present)))
            corrupted = [store_relpath(s) for s in sample if sha256_file(files_dir / store_relpath(s)) != s]
            if missing:
                failures.append("files missing from backup: " + ", ".join(missing[:20]))
            if corrupted:
                failures.append("files with wrong checksum: " + ", ".join(corrupted))
            details.update(documents=len(shas), files_missing=missing, files_sampled=len(sample),
                           files_corrupted=corrupted)
        except AppError as exc:
            failures.append(exc.message)
        finally:
            with _admin_engine().connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{temp_db}" WITH (FORCE)'))

    status = "failed" if failures else "passed"
    details["failures"] = failures
    with new_session() as db:
        run = db.get(BackupRun, run_id)
        run.restore_test_at = utcnow()
        run.restore_test_status = status
        run.restore_test_details = details
        events.record(db, "backup_run", run_id, f"restore_test_{status}",
                      {"dump": dump.name, "failures": failures}, source, actor=actor)
        db.commit()
    return {"backup_run_id": str(run_id), "status": status, "details": details}


# ---- full restore (disaster recovery, used by restore.ps1) -------------------

def latest_dump(backup_dir: Path) -> Path:
    dumps = sorted((p for p in (backup_dir / "db").glob("boms_*.dump") if stamp_of(p.name)),
                   key=lambda p: stamp_of(p.name))
    if not dumps:
        raise AppError("no_backup", f"No dump found in {backup_dir / 'db'}")
    return dumps[-1]


def full_restore(superuser: dict, backup_dir: Path, dump: Path | None = None) -> dict:
    """Recreate role + database from a backup folder and copy files into the data folder.

    The target database must not exist yet (clean PC).
    """
    from app.core import dbadmin

    config = get_config()
    dump = dump or latest_dump(backup_dir)
    manifest = json.loads(manifest_path(dump).read_text(encoding="utf-8"))
    if sha256_file(dump) != manifest["sha256"]:
        raise AppError("dump_corrupt", f"Checksum mismatch for {dump.name}")
    if dbadmin.database_exists(superuser, config.db_name):
        raise AppError("database_exists", f"Database {config.db_name} already exists; refusing to overwrite")

    dbadmin.ensure_role(superuser, config.db_user, get_secret("db_password"))
    # pg_restore (as the app role) creates the trusted extensions itself, so it owns them
    dbadmin.create_database(superuser, config.db_name, config.db_user, extensions=False)
    _run([pg_tool("pg_restore"), *_pg_args(config.db_name), "--exit-on-error", "--no-owner", str(dump)],
         "pg_restore")

    copied = mirror_files(backup_dir / "files", config.files_dir)
    engine = create_engine(config.db_url())
    try:
        with engine.connect() as conn:
            restored = table_counts(conn)
            shas = conn.execute(text("SELECT sha256 FROM core.document")).scalars().all()
    finally:
        engine.dispose()
    bad = [store_relpath(s) for s in shas
           if not (config.files_dir / store_relpath(s)).exists()
           or sha256_file(config.files_dir / store_relpath(s)) != s]
    mismatched = sorted(t for t, n in manifest["row_counts"].items() if restored.get(t) != n)
    return {
        "dump": dump.name,
        "tables": len(restored),
        "row_count_mismatches": mismatched,
        "documents": len(shas),
        "files_copied": copied["copied"],
        "files_problems": copied["problems"] + [f"missing or corrupt: {b}" for b in bad],
        "ok": not mismatched and not bad and not copied["problems"],
    }
