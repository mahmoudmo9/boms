"""Tenders plug into earlier modules here (loaded by ``app.core.modules.load_hooks``)."""

from app.modules.parties.command_center import register_section
from app.modules.quotes.service import register_product_quote_rows, register_terms_source
from app.modules.sourcing.inquiries import register_case_cleanup, register_case_converted, register_case_status_changed
from app.modules.sourcing.items import register_sold_check
from app.modules.tenders import cleanup, dashboard, proposal, results, service
from app.modules.tenders.common import tender_of_case


def _case_status(db, case, old_status, source, actor) -> None:
    """A cancelled case cancels its tender's open reminders (dates, opening, contract)."""
    if case.status != "cancelled":
        return
    from app.modules.tenders import reminders

    tender = tender_of_case(db, case.id)
    if tender is not None:
        reminders.cancel(db, "case cancelled", source, actor, tender_id=tender.id,
                         purposes=("date_reminder", "opening", "contract"))


register_case_converted(service.on_case_converted)       # an inquiry of kind "tender" gets its tender part
register_case_status_changed(_case_status)
register_case_cleanup(5, cleanup.cleanup_case)            # before the quotes (10) and the cost sheets (20)
register_sold_check(results.is_sold)                      # a won tender sells the case's items


def _terms(db, quote):
    """Letterhead mode: a Persian quote of a tender case uses "Tender (fa)" with the tender number."""
    tender = tender_of_case(db, quote.case_id)
    if tender is None or tender.financial_mode != "letterhead":
        return None
    return {"template_name": "Tender (fa)", "number": tender.tender_no or ""}


register_terms_source(_terms)
register_product_quote_rows(proposal.proposals_for_product)
register_section("tenders", dashboard.summary)
