"""Shared API schema pieces."""

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class InputModel(BaseModel):
    """Base for every POST/PATCH request body: unknown fields are a 422, not silently ignored."""

    model_config = ConfigDict(extra="forbid")


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


def page_params(page: int, page_size: int, max_size: int = 500) -> tuple[int, int]:
    return max(1, page), min(max(1, page_size), max_size)
