"""Closing a deal (v0.8.0).

The checklist lists every open obligation together: sold items not delivered or cancelled; sales invoices not issued
or not fully paid and delivered quantities not invoiced; supplier invoices not approved or not paid and received goods
without an invoice; actual costs not paid; open claims; open milestones; guarantees not released (a performance
guarantee or the warranty still running is allowed with a note and keeps its tasks); Moadian status not accepted /
not required; open tasks and follow-ups of the case (closing cancels them, after confirmation).

«Close deal» passes when the checklist does, or with a typed reason for each remaining problem (event). It sets the
items ``closed`` through ``recompute_item_status``, the case ``closed`` and stores the ``deal_result`` snapshot. A
closed case is read-only (409 ``case_closed``) except notes, ratings, documents and «Reopen» (a reason), which
removes the snapshot (event) and derives the items again.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.modules.events import service as events
from app.modules.finance.common import ZERO, reason_required, today
from app.modules.finance.models import DealResult
from app.modules.parties import clock
from app.modules.sourcing.common import flush, jsonable

KEEP_TASK_KINDS = ("warranty_end", "warranty_remind", "guarantee_expiry")
RELEASED = ("released", "cancelled", "claimed")


def ensure_open(db: Session, case_id: uuid.UUID) -> None:
    """Writes on a closed case are refused (409 ``case_closed``) except notes, ratings, documents and reopening."""
    from app.modules.sourcing import inquiries as sourcing

    case = sourcing.get_case(db, case_id)
    if case.status == "closed" and not db.info.get("finance_closing"):
        raise Conflict("case_closed", "The deal is closed; reopen it (with a reason) to change it", {"status": case.status})


def _running_guarantee(g, order) -> bool:
    """A performance guarantee (or the warranty) still running may stay open at close."""
    if g.purpose not in ("performance", "warranty"):
        return False
    return g.valid_until is None or g.valid_until >= today()


def checklist(db: Session, case_id: uuid.UUID) -> dict:
    from app.modules.execution.claims import OPEN as CLAIM_OPEN
    from app.modules.execution.deliveries import warranty_ends_on
    from app.modules.execution.models import Claim, PaymentMilestone, PurchaseOrder, SalesOrder
    from app.modules.finance import costs, payments, purchase_invoices, sales_invoices
    from app.modules.sourcing import inquiries as sourcing
    from app.modules.sourcing.models import LineItem
    from app.modules.tenders.models import Guarantee

    sourcing.get_case(db, case_id)
    problems: list[dict] = []
    notes: list[dict] = []

    def add(code: str, **details) -> None:
        problems.append({"code": code, **jsonable(details)})

    items = list(db.scalars(select(LineItem).where(LineItem.case_id == case_id, LineItem.status == "sold")))
    if items:
        add("items_not_delivered", items=[{"id": i.id, "name": i.name} for i in items])
    orders = list(db.scalars(select(SalesOrder).where(SalesOrder.case_id == case_id, SalesOrder.status != "cancelled")))
    left = []
    for so in orders:
        rest = sales_invoices.delivered_not_invoiced(db, so.id)
        if rest > 0:
            left.append({"sales_order_id": so.id, "number": so.number, "quantity": rest})
    if left:
        add("delivered_not_invoiced", orders=left)
    from app.modules.finance import profit as profit_mod

    no_cost = []
    for so in orders:     # v0.9.0: goods delivered with no purchase cost at all would freeze a profit that is too high
        for row in profit_mod.goods_cost_coverage(db, so.id):
            if row["delivered"] > row["covered"]:
                no_cost.append({"sales_order_item_id": row["item"].id, "description": row["item"].description,
                                "delivered": row["delivered"], "with_cost": row["covered"]})
    if no_cost:
        add("goods_cost_missing", items=no_cost)
    drafts, unpaid, moadian = [], [], []
    for inv in sales_invoices.invoices_of(db, case_id=case_id):
        if inv.status == "draft":
            drafts.append({"id": inv.id, "kind": inv.kind})
        elif inv.status == "issued":
            if inv.kind == "invoice" and sales_invoices.balance_due(db, inv) > 0:
                unpaid.append({"id": inv.id, "number": inv.number, "balance": sales_invoices.balance_due(db, inv),
                               "currency": inv.currency})
            if inv.moadian_status not in ("accepted", "not_required"):
                moadian.append({"id": inv.id, "number": inv.number, "moadian_status": inv.moadian_status})
    if drafts:
        add("invoice_drafts", invoices=drafts)
    if unpaid:
        add("invoices_unpaid", invoices=unpaid)
    if moadian:
        add("moadian_pending", invoices=moadian)
    not_approved, supplier_unpaid = [], []
    for inv in purchase_invoices.invoices_of(db, case_id=case_id):
        if inv.status in ("received", "disputed"):
            not_approved.append({"id": inv.id, "supplier_invoice_no": inv.supplier_invoice_no, "status": inv.status})
        if inv.status == "approved" and purchase_invoices.balance_due(db, inv) > 0:
            supplier_unpaid.append({"id": inv.id, "supplier_invoice_no": inv.supplier_invoice_no,
                                    "balance": purchase_invoices.balance_due(db, inv), "currency": inv.currency})
    if not_approved:
        add("supplier_invoices_not_approved", invoices=not_approved)
    if supplier_unpaid:
        add("supplier_invoices_unpaid", invoices=supplier_unpaid)
    missing = []
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.case_id == case_id,
                                                     PurchaseOrder.status.not_in(("draft", "cancelled", "superseded")))):
        rest = purchase_invoices.received_not_invoiced(db, po.id)
        if rest:
            missing.append({"purchase_order_id": po.id, "number": po.number,
                            "quantity": sum((r["quantity"] for r in rest), ZERO)})
    if missing:
        add("received_not_invoiced", orders=missing)
    open_costs = [{"id": c.id, "description": c.description, "balance": payments.cost_balance(db, c), "currency": c.currency}
                  for c in costs.costs_of(db, case_id) if c.status != "paid"]
    if open_costs:
        add("costs_unpaid", costs=open_costs)
    claims = [{"id": c.id, "kind": c.kind, "status": c.status}
              for c in db.scalars(select(Claim).where(Claim.case_id == case_id, Claim.status.in_(CLAIM_OPEN)))]
    if claims:
        add("claims_open", claims=claims)
    milestones = [{"id": m.id, "kind": m.kind, "direction": m.direction, "status": m.status}
                  for m in db.scalars(select(PaymentMilestone).where(PaymentMilestone.case_id == case_id,
                                                                     PaymentMilestone.status.in_(("expected", "partly"))))]
    if milestones:
        add("milestones_open", milestones=milestones)
    guarantees = []
    for g in db.scalars(select(Guarantee).where(Guarantee.case_id == case_id, Guarantee.status.not_in(RELEASED))):
        if _running_guarantee(g, orders[0] if orders else None):
            notes.append({"code": "guarantee_running", "id": str(g.id), "purpose": g.purpose,
                          "valid_until": g.valid_until.isoformat() if g.valid_until else None})
        else:
            guarantees.append({"id": g.id, "purpose": g.purpose, "status": g.status})
    if guarantees:
        add("guarantees_not_released", guarantees=guarantees)
    for so in orders:
        ends = warranty_ends_on(db, so)
        if ends and ends >= today():
            notes.append({"code": "warranty_running", "sales_order_id": str(so.id), "ends_on": ends.isoformat()})
    open_items = open_tasks_and_followups(db, case_id)
    return {"passes": not problems, "problems": problems, "notes": notes, "to_cancel": open_items}


def open_tasks_and_followups(db: Session, case_id: uuid.UUID) -> dict:
    """Open tasks (except those of a running guarantee or warranty) and the case's follow-ups closing cancels."""
    from app.modules.execution import followups as ex_followups
    from app.modules.tasks import service as tasks

    task_rows = [{"id": t.id, "title": t.title, "kind": t.source_kind, "due_on": t.due_on}
                 for t in tasks.tasks_of(db, case_id=case_id) if t.source_kind not in KEEP_TASK_KINDS]
    followups = [{"id": f.id, "action": f.action, "due_on": f.due_on, "purpose": link.purpose}
                 for link, f in ex_followups.links(db, case_id=case_id) if not hasattr(f, "kind")]
    from app.modules.tenders.models import Tender

    tender = db.scalar(select(Tender).where(Tender.case_id == case_id))
    if tender is not None:
        from app.modules.tenders import reminders

        followups += [{"id": f.id, "action": f.action, "due_on": f.due_on, "purpose": link.purpose}
                      for link, f in reminders.links(db, tender_id=tender.id) if not hasattr(f, "kind")
                      and link.purpose != "guarantee_release"]
    return jsonable({"tasks": task_rows, "followups": followups})


