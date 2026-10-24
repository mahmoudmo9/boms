"""Database engine, session factory and ORM base."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_config


class Base(DeclarativeBase):
    metadata = MetaData()


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_config().db_url(),
        pool_pre_ping=True,
        connect_args={"application_name": "boms"},
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def new_session() -> Session:
    return get_sessionmaker()()


def get_db() -> Iterator[Session]:
    """FastAPI dependency. Routers commit explicitly after the service call."""
    db = new_session()
    try:
        yield db
    finally:
        db.close()


def reset_engine() -> None:
    """Drop cached engine/config (used by tests and CLI after env changes)."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    get_config.cache_clear()
