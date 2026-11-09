import uuid
from typing import Any

from sqlalchemy import Boolean, Computed, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.parties.models import Timestamps, _id


class ProductCategory(Timestamps, Base):
    __tablename__ = "product_category"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.product_category.id"))
    name_fa: Mapped[str | None] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")


class Product(Timestamps, Base):
    __tablename__ = "product"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str | None] = mapped_column(Text)     # v0.9.0: the record's code (codes module)
    name_fa: Mapped[str | None] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    name_norm: Mapped[str] = mapped_column(Text, Computed("x", persisted=True))
    kind_note: Mapped[str | None] = mapped_column(Text)
    default_unit_code: Mapped[str | None] = mapped_column(Text)
    hs_code: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    # v0.9.0: noun-modifier description (section 7)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    canonical_fa: Mapped[str | None] = mapped_column(Text)
    canonical_en: Mapped[str | None] = mapped_column(Text)
    canonical_override: Mapped[bool] = mapped_column(Boolean, default=False)


class ProductTemplate(Timestamps, Base):
    """v0.9.0: noun-modifier template (a noun and ordered attributes)."""
    __tablename__ = "product_template"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    key: Mapped[str] = mapped_column(Text)
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    noun_fa: Mapped[str] = mapped_column(Text)
    noun_en: Mapped[str] = mapped_column(Text)
    attributes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(Text, default="active")
    seeded: Mapped[bool] = mapped_column(Boolean, default=False)


class ProductAlias(Timestamps, Base):
    __tablename__ = "product_alias"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.product.id"))
    alias: Mapped[str] = mapped_column(Text)
    alias_norm: Mapped[str] = mapped_column(Text, Computed("x", persisted=True))
