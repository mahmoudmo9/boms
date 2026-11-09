"""AI tasks as jobs on the ``ai`` lane (v0.9.0 section 1.3): ``start`` creates a pending draft and queues the job; the
handler runs the task's ``build`` (which calls ``service.run``) and fills the draft. The UI polls the draft."""
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.ai import drafts

LANE = "ai"
JOB = "ai.task"


@dataclass
class Task:
    name: str
    route: str                 # the ai.route task kind (extraction, drafting, party_parse, classification)
    build: Callable            # (db, draft, payload, job_id) -> None: runs the model and fills the draft


TASKS: dict[str, Task] = {}


def register(name: str, route: str, build: Callable) -> None:
    TASKS[name] = Task(name, route, build)


def start(db: Session, name: str, *, target_type: str, target_id=None, case_id=None, payload: dict | None = None,
          sources: list | None = None, source: str = "api", actor: str | None = None):
    from app.core.errors import AppError
    from app.modules.ai import service
    from app.modules.system import jobs

    if name not in TASKS:
        raise AppError("unknown_ai_task", "Unknown AI task", {"task": name}, status=422)
    if not service.configured(db):
        raise AppError("ai_not_configured", "No AI provider is connected; connect one in Settings → «هوش مصنوعی», "
                       "or enter the data by hand", status=409)
    draft = drafts.create(db, task=name, target_type=target_type, target_id=target_id, case_id=case_id,
                          sources=sources, source=source, actor=actor)
    job = jobs.enqueue(db, JOB, {"task": name, "draft_id": str(draft.id), **(payload or {})}, max_attempts=1,
                       source=source, actor=actor, lane=LANE)
    draft.job_id = job.id
    db.flush()
    return draft


def run_job(db: Session, payload: dict, job_id=None) -> dict:
    from app.core.errors import AppError

    draft = drafts.get(db, payload["draft_id"])
    if draft.status != "pending":
        return {"skipped": draft.status}
    task = TASKS[payload["task"]]
    try:
        task.build(db, draft, payload, job_id)
    except AppError as exc:
        drafts.fail(db, draft, f"{exc.code}: {exc.message}")
        return {"failed": exc.code}
    return {"draft_id": str(draft.id), "status": draft.status}
