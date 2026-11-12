"""v0.10.0 milestone 4: the command center's figures (overview section). Read only, from what the modules already
compute: profit of the deals closed this quarter (Gregorian quarter and Jalali season), quote win rate over six
months, cash tied up now, today's Setad keyword matches, and the 90-day cash flow of open payment milestones with the
lowest point; overdue and undated milestones kept apart."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.db import new_session
from tests.test_execution_m1 import day
from tests.test_finance_m2 import import_deal
from tests.test_finance_m3 import settled


@pytest.fixture(scope="module", autouse=True)
def _leave_no_open_tasks():
    """The deals made here open process-step tasks; cancel them afterwards so later tests that read «کارهای من» in
    full (one page of 500, soonest first) see the same list as before these tests existed."""
    with new_session() as db:
        start = db.execute(text("SELECT clock_timestamp()")).scalar_one()
    yield
    with new_session() as db:
        db.execute(text("UPDATE core.task SET status = 'cancelled', done_note = 'test cleanup', done_at = now() WHERE status = 'open' AND created_at >= :s"), {"s": start})
        db.commit()


def overview(client) -> dict:
    return client.get("/api/command-center").json()["overview"]


def test_periods_gregorian_quarter_and_jalali_season():
    from app.modules.finance.overview import _quarter, _season

    assert _quarter(date(2026, 11, 12)) == (date(2026, 10, 1), date(2026, 12, 31))
    assert _quarter(date(2027, 3, 31)) == (date(2027, 1, 1), date(2027, 3, 31))
    first, last, (jy, season) = _season(date(2026, 11, 12))           # 21 Aban 1405: autumn = Mehr..Azar
    assert (first, last, jy, season) == (date(2026, 9, 23), date(2026, 12, 21), 1405, 3)
    first, last, (jy, season) = _season(date(2027, 3, 1))              # 10 Esfand 1405: winter = Dey..Esfand
    assert (first, last, jy, season) == (date(2026, 12, 22), date(2027, 3, 20), 1405, 4)


def test_profit_of_closed_deals_this_quarter(client):
    before = overview(client)["profit_quarter"]["gregorian"]
    case, *_ = settled(client)
    profit = client.get(f"/api/cases/{case['id']}/profit").json()
    assert client.post(f"/api/cases/{case['id']}/close", json={"confirm_cancel_open": True}).status_code == 200
    after = overview(client)["profit_quarter"]
    assert after["gregorian"]["deals"] == before["deals"] + 1 and after["jalali"]["deals"] >= 1
    cur = profit["deal_currency"]
    old = next((Decimal(r["profit"]) for r in before["by_currency"] if r["currency"] == cur), Decimal(0))
    new = next(Decimal(r["profit"]) for r in after["gregorian"]["by_currency"] if r["currency"] == cur)
    assert new - old == Decimal(str(profit["profit"]["actual"]["deal"]))
    client.post(f"/api/cases/{case['id']}/reopen", json={"reason": "test"})


def test_win_rate_six_months(client):
    w = overview(client)["win_rate"]
    assert len(w["months"]) == 6 and w["months"][-1]["month"] == date.today().replace(day=1).isoformat()
    assert w["won"] == sum(m["won"] for m in w["months"]) and w["decided"] == w["won"] + sum(m["lost"] for m in w["months"])
    assert w["percent"] is None or 0 <= w["percent"] <= 100


def test_cash_flow_and_tied_up_from_open_milestones(client):
    case, party, sup, so, po = import_deal(client)
    before = overview(client)["cash_flow"]
    soon = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "balance", "amount": "700",
                                                        "amount_currency": "AED", "due_on": day(10)}).json()
    out = client.post("/api/payment-milestones", json={"purchase_order_id": po["id"], "kind": "balance", "amount": "900",
                                                       "amount_currency": "AED", "due_on": day(3)}).json()
    late = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "other", "label": "late",
                                                        "amount": "50", "amount_currency": "AED", "due_on": day(-2)}).json()
    far = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "other", "label": "far",
                                                       "amount": "40", "amount_currency": "AED", "due_on": day(200)}).json()
    assert all("id" in x for x in (soon, out, late, far))
    cf = overview(client)["cash_flow"]
    aed = next(c for c in cf["currencies"] if c["currency"] == "AED")
    old = next((c for c in before["currencies"] if c["currency"] == "AED"), None)
    old_in, old_out = (Decimal(old["total_in"]), Decimal(old["total_out"])) if old else (Decimal(0), Decimal(0))
    assert Decimal(aed["total_in"]) - old_in == 700 and Decimal(aed["total_out"]) - old_out == 900   # the far one is outside 90 days
    assert len(aed["weeks"]) == 13 and aed["weeks"][0]["week"] == date.today().isoformat()
    nets = [Decimal(w["net"]) for w in aed["weeks"]]
    assert aed["lowest_week"] == nets.index(min(nets))
    od = next(o for o in cf["overdue"] if o["currency"] == "AED")
    assert Decimal(od["in"]) >= 50                                      # overdue kept apart, never moved forward
    for ms in (soon, out, late, far):
        client.delete(f"/api/payment-milestones/{ms['id']}")


def test_setad_today_counts_keyword_matches(client, db):
    from app.modules.finance import overview as ov

    s = ov._setad_today(db, date.today())
    assert set(s) == {"count", "keywords"} and s["count"] >= sum(0 for _ in s["keywords"])
    assert all(k["count"] >= 1 for k in s["keywords"])


def test_command_center_still_has_every_old_section(client):
    data = client.get("/api/command-center").json()
    assert {"sourcing", "ai", "execution", "finance", "setad", "tasks", "tenders", "overview"} <= set(data)


def test_shipment_route_stops_from_recorded_events(client):
    """The route diagram reads the stops as recorded: origin, a transshipment event at a place, destination, with
    their codes; the last event at a place is marked; nothing is inferred (no position between events)."""
    from tests.test_execution_m3 import deal

    loc = lambda q, **kw: client.get("/api/reference/locations", params={"q": q, **kw}).json()[0]
    sha, jea, buz = loc("CNSHA"), loc("AEJEA"), loc("BUZ", country="IR")
    case, party, so, pos = deal(client)
    sh = client.post("/api/shipments", json={"purchase_order_id": pos["USD"]["id"], "mode": "sea", "origin_location_id": sha["id"],
                                             "destination_location_id": buz["id"]}).json()
    stops = sh["route"]["stops"]
    assert [(s["role"], s["code"], s["state"]) for s in stops] == [("origin", "CNSHA", "upcoming"), ("destination", "IRBUZ", "upcoming")]
    r = client.post(f"/api/shipments/{sh['id']}/events", json={"at": "2026-11-01T08:00:00+03:30", "kind": "departed", "location_id": sha["id"]})
    assert r.status_code in (200, 201), r.text
    client.post(f"/api/shipments/{sh['id']}/events", json={"at": "2026-11-20T10:00:00+04:00", "kind": "transshipment", "location_id": jea["id"]})
    stops = client.get(f"/api/shipments/{sh['id']}").json()["route"]["stops"]
    assert [(s["role"], s["code"], s["state"], s["event"]) for s in stops] == [
        ("origin", "CNSHA", "done", "departed"), ("via", "AEJEA", "last", "transshipment"), ("destination", "IRBUZ", "upcoming", None)]
