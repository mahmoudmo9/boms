"""Unified lookup (v0.9.0 section 8.1): ``GET /api/lookup?kind=…&q=…``.

One contract for every picker: party, contact, product, case, location (with a function filter: port, airport, rail,
road), airport, currency, unit, HS, ISIC, Incoterm, legal form, container type and record codes. The query is
normalised like the database does it (Persian ی/ک, half-space, digits); results are ranked exact code, code prefix,
name prefix, name contains, trigram. Each result returns id, code, display names fa/en and a subtitle."""
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.text import normalize_fa

KINDS = ("party", "contact", "product", "case", "location", "airport", "currency", "unit", "hs", "isic", "incoterm",
         "legal_form", "container", "code")
RANKS = {0: "exact_code", 1: "code_prefix", 2: "name_prefix", 3: "name_contains", 4: "similar"}


@dataclass(frozen=True)
class Source:
    """One table: its id, code and name expressions, the normalised name to match, a subtitle and extra filters."""
    table: str
    id: str
    code: str
    name_fa: str
    name_en: str
    norm: str
    subtitle: str = "NULL"
    where: str = "true"
    trigram: bool = True
    alt_code: str = "NULL"        # a second code that counts as exact (UN/LOCODE location part «SHA», ICAO)


SOURCES = {
    "party": Source("core.party p", "p.id::text", "p.code", "p.name_fa", "p.name_en", "p.name_norm",
                    "concat_ws(' · ', p.country_iso2, (SELECT max(c.code) FROM ops.\"case\" c WHERE c.party_id = p.id))",
                    "p.status <> 'archived'"),
    "contact": Source("core.contact ct JOIN core.party p ON p.id = ct.party_id", "ct.id::text", "p.code", "ct.name_fa",
                      "ct.name_en", "core.normalize_fa(coalesce(ct.name_fa, '') || ' ' || coalesce(ct.name_en, ''))",
                      "coalesce(p.name_fa, p.name_en)", "ct.status = 'active'"),
    "product": Source("core.product x", "x.id::text", "x.code", "coalesce(x.canonical_fa, x.name_fa)",
                      "coalesce(x.canonical_en, x.name_en)", "x.name_norm", "x.hs_code", "x.status = 'active'"),
    "case": Source("ops.\"case\" x LEFT JOIN core.party p ON p.id = x.party_id", "x.id::text", "x.code", "x.title", "x.title",
                   "x.title_norm", "coalesce(p.name_fa, p.name_en)"),
    "location": Source("ref.location x", "x.id::text", "x.unlocode", "coalesce(x.name_fa, x.name)", "x.name",
                       "core.normalize_fa(coalesce(x.name_fa, '') || ' ' || x.name_ascii)",
                       "concat_ws(' · ', x.code, x.country_iso2, x.iata)", "x.active", alt_code="x.code"),
    "airport": Source("ref.airport x", "x.id::text", "x.iata", "coalesce(x.name_fa, x.name)", "x.name",
                      "core.normalize_fa(coalesce(x.name_fa, '') || ' ' || x.name || ' ' || coalesce(x.city, ''))",
                      "concat_ws(' · ', x.city, x.country_iso2, x.icao)", "x.active", alt_code="x.icao"),
    "currency": Source("sys.currency x", "x.code", "x.code", "x.name_fa", "x.name_en",
                       "core.normalize_fa(x.name_fa || ' ' || x.name_en)", where="x.active", trigram=False),
    "unit": Source("sys.unit x", "x.code", "coalesce(x.unece_code, x.code)", "x.name_fa", "x.name_en",
                   "core.normalize_fa(x.name_fa || ' ' || x.name_en || ' ' || x.code)", "x.kind", "x.active",
                   trigram=False),
    "hs": Source("ref.hs_code x", "x.code", "x.code", "x.title_fa", "x.title_en", "x.title_norm"),
    "isic": Source("ref.isic_code x", "x.code", "x.code", "x.title_fa", "x.title_en", "x.title_norm"),
    "incoterm": Source("ref.incoterm x", "x.code", "x.code", "x.name_fa", "x.name_en",
                       "core.normalize_fa(x.name_fa || ' ' || x.name_en)",
                       "CASE WHEN x.any_mode THEN 'any mode' ELSE 'sea and inland waterway' END", "x.active", trigram=False),
    "legal_form": Source("ref.legal_form x", "x.id::text", "x.code", "coalesce(x.name_fa, x.local_name)", "x.local_name",
                         "core.normalize_fa(coalesce(x.name_fa, '') || ' ' || x.local_name || ' ' || "
                         "coalesce(x.transliterated, '') || ' ' || array_to_string(x.abbreviations, ' '))",
                         "x.country_iso2", "x.active"),
    "container": Source("ref.container_type x", "x.code", "x.code", "x.description_fa", "x.description_en",
                        "core.normalize_fa(x.description_fa || ' ' || x.description_en)", "x.teu::text || ' TEU'",
                        "x.active", trigram=False),
}
LOCATION_FUNCTIONS = {"port": "x.is_port", "airport": "x.is_airport", "rail": "x.is_rail", "road": "x.is_road",
                      "border": "x.is_border"}


