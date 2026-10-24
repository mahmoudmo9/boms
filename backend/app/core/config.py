"""Non-secret runtime configuration.

Values are read, in increasing priority, from built-in defaults, the optional
file <app root>/boms.toml (section [boms], written by install.ps1) and BOMS_*
environment variables. Secrets never live here; see core.secrets.
"""

import os
import tomllib
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[3]  # repo root in dev, C:\BOMS\app when installed
VERSION = "0.1.0"


@dataclass(frozen=True)
class Config:
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "boms"
    db_user: str = "boms_app"
    data_dir: str = str(APP_ROOT / "dev-data")
    pg_bin: str = r"C:\Program Files\PostgreSQL\18\bin"
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    frontend_dist: str = str(APP_ROOT / "frontend" / "dist")

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def files_dir(self) -> Path:
        return self.data_path / "files"

    @property
    def backups_dir(self) -> Path:
        return self.data_path / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_path / "logs"

    @property
    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.http_port}", f"localhost:{self.http_port}"}

    @property
    def allowed_origins(self) -> set[str]:
        return {f"http://{h}" for h in self.allowed_hosts}

    def pg_tool(self, name: str) -> str:
        exe = Path(self.pg_bin) / (name + (".exe" if os.name == "nt" else ""))
        return str(exe) if exe.exists() else name


def _load() -> Config:
    values: dict[str, object] = {}
    toml_path = Path(os.environ.get("BOMS_CONFIG", APP_ROOT / "boms.toml"))
    if toml_path.is_file():
        with toml_path.open("rb") as fh:
            values.update(tomllib.load(fh).get("boms", {}))
    for f in fields(Config):
        env = os.environ.get("BOMS_" + f.name.upper())
        if env is not None:
            values[f.name] = int(env) if f.type is int or f.type == "int" else env
    return Config(**values)


@lru_cache
def get_config() -> Config:
    return _load()
