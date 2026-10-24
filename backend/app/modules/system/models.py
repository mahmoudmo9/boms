import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, FetchedValue, Integer, Numeric, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

TZ = TIMESTAMP(timezone=True)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=FetchedValue())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=FetchedValue(), server_onupdate=FetchedValue())


class AppUser(Timestamps, Base):
    __tablename__ = "app_user"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=FetchedValue())
    username: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, server_default=FetchedValue())
    calendar: Mapped[str] = mapped_column(Text, server_default=FetchedValue())
    digits: Mapped[str] = mapped_column(Text, server_default=FetchedValue())
    theme: Mapped[str] = mapped_column(Text, server_default=FetchedValue())
    idle_lock_minutes: Mapped[int] = mapped_column(Integer, server_default=FetchedValue())


class Setting(Timestamps, Base):
    __tablename__ = "setting"
    __table_args__ = {"schema": "sys"}

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)


class Country(Timestamps, Base):
    __tablename__ = "country"
    __table_args__ = {"schema": "sys"}

    iso2: Mapped[str] = mapped_column(Text, primary_key=True)
    iso3: Mapped[str] = mapped_column(Text)
    name_fa: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)


class Currency(Timestamps, Base):
    __tablename__ = "currency"
    __table_args__ = {"schema": "sys"}

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_fa: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str] = mapped_column(Text)
    symbol: Mapped[str | None] = mapped_column(Text)
    minor_units: Mapped[int | None] = mapped_column(SmallInteger)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Unit(Timestamps, Base):
    __tablename__ = "unit"
    __table_args__ = {"schema": "sys"}

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_fa: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    base_factor: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Job(Timestamps, Base):
    __tablename__ = "job"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=FetchedValue())
    type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(Text, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_after: Mapped[datetime] = mapped_column(TZ, server_default=FetchedValue())
    locked_at: Mapped[datetime | None] = mapped_column(TZ)
    last_error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)


class BackupRun(Timestamps, Base):
    __tablename__ = "backup_run"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=FetchedValue())
    kind: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TZ, server_default=FetchedValue())
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    status: Mapped[str] = mapped_column(Text, default="running")
    db_dump_path: Mapped[str | None] = mapped_column(Text)
    db_dump_sha256: Mapped[str | None] = mapped_column(Text)
    db_dump_bytes: Mapped[int | None] = mapped_column(BigInteger)
    files_copied: Mapped[int | None] = mapped_column(Integer)
    files_bytes: Mapped[int | None] = mapped_column(BigInteger)
    secondary_status: Mapped[str | None] = mapped_column(Text)
    restore_test_at: Mapped[datetime | None] = mapped_column(TZ)
    restore_test_status: Mapped[str | None] = mapped_column(Text)
    restore_test_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
