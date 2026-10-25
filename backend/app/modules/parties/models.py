import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Computed, Date, FetchedValue, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

TZ = TIMESTAMP(timezone=True)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=FetchedValue())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=FetchedValue(), server_onupdate=FetchedValue())


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID, primary_key=True, server_default=FetchedValue())


class FunnelStage(Timestamps, Base):
    __tablename__ = "funnel_stage"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    role: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer)
    label_fa: Mapped[str] = mapped_column(Text)
    label_en: Mapped[str] = mapped_column(Text)
    is_terminal: Mapped[bool] = mapped_column(Boolean)


class Party(Timestamps, Base):
    __tablename__ = "party"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    name_fa: Mapped[str | None] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    name_norm: Mapped[str] = mapped_column(Text, Computed("x", persisted=True))
    kind: Mapped[str] = mapped_column(Text, default="company")
    country_iso2: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    do_not_contact_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    ref_company_id: Mapped[uuid.UUID | None] = mapped_column(UUID)


class PartyRole(Timestamps, Base):
    __tablename__ = "party_role"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.party.id"))
    role: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text)
    stage_changed_at: Mapped[datetime] = mapped_column(TZ, server_default=FetchedValue())


class Contact(Timestamps, Base):
    __tablename__ = "contact"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.party.id"))
    name_fa: Mapped[str | None] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    job_title: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")


class ContactMethod(Timestamps, Base):
    __tablename__ = "contact_method"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.contact.id"))
    type: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)
    value_norm: Mapped[str] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(Text, default="active")


class Interaction(Timestamps, Base):
    __tablename__ = "interaction"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.party.id"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.contact.id"))
    channel: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(TZ)
    subject: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    body_norm: Mapped[str | None] = mapped_column(Text, Computed("x", persisted=True), deferred=True)
    no_followup_reason: Mapped[str | None] = mapped_column(Text)


class Followup(Timestamps, Base):
    __tablename__ = "followup"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    interaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.interaction.id"))
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.party.id"))
    action: Mapped[str] = mapped_column(Text)
    due_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="open")
    done_at: Mapped[datetime | None] = mapped_column(TZ)
    done_note: Mapped[str | None] = mapped_column(Text)
