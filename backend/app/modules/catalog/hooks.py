"""Catalog plugs into later core services here (loaded by ``app.core.modules.load_hooks``)."""
import re

from app.modules.catalog.models import Product
from app.modules.codes.service import register


def _product_context(_db, product) -> dict:
    digits = re.sub(r"\D", "", product.hs_code or "")
    return {"hs4": digits[:4] if len(digits) >= 4 else "0000"}


register("product", Product, context=_product_context, link=lambda _db, r: f"/sourcing/catalog/{r.id}")
