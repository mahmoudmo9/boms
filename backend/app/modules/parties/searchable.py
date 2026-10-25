"""Parties, contacts (names + phone/email) and interactions (subject + pasted text) in global search."""

from sqlalchemy import select, text

from app.modules.parties.interactions import match_condition
from app.modules.parties.models import Interaction, Party
from app.modules.search.registry import SearchHit, SearchProvider, register

PARTY_EXPR = "p.name_norm"
CONTACT_EXPR = "core.normalize_fa(coalesce(c.name_fa, '') || ' ' || coalesce(c.name_en, ''))"


def _like(needle: str) -> str:
    return "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _title(name_fa: str | None, name_en: str | None) -> tuple[str, dict]:
    return name_fa or name_en or "", {"fa": name_fa or name_en or "", "en": name_en or name_fa or ""}


def _parties(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        f"""
        SELECT p.id, p.name_fa, p.name_en, p.status, p.do_not_contact,
               word_similarity(:needle, {PARTY_EXPR}) AS score
        FROM core.party p
        WHERE {PARTY_EXPR} LIKE :like OR {PARTY_EXPR} %> :needle
        ORDER BY (p.status = 'active') DESC, score DESC, p.id LIMIT :limit
        """
    ), {"needle": needle, "like": _like(needle), "limit": limit}).all()
    hits = []
    for r in rows:
        title, i18n = _title(r.name_fa, r.name_en)
        hits.append(SearchHit(id=str(r.id), title=title, title_i18n=i18n, subtitle=r.name_en if r.name_fa else None,
                              score=float(r.score), link=f"/parties/{r.id}",
                              extra={"status": r.status, "do_not_contact": r.do_not_contact}))
    return hits


def _contacts(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    digits = "".join(ch for ch in needle if ch.isdigit())
    rows = db.execute(text(
        f"""
        SELECT DISTINCT ON (c.id) c.id, c.party_id, c.name_fa, c.name_en, p.name_fa AS party_fa,
               p.name_en AS party_en, m.value AS method_value,
               greatest(word_similarity(:needle, {CONTACT_EXPR}),
                        CASE WHEN m.value_norm LIKE :like THEN 1 ELSE 0 END) AS score
        FROM core.contact c
        JOIN core.party p ON p.id = c.party_id
        LEFT JOIN core.contact_method m ON m.contact_id = c.id
             AND (m.value_norm LIKE :like OR (:digits <> '' AND length(:digits) >= 4 AND m.value_norm LIKE :dlike))
        WHERE {CONTACT_EXPR} LIKE :like OR {CONTACT_EXPR} %> :needle OR m.id IS NOT NULL
        ORDER BY c.id, score DESC
        """
    ), {"needle": needle, "like": _like(needle), "digits": digits, "dlike": f"%{digits}%"}).all()
    rows = sorted(rows, key=lambda r: -float(r.score))[:limit]
    hits = []
    for r in rows:
        title, i18n = _title(r.name_fa, r.name_en)
        party = r.party_fa or r.party_en or ""
        hits.append(SearchHit(id=str(r.id), title=title, title_i18n=i18n,
                              subtitle=f"{party} · {r.method_value}" if r.method_value else party,
                              score=float(r.score), link=f"/parties/{r.party_id}?tab=contacts"))
    return hits


def _interactions(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    condition = match_condition(db, raw)
    if condition is None:
        return []
    rows = db.execute(
        select(Interaction.id, Interaction.party_id, Interaction.subject, Interaction.body, Interaction.channel,
               Interaction.occurred_at, Party.name_fa, Party.name_en)
        .join(Party, Party.id == Interaction.party_id)
        .where(condition).order_by(Interaction.occurred_at.desc()).limit(limit)
    ).all()
    hits = []
    for r in rows:
        lines = (r.body or "").strip().splitlines()
        snippet = (r.subject or (lines[0] if lines else ""))[:120]
        hits.append(SearchHit(id=str(r.id), title=snippet or r.channel,
                              subtitle=r.name_fa or r.name_en, score=1.0,
                              link=f"/parties/{r.party_id}?tab=interactions&interaction={r.id}",
                              extra={"channel": r.channel, "occurred_at": r.occurred_at.isoformat()}))
    return hits


register(SearchProvider(type="party", label_key="search.type.party", search=_parties, order=5))
register(SearchProvider(type="contact", label_key="search.type.contact", search=_contacts, order=6))
register(SearchProvider(type="interaction", label_key="search.type.interaction", search=_interactions, order=7))
