"""Job handler registry.

A module registers handlers in its own ``handlers.py``::

    from app.worker.registry import job_handler

    @job_handler("documents.extract_text")
    def extract_text(db, payload): ...

Handlers must be idempotent: a job can run again after a crash or a retry.
They run inside a transaction that also marks the job done, so their DB
writes commit only on success.
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.modules import load_module_parts

Handler = Callable[[Session, dict], dict | None]

HANDLERS: dict[str, Handler] = {}


def job_handler(job_type: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn

    return register


def load_handlers() -> dict[str, Handler]:
    load_module_parts("handlers")
    return HANDLERS
