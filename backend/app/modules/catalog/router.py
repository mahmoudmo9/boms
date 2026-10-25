import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.schemas import page_params
from app.core.web import request_source
from app.modules.catalog import service
from app.modules.catalog.schemas import AliasIn, CategoryIn, ProductCreate, ProductPatch
from app.modules.parties.service import jsonable
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
products_router = APIRouter(prefix="/api/products", tags=["catalog"])


def _product(db: Session, product_id: uuid.UUID) -> dict:
    product = service.get_product(db, product_id)
    aliases = service.aliases_of(db, [product.id])[product.id]
    return {**service.snapshot(product), "aliases": [{"id": str(a.id), "alias": a.alias} for a in aliases]}


def product_page(db: Session, product_id: uuid.UUID) -> dict:
    """Product + price memory + demand + suppliers (by offers and by HS capability). View only."""
    from app.modules.sourcing import capabilities

    product = _product(db, product_id)
    by_capability = capabilities.suggest_suppliers(db, [product["hs_code"]]) if product["hs_code"] else []
    return {**product, "prices": service.price_memory(db, product_id), "demand": service.demand(db, product_id),
            "suppliers_by_offers": service.suppliers_by_offers(db, product_id),
            "suppliers_by_capability": by_capability}


@products_router.get("")
def list_products(_: CurrentUser, db: Db, q: str | None = None, category_id: uuid.UUID | None = None,
                  status: Literal["active", "archived", "all"] = "active",
                  sort: Literal["name", "last_requested", "offers"] = "name", page: int = 1,
                  page_size: Annotated[int, Query(le=200)] = 50):
    page, page_size = page_params(page, page_size, 200)
    rows, total = service.list_products(db, q=q, category_id=category_id, status=None if status == "all" else status,
                                        sort=sort, page=page, page_size=page_size)
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


@products_router.get("/duplicates")
def duplicates(_: CurrentUser, db: Db, name: Annotated[list[str], Query()], exclude: uuid.UUID | None = None):
    return {"possible_duplicates": jsonable(service.find_duplicates(db, name, exclude))}


@products_router.get("/categories")
def categories(_: CurrentUser, db: Db):
    return [service.snapshot(c) for c in service.categories(db)]


@products_router.post("/categories", status_code=201)
def create_category(body: CategoryIn, request: Request, user: CurrentUser, db: Db):
    row = service.create_category(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return service.snapshot(row)


@products_router.delete("/categories/{category_id}", status_code=204)
def delete_category(category_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.delete_category(db, category_id, request_source(request), user.username)
    db.commit()


@products_router.post("")
def create_product(body: ProductCreate, request: Request, response: Response, user: CurrentUser, db: Db):
    product, dups = service.create_product(db, body.model_dump(), request_source(request), user.username)
    if product is None:
        response.status_code = 200
        return {"created": False, "possible_duplicates": jsonable(dups)}
    db.commit()
    response.status_code = 201
    return {"created": True, "possible_duplicates": jsonable(dups), "product": _product(db, product.id)}


@products_router.get("/{product_id}")
def get_product(product_id: uuid.UUID, _: CurrentUser, db: Db):
    return product_page(db, product_id)


@products_router.patch("/{product_id}")
def update_product(product_id: uuid.UUID, body: ProductPatch, request: Request, user: CurrentUser, db: Db):
    service.update_product(db, product_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return _product(db, product_id)


@products_router.post("/{product_id}/archive")
def archive_product(product_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.set_status(db, product_id, "archived", request_source(request), user.username)
    db.commit()
    return _product(db, product_id)


@products_router.post("/{product_id}/unarchive")
def unarchive_product(product_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.set_status(db, product_id, "active", request_source(request), user.username)
    db.commit()
    return _product(db, product_id)


@products_router.delete("/{product_id}", status_code=204)
def delete_product(product_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.delete_product(db, product_id, request_source(request), user.username)
    db.commit()


@products_router.post("/{product_id}/aliases", status_code=201)
def add_alias(product_id: uuid.UUID, body: AliasIn, request: Request, user: CurrentUser, db: Db):
    service.add_alias(db, product_id, body.alias, request_source(request), user.username)
    db.commit()
    return _product(db, product_id)


@products_router.delete("/aliases/{alias_id}", status_code=204)
def remove_alias(alias_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.remove_alias(db, alias_id, request_source(request), user.username)
    db.commit()


ROUTERS = [products_router]
