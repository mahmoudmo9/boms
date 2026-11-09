"""Parties plug into later core services here (loaded by ``app.core.modules.load_hooks``)."""

from app.modules.codes.service import register
from app.modules.parties.models import Party


def _party_context(_db, party) -> dict:
    """SUP- / CUS- by the first role at creation, BP- when it starts with both (or another role); the country."""
    roles = set(getattr(party, "_code_roles", None) or ())
    role = "BP" if {"buyer", "supplier"} <= roles else "SUP" if "supplier" in roles else "CUS" if "buyer" in roles else "BP"
    return {"role": role, "country": party.country_iso2 or "XX"}


register("party", Party, context=_party_context, link=lambda _db, r: f"/parties/{r.id}")
