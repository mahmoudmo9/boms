"""Job handlers of the parties module (v0.10.1, 0.4.3). They only change stages and record events; nobody is contacted."""

from app.modules.parties import rules
from app.worker.registry import job_handler


@job_handler("parties.dormant")
def dormant(db, payload: dict) -> dict:
    """Roles with no activity for ``parties.dormant_days`` become dormant (reversible: the next activity)."""
    return {"dormant": len(rules.make_dormant(db))}
