"""Content-addressed file store helpers: ``<root>/<aa>/<bb>/<sha256>``, read-only after write."""

import hashlib
import os
import re
import stat
from collections.abc import Iterator
from pathlib import Path

CHUNK = 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def store_relpath(sha256: str) -> str:
    return f"{sha256[:2]}/{sha256[2:4]}/{sha256}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def make_read_only(path: Path) -> None:
    os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def iter_store(root: Path) -> Iterator[tuple[str, Path]]:
    if not root.is_dir():
        return
    for first in sorted(root.iterdir()):
        if not first.is_dir() or len(first.name) != 2:
            continue
        for second in sorted(first.iterdir()):
            if not second.is_dir():
                continue
            for path in sorted(second.iterdir()):
                if SHA_RE.match(path.name) and path.name[:2] == first.name and path.name[2:4] == second.name:
                    yield path.name, path


def copy_verified(src: Path, dst: Path, expected_sha256: str) -> int:
    """Copy ``src`` to ``dst`` while hashing; raise ValueError if the hash is not ``expected_sha256``."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    partial = dst.with_name(dst.name + ".partial")
    digest = hashlib.sha256()
    size = 0
    with open(src, "rb") as fin, open(partial, "wb") as fout:
        while chunk := fin.read(CHUNK):
            digest.update(chunk)
            fout.write(chunk)
            size += len(chunk)
    if digest.hexdigest() != expected_sha256:
        partial.unlink(missing_ok=True)
        raise ValueError(f"checksum mismatch for {src}")
    if dst.exists():
        partial.unlink()
    else:
        partial.replace(dst)
        make_read_only(dst)
    return size
