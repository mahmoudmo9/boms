"""v0.8.0 milestone 0: internal tasks instead of party follow-ups (the data move on Phase 7b / 8 data, the service and
API, reminders as tasks) and the other carry-over fixes (prepayment gate, already sent PO, claim counterparty default,
the PO price check across currencies, the warranty reminder)."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, text

from tests.test_execution_m1 import confirmed_order, day
from tests.test_execution_m2 import by_currency, create_pos, sent_po
from tests.test_execution_m3 import deal, open_followups
from tests.test_sourcing_inquiries import events
from tests.test_tenders import at, followups, manual_tender, tasks


# ---- the data move (migration 0014) ------------------------------------------------------------------------------------

def test_migration_0014_moves_internal_reminders_to_tasks_on_phase7b_and_8_data():
    from alembic import command

    from app.cli import alembic_config
    from app.core import dbadmin
    from app.core.config import get_config
    from tests.conftest import create_empty_database, superuser_conninfo

    name = "boms_test_p9_migrations"
    create_empty_database(name)
    url = get_config().db_url(name)
    cfg = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "0013")
        with engine.begin() as conn:
            def q(sql, **p):
                result = conn.execute(text(sql), p)
                return result.scalar() if result.returns_rows else None
            q("INSERT INTO sys.currency (code, name_fa, name_en, minor_units) VALUES ('IRR', 'ریال', 'Rial', 0)")
            organizer = q("INSERT INTO core.party (name_fa) VALUES ('برگزارکننده') RETURNING id")
            customer = q("INSERT INTO core.party (name_fa) VALUES ('مشتری') RETURNING id")
            supplier = q("INSERT INTO core.party (name_fa) VALUES ('تأمین‌کننده') RETURNING id")
            case = q("INSERT INTO ops.\"case\" (title, party_id) VALUES ('Deal', :p) RETURNING id", p=customer)
            tender = q("INSERT INTO ops.tender (case_id, organizer_party_id, stage) VALUES (:c, :p, 'pricing') RETURNING id",
                       c=case, p=organizer)
            deadline = q("INSERT INTO ops.tender_date (tender_id, kind, at, remind_days_before) VALUES "
                         "(:t, 'proposal_deadline', now() + interval '10 days', '{3}') RETURNING id", t=tender)
            g = q("INSERT INTO ops.guarantee (case_id, tender_id, purpose, status, valid_until) VALUES "
                  "(:c, :t, 'bid', 'issued', current_date + 40) RETURNING id", c=case, t=tender)
            process = q("INSERT INTO ops.process (case_id, deal_type, name) VALUES (:c, 'import', 'Import') RETURNING id", c=case)
            step = q("INSERT INTO ops.process_step (process_id, position, code, label_fa, label_en, due_on) VALUES "
                     "(:p, 1, 'order_registration', 'ثبت سفارش', 'Order registration', current_date + 12) RETURNING id",
                     p=process)

            def fu(party, action, due, status="open", note=None):
                return q("INSERT INTO core.followup (party_id, action, due_on, status, done_at, done_note) VALUES "
                         "(:p, :a, current_date + :d, :s, CASE WHEN :s <> 'open' THEN now() END, :n) RETURNING id",
                         p=party, a=action, d=due, s=status, n=note)

            def tl(f, purpose, ref, days=None):
                q("INSERT INTO ops.tender_followup (tender_id, followup_id, purpose, ref_id, days_before) VALUES "
                  "(:t, :f, :p, :r, :d)", t=tender, f=f, p=purpose, r=ref, d=days)

            def el(f, purpose, ref, days=None):
                q("INSERT INTO ops.execution_followup (case_id, followup_id, purpose, ref_id, days_before) VALUES "
                  "(:c, :f, :p, :r, :d)", c=case, f=f, p=purpose, r=ref, d=days)

            tl(fu(organizer, "یادآوری: مهلت ارسال پیشنهاد", 7), "date_reminder", deadline, 3)
            tl(fu(organizer, "یادآوری: سررسید ضمانت‌نامه", 10, "done", "تمدید شد"), "guarantee_expiry", g, 30)
            tl(fu(organizer, "پیگیری آزادسازی تضمین", 20), "guarantee_release", g)            # counterparty: stays
            el(fu(customer, "ثبت سفارش — Deal", 9), "step_reminder", step, 3)
            el(fu(customer, "ثبت سفارش — Deal", 11, "cancelled", "step done"), "step_reminder", step, 1)
            el(fu(customer, "صدور فاکتور و پیگیری تسویه", 3), "invoice", None)
            el(fu(customer, "پایان گارانتی", 365), "warranty_end", None)
            el(fu(supplier, "پیگیری تأیید سفارش", 3), "po_confirm", None)                     # counterparty: stays
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM core.task ORDER BY source_kind, due_on")).mappings().all()
            kinds = {}
            for r in rows:
                kinds[r["source_kind"]] = kinds.get(r["source_kind"], 0) + 1
            assert kinds == {"tender_date": 1, "guarantee_expiry": 1, "process_step": 2, "invoice_issue": 1, "warranty_end": 1}
            moved = conn.execute(text("SELECT data FROM core.event WHERE action = 'reminders_moved'")).scalar()
            assert moved == kinds
            by_kind = {(r["source_kind"], r["remind_days_before"]): r for r in rows}
            d = by_kind[("tender_date", 3)]
            assert d["source"] == "tenders" and d["source_id"] == deadline and d["case_id"] == case and d["due_at"]
            assert d["party_id"] == organizer and d["status"] == "open" and d["title"].startswith("یادآوری")
            ge = by_kind[("guarantee_expiry", 30)]
            assert ge["status"] == "done" and ge["done_note"] == "تمدید شد" and ge["done_at"]
            assert ge["remind_of_due"] == date.today() + timedelta(days=40)
            s3, s1 = by_kind[("process_step", 3)], by_kind[("process_step", 1)]
            assert s3["source"] == "execution" and s3["source_id"] == step and s3["remind_of_due"] == date.today() + timedelta(days=12)
            assert s1["status"] == "cancelled" and s1["done_note"] == "step done"
            # the customer's follow-up list no longer shows checklist or date reminders; counterparty ones stay
            assert conn.execute(text("SELECT count(*) FROM core.followup WHERE party_id = :p"), {"p": customer}).scalar() == 0
            assert conn.execute(text("SELECT action FROM core.followup WHERE party_id = :p"), {"p": organizer}).scalars().all() \
                == ["پیگیری آزادسازی تضمین"]
            assert conn.execute(text("SELECT purpose FROM ops.tender_followup")).scalars().all() == ["guarantee_release"]
            assert conn.execute(text("SELECT purpose FROM ops.execution_followup")).scalars().all() == ["po_confirm"]
            # the deleted follow-ups stay in the audit
            assert conn.execute(text("SELECT count(*) FROM core.audit WHERE table_name = 'core.followup' AND op = 'D'")).scalar() == 6
        # v0.9.0: down / up / up keeps every reminder (counts per kind compared at each step)
        def task_kinds():
            with engine.connect() as conn:
                return dict(conn.execute(text("SELECT source_kind, count(*) FROM core.task GROUP BY 1")).all())

        def followup_purposes():
            with engine.connect() as conn:
                return dict(conn.execute(text(
                    "SELECT purpose, count(*) FROM (SELECT purpose FROM ops.tender_followup UNION ALL "
                    "SELECT purpose FROM ops.execution_followup) x GROUP BY 1")).all())

        at_head = task_kinds()
        command.downgrade(cfg, "0013")
        back = followup_purposes()
        assert back == {"date_reminder": 1, "guarantee_expiry": 1, "guarantee_release": 1, "step_reminder": 2,
                        "invoice": 1, "warranty_end": 1, "po_confirm": 1}, back
        with engine.connect() as conn:            # the customer's reminders are follow-ups again, statuses kept
            rows = dict(conn.execute(text("SELECT status, count(*) FROM core.followup WHERE party_id = :p GROUP BY 1"),
                                     {"p": customer}).all())
        assert rows == {"open": 3, "cancelled": 1}
        command.upgrade(cfg, "head")
        assert task_kinds() == at_head
        command.downgrade(cfg, "0013")
        command.upgrade(cfg, "head")
        assert task_kinds() == at_head
        # a manual task has no follow-up form: the downgrade refuses with a message and changes nothing
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO core.task (title, due_on) VALUES ('manual', current_date)"))
        import pytest

        with pytest.raises(Exception, match="Downgrade below 0014 refused"):
            command.downgrade(cfg, "0013")
        assert task_kinds()["manual"] == 1
    finally:
        engine.dispose()
        dbadmin.drop_database(superuser_conninfo(), name)


# ---- the service and the API ------------------------------------------------------------------------------------------

def test_manual_task_lifecycle_and_my_tasks_groups_and_filters(client):
    case = client.post("/api/cases", json={"title": "Tasks case"}).json()
    r = client.post("/api/tasks", json={"title": " ", "due_on": day(0)})
    assert r.status_code == 422
    r = client.post("/api/tasks", json={"title": "تماس با گمرک", "due_on": day(-1), "case_id": case["id"], "priority": "high"})
    assert r.status_code == 201, r.text
    late = r.json()
    assert late["source"] == "manual" and late["source_kind"] == "manual" and late["status"] == "open"
    today = client.post("/api/tasks", json={"title": "امروز", "due_on": day(0), "case_id": case["id"]}).json()
    week = client.post("/api/tasks", json={"title": "این هفته", "due_on": day(5)}).json()
    later = client.post("/api/tasks", json={"title": "بعداً", "due_on": day(30)}).json()
    r = client.post("/api/tasks", json={"title": "x", "due_on": day(0), "bogus": 1})
    assert r.status_code == 422
    groups = client.get("/api/tasks").json()["groups"]
    ids = {k: {t["id"] for t in v} for k, v in groups.items()}
    assert late["id"] in ids["overdue"] and today["id"] in ids["today"] and week["id"] in ids["week"]
    assert later["id"] in ids["later"]
    flt = client.get("/api/tasks", params={"case_id": case["id"]}).json()["groups"]
    assert {t["id"] for v in flt.values() for t in v} == {late["id"], today["id"]}
    assert all(t["case_title"] == "Tasks case" for t in flt["overdue"])
    assert {t["id"] for v in client.get("/api/tasks", params={"kind": "manual", "q": "بعداً"}).json()["groups"].values()
            for t in v} == {later["id"]}
    # move, done, reopen, cancel (a note is required)
    r = client.post(f"/api/tasks/{late['id']}/move", json={"due_on": day(2), "note": "منتظر پاسخ"})
    assert r.status_code == 200 and r.json()["due_on"] == day(2)
    r = client.post(f"/api/tasks/{late['id']}/done", json={"note": "انجام شد"})
    assert r.json()["status"] == "done" and r.json()["done_note"] == "انجام شد"
    assert client.post(f"/api/tasks/{late['id']}/move", json={"due_on": day(3)}).status_code == 409
    assert client.post(f"/api/tasks/{late['id']}/reopen").json()["status"] == "open"
    r = client.post(f"/api/tasks/{late['id']}/cancel", json={"note": "  "})
    assert r.status_code == 422 and r.json()["error"]["code"] == "note_required"
    r = client.post(f"/api/tasks/{late['id']}/cancel", json={"note": "دیگر لازم نیست"})
    assert r.json()["status"] == "cancelled"
    assert [e["action"] for e in events(client, "task", late["id"])] == ["cancel", "reopen", "done", "move", "create"]
    done_ids = {t["id"] for t in client.get("/api/tasks").json()["groups"]["done"]}
    assert late["id"] in done_ids
    assert [t["id"] for t in client.get(f"/api/cases/{case['id']}/tasks").json()] == [today["id"]]
    cc = client.get("/api/command-center").json()["tasks"]
    assert today["id"] in {t["id"] for t in cc["today"]} and week["id"] not in str(cc)


def test_tender_date_reminders_are_tasks_not_on_the_organizers_followups(client, db):
    case, t, party = manual_tender(client)
    r = client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "proposal_deadline", "at": at(10)})
    d = next(x for x in r.json()["dates"] if x["kind"] == "proposal_deadline")
    assert len(d["reminders"]) == 2 and followups(db, party["id"]) == []
    rows = db.execute(text("SELECT source, source_kind, source_id, case_id, remind_of_due FROM core.task "
                           "WHERE source_id = :d AND status = 'open'"), {"d": d["id"]}).all()
    assert {(r.source, r.source_kind, str(r.case_id)) for r in rows} == {("tenders", "tender_date", case["id"])}
    assert {r.remind_of_due for r in rows} == {date.today() + timedelta(days=10)}
    groups = client.get("/api/tasks", params={"case_id": case["id"], "kind": "tender_date"}).json()["groups"]
    assert len(groups["week"]) + len(groups["later"]) == 2
    # the party's follow-up API stays clean too
    party_page = client.get(f"/api/parties/{party['id']}/followups")
    if party_page.status_code == 200:
        assert not [f for f in party_page.json() if "یادآوری" in str(f)]


def test_step_reminders_are_tasks_and_cancelled_with_the_case(client, db):
    case, items, party, quote, so = confirmed_order(client)
    p = client.get(f"/api/cases/{case['id']}/execution").json()["processes"][0]
    r = client.patch(f"/api/process-steps/{p['steps'][0]['id']}", json={"due_on": day(12)})
    assert r.status_code == 200, r.text
    n = db.execute(text("SELECT count(*) FROM core.task WHERE case_id = :c AND source_kind = 'process_step' AND status = 'open'"),
                   {"c": case["id"]}).scalar()
    assert n > 0
    assert not [f for f in followups(db, party["id"]) if "—" in f.action]                  # no step reminders on the customer
    client.patch(f"/api/cases/{case['id']}", json={"status": "cancelled"})
    db.expire_all()
    assert db.execute(text("SELECT count(*) FROM core.task WHERE case_id = :c AND source_kind = 'process_step' "
                           "AND status = 'open'"), {"c": case["id"]}).scalar() == 0


def test_delivered_creates_invoice_warranty_and_warranty_reminder_tasks(client, db):
    case, party, so, pos = deal(client, warranty_months=12)
    from app.modules.execution.deliveries import add_months

    r = client.post("/api/deliveries", json={"sales_order_id": so["id"], "delivered_on": day(0),
                                             "items": [{"sales_order_item_id": i["id"], "quantity": i["quantity"]} for i in so["items"]]})
    assert r.json()["status"] == "delivered"
    db.expire_all()
    ends = add_months(date.today(), 12)
    assert [f.due_on for f in open_followups(db, so["id"], "warranty_end")] == [ends]
    remind = open_followups(db, so["id"], "warranty_remind")
    assert [f.due_on for f in remind] == [ends - timedelta(days=30)]                          # setting default 30
    assert len(open_followups(db, so["id"], "invoice")) == 1
    assert not [f for f in followups(db, party["id"]) if "گارانتی" in f.action or "فاکتور" in f.action]
    # the setting changes the offset
    assert client.patch("/api/settings", json={"execution.warranty_remind_days": 45}).status_code in (200, 204)
    case2, party2, so2, _ = deal(client, warranty_months=6)
    client.post("/api/deliveries", json={"sales_order_id": so2["id"], "delivered_on": day(0),
                                         "items": [{"sales_order_item_id": i["id"], "quantity": i["quantity"]} for i in so2["items"]]})
    db.expire_all()
    assert [f.due_on for f in open_followups(db, so2["id"], "warranty_remind")] == [add_months(date.today(), 6) - timedelta(days=45)]
    client.patch("/api/settings", json={"execution.warranty_remind_days": 30})


# ---- 0.2 fixes ------------------------------------------------------------------------------------------------------------

def test_a_partly_received_prepayment_keeps_the_gate_closed(client):
    case, items, party, quote, so = confirmed_order(client)
    usd = by_currency(create_pos(client, so)["created"])["USD"]
    ms = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "prepayment", "amount": "1875",
                                                      "amount_currency": so["currency"]}).json()
    client.post(f"/api/payment-milestones/{ms['id']}/payments", json={"amount": "1000", "paid_on": day(0)})
    client.post(f"/api/purchase-orders/{usd['id']}/approve")
    r = client.post(f"/api/purchase-orders/{usd['id']}/mark-sent", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "customer_prepayment_missing"
    pre = r.json()["error"]["details"]["prepayments"][0]
    assert pre["status"] == "partly" and Decimal(pre["received"]) == 1000 and Decimal(pre["expected"]) == 1875
    r = client.post(f"/api/purchase-orders/{usd['id']}/mark-sent", json={"confirm_without_prepayment": True, "reason": "مشتری معتبر"})
    assert r.status_code == 200 and r.json()["prepayment_override_reason"] == "مشتری معتبر"
    # fully received: no reason needed
    eur = by_currency(client.get(f"/api/cases/{case['id']}/execution").json()["purchase_orders"])["EUR"]
    client.post(f"/api/payment-milestones/{ms['id']}/payments", json={"amount": "875", "paid_on": day(0)})
    assert sent_po(client, eur)["prepayment_override_reason"] is None


def test_sending_an_already_sent_or_confirmed_po_says_so(client):
    case, items, party, quote, so = confirmed_order(client)
    usd = by_currency(create_pos(client, so)["created"])["USD"]
    po = sent_po(client, usd)
    r = client.post(f"/api/purchase-orders/{po['id']}/mark-sent", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "purchase_order_already_sent"
    assert r.json()["error"]["details"]["status"] == "sent"
    client.post(f"/api/purchase-orders/{po['id']}/confirm", json={"confirmed_ready_on": day(10)})
    r = client.post(f"/api/purchase-orders/{po['id']}/mark-sent", json={})
    assert r.json()["error"]["code"] == "purchase_order_already_sent" and r.json()["error"]["details"]["status"] == "confirmed"
    eur = by_currency(client.get(f"/api/cases/{case['id']}/execution").json()["purchase_orders"])["EUR"]
    r = client.post(f"/api/purchase-orders/{eur['id']}/mark-sent", json={})                     # still a draft
    assert r.json()["error"]["code"] == "purchase_order_not_approved"


def test_claim_counterparty_defaults_from_the_linked_record(client):
    case, party, so, pos = deal(client)
    usd = pos["USD"]
    carrier = client.post("/api/parties", json={"name_en": "Carrier Co", "roles": ["forwarder"], "confirm_duplicate": True})
    carrier_id = carrier.json()["party"]["id"] if carrier.status_code < 300 else None
    s = client.post("/api/shipments", json={"purchase_order_id": usd["id"], "carrier_party_id": carrier_id}).json()
    rec = client.post("/api/receipts", json={"purchase_order_id": usd["id"], "received_on": day(0), "items": [
        {"purchase_order_item_id": usd["items"][0]["id"], "quantity": "1"}]}).json()
    insp = client.post("/api/inspections", json={"purchase_order_id": usd["id"], "kind": "on_arrival"}).json()
    d = client.post("/api/deliveries", json={"sales_order_id": so["id"], "delivered_on": day(0), "items": [
        {"sales_order_item_id": so["items"][0]["id"], "quantity": "1"}]}).json()
    delivery_id = client.get(f"/api/cases/{case['id']}/execution").json()["deliveries"][0]["id"]
    assert d
    for link, expected in ((("purchase_order_id", usd["id"]), usd["supplier_party_id"]),
                           (("receipt_id", rec["id"]), usd["supplier_party_id"]),
                           (("inspection_id", insp["id"]), usd["supplier_party_id"]),
                           (("shipment_id", s["id"]), carrier_id),
                           (("delivery_id", delivery_id), so["customer_party_id"])):
        r = client.post("/api/claims", json={"direction": "against_supplier", "kind": "other", link[0]: link[1]})
        assert r.status_code == 201, (link, r.text)
        assert r.json()["counterparty_id"] == expected, link
    # the owner can change it
    other = client.post("/api/parties", json={"name_en": "Other party", "roles": ["supplier"], "confirm_duplicate": True}).json()["party"]
    r = client.post("/api/claims", json={"direction": "against_supplier", "kind": "other", "purchase_order_id": usd["id"],
                                         "counterparty_id": other["id"]})
    assert r.json()["counterparty_id"] == other["id"]
    # nothing to default from: still required
    r = client.post("/api/claims", json={"case_id": case["id"], "direction": "against_supplier", "kind": "other"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "counterparty_required"


def test_po_price_check_converts_with_the_sheet_rates_or_flags_a_missing_rate(client, db):
    from app.modules.costing import service as costing
    from app.modules.costing.models import CostLine, FxRateEntry
    from app.modules.execution import purchase_orders as po_service
    from app.modules.execution.models import PurchaseOrder

    case, items, party, quote, so = confirmed_order(client)
    pos = by_currency(create_pos(client, so)["created"])
    usd = db.get(PurchaseOrder, __import__("uuid").UUID(pos["USD"]["id"]))
    sheet = costing.current_sheet(db, usd.case_id)
    line = next(ln for ln in costing.lines_of(db, sheet.id) if ln.kind == "purchase" and ln.scope == "item"
                and str(ln.line_item_id) == str(po_service.items_of(db, usd.id)[0].line_item_id))
    item = po_service.items_of(db, usd.id)[0]
    assert po_service.above_cost_sheet(db, usd) == []                         # same currency, at the sheet price
    # the sheet line in IRR; the PO in USD
    line.currency, line.amount = "IRR", item.unit_price * Decimal(600000)
    for e in costing.fx_of(db, sheet.id):
        db.delete(e)
    db.flush()
    flagged = po_service.above_cost_sheet(db, usd)
    assert flagged and flagged[0]["check"] == "fx_missing" and flagged[0]["message_fa"] == "نرخ ارز در برگهٔ هزینه نیست"
    db.add(FxRateEntry(cost_sheet_id=sheet.id, from_currency="USD", to_currency="IRR", rate=Decimal(600000),
                       rate_kind="free market", as_of=date.today()))
    db.flush()
    assert po_service.above_cost_sheet(db, usd) == []                         # converted: equal to the sheet price
    db.query(FxRateEntry).filter(FxRateEntry.cost_sheet_id == sheet.id).update({"rate": Decimal(700000)})
    db.flush()
    above = po_service.above_cost_sheet(db, usd)
    assert above and above[0]["check"] == "above" and Decimal(above[0]["rate"]) == 700000
    assert Decimal(above[0]["unit_price_converted"]) == item.unit_price * 700000
    # approving needs a reason
    db.commit()
    r = client.post(f"/api/purchase-orders/{usd.id}/approve")
    assert r.status_code == 409 and r.json()["error"]["details"]["items"][0]["check"] == "above"
    assert isinstance(line, CostLine)
    db.rollback()
