"""The finance workspace «مالی معاملات» (v0.8.0): receivables with aging, payables, invoices, payments, deals, VAT,
and the CSV exports for the accountant (UTF-8 with BOM, headers in the UI language, dates in the user's calendar plus
an ISO column; «Export all for period» zips them with the standard library). No general ledger.
"""
import csv
import io
import uuid
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.finance import costs, payments, profit, purchase_invoices, sales_invoices
from app.modules.finance.common import ZERO, base_currency, money, today
from app.modules.finance.models import ActualCost, PurchaseInvoice, SalesInvoice
from app.modules.sourcing.common import jsonable

BUCKETS = ("0-30", "31-60", "61-90", "90+")


def bucket(days_past_due: int) -> str:
    """Aging by days past the due date: 0-30 (including not yet due), 31-60, 61-90, 90+."""
    if days_past_due <= 30:
        return "0-30"
    if days_past_due <= 60:
        return "31-60"
    if days_past_due <= 90:
        return "61-90"
    return "90+"


def _party_names(db: Session, ids) -> dict:
    from app.modules.parties.models import Party

    ids = {i for i in ids if i}
    return {p.id: {"name_fa": p.name_fa, "name_en": p.name_en} for p in db.scalars(select(Party).where(Party.id.in_(ids)))} if ids else {}


def _case_titles(db: Session, ids) -> dict:
    from app.modules.sourcing.models import Case

    ids = {i for i in ids if i}
    return {c.id: c.title for c in db.scalars(select(Case).where(Case.id.in_(ids)))} if ids else {}


def receivables(db: Session, on: date | None = None) -> dict:
    on = on or today()
    rows = []
    for inv in db.scalars(select(SalesInvoice).where(SalesInvoice.status == "issued", SalesInvoice.kind == "invoice")
                          .order_by(SalesInvoice.due_date, SalesInvoice.issue_date)):
        due = sales_invoices.balance_due(db, inv)
        if due <= 0:
            continue
        past = (on - (inv.due_date or inv.issue_date)).days
        rows.append({"invoice_id": inv.id, "number": inv.number, "case_id": inv.case_id, "party_id": inv.customer_party_id,
                     "issue_date": inv.issue_date, "due_date": inv.due_date, "currency": inv.currency, "total": inv.total,
                     "balance": due, "days_past_due": max(0, past), "overdue": past > 0, "bucket": bucket(past)})
    names, titles = _party_names(db, [r["party_id"] for r in rows]), _case_titles(db, [r["case_id"] for r in rows])
    by_party: dict = {}
    for r in rows:
        r["party"], r["case_title"] = names.get(r["party_id"]), titles.get(r["case_id"])
        key = (r["party_id"], r["currency"])
        entry = by_party.setdefault(key, {"party_id": r["party_id"], "party": r["party"], "currency": r["currency"],
                                          "total": ZERO, **{b: ZERO for b in BUCKETS}})
        entry[r["bucket"]] += r["balance"]
        entry["total"] += r["balance"]
    advances = payments.unallocated_advances(db)
    for a in advances:
        a["party"] = names.get(uuid.UUID(a["party_id"])) or _party_names(db, [uuid.UUID(a["party_id"])]).get(uuid.UUID(a["party_id"]))
    return jsonable({"on": on, "invoices": rows, "by_party": list(by_party.values()), "advances": advances})


