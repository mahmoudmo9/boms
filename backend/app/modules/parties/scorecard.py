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


TIMELINE_SQL = """
    SELECT 'rfq_sent' AS kind, rr.sent_at AS at, r.code AS ref, NULL::numeric AS amount, NULL AS currency, r.case_id
      FROM ops.rfq_recipient rr JOIN ops.rfq r ON r.id = rr.rfq_id WHERE rr.party_id = :p AND rr.sent_at IS NOT NULL
    UNION ALL SELECT 'offer', o.received_at, r.code, NULL, o.currency, o.case_id FROM ops.supplier_offer o
      LEFT JOIN ops.rfq_recipient rr ON rr.id = o.rfq_recipient_id LEFT JOIN ops.rfq r ON r.id = rr.rfq_id
      WHERE o.party_id = :p AND o.received_at IS NOT NULL
    UNION ALL SELECT 'purchase_order', coalesce(po.sent_at, po.approved_at, po.created_at), po.number, po.total, po.currency, po.case_id FROM ops.purchase_order po
      WHERE po.supplier_party_id = :p AND po.status NOT IN ('draft', 'cancelled', 'superseded')
    UNION ALL SELECT 'sales_order', coalesce(so.contract_date::timestamptz, so.confirmed_at, so.created_at), so.number, so.total, so.currency, so.case_id FROM ops.sales_order so
      WHERE so.customer_party_id = :p AND so.status <> 'cancelled'
    UNION ALL SELECT CASE WHEN m.direction = 'in' THEN 'payment_in' ELSE 'payment_out' END, pr.paid_on::timestamptz, pr.code,
                     pr.amount, pr.amount_currency, m.case_id
      FROM ops.payment_record pr JOIN ops.payment_milestone m ON m.id = pr.milestone_id
      WHERE m.party_id = :p OR m.purchase_order_id IN (SELECT id FROM ops.purchase_order WHERE supplier_party_id = :p)
         OR m.sales_order_id IN (SELECT id FROM ops.sales_order WHERE customer_party_id = :p)
    UNION ALL SELECT 'shipment', coalesce(sh.ata, sh.atd, sh.etd)::timestamptz, sh.code, NULL, NULL, sh.case_id FROM ops.shipment sh
      WHERE (sh.carrier_party_id = :p OR sh.purchase_order_id IN (SELECT id FROM ops.purchase_order WHERE supplier_party_id = :p))
        AND coalesce(sh.ata, sh.atd, sh.etd) IS NOT NULL
    UNION ALL SELECT 'claim', c.opened_on::timestamptz, c.kind, c.claimed_amount, c.claimed_amount_currency, c.case_id FROM ops.claim c
      WHERE c.counterparty_id = :p
    UNION ALL SELECT 'followup_done', f.done_at, f.action, NULL, NULL, NULL::uuid FROM core.followup f
      WHERE f.party_id = :p AND f.status = 'done'
"""


def story(db: Session, party_id: uuid.UUID, limit: int = 14) -> dict:
    """v0.10.1 section 4.6 (read-only): «همکاری از …» with counts, the party's past timeline across RFQs, offers,
    orders, payments, shipments, claims and done follow-ups (open ones are listed on their own), and the deals with this party with their margin."""
    rows = db.execute(text(f"SELECT * FROM ({TIMELINE_SQL}) t WHERE t.at IS NOT NULL AND t.at <= now() ORDER BY t.at DESC LIMIT :n"),
                      {"p": party_id, "n": limit}).all()
    first = db.execute(text(f"SELECT min(at) FROM ({TIMELINE_SQL}) t"), {"p": party_id}).scalar()
    since = db.execute(text("SELECT least(:f, (SELECT min(occurred_at) FROM core.interaction WHERE party_id = :p))"),
                       {"p": party_id, "f": first}).scalar()
    counts = dict(db.execute(text("""SELECT
        (SELECT count(*) FROM ops.rfq_recipient WHERE party_id = :p AND sent_at IS NOT NULL) AS rfqs,
        (SELECT count(*) FROM ops.purchase_order WHERE supplier_party_id = :p AND status NOT IN ('draft', 'cancelled', 'superseded'))
          + (SELECT count(*) FROM ops.sales_order WHERE customer_party_id = :p AND status <> 'cancelled') AS orders,
        (SELECT count(*) FROM ops.claim WHERE counterparty_id = :p) AS claims"""), {"p": party_id}).one()._mapping)
    deals = []
    for r in db.execute(text("""
            SELECT c.id, c.title, c.status FROM ops.case c
            WHERE c.party_id = :p OR c.id IN (SELECT case_id FROM ops.purchase_order WHERE supplier_party_id = :p
                                               AND status NOT IN ('draft', 'cancelled', 'superseded'))
            ORDER BY c.updated_at DESC LIMIT 8"""), {"p": party_id}):
        margin = {"actual": None, "planned": None, "expected": None, "currency": None}
        try:
            from app.modules.finance import profit as profit_service

            res = profit_service.result(db, r.id)
            mp = res.get("margin_percent") or {}
            margin = {"actual": mp.get("actual") if r.status == "closed" else None, "planned": mp.get("planned"),
                      "expected": (res.get("expected") or {}).get("margin_percent"), "currency": res.get("deal_currency")}
        except Exception:   # noqa: BLE001 - a deal without a sales order or cost sheet has no margin yet
            pass
        deals.append({"case_id": r.id, "title": r.title, "status": r.status, "margin": margin})
    return {"since": since, "counts": counts, "deals": deals,
            "timeline": [dict(r._mapping) for r in rows]}


def scorecard(db: Session, party_id: uuid.UUID) -> dict:
    from app.modules.sourcing.common import jsonable

    return jsonable({"on_time": on_time(db, party_id), "inspection": inspection(db, party_id),
                     "response_time": response_time(db, party_id), "price_position": price_position(db, party_id),
                     "min_sample": MIN_SAMPLE, "story": story(db, party_id)})
