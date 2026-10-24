"""Logging to the console and to ``<data>/logs/<name>.log`` (rotated)."""

import logging
import logging.handlers

from app.core.config import get_config

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(name: str) -> None:
    root = logging.getLogger()
    if getattr(root, "_boms_configured", False):
        return
    root.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(console)
    logs_dir = get_config().logs_dir
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            logs_dir / f"{name}.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(handler)
    except OSError:
        root.warning("cannot write log files to %s", logs_dir)
    root._boms_configured = True  # type: ignore[attr-defined]
