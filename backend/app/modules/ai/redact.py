"""Redaction for ``cloud_redacted`` routes (v0.9.0 section 1.2).

Before a text leaves the PC, names of parties, contacts and the owner's company, identifiers (national ID, economic
code, IBAN, phone, e-mail) and prices marked private are replaced by stable placeholders such as ``⟦PARTY_1⟧``; the
model's answer gets the originals back (``restore``). The same value always gets the same placeholder within a call,
so the model can still relate repeated mentions."""
import re
from dataclasses import dataclass, field
from typing import Any

PATTERNS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")),
    ("PHONE", re.compile(r"(?<![\w])(?:\+|00)\d[\d\s\-()]{7,}\d|(?<![\w])0\d{2,3}[\s\-]?\d{3,4}[\s\-]?\d{4}(?![\w])")),
    # national ID (10/11) and economic code (12); \d also matches Persian and Arabic-Indic digits
    ("ID", re.compile(r"(?<!\d)(?:\d{10}|\d{11}|\d{12})(?!\d)")),
]


@dataclass
class Redactor:
    names: dict[str, str] = field(default_factory=dict)        # value -> kind (PARTY, CONTACT, COMPANY, PRICE)
    mapping: dict[str, str] = field(default_factory=dict)      # placeholder -> original
    _seen: dict[str, str] = field(default_factory=dict)        # original -> placeholder
    counts: dict[str, int] = field(default_factory=dict)
    patterns: bool = True                                      # False: nothing is replaced (local models)

    def add(self, value: str | None, kind: str) -> None:
        if value and len(value.strip()) >= 3:
            self.names[value.strip()] = kind

    def _token(self, value: str, kind: str) -> str:
        if value not in self._seen:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            token = f"⟦{kind}_{self.counts[kind]}⟧"
            self._seen[value] = token
            self.mapping[token] = value
        return self._seen[value]

    def redact(self, text: str) -> str:
        if not text or not self.patterns:
            return text
        for value in sorted(self.names, key=len, reverse=True):
            if value in text:
                text = text.replace(value, self._token(value, self.names[value]))
        for kind, pattern in PATTERNS:
            text = pattern.sub(lambda m: self._token(m.group(0), kind), text)
        return text

    def restore(self, value: Any) -> Any:
        if isinstance(value, str):
            for token, original in self.mapping.items():
                value = value.replace(token, original)
            return value
        if isinstance(value, list):
            return [self.restore(v) for v in value]
        if isinstance(value, dict):
            return {k: self.restore(v) for k, v in value.items()}
        return value

    def summary(self) -> dict:
        """For the privacy log: how many of each kind were replaced (never the values)."""
        return dict(self.counts)


def for_context(db, case_id=None, party_ids=(), private_prices=()) -> Redactor:
    """Names known to BOMS for this call: the case's parties and contacts, every party given, the owner's company."""
    from sqlalchemy import text

    from app.modules.system import settings

    r = Redactor()
    for key in ("company.name", "company.name_fa", "company.name_en"):
        r.add(settings.get(db, key), "COMPANY")
    ids = set(party_ids)
    if case_id:
        ids |= set(db.execute(text("SELECT party_id FROM ops.\"case\" WHERE id = :c AND party_id IS NOT NULL "
                                   "UNION SELECT party_id FROM ops.supplier_offer WHERE case_id = :c "
                                   "UNION SELECT r.party_id FROM ops.rfq_recipient r JOIN ops.rfq q ON q.id = r.rfq_id "
                                   "WHERE q.case_id = :c"), {"c": case_id}).scalars())
    if ids:
        for name_fa, name_en in db.execute(text("SELECT name_fa, name_en FROM core.party WHERE id = ANY(:i)"), {"i": list(ids)}):
            r.add(name_fa, "PARTY")
            r.add(name_en, "PARTY")
        for name_fa, name_en in db.execute(text("SELECT name_fa, name_en FROM core.contact WHERE party_id = ANY(:i)"),
                                           {"i": list(ids)}):
            r.add(name_fa, "CONTACT")
            r.add(name_en, "CONTACT")
    for price in private_prices:
        r.add(str(price), "PRICE")
    return r
