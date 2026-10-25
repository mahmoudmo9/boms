"""Application configuration.

Non-secret configuration comes from environment variables (set by the
Windows start scripts or by the developer). Secrets come from ``core.secrets``.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.secrets import get_secret

VERSION = "0.2.1"


@dataclass(frozen=True)
class Config:
    data_dir: Path
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    http_port: int
    pg_bin_dir: str | None

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.http_port}", f"localhost:{self.http_port}"}

    def db_url(self, database: str | None = None) -> str:
        from sqlalchemy import URL

        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=get_secret("db_password"),
            host=self.db_host,
            port=self.db_port,
            database=database or self.db_name,
        ).render_as_string(hide_password=False)


def _default_data_dir() -> Path:
    if os.name == "nt":
        return Path("D:/BOMS-Data") if Path("D:/").exists() else Path("C:/BOMS-Data")
    return Path(__file__).resolve().parents[3] / "dev-data"


@lru_cache
def get_config() -> Config:
    env = os.environ
    return Config(
        data_dir=Path(env.get("BOMS_DATA_DIR") or _default_data_dir()),
        db_host=env.get("BOMS_DB_HOST", "127.0.0.1"),
        db_port=int(env.get("BOMS_DB_PORT", "5432")),
        db_name=env.get("BOMS_DB_NAME", "boms"),
        db_user=env.get("BOMS_DB_USER", "boms"),
        http_port=int(env.get("BOMS_HTTP_PORT", "8765")),
        pg_bin_dir=env.get("BOMS_PG_BIN") or None,
    )
