"""v0.10.1 section 4.2: the case page's story blocks in one read-only view — the deal type, the order line, the next
step, the people of the deal, the documents with the missing required ones, the money and the dated milestones still
ahead («پیش‌بینی»). Nothing is computed that BOMS did not already have; this only gathers it.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modules.parties import clock
from app.modules.sourcing.common import jsonable

ZERO = Decimal(0)


def _party(db: Session, party_id) -> dict | None:
    if not party_id:
        return None
    row = db.execute(text("SELECT id, code, name_fa, name_en, country_iso2 FROM core.party WHERE id = :p"), {"p": party_id}).first()
    return dict(row._mapping) if row else None


def next_step(db: Session, case_id: uuid.UUID) -> dict | None:
    """The earliest open required process step (by due date, then position), else the earliest open task."""
    from app.modules.execution.models import Process, ProcessStep

    step = db.scalars(select(ProcessStep).join(Process, Process.id == ProcessStep.process_id)
                      .where(Process.case_id == case_id, ProcessStep.status.in_(("pending", "in_progress")))
                      .order_by(ProcessStep.due_on.is_(None), ProcessStep.due_on, Process.created_at, ProcessStep.position)).first()
    if step is not None:
        return {"kind": "step", "id": step.id, "process_id": step.process_id, "label_fa": step.label_fa, "label_en": step.label_en,
                "group": step.group, "reference_label": step.reference_label, "requires_document": step.requires_document,
                "due_on": step.due_on, "status": step.status, "shipment_id": step.shipment_id}
    task = db.execute(text("""SELECT id, title, due_on, due_at FROM core.task WHERE case_id = :c AND status = 'open'
                              ORDER BY due_on, due_at NULLS LAST LIMIT 1"""), {"c": case_id}).first()
    if task is not None:
        return {"kind": "task", "id": task.id, "title": task.title, "due_on": task.due_on, "due_at": task.due_at}
    return None


def people(db: Session, case_id: uuid.UUID, buyer_id) -> list[dict]:
    """Every party in the deal with its role here: the buyer and its contacts, suppliers (purchase orders), carriers,
    forwarders and inspectors (shipments, inspections)."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(party_id, role: str) -> None:
        if not party_id or (str(party_id), role) in seen:
            return
        p = _party(db, party_id)
        if p:
            seen.add((str(party_id), role))
            out.append({**p, "role": role})

    add(buyer_id, "buyer")
    for (pid,) in db.execute(text("SELECT DISTINCT supplier_party_id FROM ops.purchase_order WHERE case_id = :c AND status NOT IN ('cancelled', 'superseded')"), {"c": case_id}):
        add(pid, "supplier")
    for carrier, forwarder in db.execute(text("SELECT carrier_party_id, forwarder_party_id FROM ops.shipment WHERE case_id = :c"), {"c": case_id}):
        add(carrier, "carrier")
        add(forwarder, "forwarder")
    for (pid,) in db.execute(text("SELECT DISTINCT inspector_party_id FROM ops.inspection WHERE case_id = :c"), {"c": case_id}):
        add(pid, "inspector")
    contacts = []
    if buyer_id:
        contacts = [dict(r._mapping) for r in db.execute(text(
            """SELECT id, name_fa, name_en, job_title, is_primary FROM core.contact WHERE party_id = :p AND status = 'active'
               ORDER BY is_primary DESC, created_at LIMIT 6"""), {"p": buyer_id})]
    return [{**p, "contacts": contacts if p["role"] == "buyer" else []} for p in out]


def documents(db: Session, case_id: uuid.UUID) -> dict:
    """The deal's files by type, the shipping documents by kind, and the required step documents still missing."""
    files = db.execute(text("""
        SELECT d.id, d.title, d.original_filename, d.mime_type, d.uploaded_at FROM core.document d
        WHERE d.id IN (SELECT document_id FROM core.document_link WHERE entity_type = 'case' AND entity_id = :c)
           OR d.id IN (SELECT s.document_id FROM ops.process_step s JOIN ops.process p ON p.id = s.process_id
                       WHERE p.case_id = CAST(:c AS uuid) AND s.document_id IS NOT NULL)
           OR d.id IN (SELECT sd.document_id FROM ops.shipment_document sd JOIN ops.shipment sh ON sh.id = sd.shipment_id
                       WHERE sh.case_id = CAST(:c AS uuid))
        ORDER BY d.uploaded_at DESC"""), {"c": str(case_id)}).all()
    shipping = db.execute(text("""SELECT sd.kind, count(*) AS n FROM ops.shipment_document sd JOIN ops.shipment sh ON sh.id = sd.shipment_id
                                  WHERE sh.case_id = :c GROUP BY sd.kind ORDER BY sd.kind"""), {"c": case_id}).all()
    missing = db.execute(text("""SELECT s.id, s.label_fa, s.label_en, s.due_on FROM ops.process_step s JOIN ops.process p ON p.id = s.process_id
                                 WHERE p.case_id = :c AND s.requires_document AND s.document_id IS NULL AND s.no_document_reason IS NULL
                                   AND s.status IN ('pending', 'in_progress')
                                 ORDER BY s.due_on NULLS LAST, s.position"""), {"c": case_id}).all()
    return {"files": [dict(r._mapping) for r in files], "count": len(files),
            "shipping": [{"kind": r.kind, "n": r.n} for r in shipping],
            "missing": [dict(r._mapping) for r in missing]}


