from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.search import service
from app.modules.system.auth import CurrentUser

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search(_: CurrentUser, db: Annotated[Session, Depends(get_db)],
           q: Annotated[str, Query(max_length=200)] = "", limit: Annotated[int, Query(ge=1, le=50)] = 5,
           types: Annotated[list[str] | None, Query()] = None):
    return {"q": q, "groups": service.search(db, q, limit, types)}
