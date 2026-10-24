"""Search provider registry.

A module makes its entities searchable by adding ``searchable.py``::

    from app.modules.search.registry import SearchHit, SearchProvider, register

    def _search(db, needle, raw, limit) -> list[SearchHit]: ...

    register(SearchProvider(type="party", label_key="search.type.party", search=_search, order=50))

``needle`` is the query after ``normalize_fa``; ``raw`` is the user's input.
The search module discovers these files itself; it never needs editing.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session


@dataclass
class SearchHit:
    id: str
    title: str
    link: str
    score: float = 0.0
    subtitle: str | None = None
    title_i18n: dict[str, str] | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SearchProvider:
    type: str
    label_key: str
    search: Callable[[Session, str, str, int], list[SearchHit]]
    order: int = 100


PROVIDERS: dict[str, SearchProvider] = {}


def register(provider: SearchProvider) -> None:
    PROVIDERS[provider.type] = provider
