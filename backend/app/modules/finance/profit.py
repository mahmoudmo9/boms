"""Deal profit, actual against plan (v0.8.0). Computed, read-only, per case; frozen in ``ops.deal_result`` at close.

Revenue: issued sales invoices net of credit / debit notes, excluding VAT (subtotal − discount).
Cost, by cost-sheet line kind:
- goods (``purchase``) = approved supplier invoices (subtotal); received goods not yet on an approved invoice at the
  PO price, marked ``estimated``; a supplier invoice without a PO counts as ``other``;
- actual costs by kind (owned rows; ``expected`` ones are ``estimated``) and the read-only rows (tender costs, guarantee
  fees, payment bank fees);
- claim resolutions received (credit note, refund or discount from a supplier, carrier or insurer) lower the cost of
  goods, freight or insurance. A credit given to the customer is a sales credit note (already in revenue).
Plan: the final cost sheet of the accepted quote or approved tender proposal (else the current sheet), limited to the
items of the sales order, by line kind. Cost of money and the guarantee cost are information lines, not in the totals.

Currencies: every figure in the deal currency (the sales order's) and in the base currency (rials). A paid amount is
valued at the real rate of the payments allocated to it, an actual cost at its own rate; what is not paid yet is valued
at the latest rate entered on the case (payments and costs, else the sheet's) and reported as ``unrealized``. The FX
effect «سود/زیان تفاوت نرخ ارز» is the same foreign amounts at the cost sheet's rates against the real rates (gain +).
VAT is outside profit: output VAT, input VAT and net.
Cost of money (actual): the rial cash tied up between payment dates (out − in, when positive) × days × the sheet's
annual percent / 365, next to the planned cost of money.
"""
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.finance import costs as cost_rows
from app.modules.finance import payments, purchase_invoices, sales_invoices
from app.modules.finance.common import ZERO, base_currency, decimals, today
from app.modules.finance.models import PaymentAllocation
from app.modules.sourcing.common import jsonable

KINDS = ("purchase", "freight_international", "insurance", "bank_fees", "customs_duty", "levy", "customs_clearance",
         "storage", "inspection", "freight_domestic", "export_clearance", "other")
HUNDRED = Decimal(100)
CLAIM_KIND = {"against_supplier": "purchase", "against_carrier": "freight_international", "against_insurer": "insurance"}


@dataclass
class Entry:
    side: str                # revenue | cost
    kind: str
    label: str
    amount: Decimal          # in its currency, net of VAT (negative lowers revenue / cost)
    currency: str
    paid_fraction: Decimal = ZERO
    real_rate: Decimal | None = None   # base per unit for the paid part (payments) or the whole (own rate)
    estimated: bool = False
    source: str = ""
    source_id: str | None = None
    values: dict = field(default_factory=dict)


def _q(value: Decimal, places: int) -> Decimal:
    return Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


# ---- rates ------------------------------------------------------------------------------------------------------------

def _sheet_rate(fx: dict, src: str, dst: str, pricing: str | None) -> Decimal | None:
    if src == dst:
        return Decimal(1)
    if (src, dst) in fx:
        return fx[(src, dst)]
    if (dst, src) in fx and fx[(dst, src)]:
        return Decimal(1) / fx[(dst, src)]
    if pricing and pricing not in (src, dst):
        a, b = _sheet_rate(fx, src, pricing, None), _sheet_rate(fx, dst, pricing, None)
        if a is not None and b:
            return a / b
    return None


def _records(db: Session, case_id):
    from app.modules.execution.models import PaymentMilestone, PaymentRecord

    return db.execute(select(PaymentRecord, PaymentMilestone).join(PaymentMilestone, PaymentMilestone.id == PaymentRecord.milestone_id)
                      .where(PaymentMilestone.case_id == case_id).order_by(PaymentRecord.paid_on, PaymentRecord.created_at)).all()


def latest_rates(db: Session, case_id) -> dict:
    """The latest real rate to the base currency entered on the case per currency (payments, then actual costs)."""
    dated: dict[str, tuple] = {}
    for r, _ms in _records(db, case_id):
        if r.fx_rate_to_base:
            key = (r.paid_on, r.created_at)
            if r.amount_currency not in dated or key >= dated[r.amount_currency][0]:
                dated[r.amount_currency] = (key, r.fx_rate_to_base)
    for c in cost_rows.costs_of(db, case_id):
        if c.fx_rate_to_base:
            key = (c.incurred_on or c.created_at.date(), c.created_at)
            if c.currency not in dated or key >= dated[c.currency][0]:
                dated[c.currency] = (key, c.fx_rate_to_base)
    return {cur: rate for cur, (_k, rate) in dated.items()}


