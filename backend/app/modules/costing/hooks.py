"""Costing plugs into earlier modules here (loaded by ``app.core.modules.load_hooks``)."""

from app.modules.costing import service
from app.modules.sourcing.inquiries import register_case_cleanup

register_case_cleanup(20, service.cleanup_case)  # after the quotes, before the line items / offers
