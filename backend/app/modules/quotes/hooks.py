"""Quotes plug into earlier modules here (loaded by ``app.core.modules.load_hooks``)."""

from sqlalchemy import func, select

from app.modules.costing.usage import register_sheet_usage
from app.modules.parties.command_center import register_sourcing_extension
from app.modules.quotes import service
from app.modules.quotes.models import Quote
from app.modules.sourcing.inquiries import register_case_cleanup
from app.modules.sourcing.items import register_sold_check


def _sheet_usage(db, sheet_id) -> int:
    return db.scalar(select(func.count()).select_from(Quote).where(Quote.cost_sheet_id == sheet_id)) or 0


register_sold_check(service.is_sold)
register_sheet_usage(_sheet_usage)
register_sourcing_extension(service.dashboard)
register_case_cleanup(10, service.cleanup_case)  # before the cost sheets the quotes point at
