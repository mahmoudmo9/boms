"""Schema ``ext`` (migration 0010): listings fetched from Setad, the owner's screening decisions, fetch runs and the
Setad agent's status row. Machine rows (listing, detail, file, change) are written only through this module's
store/service; the connector package never writes tables."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Computed, ForeignKey, Integer, Numeric, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.parties.models import TZ, Timestamps, _id

AMOUNT = Numeric(20, 4)


class HarvestRun(Timestamps, Base):
    __tablename__ = "harvest_run"
    __table_args__ = {"schema": "ext"}

    id: Mapped[uuid.UUID] = _id()
    source: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    status: Mapped[str] = mapped_column(Text, default="running")
    reported_count: Mapped[int | None] = mapped_column(Integer)
    pages_total: Mapped[int | None] = mapped_column(Integer)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    rows_seen: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str] = mapped_column(Text, default="")
    issues: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Listing(Timestamps, Base):
    __tablename__ = "listing"
    __table_args__ = {"schema": "ext"}

    id: Mapped[uuid.UUID] = _id()
    source: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(Text)
    external_no: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    organization: Mapped[str] = mapped_column(Text, default="")
    province: Mapped[str] = mapped_column(Text, default="")
    city: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(Text, default="")
    goods_group: Mapped[str] = mapped_column(Text, default="")
    service_group: Mapped[str] = mapped_column(Text, default="")
    type_name: Mapped[str] = mapped_column(Text, default="")
    need_type: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(TZ)
    documents_deadline: Mapped[datetime | None] = mapped_column(TZ)
    proposal_deadline: Mapped[datetime | None] = mapped_column(TZ)
    inquiry_deadline: Mapped[datetime | None] = mapped_column(TZ)
    opening_at: Mapped[datetime | None] = mapped_column(TZ)
    edition_date: Mapped[datetime | None] = mapped_column(TZ)
    edition_no: Mapped[str] = mapped_column(Text, default="")
    response_deadline: Mapped[datetime | None] = mapped_column(TZ)
    deadline_exact: Mapped[bool] = mapped_column(Boolean, default=False)
    price_valid_until: Mapped[datetime | None] = mapped_column(TZ)
    document_price: Mapped[Decimal | None] = mapped_column(AMOUNT)
    guarantee_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    estimate: Mapped[Decimal | None] = mapped_column(AMOUNT)
    guarantee_currency: Mapped[str | None] = mapped_column(Text)      # v0.6.0 (0011): as the site writes it
    guarantee_description: Mapped[str | None] = mapped_column(Text)
    estimate_currency: Mapped[str | None] = mapped_column(Text)
    renewal_appendix_count: Mapped[int | None] = mapped_column(Integer)   # v0.6.0 (0012)
    price_appendix_count: Mapped[int | None] = mapped_column(Integer)
    cancel_appendix_count: Mapped[int | None] = mapped_column(Integer)
    site_state: Mapped[str] = mapped_column(Text, default="")
    site_state_name: Mapped[str] = mapped_column(Text, default="")
    in_my_calls: Mapped[bool] = mapped_column(Boolean, default=False)
    detail_url: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    content_hash: Mapped[str] = mapped_column(Text, default="")
    search_norm: Mapped[str] = mapped_column(Text, Computed(
        "core.normalize_fa(external_no || ' ' || title || ' ' || organization || ' ' || description)", persisted=True))
    first_seen: Mapped[datetime] = mapped_column(TZ)
    last_seen: Mapped[datetime] = mapped_column(TZ)
    first_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("ext.harvest_run.id"))
    last_full_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("ext.harvest_run.id"))


class ListingChange(Base):
    __tablename__ = "listing_change"
    __table_args__ = {"schema": "ext"}

    id: Mapped[uuid.UUID] = _id()
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ext.listing.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    field: Mapped[str] = mapped_column(Text)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(TZ)


class ListingDetail(Timestamps, Base):
    __tablename__ = "listing_detail"
    __table_args__ = {"schema": "ext"}

    listing_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ext.listing.id"), primary_key=True)
    fields: Mapped[list] = mapped_column(JSONB, default=list)
    buyer_note: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    text: Mapped[str] = mapped_column(Text, default="")
    info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(TZ)


class ListingFile(Timestamps, Base):
    __tablename__ = "listing_file"
    __table_args__ = {"schema": "ext"}

    id: Mapped[uuid.UUID] = _id()
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ext.listing.id"))
    group_key: Mapped[str] = mapped_column(Text, default="")
    group_title: Mapped[str] = mapped_column(Text, default="")
    appendix_id: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    extension: Mapped[str] = mapped_column(Text, default="")
    size: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(Text, default="pending")
    local_path: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    reported_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ListingScreening(Timestamps, Base):
    __tablename__ = "listing_screening"
    __table_args__ = {"schema": "ext"}

    listing_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ext.listing.id"), primary_key=True)
    status: Mapped[str] = mapped_column(Text, default="new")
    dismiss_reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    checklist: Mapped[list] = mapped_column(JSONB, default=list)
    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    starred_at: Mapped[datetime | None] = mapped_column(TZ)
    converted_at: Mapped[datetime | None] = mapped_column(TZ)


class AgentStatus(Timestamps, Base):
    __tablename__ = "agent_status"
    __table_args__ = {"schema": "ext"}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    pid: Mapped[int | None] = mapped_column(Integer)
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str | None] = mapped_column(Text)
    browser_channel: Mapped[str | None] = mapped_column(Text)
    command: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    pages_done: Mapped[int | None] = mapped_column(Integer)
    pages_total: Mapped[int | None] = mapped_column(Integer)
    rows_seen: Mapped[int | None] = mapped_column(Integer)
    captcha_waiting: Mapped[bool] = mapped_column(Boolean, default=False)
    captcha_message: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    recording: Mapped[bool] = mapped_column(Boolean, default=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(TZ)
    started_at: Mapped[datetime | None] = mapped_column(TZ)
    listing_id: Mapped[uuid.UUID | None] = mapped_column(UUID)   # v0.6.0: the listing the command works on now
    files_done: Mapped[int | None] = mapped_column(Integer)
    files_total: Mapped[int | None] = mapped_column(Integer)
