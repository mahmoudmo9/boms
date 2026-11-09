"""Default code patterns (v0.9.0). A pattern is a setting ``codes.pattern.<kind>``; a change applies to new codes only.

Tokens: ``{yyyy}`` the year of the user's calendar, ``{0000}`` the sequence (as many digits as zeros), ``{country}``
ISO 3166 alpha-2 (``XX`` when unknown), ``{role}`` SUP / CUS / BP, ``{hs4}`` the HS heading (``0000`` when unknown)."""
import re

DEFAULTS = {
    "inquiry": "INQ-{yyyy}-{0000}", "case": "CS-{yyyy}-{0000}", "rfq": "RFQ-{yyyy}-{0000}", "tender": "TDR-{yyyy}-{0000}",
    "shipment": "SH-{yyyy}-{0000}", "receipt": "RCV-{yyyy}-{0000}", "delivery": "DLV-{yyyy}-{0000}",
    "payment": "PAY-{yyyy}-{0000}", "claim": "CLM-{yyyy}-{0000}", "inspection": "INS-{yyyy}-{0000}",
    "guarantee": "GTE-{yyyy}-{0000}", "contract": "CT-{yyyy}-{0000}", "letter": "LT-{yyyy}-{0000}",
    "party": "{role}-{country}-{0000}", "product": "PRD-{hs4}-{0000}",
    # numbering that existed before v0.9.0, moved onto the service without changing any number
    "quote": "PI-{yyyy}-{0000}", "sales_order": "SO-{yyyy}-{0000}", "purchase_order": "PO-{yyyy}-{0000}",
    "sales_invoice": "INV-{yyyy}-{0000}", "credit_note": "CN-{yyyy}-{0000}", "debit_note": "DN-{yyyy}-{0000}",
}
SEQ = re.compile(r"\{(0+)\}")
TOKENS = {"yyyy", "country", "role", "hs4"}


def check(pattern: str) -> str:
    if not isinstance(pattern, str) or len(pattern) > 60:
        raise ValueError("expected a pattern (up to 60 characters)")
    if len(SEQ.findall(pattern)) != 1:
        raise ValueError("a pattern has exactly one sequence token like {0000}")
    unknown = {t for t in re.findall(r"\{([a-z0-9]+)\}", pattern) if t not in TOKENS and not set(t) <= {"0"}}
    if unknown:
        raise ValueError(f"unknown token(s): {', '.join(sorted(unknown))}")
    if not re.fullmatch(r"[A-Za-z0-9{}\-_/.]+", pattern):
        raise ValueError("letters, digits, - _ / . and tokens only")
    return pattern


def render(pattern: str, context: dict, number: int | None = None) -> str:
    """The pattern with its tokens; without ``number`` the sequence part is left out (the scope prefix)."""
    out = pattern
    for token in TOKENS:
        if "{" + token + "}" in out:
            out = out.replace("{" + token + "}", str(context.get(token) or ("0000" if token == "hs4" else "XX")))
    m = SEQ.search(out)
    if number is None:
        return out[:m.start()] + "#" + out[m.end():]
    return out[:m.start()] + str(number).zfill(len(m.group(1))) + out[m.end():]
