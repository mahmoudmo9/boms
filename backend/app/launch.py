"""Process launcher used by Windows Task Scheduler (runs under pythonw.exe, no console).

    pythonw.exe -m app.launch backend --config C:\\BOMS\\config.json
    pythonw.exe -m app.launch worker  --config C:\\BOMS\\config.json

Reads the non-secret install configuration, exports it as BOMS_* environment
variables, then starts Uvicorn (127.0.0.1 only) or the worker loop. Secrets are
read from Credential Manager by ``app.core.secrets``.
"""

import argparse
import json
import os
import sys
from pathlib import Path

CONFIG_KEYS = {
    "data_dir": "BOMS_DATA_DIR",
    "db_host": "BOMS_DB_HOST",
    "db_port": "BOMS_DB_PORT",
    "db_name": "BOMS_DB_NAME",
    "db_user": "BOMS_DB_USER",
    "http_port": "BOMS_HTTP_PORT",
    "pg_bin": "BOMS_PG_BIN",
}


def apply_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    for key, env in CONFIG_KEYS.items():
        if config.get(key) not in (None, ""):
            os.environ[env] = str(config[key])
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.launch")
    parser.add_argument("process", choices=["backend", "worker"])
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    apply_config(Path(args.config))

    # pythonw has no console: make sure stray prints cannot crash the process.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115

    if args.process == "worker":
        from app.worker.__main__ import main as worker_main

        return worker_main()

    import uvicorn

    from app.core.config import get_config
    from app.core.logs import setup_logging

    setup_logging("backend")
    uvicorn.run("app.main:app", host="127.0.0.1", port=get_config().http_port, log_config=None,
                proxy_headers=False, server_header=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
