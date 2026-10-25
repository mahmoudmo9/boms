"""Slot for a later AI assistant: turn free text (an inquiry, a PDF's text) into line items.

Phase 5 ships only the interface and a disabled default. Nothing here calls an external service.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ExtractResult:
    configured: bool
    items: list[dict]
    message: str


class ItemExtractor(Protocol):
    name: str

    def is_configured(self) -> bool: ...

    def extract(self, text: str, language: str | None = None) -> ExtractResult: ...


class DisabledExtractor:
    """Default: not configured. Returns no items and never contacts anything."""

    name = "disabled"

    def is_configured(self) -> bool:
        return False

    def extract(self, text: str, language: str | None = None) -> ExtractResult:
        return ExtractResult(configured=False, items=[], message="not configured")


_extractor: ItemExtractor = DisabledExtractor()


def get_extractor() -> ItemExtractor:
    return _extractor