def lookup(db: Session, kind: str, q: str | None, *, limit: int = 20, function: str | None = None,
           country: str | None = None) -> list[dict]:
    if kind == "code":
        return _codes(db, q or "", limit)
    src = SOURCES[kind]
    raw = (q or "").strip()
    needle = normalize_fa(raw) or ""
    where = [src.where]
    params: dict = {"raw": raw, "up": raw.upper(), "n": needle, "limit": limit}
    if kind == "location":
        if function in LOCATION_FUNCTIONS:
            where.append(LOCATION_FUNCTIONS[function])
        if country:
            where.append("x.country_iso2 = :country")
            params["country"] = country.upper()
    if kind == "legal_form" and country:
        where.append("x.country_iso2 = :country")
        params["country"] = country.upper()
    code = f"coalesce({src.code}, '')"
    if needle or raw:
        alt = f"upper(coalesce({src.alt_code}, ''))"
        rank = (f"CASE WHEN upper({code}) = :up OR upper({src.id}) = :up OR {alt} = :up THEN 0 "
                f"WHEN upper({code}) LIKE :up || '%' THEN 1 "
                f"WHEN {src.norm} LIKE :n || '%' OR {src.norm} LIKE '% ' || :n || '%' THEN 2 "
                f"WHEN {src.norm} LIKE '%' || :n || '%' THEN 3 ELSE 4 END")
        match = (f"(upper({code}) LIKE :up || '%' OR upper({src.id}) = :up OR {alt} = :up OR {src.norm} LIKE '%' || :n || '%'"
                 + (f" OR similarity({src.norm}, :n) > 0.3" if src.trigram and len(needle) >= 3 else "") + ")")
        where.append(match)
        order = f"{rank}, " + (f"similarity({src.norm}, :n) DESC, " if src.trigram else "") + f"{src.name_en}"
    else:
        rank = "4"
        order = src.name_en
    sql = (f"SELECT {src.id} AS id, {src.code} AS code, {src.name_fa} AS name_fa, {src.name_en} AS name_en, "
           f"{src.subtitle} AS subtitle, {rank} AS rank FROM {src.table} WHERE {' AND '.join(where)} "
           f"ORDER BY {order} LIMIT :limit")
    rows = db.execute(text(sql), params).mappings().all()
    return [{"kind": kind, "id": r["id"], "code": r["code"], "name_fa": r["name_fa"] or r["name_en"],
             "name_en": r["name_en"] or r["name_fa"], "subtitle": r["subtitle"], "match": RANKS[int(r["rank"])]}
            for r in rows]


def _codes(db: Session, q: str, limit: int) -> list[dict]:
    from app.modules.codes import service as codes

    out = []
    for hit in codes.search(db, q, q, limit):
        out.append({"kind": "code", "id": hit.id, "code": hit.code, "name_fa": hit.subtitle or hit.title,
                    "name_en": hit.subtitle or hit.title, "subtitle": (hit.extra or {}).get("kind"), "link": hit.link,
                    "match": "exact_code" if hit.score >= 2 else "code_prefix"})
    return out
