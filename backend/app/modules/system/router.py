"""HTTP routes of the system module: profile/preferences, settings, base data."""

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_config
from app.core.db import get_db
from app.core.web import request_source
from app.modules.system import basedata, settings, users
from app.modules.system.auth import current_user, user_out
from app.modules.system.models import AppUser

router = APIRouter(prefix="/api", tags=["system"])


class PreferencesIn(BaseModel):
    language: str | None = None
    calendar: str | None = None
    digits: str | None = None
    theme: str | None = None
    idle_lock_minutes: int | None = None


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.get("/me")
def get_me(user: AppUser = Depends(current_user)):
    return user_out(user)


@router.patch("/me")
def patch_me(body: PreferencesIn, request: Request, user: AppUser = Depends(current_user), db: Session = Depends(get_db)):
    updated = users.update_preferences(db, body.model_dump(exclude_none=True), request_source(request))
    db.commit()
    return user_out(updated)


@router.post("/me/password")
def change_password(body: PasswordIn, request: Request, user: AppUser = Depends(current_user), db: Session = Depends(get_db)):
    users.change_password(db, body.current_password, body.new_password, request_source(request))
    db.commit()
    return {"ok": True}


@router.get("/settings")
def get_settings(user: AppUser = Depends(current_user), db: Session = Depends(get_db)):
    return {"values": settings.get_all(db), "data_dir": get_config().data_dir}


@router.patch("/settings")
def patch_settings(body: dict, request: Request, user: AppUser = Depends(current_user), db: Session = Depends(get_db)):
    values = settings.update(db, body, request_source(request), actor=user.username)
    db.commit()
    return {"values": values, "data_dir": get_config().data_dir}


def item_out(item) -> dict:
    out = {}
    for col in item.__table__.columns.keys():
        value = getattr(item, col)
        out[col] = str(value) if isinstance(value, Decimal) else value
    return out


@router.get("/base/{kind}")
def list_base(kind: str, q: str | None = None, active: bool | None = None,
              user: AppUser = Depends(current_user), db: Session = Depends(get_db)):
    return {"items": [item_out(i) for i in basedata.list_items(db, kind, q, active)]}


@router.post("/base/{kind}", status_code=201)
def create_base(kind: str, body: dict, request: Request, user: AppUser = Depends(current_user), db: Session = Depends(get_db)):
    item = basedata.create_item(db, kind, body, request_source(request), actor=user.username)
    db.commit()
    return item_out(item)


@router.patch("/base/{kind}/{pk}")
def update_base(kind: str, pk: str, body: dict, request: Request,
                user: AppUser = Depends(current_user), db: Session = Depends(get_db)):
    item = basedata.update_item(db, kind, pk, body, request_source(request), actor=user.username)
    db.commit()
    return item_out(item)