def payables(db: Session, on: date | None = None) -> dict:
    on = on or today()
    rows = []
    for inv in db.scalars(select(PurchaseInvoice).where(PurchaseInvoice.status != "cancelled")
                          .order_by(PurchaseInvoice.due_date, PurchaseInvoice.invoice_date)):
        due = purchase_invoices.balance_due(db, inv)
        if due > 0:
            rows.append({"kind": "purchase_invoice", "id": inv.id, "label": inv.supplier_invoice_no, "case_id": inv.case_id,
                         "party_id": inv.supplier_party_id, "due_date": inv.due_date, "currency": inv.currency,
                         "total": inv.total, "balance": due, "status": inv.status})
    for c in db.scalars(select(ActualCost).where(ActualCost.status != "paid").order_by(ActualCost.due_date)):
        due = payments.cost_balance(db, c)
        if due > 0:
            rows.append({"kind": "actual_cost", "id": c.id, "label": c.description, "case_id": c.case_id, "party_id": c.party_id,
                         "due_date": c.due_date or c.incurred_on, "currency": c.currency, "total": c.amount + (c.vat_amount or ZERO),
                         "balance": due, "status": c.status})
    names, titles = _party_names(db, [r["party_id"] for r in rows]), _case_titles(db, [r["case_id"] for r in rows])
    windows = {"overdue": [], "due_7": [], "due_30": [], "later": []}
    for r in rows:
        r["party"], r["case_title"] = names.get(r["party_id"]), titles.get(r["case_id"])
        d = r["due_date"]
        r["window"] = ("later" if d is None else "overdue" if d < on else "due_7" if d <= on + timedelta(days=7)
                       else "due_30" if d <= on + timedelta(days=30) else "later")
        windows[r["window"]].append(r["id"])
    by_party: dict = {}
    for r in rows:
        key = (r["party_id"], r["currency"])
        entry = by_party.setdefault(key, {"party_id": r["party_id"], "party": r["party"], "currency": r["currency"],
                                          "total": ZERO, "overdue": ZERO, "due_7": ZERO, "due_30": ZERO, "later": ZERO})
        entry[r["window"]] += r["balance"]
        entry["total"] += r["balance"]
    return jsonable({"on": on, "items": rows, "by_party": list(by_party.values()),
                     "counts": {k: len(v) for k, v in windows.items()}})


def invoices(db: Session, *, kind: str = "sales", status: str | None = None, moadian_status: str | None = None,
             date_from: date | None = None, date_to: date | None = None, party_id=None, case_id=None) -> list[dict]:
    if kind == "sales":
        query = select(SalesInvoice)
        if status:
            query = query.where(SalesInvoice.status == status)
        if moadian_status:
            query = query.where(SalesInvoice.moadian_status == moadian_status)
        if date_from:
            query = query.where(SalesInvoice.issue_date >= date_from)
        if date_to:
            query = query.where(SalesInvoice.issue_date <= date_to)
        if party_id:
            query = query.where(SalesInvoice.customer_party_id == party_id)
        if case_id:
            query = query.where(SalesInvoice.case_id == case_id)
        rows = list(db.scalars(query.order_by(SalesInvoice.issue_date.desc().nulls_first(), SalesInvoice.created_at.desc())))
        names, titles = _party_names(db, [r.customer_party_id for r in rows]), _case_titles(db, [r.case_id for r in rows])
        return jsonable([{"id": r.id, "number": r.number, "kind": r.kind, "status": r.status, "language": r.language,
                          "issue_date": r.issue_date, "due_date": r.due_date, "currency": r.currency, "subtotal": r.subtotal,
                          "vat_amount": r.vat_amount, "total": r.total, "moadian_status": r.moadian_status,
                          "moadian_tax_id": r.moadian_tax_id, "balance": sales_invoices.balance_due(db, r) if r.kind == "invoice" else None,
                          "payment_status": sales_invoices.payment_status(db, r), "party_id": r.customer_party_id,
                          "party": names.get(r.customer_party_id), "case_id": r.case_id, "case_title": titles.get(r.case_id)}
                         for r in rows])
    query = select(PurchaseInvoice)
    if status:
        query = query.where(PurchaseInvoice.status == status)
    if date_from:
        query = query.where(PurchaseInvoice.invoice_date >= date_from)
    if date_to:
        query = query.where(PurchaseInvoice.invoice_date <= date_to)
    if party_id:
        query = query.where(PurchaseInvoice.supplier_party_id == party_id)
    if case_id:
        query = query.where(PurchaseInvoice.case_id == case_id)
    rows = list(db.scalars(query.order_by(PurchaseInvoice.invoice_date.desc(), PurchaseInvoice.created_at.desc())))
    names, titles = _party_names(db, [r.supplier_party_id for r in rows]), _case_titles(db, [r.case_id for r in rows])
    return jsonable([{"id": r.id, "number": r.supplier_invoice_no, "status": r.status, "issue_date": r.invoice_date,
                      "due_date": r.due_date, "currency": r.currency, "subtotal": r.subtotal, "vat_amount": r.vat_amount,
                      "total": r.total, "balance": purchase_invoices.balance_due(db, r),
                      "payment_status": purchase_invoices.payment_status(db, r), "party_id": r.supplier_party_id,
                      "party": names.get(r.supplier_party_id), "case_id": r.case_id, "case_title": titles.get(r.case_id)}
                     for r in rows])


