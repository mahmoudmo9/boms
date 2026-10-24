"""ORM models for the sys schema. Only the system module writes these tables."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import FetchedValue, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

UUID_PK = {"primary_key": True, "server_default": text("uuidv7()")}
NOW = {"server_default": text("now()")}
# updated_at is maintained by the core.touch_updated_at trigger; the ORM re-reads it after UPDATE.
TOUCHED = {"server_default": text("now()"), "server_onupdate": FetchedValue()}


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(**UUID_PK)
    username: Mapped[str]
    password_hash: Mapped[str]
    language: Mapped[str] = mapped_column(server_default="fa")
    calendar: Mapped[str] = mapped_column(server_default="jalali")
    digits: Mapped[str] = mapped_column(server_default="fa")
    theme: Mapped[str] = mapped_column(server_default="system")
    idle_lock_minutes: Mapped[int] = mapped_column(server_default="30")
    created_at: Mapped[datetime] = mapped_column(**NOW)
    updated_at: Mapped[datetime] = mapped_column(**TOUCHED)


class Setting(Base):
    __tablename__ = "setting"
    __table_args__ = {"schema": "sys"}

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[object] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(**TOUCHED)


class Country(Base):
    __tablename__ = "country"
    __table_args__ = {"schema": "sys"}

    iso2: Mapped[str] = mapped_column(String(2), primary_key=True)
    iso3: Mapped[str] = mapped_column(String(3))
    name_fa: Mapped[str]
    name_en: Mapped[str]
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(server_default="100")
    created_at: Mapped[datetime] = mapped_column(**NOW)
    updated_at: Mapped[datetime] = mapped_column(**TOUCHED)


class Currency(Base):
    __tablename__ = "currency"
    __table_args__ = {"schema": "sys"}

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name_fa: Mapped[str]
    name_en: Mapped[str]
    symbol: Mapped[str] = mapped_column(server_default="")
    minor_units: Mapped[int] = mapped_column(server_default="2")
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(**NOW)
    updated_at: Mapped[datetime] = mapped_column(**TOUCHED)


class Unit(Base):
    __tablename__ = "unit"
    __table_args__ = {"schema": "sys"}

    code: Mapped[str] = mapped_column(primary_key=True)
    name_fa: Mapped[str]
    name_en: Mapped[str]
    kind: Mapped[str]
    base_factor: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(**NOW)
    updated_at: Mapped[datetime] = mapped_column(**TOUCHED)


class Job(Base):
    __tablename__ = "job"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(**UUID_PK)
    type: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(server_default="queued")
    attempts: Mapped[int] = mapped_column(server_default="0")
    max_attempts: Mapped[int] = mapped_column(server_default="5")
    run_after: Mapped[datetime] = mapped_column(**NOW)
    locked_at: Mapped[datetime | None]
    last_error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(**NOW)
    updated_at: Mapped[datetime] = mapped_column(**TOUCHED)
    finished_at: Mapped[datetime | None]


class BackupRun(Base):
    __tablename__ = "backup_run"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(**UUID_PK)
    kind: Mapped[str]
    started_at: Mapped[datetime] = mapped_column(**NOW)
    finished_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(server_default="running")
    db_dump_path: Mapped[str | None]
    db_dump_sha256: Mapped[str | None]
    db_dump_bytes: Mapped[int | None]
    files_copied: Mapped[int | None]
    files_bytes: Mapped[int | None]
    secondary_status: Mapped[str | None]
    restore_test_at: Mapped[datetime | None]
    restore_test_status: Mapped[str | None]
    restore_test_details: Mapped[dict | None] = mapped_column(JSONB)
    details: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(**NOW)
    updated_at: Mapped[datetime] = mapped_column(**TOUCHED)
