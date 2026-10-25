"""Job handlers of the sourcing module. They only change statuses and record events; nobody is contacted."""

from app.modules.sourcing import offers, rfq
from app.worker.registry import job_handler


@job_handler("sourcing.expire")
def expire(db, payload: dict) -> dict:
    recipients = rfq.expire_no_reply(db)
    expired = offers.expire_offers(db)
    return {"no_response": len(recipients), "offers_expired": len(expired)}