def payment_list(db: Session, *, date_from: date | None = None, date_to: date | None = None, direction: str | None = None) -> list[dict]:
    from app.modules.execution.models import PaymentMilestone, PaymentRecord

    query = select(PaymentRecord, PaymentMilestone).join(PaymentMilestone, PaymentMilestone.id == PaymentRecord.milestone_id)
    if date_from:
        query = query.where(PaymentRecord.paid_on >= date_from)
    if date_to:
        query = query.where(PaymentRecord.paid_on <= date_to)
    if direction:
        query = query.where(PaymentMilestone.direction == direction)
    rows = db.execute(query.order_by(PaymentRecord.paid_on.desc(), PaymentRecord.created_at.desc())).all()
    out = [payments.record_out(db, r, ms) for r, ms in rows]
    names, titles = _party_names(db, [ms.party_id for _r, ms in rows]), _case_titles(db, [ms.case_id for _r, ms in rows])
    for o, (_r, ms) in zip(out, rows):
        o["party"], o["case_title"] = names.get(ms.party_id), titles.get(ms.case_id)
    return out


def deals(db: Session, *, state: str | None = None, date_from: date | None = None, date_to: date | None = None) -> list[dict]:
    """One row per case with a sales order: revenue, cost, profit, margin (planned and actual), status."""
    from app.modules.execution.models import SalesOrder
    from app.modules.sourcing.models import Case

    query = select(Case).where(Case.id.in_(select(SalesOrder.case_id).where(SalesOrder.status != "cancelled")))
    if state == "open":
        query = query.where(Case.status != "closed")
    elif state == "closed":
        query = query.where(Case.status == "closed")
    out = []
    for case in db.scalars(query.order_by(Case.updated_at.desc())):
        order = db.scalar(select(SalesOrder).where(SalesOrder.case_id == case.id, SalesOrder.status != "cancelled")
                          .order_by(SalesOrder.created_at).limit(1))
        on = (order.confirmed_at or order.created_at).date()
        if (date_from and on < date_from) or (date_to and on > date_to):
            continue
        p = profit.result(db, case.id)
        out.append({"case_id": case.id, "title": case.title, "status": case.status, "frozen": p.get("frozen", False),
                    "order_number": order.number, "confirmed_on": on, "deal_currency": p["deal_currency"],
                    "revenue": p["revenue"], "cost": p["cost"], "profit": p["profit"], "margin_percent": p["margin_percent"],
                    "markup_percent": p["markup_percent"]})
    return jsonable(out)


def _month(on: date, calendar: str) -> str:
    if calendar == "jalali":
        from app.modules.sourcing.jalali import to_jalali

        y, m, _d = to_jalali(on)
        return f"{y}-{m:02d}"
    return f"{on.year}-{on.month:02d}"


def vat(db: Session, *, calendar: str = "gregorian", date_from: date | None = None, date_to: date | None = None) -> dict:
    """Output / input VAT per month of the user's calendar, in the base currency (information only)."""
    base = base_currency(db)
    periods: dict[str, dict] = {}
    rates: dict = {}

    def rate(case_id, cur: str) -> Decimal:
        if cur == base:
            return Decimal(1)
        if case_id not in rates:
            rates[case_id] = profit.latest_rates(db, case_id)
        return rates[case_id].get(cur) or ZERO

    def add(on: date | None, key: str, value: Decimal) -> None:
        if on is None or (date_from and on < date_from) or (date_to and on > date_to) or not value:
            return
        p = periods.setdefault(_month(on, calendar), {"output": ZERO, "input": ZERO})
        p[key] += value

    for inv in db.scalars(select(SalesInvoice).where(SalesInvoice.status == "issued")):
        add(inv.issue_date, "output", (-1 if inv.kind == "credit_note" else 1) * inv.vat_amount * rate(inv.case_id, inv.currency))
    for inv in db.scalars(select(PurchaseInvoice).where(PurchaseInvoice.status == "approved")):
        add(inv.invoice_date, "input", inv.vat_amount * rate(inv.case_id, inv.currency))
    for c in db.scalars(select(ActualCost).where(ActualCost.vat_amount.is_not(None))):
        add(c.incurred_on or c.created_at.date(), "input",
            c.vat_amount * (Decimal(1) if c.currency == base else (c.fx_rate_to_base or rate(c.case_id, c.currency))))
    rows = [{"period": k, "output": money(v["output"]), "input": money(v["input"]), "net": money(v["output"] - v["input"])}
            for k, v in sorted(periods.items())]
    return jsonable({"currency": base, "calendar": calendar, "periods": rows})


