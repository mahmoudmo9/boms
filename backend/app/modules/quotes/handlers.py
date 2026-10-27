"""Job handlers of the quotes module. They only change statuses and record events; nobody is contacted."""

from app.modules.quotes import service
from app.worker.registry import job_handler


@job_handler("quotes.expire")
def expire(db, payload: dict) -> dict:
    return {"quotes_expired": len(service.expire_quotes(db))}
