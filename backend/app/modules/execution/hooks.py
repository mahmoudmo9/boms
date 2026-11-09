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

from app.modules.codes.service import register as _register_code  # noqa: E402
from app.modules.execution import models as _m  # noqa: E402


def _case_of(db, model, row_id):
    row = db.get(model, row_id) if row_id else None
    return getattr(row, "case_id", None)


# v0.9.0: record codes SH-, RCV-, DLV-, PAY-, CLM-, INS-
_register_code("shipment", _m.Shipment, link=lambda _db, r: f"/cases/{r.case_id}?tab=logistics&shipment={r.id}")
_register_code("receipt", _m.Receipt, link=lambda db, r: f"/cases/{_case_of(db, _m.PurchaseOrder, r.purchase_order_id)}?tab=logistics&receipt={r.id}")
_register_code("delivery", _m.Delivery, link=lambda db, r: f"/cases/{_case_of(db, _m.SalesOrder, r.sales_order_id)}?tab=delivery&delivery={r.id}")
_register_code("payment", _m.PaymentRecord, link=lambda db, r: f"/cases/{_case_of(db, _m.PaymentMilestone, r.milestone_id)}?tab=finance&payment={r.id}")
_register_code("claim", _m.Claim, link=lambda _db, r: f"/cases/{r.case_id}?tab=delivery&claim={r.id}")
_register_code("inspection", _m.Inspection, link=lambda _db, r: f"/cases/{r.case_id}?tab=logistics&inspection={r.id}")