# ---- CSV ------------------------------------------------------------------------------------------------------------------------

HEADERS = {
    "sales_invoices": [("number", "شماره", "Number"), ("kind", "نوع", "Kind"), ("status", "وضعیت", "Status"),
                       ("issue_date", "تاریخ صدور", "Issue date"), ("due_date", "سررسید", "Due date"),
                       ("customer", "خریدار", "Customer"), ("case", "پرونده", "Case"), ("currency", "ارز", "Currency"),
                       ("line_no", "ردیف", "Line"), ("description", "شرح", "Description"), ("quantity", "مقدار", "Quantity"),
                       ("unit_price", "مبلغ واحد", "Unit price"), ("line_total", "مبلغ ردیف", "Line amount"),
                       ("subtotal", "جمع", "Subtotal"), ("discount", "تخفیف", "Discount"), ("vat_rate", "نرخ مالیات", "VAT %"),
                       ("vat_amount", "مالیات", "VAT"), ("total", "جمع کل", "Total"), ("moadian_status", "وضعیت مودیان", "Moadian status"),
                       ("moadian_tax_id", "شماره مالیاتی", "Tax ID")],
    "purchase_invoices": [("number", "شماره فاکتور تأمین‌کننده", "Supplier invoice no."), ("status", "وضعیت", "Status"),
                          ("invoice_date", "تاریخ", "Date"), ("due_date", "سررسید", "Due date"), ("supplier", "تأمین‌کننده", "Supplier"),
                          ("case", "پرونده", "Case"), ("purchase_order", "سفارش خرید", "PO"), ("currency", "ارز", "Currency"),
                          ("subtotal", "جمع", "Subtotal"), ("vat_amount", "مالیات", "VAT"), ("total", "جمع کل", "Total"),
                          ("balance", "مانده", "Balance")],
    "payments": [("paid_on", "تاریخ پرداخت", "Paid on"), ("direction", "جهت", "Direction"), ("party", "طرف", "Party"),
                 ("case", "پرونده", "Case"), ("amount", "مبلغ", "Amount"), ("currency", "ارز", "Currency"),
                 ("fx_rate_to_base", "نرخ ارز", "FX rate"), ("base_amount", "مبلغ ریالی", "Base amount"),
                 ("reference", "مرجع", "Reference"), ("allocated_to", "تخصیص به", "Allocated to"),
                 ("allocated_amount", "مبلغ تخصیص", "Allocated amount"), ("unallocated", "تخصیص‌نیافته", "Unallocated")],
    "actual_costs": [("incurred_on", "تاریخ", "Date"), ("case", "پرونده", "Case"), ("kind", "نوع هزینه", "Kind"),
                     ("description", "شرح", "Description"), ("party", "طرف", "Party"), ("amount", "مبلغ", "Amount"),
                     ("currency", "ارز", "Currency"), ("fx_rate_to_base", "نرخ ارز", "FX rate"), ("base_amount", "مبلغ ریالی", "Base amount"),
                     ("vat_amount", "مالیات", "VAT"), ("status", "وضعیت", "Status"), ("source", "منبع", "Source")],
    "deals": [("case", "پرونده", "Case"), ("order", "سفارش فروش", "Sales order"), ("status", "وضعیت", "Status"),
              ("currency", "ارز معامله", "Deal currency"), ("revenue_planned", "درآمد برنامه", "Planned revenue"),
              ("revenue_actual", "درآمد واقعی", "Actual revenue"), ("cost_planned", "هزینه برنامه", "Planned cost"),
              ("cost_actual", "هزینه واقعی", "Actual cost"), ("profit_planned", "سود برنامه", "Planned profit"),
              ("profit_actual", "سود واقعی", "Actual profit"), ("profit_base", "سود ریالی", "Profit (base)"),
              ("margin_planned", "حاشیه برنامه ٪", "Planned margin %"), ("margin_actual", "حاشیه واقعی ٪", "Actual margin %")],
    "receivables": [("customer", "خریدار", "Customer"), ("number", "شماره", "Invoice"), ("case", "پرونده", "Case"),
                    ("issue_date", "تاریخ صدور", "Issue date"), ("due_date", "سررسید", "Due date"), ("currency", "ارز", "Currency"),
                    ("balance", "مانده", "Balance"), ("days_past_due", "روز گذشته از سررسید", "Days past due"),
                    ("bucket", "بازه", "Bucket")],
}
DATE_COLUMNS = {"issue_date", "due_date", "invoice_date", "paid_on", "incurred_on"}


