"""Build the offline Windows release zip.

    python scripts/build_release.py            # needs Python 3.12, Node.js/npm and internet (build machine only)

Steps:
1. build the frontend into backend/app/static (npm ci + npm run build)
2. download every wheel in backend/requirements.lock for win_amd64 / CPython 3.12 into wheelhouse/
   and verify the dependency closure for Windows
3. assemble dist/boms-<version>/ (backend, scripts, wheelhouse, docs, VERSION) and zip it

The user's PC never needs internet, Node.js or a compiler: install.ps1 installs from the wheelhouse.
"""

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
SCRIPT_FILES = ["common.ps1", "install.ps1", "update.ps1", "backup.ps1", "restore.ps1", "start.ps1", "stop.ps1",
                "install.bat", "update.bat", "backup.bat", "restore.bat", "start.bat", "stop.bat"]
BACKEND_EXCLUDE = {"tests", "__pycache__", ".pytest_cache", "boms.egg-info"}


def run(cmd: list[str], cwd: Path) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True, shell=sys.platform == "win32")


def version() -> str:
    text = (ROOT / "backend" / "app" / "core" / "config.py").read_text(encoding="utf-8")
    return re.search(r'^VERSION = "([^"]+)"', text, re.M).group(1)


def build_frontend() -> None:
    run(["npm", "ci", "--no-audit", "--no-fund"], ROOT / "frontend")
    run(["npm", "run", "test"], ROOT / "frontend")
    run(["npm", "run", "lint"], ROOT / "frontend")
    run(["npm", "run", "build"], ROOT / "frontend")
    if not (ROOT / "backend" / "app" / "static" / "index.html").exists():
        sys.exit("frontend build did not produce backend/app/static/index.html")


def download_wheels(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "-m", "pip", "download", "--quiet", "--only-binary=:all:", "--no-deps",
         "--platform", "win_amd64", "--python-version", "3.12", "--implementation", "cp", "--abi", "cp312",
         "-r", str(ROOT / "backend" / "requirements.lock"), "-d", str(target)], ROOT)
    pins = [line.split("==")[0] for line in (ROOT / "backend" / "requirements.lock").read_text().splitlines()
            if line and not line.startswith("#")]
    wheels = [w.name.lower().replace("_", "-") for w in target.glob("*.whl")]
    missing = [p for p in pins if not any(w.startswith(p.lower().replace("_", "-").replace(".", "-") + "-")
                                          or w.startswith(p.lower().replace("_", "-") + "-") for w in wheels)]
    if missing:
        sys.exit(f"wheels missing for: {missing}")
    print(f"wheelhouse: {len(wheels)} wheels")


def verify_closure(wheelhouse: Path) -> None:
    """Every Requires-Dist of every wheel (evaluated for Windows) must be satisfied inside the wheelhouse."""
    from email.parser import Parser

    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name, parse_wheel_filename

    sys.path.insert(0, str(ROOT / "scripts"))
    from lock_windows import marker_ok

    available = {}
    requires = {}
    for wheel in wheelhouse.glob("*.whl"):
        name, ver, _, _ = parse_wheel_filename(wheel.name)
        available[name] = ver
        with zipfile.ZipFile(wheel) as zf:
            meta = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
            requires[name] = Parser().parsestr(zf.read(meta).decode()).get_all("Requires-Dist") or []
    problems = []
    for name, reqs in requires.items():
        for raw in reqs:
            req = Requirement(raw)
            extras = {"binary"} if name == "psycopg" else set()
            if not marker_ok(req.marker, extras):
                continue
            have = available.get(canonicalize_name(req.name))
            if have is None or not req.specifier.contains(have, prereleases=True):
                problems.append(f"{name} needs {raw} (wheelhouse has {have})")
    if problems:
        sys.exit("wheelhouse incomplete:\n  " + "\n  ".join(problems))
    print(f"wheelhouse closure verified for Windows ({len(available)} packages)")


def assemble(ver: str, skip_wheels: bool) -> Path:
    out = DIST / f"boms-{ver}"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "backend", out / "backend",
                    ignore=lambda d, names: [n for n in names if n in BACKEND_EXCLUDE or n.endswith(".pyc")])
    (out / "scripts").mkdir()
    for name in SCRIPT_FILES:
        shutil.copy2(ROOT / "scripts" / name, out / "scripts" / name)
    shutil.copytree(ROOT / "docs", out / "docs")
    (out / "VERSION").write_text(ver + "\n", encoding="ascii")
    shutil.copy2(ROOT / "docs" / "README.md", out / "README.md")
    if skip_wheels:
        (out / "wheelhouse").mkdir()
    else:
        wheelhouse = ROOT / "wheelhouse"
        for old in wheelhouse.glob("*.whl"):
            old.unlink()
        download_wheels(wheelhouse)
        verify_closure(wheelhouse)
        shutil.copytree(wheelhouse, out / "wheelhouse", ignore=shutil.ignore_patterns("README.md", ".gitignore"))
    return out


def make_zip(folder: Path) -> Path:
    archive = folder.with_name(folder.name + "-win64.zip")
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            zf.write(path, Path(folder.name) / path.relative_to(folder))
    return archive


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-frontend", action="store_true", help="use the existing backend/app/static build")
    parser.add_argument("--skip-wheels", action="store_true", help="for testing the layout only")
    args = parser.parse_args()
    ver = version()
    if not args.skip_frontend:
        build_frontend()
    folder = assemble(ver, args.skip_wheels)
    archive = make_zip(folder)
    print(f"release: {archive} ({archive.stat().st_size // 1024 // 1024} MB)")


if __name__ == "__main__":
    main()
