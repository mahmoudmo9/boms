import json
import os
import random
import shutil
import stat
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.core.config import get_config
from app.core.db import new_session, reset_engine
from app.modules.system import backup
from app.modules.system.models import BackupRun
from app.worker import runner
from app.worker.registry import load_handlers
from tests.conftest import TEST_DB, make_pdf, superuser_conninfo, unique_bytes, upload


# ---- retention ---------------------------------------------------------------

def _stamps(days: int, per_day: int = 1, start=datetime(2026, 10, 24, 12, 0, tzinfo=UTC)):
    return [start - timedelta(days=d, hours=h) for d in range(days) for h in range(per_day)]


def test_retention_7_daily_4_weekly_12_monthly():
    stamps = _stamps(500, per_day=2)
    keep = backup.select_retained(stamps)
    newest = max(stamps)
    local = [s.astimezone() for s in keep]
    days = sorted({s.date() for s in local}, reverse=True)
    assert newest in keep
    # one dump per kept day (the newest of that day)
    assert len(local) == len({s.date() for s in local})
    # the 7 most recent days are all kept
    all_days = sorted({s.astimezone().date() for s in stamps}, reverse=True)
    assert all_days[:7] == days[:7]
    weeks = {s.isocalendar()[:2] for s in local}
    months = {(s.year, s.month) for s in local}
    all_weeks = sorted({s.astimezone().isocalendar()[:2] for s in stamps}, reverse=True)
    all_months = sorted({(s.astimezone().year, s.astimezone().month) for s in stamps}, reverse=True)
    assert set(all_weeks[:4]) <= weeks
    assert set(all_months[:12]) <= months
    assert len(keep) <= 7 + 4 + 12
    for stamp in keep:
        same_day = [s for s in stamps if s.astimezone().date() == stamp.astimezone().date()]
        assert stamp == max(same_day)


def test_retention_few_dumps_keeps_all():
    stamps = _stamps(3)
    assert backup.select_retained(stamps) == set(stamps)


def test_apply_retention_deletes_files_but_never_protected(tmp_path):
    names = []
    for stamp in _stamps(60):
        name = f"boms_{stamp:%Y%m%dT%H%M%S}000Z_nightly.dump"
        (tmp_path / name).write_bytes(b"x")
        backup.manifest_path(tmp_path / name).write_text("{}")
        names.append(name)
    oldest = names[-1]
    deleted = backup.apply_retention(tmp_path, protected={oldest})
    remaining = sorted(p.name for p in tmp_path.glob("*.dump"))
    assert oldest in remaining
    assert len(remaining) == 60 - len(deleted)
    assert all(not backup.manifest_path(tmp_path / d).exists() for d in deleted)
    assert len(remaining) <= 7 + 4 + 12 + 1


# ---- full backup / restore-test cycle ---------------------------------------

@pytest.fixture(scope="module")
def uploaded(request):
    from fastapi.testclient import TestClient  # noqa: F401

    from app.main import app
    from tests.conftest import TEST_PASSWORD, ApiClient

    load_handlers()
    with ApiClient(app, base_url="http://127.0.0.1:8765") as client:
        client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD})
        docs = [upload(client, f"cycle-{i}.txt", unique_bytes(f"cycle {i}")).json() for i in range(5)]
        docs.append(upload(client, "cycle.pdf", make_pdf(f"backup cycle {os.urandom(4).hex()}")).json())
        runner.run_until_idle(backoff_base=0)
        yield client, docs


def _backup_dir() -> Path:
    return get_config().backups_dir


def test_backup_then_restore_test_passes(uploaded):
    run_id = backup.run_backup("manual", source="script")
    with new_session() as db:
        run = db.get(BackupRun, run_id)
        assert run.status == "succeeded", run.details
        dump = Path(run.db_dump_path)
        assert dump.exists() and dump.parent == _backup_dir() / "db"
        assert backup.sha256_file(dump) == run.db_dump_sha256 and run.db_dump_bytes == dump.stat().st_size
        assert run.secondary_status == "disabled"
        manifest = json.loads(backup.manifest_path(dump).read_text())
        assert manifest["row_counts"]["core.document"] >= 6
        assert manifest["row_counts"]["sys.country"] >= 249
        live_docs = db.execute(text("SELECT sha256 FROM core.document")).scalars().all()
    for sha in live_docs:
        assert (_backup_dir() / "files" / sha[:2] / sha[2:4] / sha).exists()

    result = backup.restore_test(source="script")
    assert result["status"] == "passed", result
    assert result["details"]["files_sampled"] == min(20, len(live_docs))
    assert result["details"]["tables_checked"] >= 11
    with new_session() as db:
        run = db.get(BackupRun, run_id)
        assert run.restore_test_status == "passed" and run.restore_test_at is not None
        assert db.execute(text("SELECT count(*) FROM pg_database WHERE datname = :n"),
                          {"n": backup.restore_db_name()}).scalar() == 0
        actions = db.execute(text("SELECT action FROM core.event WHERE entity_id = :i ORDER BY id"),
                             {"i": str(run_id)}).scalars().all()
    assert actions == ["start", "succeeded", "restore_test_passed"]