class Csv:
    def __init__(self, name: str, lang: str, calendar: str):
        self.name, self.lang, self.calendar = name, lang, calendar
        self.columns = HEADERS[name]
        self.rows: list[dict] = []

    def add(self, **values) -> None:
        self.rows.append(values)

    def _date(self, value) -> str:
        if not value:
            return ""
        d = date.fromisoformat(str(value)[:10]) if not isinstance(value, date) else value
        if self.calendar == "jalali":
            from app.modules.sourcing.jalali import to_jalali

            y, m, dd = to_jalali(d)
            return f"{y}/{m:02d}/{dd:02d}"
        return d.isoformat()

    def render(self) -> bytes:
        buf = io.StringIO()
        writer = csv.writer(buf)
        head = []
        for key, fa, en in self.columns:
            head.append(fa if self.lang == "fa" else en)
            if key in DATE_COLUMNS:
                head.append(f"{key} (ISO)")
        writer.writerow(head)
        for row in self.rows:
            out = []
            for key, _fa, _en in self.columns:
                value = row.get(key)
                if key in DATE_COLUMNS:
                    out += [self._date(value), str(value)[:10] if value else ""]
                else:
                    out.append("" if value is None else str(value))
            writer.writerow(out)
        return ("﻿" + buf.getvalue()).encode("utf-8")


def _name(party: dict | None, lang: str) -> str:
    if not party:
        return ""
    return (party.get("name_fa") or party.get("name_en") or "") if lang == "fa" else (party.get("name_en") or party.get("name_fa") or "")


