# wheelhouse

Python wheels for **Windows x64 / CPython 3.12**, installed offline by `install.ps1` and `update.ps1`
(`pip install --no-index --find-links wheelhouse -r backend/requirements.lock`).

The wheels are not committed to git (about 30 MB of binaries). `python scripts/build_release.py`
downloads exactly the versions pinned in `backend/requirements.lock` into this folder, verifies that
every dependency (evaluated for Windows) is present, and copies them into the release zip.

To change dependencies: edit `backend/pyproject.toml`, install them into the dev venv, then run
`.venv/bin/python scripts/lock_windows.py` to regenerate `backend/requirements.lock`.
