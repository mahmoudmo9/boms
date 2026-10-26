"""Reference counters other modules register for parties and contacts (v0.3.1).

Parties must not import the tables of later modules, yet a party or contact delete has to know about rows
that point at it. A module registers a counter (``fn(db, party_id) -> {name: count}``) and, optionally, a
cleanup callback run right before the party row is deleted (for rows that do NOT block a delete, e.g. tags).
Counts of names listed in ``NON_BLOCKING`` never block a delete; all others do. Registrations live in each
module's ``references.py``, discovered like ``searchable.py``.
"""

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.modules import load_module_parts

Counter = Callable[[Session, uuid.UUID], dict[str, int]]
Cleanup = Callable[[Session, uuid.UUID, str, "str | None"], None]

_party_counters: dict[str, Counter] = {}
_contact_counters: dict[str, Counter] = {}
_party_cleanups: dict[str, Cleanup] = {}
NON_BLOCKING: set[str] = set()
_loaded = False


def _load() -> None:
    global _loaded
    if not _loaded:
        load_module_parts("references")
        _loaded = True


def register_reference_counter(name: str, fn: Counter, *, cleanup: Cleanup | None = None,
                               contact_fn: Counter | None = None, non_blocking: tuple[str, ...] = ()) -> None:
    """Register (or replace) the counters of module ``name``."""
    _party_counters[name] = fn
    if cleanup is not None:
        _party_cleanups[name] = cleanup
    if contact_fn is not None:
        _contact_counters[name] = contact_fn
    NON_BLOCKING.update(non_blocking)


def party_counts(db: Session, party_id: uuid.UUID) -> dict[str, int]:
    _load()
    out: dict[str, int] = {}
    for fn in _party_counters.values():
        out.update(fn(db, party_id))
    return out


def contact_counts(db: Session, contact_id: uuid.UUID) -> dict[str, int]:
    _load()
    out: dict[str, int] = {}
    for fn in _contact_counters.values():
        out.update(fn(db, contact_id))
    return out


def blocking(counts: dict[str, int]) -> dict[str, int]:
    return {k: v for k, v in counts.items() if v and k not in NON_BLOCKING}


def cleanup_party(db: Session, party_id: uuid.UUID, source: str, actor: str | None) -> None:
    _load()
    for fn in _party_cleanups.values():
        fn(db, party_id, source, actor)
