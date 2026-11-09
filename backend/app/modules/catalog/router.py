import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.schemas import page_params
from app.core.web import request_source
from app.core.schemas import InputModel
from app.modules.catalog import nounmod, service
from app.modules.catalog.schemas import AliasIn, CategoryIn, ProductCreate, ProductPatch, TemplateIn, TemplatePatch
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


# ---- noun-modifier templates (v0.9.0 section 7) ------------------------------------------------------------------

templates_router = APIRouter(prefix="/api/product-templates", tags=["catalog"])


class _PreviewIn(InputModel):
    attributes: dict[str, Any] = {}


@templates_router.get("")
def list_templates(_: CurrentUser, db: Db, include_archived: bool = False):
    from sqlalchemy import select

    from app.modules.catalog.models import ProductTemplate

    stmt = select(ProductTemplate).order_by(ProductTemplate.key)
    if not include_archived:
        stmt = stmt.where(ProductTemplate.status == "active")
    return [nounmod.template_out(t) for t in db.scalars(stmt)]


@templates_router.post("", status_code=201)
def create_template(body: TemplateIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.catalog.models import ProductTemplate
    from app.modules.events import service as events
    from app.modules.sourcing.common import flush

    data = body.model_dump()
    data["attributes"] = nounmod.check_template(data)
    row = ProductTemplate(**data)
    db.add(row)
    flush(db, "invalid_template")
    events.record(db, "product_template", row.id, "create", jsonable(data), request_source(request), actor=user.username)
    db.commit()
    return nounmod.template_out(row)


@templates_router.patch("/{template_id}")
def patch_template(template_id: uuid.UUID, body: TemplatePatch, request: Request, user: CurrentUser, db: Db):
    from app.modules.events import service as events
    from app.modules.sourcing.common import flush

    row = nounmod.get_template(db, template_id)
    changes = body.model_dump(exclude_unset=True)
    if "attributes" in changes:
        changes["attributes"] = nounmod.check_template(changes)
    for key, value in changes.items():
        setattr(row, key, value)
    flush(db, "invalid_template")
    events.record(db, "product_template", row.id, "update", jsonable(changes), request_source(request), actor=user.username)
    db.commit()
    return nounmod.template_out(row)


@templates_router.post("/{template_id}/preview")
def preview_template(template_id: uuid.UUID, body: _PreviewIn, _: CurrentUser, db: Db):
    """The canonical description fa/en the attributes give (validated against the template)."""
    row = nounmod.get_template(db, template_id)
    attrs = nounmod.validate(row, body.attributes)
    return {"attributes": attrs, "canonical_fa": nounmod.canonical(row, attrs, "fa"),
            "canonical_en": nounmod.canonical(row, attrs, "en"),
            "long_fa": nounmod.canonical(row, attrs, "fa", short_only=False),
            "long_en": nounmod.canonical(row, attrs, "en", short_only=False)}


ROUTERS = [products_router, templates_router]