# ---- plan ---------------------------------------------------------------------------------------------------------------

def _order(db: Session, case_id):
    from app.modules.execution.models import SalesOrder

    return db.scalar(select(SalesOrder).where(SalesOrder.case_id == case_id, SalesOrder.status != "cancelled")
                     .order_by(SalesOrder.created_at).limit(1))


def _plan_sheet(db: Session, case_id, order):
    from app.modules.costing import service as costing
    from app.modules.costing.models import CostSheet

    sheet_id = None
    if order is not None and order.quote_id:
        from app.modules.quotes.models import Quote

        quote = db.get(Quote, order.quote_id)
        sheet_id = quote.cost_sheet_id if quote else None
    elif order is not None and order.tender_proposal_id:
        from app.modules.tenders.models import TenderProposal

        proposal = db.get(TenderProposal, order.tender_proposal_id)
        sheet_id = proposal.cost_sheet_id if proposal else None
    return db.get(CostSheet, sheet_id) if sheet_id else costing.current_sheet(db, case_id)


def plan(db: Session, case_id, order=None) -> dict | None:
    from app.modules.costing import service as costing
    from app.modules.execution.sales_orders import items_of

    order = order if order is not None else _order(db, case_id)
    sheet = _plan_sheet(db, case_id, order)
    if sheet is None:
        return None
    try:
        comp = costing.compute_sheet(db, sheet)
    except Exception as exc:  # an incomplete sheet: no plan, said so
        return {"error": getattr(exc, "code", "plan_unavailable"), "sheet_id": str(sheet.id)}
    wanted = {str(i.line_item_id) for i in items_of(db, order.id)} if order is not None else None
    by_kind = {k: ZERO for k in KINDS}
    revenue = com = guarantee = ZERO
    for row in comp["items"]:
        if wanted is not None and row["item_id"] not in wanted:
            continue
        for line in row["lines"]:
            if line["kind"] in by_kind:
                by_kind[line["kind"]] += line["amount"]
        revenue += row["total_price"] or ZERO
        com += row["cost_of_money"] or ZERO
        guarantee += row["guarantee"] or ZERO
    fx = {(e.from_currency, e.to_currency): e.rate for e in costing.fx_of(db, sheet.id)}
    return {"sheet_id": str(sheet.id), "version": sheet.version, "currency": sheet.pricing_currency, "by_kind": by_kind,
            "revenue": revenue, "cost": sum(by_kind.values(), ZERO), "cost_of_money": com, "guarantee": guarantee,
            "fx": fx, "annual_percent": sheet.annual_cost_of_money_percent}


# ---- actual entries -------------------------------------------------------------------------------------------------------

def _paid(db: Session, allocations: list[PaymentAllocation], gross: Decimal) -> tuple[Decimal, Decimal | None]:
    """(paid fraction of ``gross``, real base rate per target unit) from the allocations and their payments' rates."""
    from app.modules.execution.models import PaymentRecord

    target = base = ZERO
    for a in allocations:
        r = db.get(PaymentRecord, a.payment_record_id)
        if r is None or r.base_amount is None:
            continue
        target += a.target_amount
        base += r.base_amount * a.amount / r.amount
    if target <= 0 or gross <= 0:
        return ZERO, None
    return min(Decimal(1), target / gross), base / target


