"""Job handlers of the execution module: the claim follow-ups (one open «پیگیری ادعا» per open claim)."""

from app.modules.execution import claims
from app.worker.registry import job_handler


@job_handler("execution.claim_followups")
def claim_followups(db, payload: dict) -> dict:
    return {"claim_followups_created": claims.refresh_followups(db)}
