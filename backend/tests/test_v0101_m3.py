"""v0.10.1 M3: the read-only views behind the command center, case and party pages (sections 4.1, 4.2, 4.6)."""
from sqlalchemy import text

from tests.test_parties import make_party, tag
from tests.test_v0101_m0 import _kpi_data


def test_party_story_since_counts_and_past_timeline(client, db):
    s1, _ = _kpi_data(client, db)
    case = db.execute(text("SELECT case_id FROM ops.purchase_order WHERE supplier_party_id = :p LIMIT 1"), {"p": s1["id"]}).scalar()
    db.execute(text("INSERT INTO core.followup (party_id, action, due_on, status) VALUES (:p, 'Open one', '2099-01-01', 'open')"),
               {"p": s1["id"]})
    db.commit()
    story = client.get(f"/api/parties/{s1['id']}/scorecard").json()["story"]
    assert story["counts"] == {"rfqs": 2, "orders": 4, "claims": 0}
    assert story["since"].startswith("2026-02-01")                     # the first RFQ sent
    kinds = [t["kind"] for t in story["timeline"]]
    assert "rfq_sent" in kinds and "offer" in kinds and "purchase_order" in kinds
    assert all(t["action"] != "Open one" for t in story["timeline"] if "action" in t)
    assert all(t["ref"] != "Open one" for t in story["timeline"])     # open follow-ups are not history
    ats = [t["at"] for t in story["timeline"]]
    assert ats == sorted(ats, reverse=True)
    assert [d["case_id"] for d in story["deals"]] == [str(case)]
    assert set(story["deals"][0]["margin"]) == {"actual", "planned", "expected", "currency"}


def test_party_story_of_a_new_party_is_empty(client):
    p = make_party(client, name_en=f"New {tag()}", roles=["buyer"])
    story = client.get(f"/api/parties/{p['id']}/scorecard").json()["story"]
    assert story == {"since": None, "counts": {"rfqs": 0, "orders": 0, "claims": 0}, "deals": [], "timeline": []}


def test_case_overview_of_an_empty_case(client):
    buyer = make_party(client, name_en=f"Buyer {tag()}", roles=["buyer"])
    c = client.post("/api/cases", json={"title": f"Empty {tag()}", "party_id": buyer["id"]}).json()
    out = client.get(f"/api/cases/{c['id']}/overview").json()
    assert out["order"] is None and out["next_step"] is None and out["deal_type"] is None
    assert out["customer"]["id"] == buyer["id"]
    assert [p["role"] for p in out["people"]] == ["buyer"]
    assert out["documents"] == {"files": [], "count": 0, "shipping": [], "missing": []}
    assert out["forecast"] == [] and out["money"]["expected_profit"] is None


def test_case_overview_next_step_falls_back_to_the_earliest_open_task(client):
    c = client.post("/api/cases", json={"title": f"Tasks {tag()}"}).json()
    for title, due in (("Later", "2099-02-01"), ("Sooner", "2099-01-01")):
        assert client.post("/api/tasks", json={"title": title, "due_on": due, "case_id": c["id"]}).status_code in (200, 201)
    nxt = client.get(f"/api/cases/{c['id']}/overview").json()["next_step"]
    assert nxt["kind"] == "task" and nxt["title"] == "Sooner"


def test_case_overview_unknown_case_is_404(client):
    assert client.get("/api/cases/00000000-0000-7000-8000-000000000000/overview").status_code == 404


def test_today_summary_lists_tasks_done_today(client):
    from app.modules.parties import clock

    t = client.post("/api/tasks", json={"title": f"Done {tag()}", "due_on": clock.today().isoformat()}).json()
    client.post(f"/api/tasks/{t['id']}/done", json={})
    summary = client.get("/api/command-center").json()["tasks"]
    assert any(x["id"] == t["id"] for x in summary["done_today"])
