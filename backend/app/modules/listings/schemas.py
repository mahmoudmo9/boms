"""Request models of the listings module (Setad screening). Every request body forbids unknown fields."""

import uuid
from typing import Annotated, Literal

from pydantic import Field

from app.core.schemas import InputModel

Source = Literal["setad_purchase", "setad_tender"]
Text300 = Annotated[str, Field(max_length=300)]


class ListingFilters(InputModel):
    source: Source = "setad_purchase"
    q: Annotated[str, Field(max_length=200)] | None = None
    organizations: list[Text300] = []
    provinces: list[Text300] = []
    categories: list[Text300] = []
    goods_group: Text300 | None = None
    status: Literal["new", "starred", "reviewing", "converted", "dismissed"] | None = None
    new_only: bool = False
    deadline: Literal["open", "within", "passed"] | None = None
    within_days: Annotated[int, Field(ge=1, le=365)] = 3
    downloaded: bool = False
    price: Literal["free", "paid"] | None = None
    my_calls: bool = False
    include_old: bool = False


class ListingQuery(ListingFilters):
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Literal[100, 200, 500, 1000] = 200
    sort: Literal["published", "deadline", "number", "title", "organization", "province", "category", "price",
                  "status", "first_seen"] = "deadline"
    dir: Literal["asc", "desc"] = "asc"


class ScreenIn(InputModel):
    action: Literal["star", "unstar", "reviewing", "dismiss", "restore", "note", "checklist"]
    reason: Annotated[str, Field(max_length=300)] | None = None
    note: Annotated[str, Field(max_length=4000)] | None = None
    checklist: list[bool] | None = None


class BulkIn(InputModel):
    """Ticked rows (`ids`) or every row of the current result (`filters`, "select all results")."""
    ids: list[uuid.UUID] | None = None
    filters: ListingFilters | None = None
    action: Literal["star", "unstar", "dismiss", "fetch_detail", "download_files", "export_csv"]
    reason: Annotated[str, Field(max_length=300)] | None = None


class CommandIn(InputModel):
    command: Literal["connect", "full_fetch", "quick_fetch", "fetch_detail", "download_files", "sync_my_calls",
                     "add_my_call", "remove_my_call", "open_payment_page", "set_role", "disconnect", "record_start",
                     "record_stop"]
    source: Source | None = None
    role: Literal["EPROC", "ETEND"] | None = None
    listing_id: uuid.UUID | None = None
    listing_ids: list[uuid.UUID] | None = None
    confirmed: bool | None = None


class ConvertIn(InputModel):
    """Convert to inquiry: the buyer (an existing party, the exact name match, or a new party) and, per item
    position, the product picked from the suggestions."""
    party_id: uuid.UUID | None = None
    create_party: bool = False
    party_name: Text300 | None = None
    confirm_duplicate: bool = False
    products: dict[int, uuid.UUID] = {}
    without_missing_files: bool = False
