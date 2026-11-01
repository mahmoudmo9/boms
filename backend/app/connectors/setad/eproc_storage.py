"""Safe local file handling, audit manifests, and exports.

Ported from SetadSuite v0.9.23 inquiries/storage.py (only the import path changed)."""
from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .eproc_parser import Need


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name or name.upper().split(".")[0] in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))
    }:
        name = "attachment_" + name
    return name[:180] or "attachment"


def need_folder(root: Path, need_no: str) -> Path:
    if not re.fullmatch(r"[0-9]{6,25}", need_no):
        raise ValueError("شماره نیاز نامعتبر است.")
    dest = root / need_no
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def manifest_path(folder: Path) -> Path:
    return folder / ".download_manifest.json"


def load_manifest(folder: Path) -> dict:
    path = manifest_path(folder)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def info_path(folder: Path) -> Path:
    return folder / ".download_info.json"


def record_attachment_total(folder: Path, total: int) -> None:
    """v0.9.19: how many attachments the site listed when we downloaded — so «complete / partial» needs no site later."""
    try:
        info_path(folder).write_text(json.dumps({"attachment_total": int(total),
                                                 "at_utc": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    except OSError:
        pass


def recorded_attachment_total(folder: Path):
    try:
        data = json.loads(info_path(folder).read_text(encoding="utf-8"))
        total = data.get("attachment_total") if isinstance(data, dict) else None
        return int(total) if isinstance(total, int) and total > 0 else None
    except (OSError, ValueError):
        return None


def is_downloaded(folder: Path, manifest: dict, file_id: str) -> bool:
    entry = manifest.get(file_id, {})
    if not isinstance(entry, dict):
        return False
    f = entry.get("saved_as", "")
    return bool(f and (folder / f).is_file() and (folder / f).stat().st_size > 0)


def target_path(folder: Path, name: str, file_id: str) -> Path:
    clean = safe_filename(name)
    path = folder / clean
    if path.exists():
        stem, ext = path.stem, path.suffix
        path = folder / f"{stem}__{file_id}{ext}"
    return path


def validate_download(path: Path) -> None:
    """Block obvious HTML/WAF or empty responses incorrectly delivered as attachments."""
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError("فایل خالی است")
    with path.open("rb") as f:
        sample = f.read(1024).lstrip().lower()
    if sample.startswith((b"<!doctype html", b"<html", b"<script", b"<head", b"<body")):
        raise ValueError("به‌جای فایل، پاسخ HTML یا امنیتی دریافت شد")


def record_download(folder: Path, manifest: dict, file_id: str, original_name: str, saved_as: str) -> None:
    manifest[file_id] = {
        "original_name": original_name,
        "saved_as": saved_as,
        "size": (folder / saved_as).stat().st_size,
        "saved_at_utc": datetime.now(timezone.utc).isoformat()
    }
    path = manifest_path(folder)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


FIELDS = (
    ("need_no", "شماره نیاز"), ("request_id", "شناسه داخلی"),
    ("description", "شرح کامل نیاز"), ("organization", "دستگاه خریدار"),
    ("province", "استان"), ("need_type", "نوع نیاز"), ("category", "طبقه‌بندی"),
    ("goods_group", "گروه کالا"), ("service_group", "گروه خدمت"),
    ("published_date", "تاریخ اعلام"), ("response_deadline", "مهلت پاسخ"),
    ("detail_url", "آدرس جزئیات")
)


def export_csv(rows: list[Need], location: Path) -> None:
    with location.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([label for _, label in FIELDS])
        for need in rows:
            values = [getattr(need, key) for key, _ in FIELDS]
            # Descriptions are untrusted spreadsheet inputs. Prevent CSV formula
            # execution when the file is opened by Excel or another viewer.
            safe_values = ["'" + v if str(v).lstrip().startswith(("=", "+", "-", "@")) else v for v in values]
            writer.writerow(safe_values)
