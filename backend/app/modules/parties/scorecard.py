"""The party scorecard (v0.10.1 sections 0.3.1 and 4.6): four tiles from data BOMS already records, each with its
sample size. A tile with fewer than ``MIN_SAMPLE`` data points says so («دادهٔ کافی نیست») instead of a percentage.

- on time: the supplier's purchase orders with a due date (the confirmed ready date, else the requested one) and an
  actual date (the recorded ready date, else the first receipt) — the share ready on or before the due date;
- inspection: inspections of the supplier's purchase orders with a result — the share that passed (``conditional``
  counted apart);
- response time: RFQs sent to the party and answered with an offer — the median hours from sending to receiving;
- price position: RFQ items where the party's offer can be compared with at least one other valid offer in the same
  currency — «cheapest in n of m».
"""
from __future__ import annotations

import statistics
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

MIN_SAMPLE = 2


def _tile(value, n: int, **extra) -> dict:
    enough = n >= MIN_SAMPLE
    return {"value": value if enough else None, "n": n, "enough": enough, **extra}


def on_time(db: Session, party_id: uuid.UUID) -> dict:
    rows = db.execute(text("""
        SELECT coalesce(po.confirmed_ready_on, po.ready_due_on) AS due,
               coalesce(po.ready_on, (SELECT min(r.received_on) FROM ops.receipt r WHERE r.purchase_order_id = po.id)) AS actual
        FROM ops.purchase_order po
        WHERE po.supplier_party_id = :p AND po.status NOT IN ('draft', 'cancelled', 'superseded')"""), {"p": party_id}).all()
    known = [(r.due, r.actual) for r in rows if r.due and r.actual]
    on = sum(1 for due, actual in known if actual <= due)
    late_days = [(actual - due).days for due, actual in known if actual > due]
    return _tile(round(on / len(known) * 100) if known else None, len(known), on_time=on,
                 avg_late_days=round(statistics.mean(late_days), 1) if late_days else None)


def inspection(db: Session, party_id: uuid.UUID) -> dict:
    rows = db.execute(text("""
        SELECT i.result FROM ops.inspection i JOIN ops.purchase_order po ON po.id = i.purchase_order_id
        WHERE po.supplier_party_id = :p AND i.result IN ('pass', 'fail', 'conditional')"""), {"p": party_id}).scalars().all()
    passed = sum(1 for r in rows if r == "pass")
    return _tile(round(passed / len(rows) * 100) if rows else None, len(rows), passed=passed,
                 conditional=sum(1 for r in rows if r == "conditional"), failed=sum(1 for r in rows if r == "fail"))


def response_time(db: Session, party_id: uuid.UUID) -> dict:
    rows = db.execute(text("""
        SELECT extract(epoch FROM (min(o.received_at) - rr.sent_at)) / 3600 AS hours
        FROM ops.rfq_recipient rr JOIN ops.supplier_offer o ON o.rfq_recipient_id = rr.id
        WHERE rr.party_id = :p AND rr.sent_at IS NOT NULL AND o.received_at IS NOT NULL
        GROUP BY rr.id, rr.sent_at"""), {"p": party_id}).scalars().all()
    hours = [float(h) for h in rows if h is not None and h >= 0]
    asked = db.execute(text("SELECT count(*) FROM ops.rfq_recipient WHERE party_id = :p AND sent_at IS NOT NULL"),
                       {"p": party_id}).scalar()
    return _tile(round(statistics.median(hours), 1) if hours else None, len(hours), asked=asked,
                 answered=len(hours))


def price_position(db: Session, party_id: uuid.UUID) -> dict:
    rows = db.execute(text("""
        WITH priced AS (
            SELECT oi.line_item_id, o.party_id, o.currency,
                   oi.unit_price / nullif(coalesce(oi.price_per_quantity, 1), 0) AS unit
            FROM ops.offer_item oi JOIN ops.supplier_offer o ON o.id = oi.offer_id
            WHERE o.status IN ('active', 'expired') AND o.rfq_recipient_id IS NOT NULL
              AND coalesce(oi.available, true) AND oi.unit_price IS NOT NULL),
        best AS (SELECT line_item_id, currency, party_id, min(unit) AS unit FROM priced GROUP BY 1, 2, 3)
        SELECT b.line_item_id, b.unit <= min(o.unit) AS cheapest
        FROM best b JOIN best o ON o.line_item_id = b.line_item_id AND o.currency = b.currency
        WHERE b.party_id = :p
        GROUP BY b.line_item_id, b.currency, b.unit
        HAVING count(*) >= 2"""), {"p": party_id}).all()
    cheapest = sum(1 for r in rows if r.cheapest)
    return _tile(cheapest if rows else None, len(rows), cheapest=cheapest, compared=len(rows))


def scorecard(db: Session, party_id: uuid.UUID) -> dict:
    return {"on_time": on_time(db, party_id), "inspection": inspection(db, party_id),
            "response_time": response_time(db, party_id), "price_position": price_position(db, party_id),
            "min_sample": MIN_SAMPLE}
