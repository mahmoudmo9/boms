"""Finance plugs into earlier modules here (loaded by ``app.core.modules.load_hooks``)."""

from app.modules.finance import cleanup, closing, dashboard, guard, ratings
from app.modules.parties.command_center import register_section
from app.modules.sourcing.capabilities import register_suggestion_extra
from app.modules.sourcing.inquiries import register_case_cleanup, register_case_status_guard
from app.modules.sourcing.items import register_closed_check

register_closed_check(closing.closed_check)                         # items closed with the deal, derived on reopen
register_case_status_guard(closing.status_guard)                    # close / reopen through the checklist
register_section("finance", dashboard.summary)                      # command center «مالی»


def _overview(db, today):
    from app.modules.finance import overview

    return overview.summary(db, today)


register_section("overview", _overview)       # v0.10.0: the figures of the command center (ProToday)
register_case_cleanup(0, cleanup.cleanup_case)                      # before execution (1)
register_suggestion_extra("rating", ratings.supplier_averages)      # the average next to each suggested supplier
guard.install()                                                     # a closed deal is read-only

from app.modules.execution.claims import register_claim_resolved  # noqa: E402
from app.modules.finance import sales_invoices  # noqa: E402

register_claim_resolved(sales_invoices.on_claim_resolved)          # v0.9.0: a customer claim's draft credit note