def close(db: Session, case_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> dict:
    """Close the deal: the checklist passes, or every remaining problem has a typed reason (``reasons``: code ->
    text). Open tasks / follow-ups are cancelled only with ``confirm_cancel_open``."""
    from app.modules.finance import profit
    from app.modules.sourcing import inquiries as sourcing
    from app.modules.sourcing import items as sourcing_items
    from app.modules.sourcing.models import LineItem

    case = sourcing.get_case(db, case_id)
    if case.status == "closed":
        raise Conflict("case_closed", "The deal is already closed")
    check = checklist(db, case_id)
    reasons = {k: (v or "").strip() for k, v in (data.get("reasons") or {}).items()}
    unexplained = [p for p in check["problems"] if not reasons.get(p["code"])]
    if unexplained:
        raise Conflict("close_checklist", "The deal has open obligations; resolve them or give a reason for each",
                       {"problems": check["problems"], "unexplained": [p["code"] for p in unexplained],
                        "notes": check["notes"], "to_cancel": check["to_cancel"]})
    open_count = len(check["to_cancel"]["tasks"]) + len(check["to_cancel"]["followups"])
    if open_count and not data.get("confirm_cancel_open"):
        raise Conflict("open_tasks", "Closing cancels the case's open tasks and follow-ups; confirm it",
                       {"to_cancel": check["to_cancel"]})
    note = "deal closed"
    from app.modules.parties import interactions as party_interactions
    from app.modules.tasks import service as tasks

    for t in check["to_cancel"]["tasks"]:
        tasks.cancel(db, uuid.UUID(str(t["id"])), note, source, actor)
    for f in check["to_cancel"]["followups"]:
        party_interactions.cancel_followup(db, uuid.UUID(str(f["id"])), note, source, actor)
    snapshot = profit.compute(db, case_id)
    db.info["finance_closing"] = True
    try:
        db.add(DealResult(case_id=case_id, data=jsonable({**snapshot, "status": "closed"}), computed_at=clock.now(),
                          reasons={p["code"]: reasons[p["code"]] for p in check["problems"]}, closed_by=actor))
        flush(db, "deal_result_exists")
        sourcing.update_case(db, case_id, {"status": "closed"}, source, actor)
        ids = list(db.scalars(select(LineItem.id).where(LineItem.case_id == case_id)))
        sourcing_items.recompute_items(db, ids, source, actor, cause="deal_closed")
    finally:
        db.info.pop("finance_closing", None)
    events.record(db, "case", case_id, "deal_closed", jsonable({
        "problems": [p["code"] for p in check["problems"]], "reasons": reasons, "notes": check["notes"],
        "cancelled": {"tasks": len(check["to_cancel"]["tasks"]), "followups": len(check["to_cancel"]["followups"])},
        "profit": snapshot["profit"]["actual"], "revenue": snapshot["revenue"]["actual"]}), source, actor=actor)
    return profit.result(db, case_id)


def reopen(db: Session, case_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> None:
    from app.modules.sourcing import inquiries as sourcing
    from app.modules.sourcing import items as sourcing_items
    from app.modules.sourcing.models import LineItem

    reason = reason_required(reason)
    case = sourcing.get_case(db, case_id)
    if case.status != "closed":
        raise Conflict("case_not_closed", f"The case is {case.status}", {"status": case.status})
    snap = db.scalar(select(DealResult).where(DealResult.case_id == case_id))
    db.info["finance_closing"] = True
    db.info["finance_reopening"] = case_id
    try:
        if snap is not None:
            data = {"computed_at": snap.computed_at.isoformat(), "profit": snap.data.get("profit"), "reasons": snap.reasons}
            db.delete(snap)
            flush(db, "in_use")
            events.record(db, "deal_result", case_id, "removed", jsonable({**data, "reason": reason}), source, actor=actor)
        sourcing.update_case(db, case_id, {"status": "open"}, source, actor)
        ids = list(db.scalars(select(LineItem.id).where(LineItem.case_id == case_id)))
        sourcing_items.recompute_items(db, ids, source, actor, cause="deal_reopened")
    finally:
        db.info.pop("finance_closing", None)
        db.info.pop("finance_reopening", None)
    events.record(db, "case", case_id, "deal_reopened", {"reason": reason}, source, actor=actor)


# ---- hooks -----------------------------------------------------------------------------------------------------------

def closed_check(db: Session, item) -> bool | None:
    """Items of a deal closed here are ``closed``; reopening derives them again; otherwise not decided here."""
    if db.info.get("finance_reopening") == item.case_id:
        return False
    if item.case_id is None:
        return None
    return True if db.scalar(select(DealResult.id).where(DealResult.case_id == item.case_id)) else None


def status_guard(db: Session, case, new_status: str) -> None:
    """A deal with a sales order is closed and reopened through «بستن» / «بازگشایی», not by editing the status."""
    if db.info.get("finance_closing"):
        return
    from app.modules.execution.models import SalesOrder

    has_order = db.scalar(select(SalesOrder.id).where(SalesOrder.case_id == case.id, SalesOrder.status != "cancelled"))
    if new_status == "closed" and has_order:
        raise Conflict("use_close_deal", "Close the deal with its checklist (case → Finance → Close)")
    if case.status == "closed" and db.scalar(select(DealResult.id).where(DealResult.case_id == case.id)):
        raise Conflict("use_reopen", "Reopen the closed deal with a reason")

