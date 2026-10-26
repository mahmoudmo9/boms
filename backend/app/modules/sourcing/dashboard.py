"""The "Sourcing" section of the command center (read-only; links point to the item/case)."""

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.parties import clock
from app.modules.sourcing.common import jsonable

EXPIRING_DAYS = 7
SELECTION_LOST_DAYS = 14


def summary(db: Session, today: date | None = None) -> dict:
    today = today or clock.today()
    uncovered = db.execute(text(
        """
        SELECT li.id AS item_id, li.name, li.case_id, c.title AS case_title
        FROM ops.line_item li JOIN ops."case" c ON c.id = li.case_id
        WHERE c.status = 'open' AND li.status = 'uncovered' AND NOT li.no_coverage_confirmed
        ORDER BY c.updated_at DESC, li.position
        """
    )).mappings().all()
    overdue_rfq = db.execute(text(
        """
        SELECT r.id AS recipient_id, r.party_id, p.name_fa AS party_name_fa, p.name_en AS party_name_en,
               q.id AS rfq_id, q.title AS rfq_title, q.case_id, q.respond_by
        FROM ops.rfq_recipient r JOIN ops.rfq q ON q.id = r.rfq_id JOIN core.party p ON p.id = r.party_id
        WHERE r.status IN ('sent', 'no_response') AND q.respond_by < :today AND q.status <> 'cancelled'
        ORDER BY q.respond_by, p.name_norm
        """
    ), {"today": today}).mappings().all()
    expiring = db.execute(text(
        """
        SELECT o.id AS offer_id, o.case_id, c.title AS case_title, o.party_id, p.name_fa AS party_name_fa,
               p.name_en AS party_name_en, o.valid_until, o.currency
        FROM ops.supplier_offer o JOIN ops."case" c ON c.id = o.case_id JOIN core.party p ON p.id = o.party_id
        WHERE o.status = 'active' AND o.valid_until BETWEEN :today AND :until AND c.status = 'open'
        ORDER BY o.valid_until
        """
    ), {"today": today, "until": today + timedelta(days=EXPIRING_DAYS)}).mappings().all()
    # rfq_sent items whose every non-draft recipient (non-cancelled RFQs) is no_response or declined (v0.3.2)
    resend = db.execute(text(
        """
        SELECT li.id AS item_id, li.name, li.case_id, c.title AS case_title,
               count(DISTINCT r.id) AS recipients, max(q.respond_by) AS respond_by
        FROM ops.line_item li
        JOIN ops."case" c ON c.id = li.case_id
        JOIN ops.rfq_item ri ON ri.line_item_id = li.id
        JOIN ops.rfq q ON q.id = ri.rfq_id AND q.status <> 'cancelled'
        JOIN ops.rfq_recipient r ON r.rfq_id = q.id AND r.status <> 'draft'
        WHERE c.status = 'open' AND li.status = 'rfq_sent'
        GROUP BY li.id, li.name, li.case_id, c.title, c.updated_at, li.position
        HAVING bool_and(r.status IN ('no_response', 'declined'))
        ORDER BY c.updated_at DESC, li.position
        """
    )).mappings().all()
    selection_lost = db.execute(text(
        """
        SELECT DISTINCT ON (li.id) li.id AS item_id, li.name, li.case_id, c.title AS case_title,
               e.occurred_at AS lost_at, e.data->>'cause' AS cause
        FROM core.event e
        JOIN ops.line_item li ON e.entity_type = 'line_item' AND e.entity_id = li.id::text
        JOIN ops."case" c ON c.id = li.case_id
        WHERE e.action = 'selection_lost' AND e.occurred_at >= :since
          AND li.selected_offer_item_id IS NULL AND li.status <> 'cancelled'
        ORDER BY li.id, e.occurred_at DESC
        """
    ), {"since": today - timedelta(days=SELECTION_LOST_DAYS)}).mappings().all()
    open_items = db.execute(text(
        """
        SELECT li.case_id, c.title AS case_title, li.status, li.no_coverage_confirmed
        FROM ops.line_item li JOIN ops."case" c ON c.id = li.case_id
        WHERE c.status = 'open' AND li.status <> 'cancelled'
        """
    )).mappings().all()
    cases: dict = {}
    for row in open_items:
        entry = cases.setdefault(row["case_id"], {"case_id": row["case_id"], "case_title": row["case_title"],
                                                  "items": 0, "not_covered": 0})
        entry["items"] += 1
        if row["status"] != "selected" and not row["no_coverage_confirmed"]:
            entry["not_covered"] += 1
    with_status = sum(1 for r in open_items if r["status"] != "uncovered" or r["no_coverage_confirmed"])
    percent = round(100 * with_status / len(open_items), 1) if open_items else None
    return jsonable({
        "items_without_rfq": [dict(r) for r in uncovered],
        "rfq_overdue": [dict(r) for r in overdue_rfq],
        "offers_expiring": [{**dict(r), "days_left": (r["valid_until"] - today).days} for r in expiring],
        "cases_not_covered": sorted((c for c in cases.values() if c["not_covered"]),
                                    key=lambda c: -c["not_covered"]),
        "no_response_resend": [dict(r) for r in resend],
        "selection_lost": sorted((dict(r) for r in selection_lost), key=lambda r: r["lost_at"], reverse=True),
        "coverage_status_percent": percent,
        "open_items": len(open_items),
        "open_items_with_status": with_status,
    })
