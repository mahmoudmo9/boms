"""Tables of the reference module (schema ``ref``, migration 0017)."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, Boolean, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.parties.models import TZ, Timestamps, _id


class Location(Timestamps, Base):
    __tablename__ = "location"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = _id()
    country_iso2: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    unlocode: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    name_ascii: Mapped[str] = mapped_column(Text)
    name_fa: Mapped[str | None] = mapped_column(Text)
    subdivision: Mapped[str | None] = mapped_column(Text)
    functions: Mapped[str | None] = mapped_column(Text)
    is_port: Mapped[bool] = mapped_column(Boolean, default=False)
    is_rail: Mapped[bool] = mapped_column(Boolean, default=False)
    is_road: Mapped[bool] = mapped_column(Boolean, default=False)
    is_airport: Mapped[bool] = mapped_column(Boolean, default=False)
    is_postal: Mapped[bool] = mapped_column(Boolean, default=False)
    is_multimodal: Mapped[bool] = mapped_column(Boolean, default=False)
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_border: Mapped[bool] = mapped_column(Boolean, default=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    iata: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(Text)
    release: Mapped[str | None] = mapped_column(Text)


class Airport(Timestamps, Base):
    __tablename__ = "airport"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = _id()
    iata: Mapped[str] = mapped_column(Text)
    icao: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    name_fa: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    country_iso2: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(Text)
    location_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(Text)
    release: Mapped[str | None] = mapped_column(Text)


class LegalForm(Timestamps, Base):
    __tablename__ = "legal_form"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str] = mapped_column(Text)
    elf_code: Mapped[str | None] = mapped_column(Text)
    country_iso2: Mapped[str] = mapped_column(Text)
    local_name: Mapped[str] = mapped_column(Text)
    transliterated: Mapped[str | None] = mapped_column(Text)
    name_fa: Mapped[str | None] = mapped_column(Text)
    abbreviations: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    curated: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(Text)
    release: Mapped[str | None] = mapped_column(Text)


class ContainerType(Timestamps, Base):
    __tablename__ = "container_type"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str] = mapped_column(Text)
    description_en: Mapped[str] = mapped_column(Text)
    description_fa: Mapped[str] = mapped_column(Text)
    length_ft: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    teu: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(Text)
    release: Mapped[str | None] = mapped_column(Text)


class TransportMode(Timestamps, Base):
    __tablename__ = "transport_mode"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str] = mapped_column(Text)
    name_fa: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(Text)
    release: Mapped[str | None] = mapped_column(Text)


class Incoterm(Timestamps, Base):
    __tablename__ = "incoterm"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str] = mapped_column(Text)
    name_fa: Mapped[str] = mapped_column(Text)
    any_mode: Mapped[bool] = mapped_column(Boolean)
    version: Mapped[str] = mapped_column(Text, default="2020")
    position: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(Text)
    release: Mapped[str | None] = mapped_column(Text)


class DatasetImport(Timestamps, Base):
    __tablename__ = "dataset_import"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = _id()
    dataset: Mapped[str] = mapped_column(Text)
    release: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str | None] = mapped_column(Text)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)
    imported_at: Mapped[datetime] = mapped_column(TZ)
