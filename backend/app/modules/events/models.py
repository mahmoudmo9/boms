from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, FetchedValue, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Event(Base):
    __tablename__ = "event"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, server_default=FetchedValue())
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=FetchedValue())
    actor: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(Text)


class Audit(Base):
    """Written only by the core.audit_row() trigger; read-only for the app."""

    __tablename__ = "audit"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    table_name: Mapped[str] = mapped_column(Text)
    row_id: Mapped[str | None] = mapped_column(Text)
    op: Mapped[str] = mapped_column(String(1))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    changed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