def money(db: Session, case_id: uuid.UUID) -> dict:
    """Received and paid per currency (actual), and the expected profit with its estimated parts (Phase 9 profit)."""
    from app.modules.execution.milestones import cash_position

    cash = cash_position(db, case_id)
    expected = None
    try:
        from app.modules.finance import profit as profit_service

        p = profit_service.result(db, case_id)
        if p and p.get("expected"):
            e = p["expected"]
            expected = {"profit": e.get("profit"), "currency": p.get("deal_currency"),
                        "estimated": bool(Decimal(str((e.get("estimated") or {}).get("goods") or 0)) or
                                          Decimal(str((e.get("estimated") or {}).get("planned_costs") or 0)))}
    except Exception:   # noqa: BLE001 - no costing yet: the money block shows what was received and paid
        expected = None
    return {"actual": cash.get("actual", {}), "plan": cash.get("plan"), "expected_profit": expected}


def forecast(db: Session, case_id: uuid.UUID, today: date) -> list[dict]:
    """Dated milestones still ahead: shipment ETAs, open process steps with a due date, expected payments, sales
    invoices due. Shown muted as «پیش‌بینی» on the story rail."""
    out: list[dict] = []
    for r in db.execute(text("SELECT id, code, eta, mode FROM ops.shipment WHERE case_id = :c AND ata IS NULL AND eta >= :t"), {"c": case_id, "t": today}):
        out.append({"kind": "eta", "on": r.eta, "ref": r.code, "id": r.id, "mode": r.mode})
    for r in db.execute(text("""SELECT s.id, s.label_fa, s.label_en, s.due_on FROM ops.process_step s JOIN ops.process p ON p.id = s.process_id
                                WHERE p.case_id = :c AND s.status IN ('pending', 'in_progress') AND s.due_on >= :t
                                ORDER BY s.due_on LIMIT 4"""), {"c": case_id, "t": today}):
        out.append({"kind": "step", "on": r.due_on, "label_fa": r.label_fa, "label_en": r.label_en, "id": r.id})
    for r in db.execute(text("""SELECT id, direction, amount, amount_currency, due_on, label, kind FROM ops.payment_milestone
                                WHERE case_id = :c AND status IN ('expected', 'partly') AND due_on >= :t ORDER BY due_on LIMIT 4"""),
                        {"c": case_id, "t": today}):
        out.append({"kind": "payment", "on": r.due_on, "direction": r.direction, "amount": r.amount, "currency": r.amount_currency,
                    "label": r.label, "milestone_kind": r.kind, "id": r.id})
    for r in db.execute(text("SELECT id, number, due_date FROM ops.sales_invoice WHERE case_id = :c AND status = 'issued' AND due_date >= :t"),
                        {"c": case_id, "t": today}):
        out.append({"kind": "invoice_due", "on": r.due_date, "ref": r.number, "id": r.id})
    return sorted(out, key=lambda x: x["on"])


def deal_type(db: Session, case_id: uuid.UUID) -> str | None:
    row = db.execute(text("""SELECT deal_type FROM ops.process WHERE case_id = :c
                             UNION ALL SELECT deal_type FROM ops.cost_sheet WHERE case_id = :c LIMIT 1"""), {"c": case_id}).first()
    return row[0] if row else None


def order_line(db: Session, case_id: uuid.UUID) -> dict | None:
    row = db.execute(text("""SELECT id, number, total, currency, status FROM ops.sales_order WHERE case_id = :c AND status <> 'cancelled'
                             ORDER BY created_at DESC LIMIT 1"""), {"c": case_id}).first()
    return dict(row._mapping) if row else None


def case_overview(db: Session, case_id: uuid.UUID) -> dict:
    from app.modules.sourcing.inquiries import get_case

    case = get_case(db, case_id)
    return jsonable({"case_id": case.id, "deal_type": deal_type(db, case_id), "order": order_line(db, case_id),
                     "customer": _party(db, case.party_id), "next_step": next_step(db, case_id),
                     "people": people(db, case_id, case.party_id), "documents": documents(db, case_id),
                     "money": money(db, case_id), "forecast": forecast(db, case_id, clock.today())})
