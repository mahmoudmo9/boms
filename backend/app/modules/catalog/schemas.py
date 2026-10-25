import uuid
from typing import Annotated

from pydantic import Field

from app.core.schemas import InputModel

Name = Annotated[str, Field(max_length=500)]
HsCode = Annotated[str, Field(pattern=r"^[0-9]{2,10}$")]
Code = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.\-]{1,40}$")]


class ProductCreate(InputModel):
    name_fa: Name | None = None
    name_en: Name | None = None
    kind_note: Name | None = None
    default_unit_code: Code | None = None
    hs_code: HsCode | None = None
    category_id: uuid.UUID | None = None
    notes: Annotated[str, Field(max_length=20000)] | None = None
    aliases: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=100)
    confirm_duplicate: bool = False


class ProductPatch(InputModel):
    name_fa: Name | None = None
    name_en: Name | None = None
    kind_note: Name | None = None
    default_unit_code: Code | None = None
    hs_code: HsCode | None = None
    category_id: uuid.UUID | None = None
    notes: Annotated[str, Field(max_length=20000)] | None = None


class AliasIn(InputModel):
    alias: Annotated[str, Field(min_length=1, max_length=300)]


class CategoryIn(InputModel):
    parent_id: uuid.UUID | None = None
    name_fa: Name | None = None
    name_en: Name | None = None
