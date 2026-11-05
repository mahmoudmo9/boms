"""Execution plugs into earlier modules (and its own registries) here (loaded by ``app.core.modules.load_hooks``)."""

from app.modules.execution import process, purchase_orders, sales_orders
from app.modules.sourcing.inquiries import register_case_status_changed

sales_orders.register_order_confirmed(process.on_order_confirmed)   # the checklist of the deal type
purchase_orders.register_process_hook(process.on_purchase_order_event)
register_case_status_changed(process.on_case_status)               # a closed case cancels step reminders

from app.modules.execution import cleanup, dashboard, deliveries  # noqa: E402
from app.modules.parties.command_center import register_section  # noqa: E402
from app.modules.sourcing.inquiries import register_case_cleanup  # noqa: E402
from app.modules.sourcing.items import register_delivered_check  # noqa: E402

register_delivered_check(deliveries.is_delivered)                  # delivered only from delivery quantities
register_section("execution", dashboard.summary)                   # command center «اجرا»
register_case_cleanup(1, cleanup.cleanup_case)                     # before tenders (5), quotes (10), sheets (20)
