import re
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


CODE_TOKEN = re.compile(r"[A-Za-z]{2,4}(?:-[A-Za-z0-9]+)+")
TIER_NAMES = ("exact_code", "code_prefix", "name_prefix", "name_contains", "fuzzy")


def tier(hit, raw: str, needle: str) -> int:
    """v0.9.0 ranking: 0 exact code, 1 code prefix, 2 name prefix, 3 name contains, 4 fuzzy (trigram)."""
    q = (raw or "").strip().casefold()
    codes = [c.casefold() for c in ([hit.code] if hit.code else []) + CODE_TOKEN.findall(f"{hit.title} {hit.subtitle or ''}")]
    if q and q in codes:
        return 0
    if q and any(c.startswith(q) for c in codes):
        return 1
    title = normalize_fa(hit.title or "") or ""
    if needle and title.startswith(needle):
        return 2
    if needle and needle in title:
        return 3
    return 4


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
            ranked = sorted(((tier(h, q, needle), -h.score, i, h) for i, h in enumerate(hits)), key=lambda x: x[:3])
            groups.append({"type": provider.type, "label_key": provider.label_key, "order": provider.order,
                           "best": ranked[0][0],
                           "items": [{**asdict(h), "match": TIER_NAMES[t]} for t, _s, _i, h in ranked]})
    # the group holding the best match comes first (an exact code before any name), then the providers' own order
    groups.sort(key=lambda g: (g["best"], g["order"]))
    for g in groups:
        g.pop("order")
        g.pop("best")
    return groups