def export(db: Session, name: str, lang: str, calendar: str, date_from: date | None = None, date_to: date | None = None) -> bytes:
    out = Csv(name, lang, calendar)
    if name == "sales_invoices":
        for inv in invoices(db, kind="sales", date_from=date_from, date_to=date_to):
            row = sales_invoices.get_invoice(db, uuid.UUID(inv["id"]))
            for i, line in enumerate(sales_invoices.lines_of(db, row.id), start=1):
                out.add(number=inv["number"], kind=inv["kind"], status=inv["status"], issue_date=inv["issue_date"],
                        due_date=inv["due_date"], customer=_name(inv["party"], lang), case=inv["case_title"],
                        currency=inv["currency"], line_no=i, description=line.description, quantity=line.quantity,
                        unit_price=line.unit_price, line_total=line.total, subtotal=row.subtotal, discount=row.discount,
                        vat_rate=row.vat_rate, vat_amount=row.vat_amount, total=row.total, moadian_status=row.moadian_status,
                        moadian_tax_id=row.moadian_tax_id)
    elif name == "purchase_invoices":
        for inv in invoices(db, kind="purchase", date_from=date_from, date_to=date_to):
            row = purchase_invoices.get_invoice(db, uuid.UUID(inv["id"]))
            po = None
            if row.purchase_order_id:
                from app.modules.execution.common import get_purchase_order

                po = get_purchase_order(db, row.purchase_order_id).number
            out.add(number=inv["number"], status=inv["status"], invoice_date=inv["issue_date"], due_date=inv["due_date"],
                    supplier=_name(inv["party"], lang), case=inv["case_title"], purchase_order=po, currency=inv["currency"],
                    subtotal=inv["subtotal"], vat_amount=inv["vat_amount"], total=inv["total"], balance=inv["balance"])
    elif name == "payments":
        for rec in payment_list(db, date_from=date_from, date_to=date_to):
            common = {"paid_on": rec["paid_on"], "direction": rec["direction"], "party": _name(rec["party"], lang),
                      "case": rec["case_title"], "amount": rec["amount"], "currency": rec["amount_currency"],
                      "fx_rate_to_base": rec["fx_rate_to_base"], "base_amount": rec["base_amount"], "reference": rec["reference"],
                      "unallocated": rec["unallocated"]}
            if not rec["allocations"]:
                out.add(**common)
            for a in rec["allocations"]:
                target = ("sales_invoice:" + str(a["sales_invoice_id"]) if a["sales_invoice_id"] else
                          "purchase_invoice:" + str(a["purchase_invoice_id"]) if a["purchase_invoice_id"] else
                          "actual_cost:" + str(a["actual_cost_id"]))
                out.add(**common, allocated_to=_target_label(db, a) or target, allocated_amount=a["amount"])
    elif name == "actual_costs":
        from app.modules.sourcing.models import Case

        for case in db.scalars(select(Case).where(Case.id.in_(select(ActualCost.case_id)))):
            for c in costs.all_rows(db, case.id):
                on = c.get("incurred_on")
                if on and ((date_from and str(on) < date_from.isoformat()) or (date_to and str(on) > date_to.isoformat())):
                    continue
                party = _party_names(db, [uuid.UUID(str(c["party_id"]))]).get(uuid.UUID(str(c["party_id"]))) if c.get("party_id") else None
                out.add(incurred_on=on, case=case.title, kind=c["kind"], description=c["description"], party=_name(party, lang),
                        amount=c["amount"], currency=c["currency"], fx_rate_to_base=c.get("fx_rate_to_base"),
                        base_amount=c.get("base_amount"), vat_amount=c.get("vat_amount"), status=c["status"], source=c["source"])
    elif name == "deals":
        for d in deals(db, date_from=date_from, date_to=date_to):
            pl = lambda block, key="deal": (block or {}).get(key) if block else None  # noqa: E731
            out.add(case=d["title"], order=d["order_number"], status=d["status"], currency=d["deal_currency"],
                    revenue_planned=pl(d["revenue"]["planned"]), revenue_actual=pl(d["revenue"]["actual"]),
                    cost_planned=pl(d["cost"]["planned"]), cost_actual=pl(d["cost"]["actual"]),
                    profit_planned=pl(d["profit"]["planned"]), profit_actual=pl(d["profit"]["actual"]),
                    profit_base=pl(d["profit"]["actual"], "base"), margin_planned=d["margin_percent"]["planned"],
                    margin_actual=d["margin_percent"]["actual"])
    elif name == "receivables":
        for r in receivables(db)["invoices"]:
            out.add(customer=_name(r["party"], lang), number=r["number"], case=r["case_title"], issue_date=r["issue_date"],
                    due_date=r["due_date"], currency=r["currency"], balance=r["balance"], days_past_due=r["days_past_due"],
                    bucket=r["bucket"])
    else:
        from app.core.errors import NotFound

        raise NotFound("not_found", "Unknown export")
    return out.render()


def _target_label(db: Session, a: dict) -> str | None:
    if a.get("sales_invoice_id"):
        inv = db.get(SalesInvoice, uuid.UUID(str(a["sales_invoice_id"])))
        return inv.number if inv else None
    if a.get("purchase_invoice_id"):
        inv = db.get(PurchaseInvoice, uuid.UUID(str(a["purchase_invoice_id"])))
        return inv.supplier_invoice_no if inv else None
    cost = db.get(ActualCost, uuid.UUID(str(a["actual_cost_id"])))
    return cost.description if cost else None


def export_all(db: Session, lang: str, calendar: str, date_from: date | None, date_to: date | None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in HEADERS:
            z.writestr(f"{name}.csv", export(db, name, lang, calendar, date_from, date_to))
    return buf.getvalue()
