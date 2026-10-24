import uuid
from datetime import datetime

from sqlalchemy import BigInteger, FetchedValue, ForeignKey, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

TZ = TIMESTAMP(timezone=True)


class Document(Base):
    __tablename__ = "document"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=FetchedValue())
    sha256: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_relpath: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    text_content: Mapped[str | None] = mapped_column(Text, deferred=True)
    text_status: Mapped[str] = mapped_column(Text, default="none")
    source: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(TZ, server_default=FetchedValue())
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=FetchedValue())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=FetchedValue(), server_onupdate=FetchedValue())


class DocumentLink(Base):
    __tablename__ = "document_link"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=FetchedValue())
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.document.id"))
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default="attachment")
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=FetchedValue())
