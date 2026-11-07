"""The task table (schema ``core``, migration 0014)."""
import uuid
from datetime import date, datetime

from sqlalchemy import Date, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.parties.models import TZ, Timestamps, _id


class Task(Timestamps, Base):
    __tablename__ = "task"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    title: Mapped[str] = mapped_column(Text)
    due_on: Mapped[date] = mapped_column(Date)
    due_at: Mapped[datetime | None] = mapped_column(TZ)
    status: Mapped[str] = mapped_column(Text, default="open")
    done_at: Mapped[datetime | None] = mapped_column(TZ)
    done_note: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text, default="normal")
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    party_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    source: Mapped[str] = mapped_column(Text, default="manual")
    source_kind: Mapped[str] = mapped_column(Text, default="manual")
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    remind_of_due: Mapped[date | None] = mapped_column(Date)
    remind_days_before: Mapped[int | None] = mapped_column(Integer)
    followup_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    notes: Mapped[str | None] = mapped_column(Text)
