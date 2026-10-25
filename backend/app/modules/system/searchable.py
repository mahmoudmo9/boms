"""Base data in global search (substring + fuzzy trigram on codes and both names)."""

from sqlalchemy import text

from app.modules.search.registry import SearchHit, SearchProvider, register

# Expressions must match the trigram indexes in migration 0003.
SOURCES = {
    "country": ("sys.country", "iso2", "iso2 || ' ' || iso3 || ' ' || name_fa || ' ' || name_en", "countries"),
    "currency": ("sys.currency", "code", "code || ' ' || name_fa || ' ' || name_en", "currencies"),
    "unit": ("sys.unit", "code", "code || ' ' || name_fa || ' ' || name_en", "units"),
}


def _provider(kind: str):
    table, key, expr, page = SOURCES[kind]
    norm = f"core.normalize_fa({expr})"

    def search(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
        like = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = db.execute(text(
            f"SELECT {key} AS code, name_fa, name_en, active, "
            f"  (CASE WHEN lower({key}) = :exact THEN 2 ELSE 0 END) + word_similarity(:needle, {norm}) AS score "
            f"FROM {table} WHERE {norm} LIKE :like OR {norm} %> :needle "
            f"ORDER BY score DESC, {key} LIMIT :limit"
        ), {"needle": needle, "like": like, "exact": needle, "limit": limit}).all()
        return [SearchHit(id=r.code, title=r.name_en, title_i18n={"fa": r.name_fa, "en": r.name_en},
                          subtitle=r.code, score=float(r.score), link=f"/settings/basedata/{page}?q={r.code}",
                          extra={"active": r.active}) for r in rows]

    return search


register(SearchProvider(type="country", label_key="search.type.country", search=_provider("country"), order=20))
register(SearchProvider(type="currency", label_key="search.type.currency", search=_provider("currency"), order=30))
register(SearchProvider(type="unit", label_key="search.type.unit", search=_provider("unit"), order=40))
