"""File type detection: block executables/scripts, sniff common document types."""

import mimetypes
import zipfile
from pathlib import Path

BLOCKED_EXTENSIONS = {"exe", "dll", "bat", "cmd", "ps1", "js", "vbs", "msi", "scr", "com", "jar", "lnk", "hta"}

# Root-storage CLSID of Windows Installer (.msi) packages inside an OLE compound file.
MSI_CLSID = bytes.fromhex("84100c0000000000c000000000000046")
OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
LNK_MAGIC = bytes.fromhex("4c0000000114020000000000c000000000000046")

INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp"}

SNIFF = [
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]


def extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def blocked_reason(filename: str, path: Path) -> str | None:
    """Return why the file is rejected, or None if it is allowed."""
    ext = extension(filename)
    if ext in BLOCKED_EXTENSIONS:
        return f"extension .{ext}"
    with open(path, "rb") as fh:
        head = fh.read(64 * 1024)
    if head[:2] == b"MZ":
        return "Windows executable content"
    if head[:4] == b"\x7fELF":
        return "executable content"
    if head[:20] == LNK_MAGIC:
        return "Windows shortcut content"
    if head[:8] == OLE_MAGIC and _is_msi(path):
        return "Windows Installer content"
    if head[:2] == b"#!":
        return "script content"
    lowered = head[:4096].lower()
    if b"<hta:application" in lowered:
        return "HTML application content"
    if lowered.lstrip().startswith(b"@echo off"):
        return "batch script content"
    if head[:4] == b"PK\x03\x04" and _is_jar(path):
        return "Java archive content"
    return None


def _is_msi(path: Path) -> bool:
    with open(path, "rb") as fh:
        header = fh.read(512)
        if len(header) < 512:
            return False
        sector_size = 1 << int.from_bytes(header[30:32], "little")
        first_dir_sector = int.from_bytes(header[48:52], "little")
        fh.seek((first_dir_sector + 1) * sector_size)
        root_entry = fh.read(128)
    return len(root_entry) == 128 and root_entry[80:96] == MSI_CLSID


def _is_jar(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, OSError):
        return False
    return any(n.upper() == "META-INF/MANIFEST.MF" or n.endswith(".class") for n in names)


def detect_mime(filename: str, path: Path) -> str:
    with open(path, "rb") as fh:
        head = fh.read(16)
    for magic, mime in SNIFF:
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    guessed, _ = mimetypes.guess_type(filename, strict=False)
    if guessed in INLINE_TYPES:
        # extension claims a previewable type but the content does not match
        return "application/octet-stream"
    return guessed or "application/octet-stream"
