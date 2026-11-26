"""Parties plug into later core services here (loaded by ``app.core.modules.load_hooks``)."""

from app.modules.codes.service import register
from app.modules.parties.models import Party


def _party_context(_db, party) -> dict:
    """SUP- / CUS- by the first role at creation, BP- when it starts with both (or another role); the country.
    v0.10.1 (0.4.2): a manufacturer is on the supplier side (SUP-: the supplier type says it is a factory); a carrier
    follows the rule for other roles (BP-)."""
    roles = set(getattr(party, "_code_roles", None) or ())
    supplier = bool(roles & {"supplier", "manufacturer"})
    role = "BP" if supplier and "buyer" in roles else "SUP" if supplier else "CUS" if "buyer" in roles else "BP"
    return {"role": role, "country": party.country_iso2 or "XX"}


register("party", Party, context=_party_context, link=lambda _db, r: f"/parties/{r.id}")