def entries(db: Session, case_id) -> list[Entry]:
    out: list[Entry] = []
    base = base_currency(db)
    for inv in sales_invoices.invoices_of(db, case_id=case_id):
        if inv.status != "issued":
            continue
        net = inv.subtotal - (inv.discount or ZERO)
        sign = Decimal(-1) if inv.kind == "credit_note" else Decimal(1)
        frac, rate = _paid(db, payments.allocations_of(db, sales_invoice_id=inv.id), inv.total) if inv.kind != "credit_note" \
            else (ZERO, None)
        out.append(Entry("revenue", "revenue", inv.number or "", sign * net, inv.currency, frac, rate,
                         source="sales_invoice", source_id=str(inv.id)))
    # goods: approved supplier invoices; received goods not on an approved invoice at the PO price (estimated)
    approved_qty: dict = {}
    for inv in purchase_invoices.invoices_of(db, case_id=case_id):
        if inv.status != "approved":
            continue
        frac, rate = _paid(db, payments.allocations_of(db, purchase_invoice_id=inv.id), inv.total)
        out.append(Entry("cost", "purchase" if inv.purchase_order_id else "other", inv.supplier_invoice_no, inv.subtotal,
                         inv.currency, frac, rate, source="purchase_invoice", source_id=str(inv.id)))
        for line in purchase_invoices.lines_of(db, inv.id):
            if line.purchase_order_item_id:
                approved_qty[line.purchase_order_item_id] = approved_qty.get(line.purchase_order_item_id, ZERO) + line.quantity
    from app.modules.execution.models import PurchaseOrder
    from app.modules.execution.purchase_orders import items_of as po_items

    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.case_id == case_id,
                                                     PurchaseOrder.status.not_in(("draft", "cancelled", "superseded")))):
        for item in po_items(db, po.id):
            qty = item.received_quantity - approved_qty.get(item.id, ZERO)
            if qty > 0:
                out.append(Entry("cost", "purchase", f"{po.number}: {item.description}", qty * item.unit_price, po.currency,
                                 estimated=True, source="received_not_invoiced", source_id=str(item.id)))
    for c in cost_rows.costs_of(db, case_id):
        rate = Decimal(1) if c.currency == base else c.fx_rate_to_base
        out.append(Entry("cost", c.kind, c.description, c.amount, c.currency, Decimal(1) if rate else ZERO, rate,
                         estimated=c.status == "expected", source="actual_cost", source_id=str(c.id)))
    for row in cost_rows.sourced_rows(db, case_id):
        amount = Decimal(str(row["amount"]))
        rate = Decimal(1) if row["currency"] == base else (Decimal(str(row["fx_rate_to_base"])) if row.get("fx_rate_to_base") else None)
        out.append(Entry("cost", row["kind"], row["description"], amount, row["currency"], Decimal(1) if rate else ZERO, rate,
                         source=row["source"], source_id=str(row["source_id"])))
    from app.modules.execution.models import Claim

    for claim in db.scalars(select(Claim).where(Claim.case_id == case_id, Claim.status == "resolved",
                                                Claim.resolution.in_(("credit_note", "refund", "discount")))):
        kind = CLAIM_KIND.get(claim.direction)
        if kind and claim.resolution_amount:
            out.append(Entry("cost", kind, f"claim {claim.kind}", -claim.resolution_amount,
                             claim.resolution_amount_currency or base, source="claim", source_id=str(claim.id)))
    return out


# ---- the computation ---------------------------------------------------------------------------------------------------------

def cost_of_money(db: Session, case_id, annual_percent: Decimal, until: date) -> dict:
    """Rial cash tied up between payment dates (out − in when positive) × days × annual percent / 365."""
    moves: dict[date, Decimal] = {}
    for r, ms in _records(db, case_id):
        if r.base_amount is None:
            continue
        moves[r.paid_on] = moves.get(r.paid_on, ZERO) + (r.base_amount if ms.direction == "out" else -r.base_amount)
    if not moves:
        return {"amount": ZERO, "days": 0, "tied_days": ZERO}
    days = sorted(moves)
    end = max(until, days[-1])
    balance = ZERO
    weighted = ZERO           # rial-days
    tied = 0
    for i, d in enumerate(days):
        balance += moves[d]
        nxt = days[i + 1] if i + 1 < len(days) else end
        span = (nxt - d).days
        if balance > 0 and span > 0:
            weighted += balance * span
            tied += span
    return {"amount": weighted * annual_percent / HUNDRED / Decimal(365), "days": tied, "rial_days": weighted}


