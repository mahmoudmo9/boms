"""Job handlers of the sourcing module. They only change statuses and record events; nobody is contacted."""

from app.modules.sourcing import items, offers, rfq
from app.worker.registry import job_handler


@job_handler("sourcing.expire")
def expire(db, payload: dict) -> dict:
    recipients = rfq.expire_no_reply(db)
    expired = offers.expire_offers(db)
    stale = items.uncovered_with_sent_rfq(db)
    items.recompute_items(db, stale, "worker")
    return {"no_response": len(recipients), "offers_expired": len(expired), "items_recomputed": len(stale)}
