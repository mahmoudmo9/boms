"""Finance plugs into earlier modules here (loaded by ``app.core.modules.load_hooks``)."""

from app.modules.finance import cleanup, closing, dashboard, guard, ratings
from app.modules.parties.command_center import register_section
from app.modules.sourcing.capabilities import register_suggestion_extra
from app.modules.sourcing.inquiries import register_case_cleanup, register_case_status_guard
from app.modules.sourcing.items import register_closed_check

register_closed_check(closing.closed_check)                         # items closed with the deal, derived on reopen
register_case_status_guard(closing.status_guard)                    # close / reopen through the checklist
register_section("finance", dashboard.summary)                      # command center «مالی»
register_case_cleanup(0, cleanup.cleanup_case)                      # before execution (1)
register_suggestion_extra("rating", ratings.supplier_averages)      # the average next to each suggested supplier
guard.install()                                                     # a closed deal is read-only
