"""core.event and core.audit (append-only; rows are only ever inserted)."""

from datetime import datetime

from sqlalchemy import BigInteger, Identity, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Event(Base):
    __tablename__ = "event"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    actor: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[str]
    action: Mapped[str]
    data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    source: Mapped[str]


class Audit(Base):
    __tablename__ = "audit"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    table_name: Mapped[str]
    row_id: Mapped[str | None]
    op: Mapped[str] = mapped_column(String(1))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    changed_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
