"""Request and response models of the parties module. Every request body forbids unknown fields."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.core.schemas import ApiModel, InputModel

Role = Literal["buyer", "supplier", "forwarder", "customs_broker", "agent", "other"]
Kind = Literal["company", "person"]
MethodType = Literal["whatsapp", "phone", "email", "telegram", "other"]
Channel = Literal["whatsapp", "call", "email", "tender_portal", "in_person", "other"]
Direction = Literal["in", "out"]

Name = Annotated[str, Field(max_length=300)]
ShortText = Annotated[str, Field(max_length=500)]
LongText = Annotated[str, Field(max_length=20000)]
Body = Annotated[str, Field(max_length=200000)]
Code = Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")]
Iso2 = Annotated[str, Field(pattern=r"^[A-Za-z]{2}$")]


def _blank_to_none(value: str | None) -> str | None:
    return value.strip() or None if isinstance(value, str) else value


class _Names(InputModel):
    @model_validator(mode="after")
    def _clean_names(self):
        for field in ("name_fa", "name_en"):
            if field in self.model_fields_set:
                setattr(self, field, _blank_to_none(getattr(self, field)))
        return self


# ---- parties ---------------------------------------------------------------------

class PartyCreate(_Names):
    name_fa: Name | None = None
    name_en: Name | None = None
    kind: Kind = "company"
    country_iso2: Iso2 | None = None
    website: ShortText | None = None
    notes: LongText | None = None
    roles: list[Role] = Field(default_factory=list, max_length=6)
    confirm_duplicate: bool = False

    @model_validator(mode="after")
    def _need_name(self):
        if not (self.name_fa or self.name_en):
            raise ValueError("name_fa or name_en is required")
        return self


class PartyPatch(_Names):
    name_fa: Name | None = None
    name_en: Name | None = None
    kind: Kind | None = None
    country_iso2: Iso2 | None = None
    website: ShortText | None = None
    notes: LongText | None = None
    do_not_contact: bool | None = None
    do_not_contact_reason: ShortText | None = None


class RoleIn(InputModel):
    role: Role
    stage: Code | None = None


class StageChange(InputModel):
    stage: Code
    reason: ShortText | None = None


class DocumentLinkIn(InputModel):
    document_id: uuid.UUID


class PartyOut(ApiModel):
    id: uuid.UUID
    name_fa: str | None
    name_en: str | None
    kind: str
    country_iso2: str | None
    website: str | None
    notes: str | None
    do_not_contact: bool
    do_not_contact_reason: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class RoleOut(ApiModel):
    role: str
    stage: str
    stage_changed_at: datetime


class DuplicateOut(ApiModel):
    id: uuid.UUID
    name_fa: str | None
    name_en: str | None
    status: str
    do_not_contact: bool
    reason: str
    score: float


# ---- contacts --------------------------------------------------------------------

class MethodIn(InputModel):
    type: MethodType
    value: Annotated[str, Field(min_length=1, max_length=300)]
    is_primary: bool = False


class MethodPatch(InputModel):
    value: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    is_primary: bool | None = None


class ContactCreate(_Names):
    party_id: uuid.UUID
    name_fa: Name | None = None
    name_en: Name | None = None
    job_title: ShortText | None = None
    is_primary: bool = False
    notes: LongText | None = None
    methods: list[MethodIn] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _need_name(self):
        if not (self.name_fa or self.name_en):
            raise ValueError("name_fa or name_en is required")
        return self


class ContactPatch(_Names):
    name_fa: Name | None = None
    name_en: Name | None = None
    job_title: ShortText | None = None
    is_primary: bool | None = None
    notes: LongText | None = None


class MethodOut(ApiModel):
    id: uuid.UUID
    type: str
    value: str
    value_norm: str
    is_primary: bool
    status: str


class ContactOut(ApiModel):
    id: uuid.UUID
    party_id: uuid.UUID
    name_fa: str | None
    name_en: str | None
    job_title: str | None
    is_primary: bool
    notes: str | None
    status: str
    methods: list[MethodOut] = []


# ---- interactions and follow-ups ----------------------------------------------------

class FollowupSpec(InputModel):
    action: Annotated[str, Field(min_length=1, max_length=1000)]
    due_on: date


class StageMove(InputModel):
    role: Role
    stage: Code
    reason: ShortText | None = None


class InteractionCreate(InputModel):
    party_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    channel: Channel
    direction: Direction
    occurred_at: datetime | None = None
    subject: ShortText | None = None
    body: Body | None = None
    followup: FollowupSpec | None = None
    no_followup_reason: ShortText | None = None
    move_stage: StageMove | None = None
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class InteractionPatch(InputModel):
    subject: ShortText | None = None
    body: Body | None = None


class InteractionOut(ApiModel):
    id: uuid.UUID
    party_id: uuid.UUID
    contact_id: uuid.UUID | None
    channel: str
    direction: str
    occurred_at: datetime
    subject: str | None
    body: str | None
    no_followup_reason: str | None
    created_at: datetime
    updated_at: datetime


class FollowupCreate(InputModel):
    party_id: uuid.UUID
    interaction_id: uuid.UUID | None = None
    action: Annotated[str, Field(min_length=1, max_length=1000)]
    due_on: date


class FollowupDone(InputModel):
    note: LongText | None = None
    next: FollowupSpec | None = None


class FollowupReschedule(InputModel):
    due_on: date
    note: ShortText | None = None


class FollowupCancel(InputModel):
    note: Annotated[str, Field(min_length=1, max_length=2000)]


class FollowupOut(ApiModel):
    id: uuid.UUID
    interaction_id: uuid.UUID | None
    party_id: uuid.UUID
    action: str
    due_on: date
    status: str
    done_at: datetime | None
    done_note: str | None
    created_at: datetime
