"""Database engine, session factory and declarative base."""

from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache

from sqlalchemy import URL, DateTime, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_config
from app.core.secrets import get_secret


class Base(DeclarativeBase):
    # Every datetime column is timestamptz; naive datetimes are never used.
    type_annotation_map = {datetime: DateTime(timezone=True)}


def app_db_url(dbname: str | None = None) -> URL:
    cfg = get_config()
    return URL.create(
        "postgresql+psycopg",
        username=cfg.db_user,
        password=get_secret("db_password"),
        host=cfg.db_host,
        port=cfg.db_port,
        database=dbname or cfg.db_name,
    )


@lru_cache
def get_engine() -> Engine:
    return create_engine(app_db_url(), pool_pre_ping=True, pool_size=5, max_overflow=5)


@lru_cache
def _sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def new_session() -> Session:
    return _sessionmaker()()


def get_db() -> Iterator[Session]:
    """FastAPI dependency. Routes commit explicitly; anything uncommitted is rolled back."""
    db = new_session()
    try:
        yield db
    finally:
        db.close()
