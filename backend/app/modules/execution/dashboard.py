"""Command center section «اجرا» (v0.7.0): what needs the owner now in execution and shipping."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.execution import logistics, milestones
from app.modules.execution.models import Claim, PaymentMilestone, Process, ProcessStep, PurchaseOrder, SalesOrder
from app.modules.sourcing.common import jsonable
from app.modules.sourcing.models import Case
from app.modules.system import settings


def _title(db: Session, case_id) -> str:
    case = db.get(Case, case_id)
    return case.title if case else ""


def summary(db: Session, today: date) -> dict:
    confirm_days = settings.get(db, "execution.po_confirm_days")
    unconfirmed = [{"purchase_order_id": po.id, "case_id": po.case_id, "number": po.number, "sent_at": po.sent_at,
                    "days": (today - po.sent_at.date()).days, "case_title": _title(db, po.case_id)}
                   for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "sent")
                                        .order_by(PurchaseOrder.sent_at))
                   if po.sent_at and (today - po.sent_at.date()).days >= confirm_days]
    warnings = logistics.delay_warnings(db, on=today)
    for w in warnings:
        w["case_title"] = _title(db, w["case_id"])
    steps = []
    rows = db.execute(select(ProcessStep, Process).join(Process, Process.id == ProcessStep.process_id).where(
        ProcessStep.status.in_(("pending", "in_progress")), ProcessStep.due_on.is_not(None),
        ProcessStep.due_on <= today + timedelta(days=3)).order_by(ProcessStep.due_on)).all()
    for step, process in rows:
        steps.append({"step_id": step.id, "case_id": process.case_id, "label_fa": step.label_fa, "label_en": step.label_en,
                      "due_on": step.due_on, "overdue": step.due_on < today, "case_title": _title(db, process.case_id)})
    payments = []
    for ms in db.scalars(select(PaymentMilestone).where(PaymentMilestone.status.in_(("expected", "partly")),
                                                        PaymentMilestone.due_on < today).order_by(PaymentMilestone.due_on)):
        amount, currency = milestones.expected_amount(db, ms)
        payments.append({"milestone_id": ms.id, "case_id": ms.case_id, "direction": ms.direction, "kind": ms.kind,
                         "due_on": ms.due_on, "amount": amount, "currency": currency, "case_title": _title(db, ms.case_id)})
    claims = [{"claim_id": c.id, "case_id": c.case_id, "kind": c.kind, "direction": c.direction, "status": c.status,
               "opened_on": c.opened_on, "case_title": _title(db, c.case_id)}
              for c in db.scalars(select(Claim).where(Claim.status.in_(("open", "submitted", "negotiating")))
                                  .order_by(Claim.opened_on))]
    deliveries = [{"sales_order_id": so.id, "case_id": so.case_id, "number": so.number, "delivery_due_on": so.delivery_due_on,
                   "overdue": so.delivery_due_on < today, "case_title": _title(db, so.case_id)}
                  for so in db.scalars(select(SalesOrder).where(SalesOrder.status.in_(("confirmed", "in_progress")),
                                                                SalesOrder.delivery_due_on.is_not(None),
                                                                SalesOrder.delivery_due_on <= today + timedelta(days=7))
                                       .order_by(SalesOrder.delivery_due_on))]
    return jsonable({
        "pos_unconfirmed": unconfirmed,
        "ready_passed": [w for w in warnings if w["kind"] == "ready_passed"],
        "shipments_delayed": [w for w in warnings if w["kind"] in ("eta_passed", "eta_moved")],
        "steps_due": steps, "payments_overdue": payments, "claims_open": claims, "deliveries_due": deliveries,
    })
