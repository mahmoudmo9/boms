"""Job handlers of the AI module: tasks on the ``ai`` lane and the nightly privacy-log retention."""
from app.worker.registry import job_handler


@job_handler("ai.task")
def run_task(db, payload: dict) -> dict:
    from app.modules.ai import builtin, tasks

    if payload.get("task") not in tasks.TASKS:
        builtin.register()
    return tasks.run_job(db, payload)


@job_handler("ai.purge_log")
def purge_log(db, _payload: dict) -> dict:
    from app.modules.ai import service

    return {"deleted": service.purge_log(db)}
