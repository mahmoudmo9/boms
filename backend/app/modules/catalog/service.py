"""Public service of the catalog module: products, aliases, categories, price and demand memory."""

import uuid

from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.catalog.models import Product


def get_product(db: Session, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound("not_found", "Product not found")
    return product