def test_second_backup_is_incremental(uploaded):
    backup.run_backup("manual", source="script")
    run_id = backup.run_backup("manual", source="script")
    with new_session() as db:
        assert db.get(BackupRun, run_id).files_copied == 0


def test_corrupted_backup_file_fails_restore_test(uploaded):
    _, docs = uploaded
    backup.run_backup("manual", source="script")
    sha = random.choice(docs)["sha256"]
    path = _backup_dir() / "files" / sha[:2] / sha[2:4] / sha
    original = path.read_bytes()
    path.chmod(stat.S_IWUSR | stat.S_IRUSR)
    path.write_bytes(original + b"corrupted")
    try:
        result = backup.restore_test(source="script")
        assert result["status"] == "failed"
        relpath = f"{sha[:2]}/{sha[2:4]}/{sha}"
        assert result["details"]["files_corrupted"] == [relpath]
        assert any(relpath in f for f in result["details"]["failures"])
    finally:
        path.write_bytes(original)
        path.chmod(stat.S_IRUSR)
    assert backup.restore_test(source="script")["status"] == "passed"


def test_missing_backup_file_fails_restore_test(uploaded):
    _, docs = uploaded
    backup.run_backup("manual", source="script")
    sha = docs[0]["sha256"]
    path = _backup_dir() / "files" / sha[:2] / sha[2:4] / sha
    moved = path.with_name("moved-away")
    path.rename(moved)
    try:
        result = backup.restore_test(source="script")
        assert result["status"] == "failed"
        assert result["details"]["files_missing"] == [f"{sha[:2]}/{sha[2:4]}/{sha}"]
    finally:
        moved.rename(path)


def test_corrupted_dump_fails_restore_test(uploaded):
    run_id = backup.run_backup("manual", source="script")
    with new_session() as db:
        dump = Path(db.get(BackupRun, run_id).db_dump_path)
    original = dump.read_bytes()
    dump.write_bytes(original[:-10] + b"0123456789")
    try:
        result = backup.restore_test(source="script")
        assert result["status"] == "failed"
        assert any("dump checksum mismatch" in f for f in result["details"]["failures"])
    finally:
        dump.write_bytes(original)


def test_secondary_unavailable_is_skipped_and_available_is_mirrored(uploaded):
    client, docs = uploaded
    client.patch("/api/settings", json={"backup.secondary_path": "/nonexistent/usb-drive"})
    try:
        run_id = backup.run_backup("manual", source="script")
        with new_session() as db:
            run = db.get(BackupRun, run_id)
            assert run.status == "succeeded"
            assert run.secondary_status == "skipped"
            assert "not available" in run.details["secondary_reason"]

        target = Path(tempfile.mkdtemp(prefix="boms_test_secondary_"))
        client.patch("/api/settings", json={"backup.secondary_path": str(target)})
        run_id = backup.run_backup("manual", source="script")
        with new_session() as db:
            run = db.get(BackupRun, run_id)
            assert run.secondary_status == "ok"
            dump_name = Path(run.db_dump_path).name
        assert (target / "db" / dump_name).exists()
        assert backup.manifest_path(target / "db" / dump_name).exists()
        for d in docs:
            assert (target / "files" / d["sha256"][:2] / d["sha256"][2:4] / d["sha256"]).exists()
    finally:
        client.patch("/api/settings", json={"backup.secondary_path": None})


