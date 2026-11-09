"""Tables of the AI module (schema ``ai``, migration 0020)."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, Boolean, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.parties.models import TZ, Timestamps, _id

S = {"schema": "ai"}


class Provider(Timestamps, Base):
    __tablename__ = "provider"
    __table_args__ = S

    id: Mapped[uuid.UUID] = _id()
    kind: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    models: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    secret_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="unknown")
    status_detail: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(TZ)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer)


class Price(Timestamps, Base):
    __tablename__ = "price"
    __table_args__ = S

    id: Mapped[uuid.UUID] = _id()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID)
    model: Mapped[str] = mapped_column(Text)
    input_per_mtok: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    output_per_mtok: Mapped[Decimal] = mapped_column(Numeric(12, 4))


class Route(Timestamps, Base):
    __tablename__ = "route"
    __table_args__ = S

    id: Mapped[uuid.UUID] = _id()
    task: Mapped[str] = mapped_column(Text)
    primary_provider_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    primary_model: Mapped[str | None] = mapped_column(Text)
    fallback_provider_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    fallback_model: Mapped[str | None] = mapped_column(Text)
    privacy: Mapped[str] = mapped_column(Text, default="cloud_redacted")


class Call(Timestamps, Base):
    __tablename__ = "call"
    __table_args__ = S

    id: Mapped[uuid.UUID] = _id()
    task: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    provider_kind: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    redactions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    privacy: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    subscription: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    fallback_of_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID)


class Draft(Timestamps, Base):
    __tablename__ = "draft"
    __table_args__ = S

    id: Mapped[uuid.UUID] = _id()
    task: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    sources: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    checks: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(Text, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    created_by_call_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    committed_at: Mapped[datetime | None] = mapped_column(TZ)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class DraftField(Timestamps, Base):
    __tablename__ = "draft_field"
    __table_args__ = S

    id: Mapped[uuid.UUID] = _id()
    draft_id: Mapped[uuid.UUID] = mapped_column(UUID)
    position: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    proposed: Mapped[Any] = mapped_column(JSONB)
    confidence: Mapped[str] = mapped_column(Text, default="medium")
    source: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    decision: Mapped[str | None] = mapped_column(Text)
    final: Mapped[Any] = mapped_column(JSONB)


class Correction(Timestamps, Base):
    __tablename__ = "correction"
    __table_args__ = S

    id: Mapped[uuid.UUID] = _id()
    task: Mapped[str] = mapped_column(Text)
    draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    field: Mapped[str] = mapped_column(Text)
    proposed: Mapped[Any] = mapped_column(JSONB)
    final: Mapped[Any] = mapped_column(JSONB)
    context: Mapped[str | None] = mapped_column(Text)


class CaseSetting(Timestamps, Base):
    __tablename__ = "case_setting"
    __table_args__ = S

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    local_only: Mapped[bool] = mapped_column(Boolean, default=False)
