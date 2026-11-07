"""Tasks name a party only as context: they never block a party delete; the party is cleared from them instead."""

from sqlalchemy import func, select, update

from app.modules.parties.references import register_reference_counter
from app.modules.tasks.models import Task


def party_counts(db, party_id) -> dict[str, int]:
    return {"tasks": db.scalar(select(func.count()).select_from(Task).where(Task.party_id == party_id)) or 0}


def cleanup(db, party_id, source, actor) -> None:
    db.execute(update(Task).where(Task.party_id == party_id).values(party_id=None))
    db.flush()


register_reference_counter("tasks", party_counts, cleanup=cleanup, non_blocking=("tasks",))