def test_encrypted_archive(uploaded, monkeypatch):
    import pyzipper

    client, _ = uploaded
    archive_dir = Path(tempfile.mkdtemp(prefix="boms_test_archive_"))
    client.patch("/api/settings", json={"backup.archive_enabled": True, "backup.archive_path": str(archive_dir)})
    try:
        run_id = backup.run_backup("manual", source="script")
        with new_session() as db:
            assert db.get(BackupRun, run_id).details["archive"]["status"] == "skipped"  # no password yet

        monkeypatch.setenv("BOMS_ARCHIVE_PASSWORD", "archive-test-password")
        run_id = backup.run_backup("manual", source="script")
        with new_session() as db:
            run = db.get(BackupRun, run_id)
        archive = Path(run.details["archive"]["path"])
        assert archive.exists()
        with pyzipper.AESZipFile(archive) as zf:
            names = zf.namelist()
            assert Path(run.db_dump_path).name in names and "files-manifest.json" in names
            info = zf.getinfo(Path(run.db_dump_path).name)
            assert info.flag_bits & 0x1  # encrypted
            aes = info.extra[info.extra.index(b"\x01\x99"):]
            assert aes[6:8] == b"AE" and aes[8] == 3  # WinZip AES, strength 3 = AES-256
            with pytest.raises(RuntimeError):
                zf.read("files-manifest.json")
            zf.setpassword(b"archive-test-password")
            assert zf.read(Path(run.db_dump_path).name) == Path(run.db_dump_path).read_bytes()
    finally:
        client.patch("/api/settings", json={"backup.archive_enabled": False, "backup.archive_path": None})


def test_failed_dump_records_failure(uploaded, monkeypatch):
    monkeypatch.setattr(backup, "pg_tool", lambda name: "/nonexistent/pg_dump")
    with pytest.raises(Exception):
        backup.run_backup("manual", source="script")
    with new_session() as db:
        run = db.scalar(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(1))
        assert run.status == "failed" and run.details["error"]
        # the most recent successful dump is still on disk
        good = db.scalar(select(BackupRun).where(BackupRun.status == "succeeded")
                         .order_by(BackupRun.started_at.desc()).limit(1))
        assert Path(good.db_dump_path).exists()


def test_backup_and_restore_test_via_api_and_worker(uploaded):
    client, _ = uploaded
    r = client.post("/api/system/backups")
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    runner.run_until_idle(backoff_base=0)
    job = client.get(f"/api/system/jobs/{job_id}").json()
    assert job["status"] == "done", job
    assert client.post("/api/system/restore-test", json={}).status_code == 202
    runner.run_until_idle(backoff_base=0)
    history = client.get("/api/system/backups").json()
    assert history["items"][0]["status"] == "succeeded"
    assert history["items"][0]["restore_test_status"] == "passed"
    health = client.get("/api/system/health").json()
    assert health["last_successful_backup"]["id"] == history["items"][0]["id"]
    assert health["last_restore_test"]["restore_test_status"] == "passed"
    assert health["disk"]["free_bytes"] > 0
    assert set(health["jobs"]) == {"queued", "running", "done", "failed"}
    assert health["worker"]["alive"] is False


def test_heartbeat(client):
    from app.modules.system import health

    health.write_heartbeat()
    body = client.get("/api/system/health").json()
    assert body["worker"]["alive"] is True and body["worker"]["last_seen"]


# ---- disaster recovery restore -----------------------------------------------

def test_full_restore_onto_clean_target(uploaded, monkeypatch):
    from app.core import dbadmin

    run_id = backup.run_backup("manual", source="script")
    with new_session() as db:
        dump = Path(db.get(BackupRun, run_id).db_dump_path)
    source_backup_dir = _backup_dir()
    target_data = Path(tempfile.mkdtemp(prefix="boms_test_restore_target_"))
    target_db = f"{TEST_DB}_fullrestore"
    dbadmin.drop_database(superuser_conninfo(), target_db)

    monkeypatch.setenv("BOMS_DB_NAME", target_db)
    monkeypatch.setenv("BOMS_DATA_DIR", str(target_data))
    reset_engine()
    try:
        result = backup.full_restore(superuser_conninfo(), source_backup_dir, dump)
        assert result["ok"], result
        assert result["documents"] >= 6 and result["files_copied"] >= 6
        with pytest.raises(backup.AppError):
            backup.full_restore(superuser_conninfo(), source_backup_dir, dump)  # refuses to overwrite
    finally:
        monkeypatch.undo()
        reset_engine()
        dbadmin.drop_database(superuser_conninfo(), target_db)
        shutil.rmtree(target_data, ignore_errors=True)
