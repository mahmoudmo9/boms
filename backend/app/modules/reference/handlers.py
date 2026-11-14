"""Job handlers of the reference module (v0.10.1): the reference import (preview and import)."""
from app.worker.registry import job_handler


@job_handler("reference.import")
def reference_import(db, payload: dict) -> dict:
    from app.modules.reference import imports

    return imports.run_job(db, payload)