def compute(db: Session, case_id: uuid.UUID, *, until: date | None = None) -> dict:
    order = _order(db, case_id)
    base = base_currency(db)
    deal = order.currency if order is not None else base
    p = plan(db, case_id, order)
    plan_ok = p is not None and "error" not in p
    sheet_fx = p["fx"] if plan_ok else {}
    pricing = p["currency"] if plan_ok else None
    latest = latest_rates(db, case_id)
    missing: set[str] = set()

    def latest_rate(cur: str) -> Decimal | None:
        if cur == base:
            return Decimal(1)
        if cur in latest:
            return latest[cur]
        rate = _sheet_rate(sheet_fx, cur, base, pricing)
        if rate is None:
            missing.add(cur)
        return rate

    def sheet_rate(cur: str) -> Decimal | None:
        return _sheet_rate(sheet_fx, cur, base, pricing)

    def to_deal(amount_cur: Decimal, cur: str, base_value: Decimal) -> Decimal:
        if cur == deal:
            return amount_cur
        if deal == base:
            return base_value
        r = latest_rate(deal)
        return base_value / r if r else ZERO

    rows = entries(db, case_id)
    fx_effect = ZERO
    unrealized = {"revenue": ZERO, "cost": ZERO}
    for e in rows:
        if e.currency == base:
            base_value, open_part = e.amount, ZERO
        else:
            lr = latest_rate(e.currency) or ZERO
            paid = e.amount * e.paid_fraction
            open_part = e.amount - paid
            base_value = paid * (e.real_rate or lr) + open_part * lr
            unrealized[e.side] += open_part * lr
            sr = sheet_rate(e.currency)
            if sr is not None:
                at_sheet = e.amount * sr
                fx_effect += (base_value - at_sheet) if e.side == "revenue" else (at_sheet - base_value)
        e.values = {"base": base_value, "deal": to_deal(e.amount, e.currency, base_value), "unrealized": open_part}

    ddec, bdec = decimals(db, deal), decimals(db, base)

    def pair(deal_value: Decimal, base_value: Decimal) -> dict:
        return {"deal": _q(deal_value, ddec), "base": _q(base_value, bdec)}

    def plan_pair(value: Decimal) -> dict | None:
        if not plan_ok:
            return None
        to_base = _sheet_rate(sheet_fx, pricing, base, pricing) if pricing != base else Decimal(1)
        to_d = Decimal(1) if pricing == deal else _sheet_rate(sheet_fx, pricing, deal, pricing)
        return {"deal": _q(value * to_d, ddec) if to_d is not None else None,
                "base": _q(value * to_base, bdec) if to_base is not None else None}

    def var(planned: dict | None, actual: dict) -> tuple[dict | None, Decimal | None]:
        if planned is None:
            return None, None
        out = {k: (actual[k] - planned[k]) if planned.get(k) is not None else None for k in ("deal", "base")}
        pct = (out["deal"] / planned["deal"] * HUNDRED).quantize(Decimal("0.01")) if planned.get("deal") else None
        return out, pct

    table = []
    total_cost_deal = total_cost_base = ZERO
    for kind in KINDS:
        mine = [e for e in rows if e.side == "cost" and e.kind == kind]
        a_deal = sum((e.values["deal"] for e in mine), ZERO)
        a_base = sum((e.values["base"] for e in mine), ZERO)
        total_cost_deal += a_deal
        total_cost_base += a_base
        planned = plan_pair(p["by_kind"][kind]) if plan_ok else None
        if not mine and (planned is None or not p["by_kind"][kind]):
            continue
        actual = pair(a_deal, a_base)
        variance, pct = var(planned, actual)
        table.append({"kind": kind, "planned": planned, "actual": actual, "variance": variance, "variance_percent": pct,
                      "estimated": any(e.estimated for e in mine),
                      "unrealized": any(e.values["unrealized"] for e in mine)})
    rev = [e for e in rows if e.side == "revenue"]
    revenue = pair(sum((e.values["deal"] for e in rev), ZERO), sum((e.values["base"] for e in rev), ZERO))
    cost = pair(total_cost_deal, total_cost_base)
    profit = {k: revenue[k] - cost[k] for k in ("deal", "base")}
    p_rev = plan_pair(p["revenue"]) if plan_ok else None
    p_cost = plan_pair(p["cost"]) if plan_ok else None
    p_profit = {k: p_rev[k] - p_cost[k] for k in ("deal", "base")} if plan_ok and p_rev["deal"] is not None and \
        p_cost["deal"] is not None and p_rev["base"] is not None and p_cost["base"] is not None else None

    def pct(num: Decimal, den: Decimal) -> Decimal | None:
        return (num / den * HUNDRED).quantize(Decimal("0.01")) if den else None

    # VAT, outside profit
    out_vat = in_vat = ZERO
    for inv in sales_invoices.invoices_of(db, case_id=case_id):
        if inv.status == "issued":
            r = latest_rate(inv.currency) or ZERO
            out_vat += (-1 if inv.kind == "credit_note" else 1) * inv.vat_amount * r
    for inv in purchase_invoices.invoices_of(db, case_id=case_id):
        if inv.status == "approved":
            in_vat += inv.vat_amount * (latest_rate(inv.currency) or ZERO)
    for c in cost_rows.costs_of(db, case_id):
        if c.vat_amount:
            in_vat += c.vat_amount * (Decimal(1) if c.currency == base else (c.fx_rate_to_base or latest_rate(c.currency) or ZERO))
    r_deal = latest_rate(deal) or Decimal(1)

    def base_pair(value: Decimal) -> dict:
        return pair(value / r_deal if deal != base else value, value)

    annual = p["annual_percent"] if plan_ok else ZERO
    com = cost_of_money(db, case_id, annual or ZERO, until or today())
    from app.modules.sourcing import inquiries as sourcing

    closed = sourcing.get_case(db, case_id).status == "closed"
    expected = None
    if not closed:
        so_net = (order.subtotal if order is not None else ZERO)
        exp_rev = max(revenue["deal"], so_net)
        exp_cost = ZERO
        for kind in KINDS:
            mine = next((r for r in table if r["kind"] == kind), None)
            actual_deal = mine["actual"]["deal"] if mine else ZERO
            planned_deal = (mine["planned"]["deal"] if mine and mine["planned"] else
                            (plan_pair(p["by_kind"][kind])["deal"] if plan_ok and p["by_kind"][kind] else ZERO)) or ZERO
            exp_cost += actual_deal if actual_deal else planned_deal
        expected = {"revenue": _q(exp_rev, ddec), "cost": _q(exp_cost, ddec), "profit": _q(exp_rev - exp_cost, ddec)}
    return jsonable({
        "case_id": case_id, "status": "closed" if closed else "open", "deal_currency": deal, "base_currency": base,
        "plan": None if p is None else ({"error": p["error"]} if not plan_ok else
                                        {"sheet_id": p["sheet_id"], "version": p["version"], "currency": pricing}),
        "rows": table,
        "revenue": {"planned": p_rev, "actual": revenue, "variance": var(p_rev, revenue)[0]},
        "cost": {"planned": p_cost, "actual": cost, "variance": var(p_cost, cost)[0]},
        "profit": {"planned": p_profit, "actual": profit, "variance": var(p_profit, profit)[0] if p_profit else None},
        "margin_percent": {"planned": pct(p_profit["deal"], p_rev["deal"]) if p_profit else None,
                           "actual": pct(profit["deal"], revenue["deal"])},
        "markup_percent": {"planned": pct(p_profit["deal"], p_cost["deal"]) if p_profit else None,
                           "actual": pct(profit["deal"], cost["deal"])},
        "fx_effect": base_pair(fx_effect),
        "unrealized": {"revenue": _q(unrealized["revenue"], bdec), "cost": _q(unrealized["cost"], bdec)},
        "vat": {"output": base_pair(out_vat), "input": base_pair(in_vat), "net": base_pair(out_vat - in_vat)},
        "cost_of_money": {"planned": plan_pair(p["cost_of_money"]) if plan_ok else None,
                          "actual": base_pair(com["amount"]), "days": com["days"], "annual_percent": annual},
        "guarantee_planned": plan_pair(p["guarantee"]) if plan_ok else None,
        "expected": expected,
        "rates": {"latest": latest, "sheet": {f"{a}->{b}": r for (a, b), r in sheet_fx.items()}},
        "missing_rates": sorted(missing),
        "entries": [{"side": e.side, "kind": e.kind, "label": e.label, "amount": e.amount, "currency": e.currency,
                     "paid_fraction": e.paid_fraction, "real_rate": e.real_rate, "estimated": e.estimated,
                     "source": e.source, "source_id": e.source_id, "deal": _q(e.values["deal"], ddec),
                     "base": _q(e.values["base"], bdec), "unrealized": e.values["unrealized"]} for e in rows],
    })


def result(db: Session, case_id: uuid.UUID) -> dict:
    """The frozen snapshot of a closed deal, else the live computation."""
    from app.modules.finance.models import DealResult

    snap = db.scalar(select(DealResult).where(DealResult.case_id == case_id))
    if snap is not None:
        return {**snap.data, "frozen": True, "computed_at": snap.computed_at.isoformat()}
    return {**compute(db, case_id), "frozen": False}

