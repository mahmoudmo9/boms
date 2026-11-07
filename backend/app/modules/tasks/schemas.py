"""Request models of the tasks module."""
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from app.core.schemas import InputModel

Title = Annotated[str, Field(min_length=1, max_length=500)]


class TaskIn(InputModel):
    title: Title
    due_on: date
    due_at: datetime | None = None
    priority: Literal["normal", "high"] = "normal"
    case_id: uuid.UUID | None = None
    party_id: uuid.UUID | None = None
    notes: Annotated[str, Field(max_length=4000)] | None = None


class TaskPatch(InputModel):
    title: Title | None = None
    due_on: date | None = None
    due_at: datetime | None = None
    priority: Literal["normal", "high"] | None = None
    case_id: uuid.UUID | None = None
    notes: Annotated[str, Field(max_length=4000)] | None = None


class DoneIn(InputModel):
    note: Annotated[str, Field(max_length=2000)] | None = None


class MoveIn(InputModel):
    due_on: date
    note: Annotated[str, Field(max_length=2000)] | None = None


class CancelIn(InputModel):
    note: Annotated[str, Field(min_length=1, max_length=2000)]
