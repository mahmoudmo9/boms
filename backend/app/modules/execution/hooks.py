"""Execution plugs into earlier modules (and its own registries) here (loaded by ``app.core.modules.load_hooks``)."""

from app.modules.execution import process, purchase_orders, sales_orders
from app.modules.sourcing.inquiries import register_case_status_changed

sales_orders.register_order_confirmed(process.on_order_confirmed)   # the checklist of the deal type
purchase_orders.register_process_hook(process.on_purchase_order_event)
register_case_status_changed(process.on_case_status)               # a closed case cancels step reminders
