from dataclasses import asdict
from functools import cache

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.modules import load_module_parts
from app.core.text import WORD_SIMILARITY, normalize_fa
from app.modules.search.registry import PROVIDERS



@cache
def load_providers() -> tuple[str, ...]:
    load_module_parts("searchable")
    return tuple(sorted(PROVIDERS))


def search(db: Session, q: str, limit: int = 5, types: list[str] | None = None) -> list[dict]:
    load_providers()
    needle = normalize_fa(q) or ""
    if not needle:
        return []
    db.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :v, true)"), {"v": str(WORD_SIMILARITY)})
    groups = []
    for provider in sorted(PROVIDERS.values(), key=lambda p: (p.order, p.type)):
        if types and provider.type not in types:
            continue
        hits = provider.search(db, needle, q, limit)
        if hits:
            groups.append({"type": provider.type, "label_key": provider.label_key,
                           "items": [asdict(h) for h in hits]})
    return groups
