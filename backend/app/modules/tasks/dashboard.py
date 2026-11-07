"""Command center section «کارها» (v0.8.0): overdue tasks and tasks due today or tomorrow."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.tasks.models import Task
from app.modules.tasks.service import task_out


def summary(db: Session, today: date) -> dict:
    from app.modules.sourcing.models import Case

    rows = list(db.scalars(select(Task).where(Task.status == "open", Task.due_on <= today + timedelta(days=1))
                           .order_by(Task.due_on, Task.priority.desc(), Task.created_at)))
    titles = {c.id: c.title for c in db.scalars(select(Case).where(Case.id.in_({r.case_id for r in rows if r.case_id})))} if rows else {}
    out = [task_out(r, titles) for r in rows]
    return {"overdue": [r for r in out if r["due_on"] < today.isoformat()],
            "today": [r for r in out if r["due_on"] == today.isoformat()],
            "tomorrow": [r for r in out if r["due_on"] == (today + timedelta(days=1)).isoformat()]}
