"""v0.6.0 Phase 7b, milestone 1: the tender part of a case, Setad prefill and refresh, dates with reminders and
history, addenda, the Setad date-change banner and new-addenda notice."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.connectors.setad import jalali
from app.connectors.setad.rows import TEHRAN
from app.core.db import new_session
from app.modules.listings.store import ListingStore

from tests.test_listings_store import tag, tender_raw
from tests.test_sourcing_inquiries import decide, events
from tests.test_sourcing_rfq import make_case


def jdate(days: int, hm: str = "12:00:00") -> str:
    return f"{jalali.from_date(date.today() + timedelta(days=days))} {hm}"


def setad_raw(i: int, p: str, **extra):
    return tender_raw(i, p, **{
        "typeName": "مناقصه عمومی یک مرحله ای", "type": "ONE_STAGE_TENDER", "tenderDocumentsPrice": 1500000.0,
        "documentsDeadlineDate": jdate(10), "proposalDeadlineDate": jdate(20), "openingDate": jdate(21, "10:00:00"),
        "guarantyPrice": 1250000000.0, "guarantyPriceCurrency": "ریال", "guarantyDescription": "ضمانت‌نامه بانکی",
        "financialEstimatePrice": 25000000000.0, "financialEstimatePriceCurrencyStr": "ریال",
        "renewalAppendixCount": 0, "priceAppendixCount": 0, "cancelAppendixCount": 0, **extra})


def setad_listing(db, raw) -> str:
    store = ListingStore(new_session)
    store.start_run("setad_tender", "full")
    store.add_tenders([raw])
    store.finish_run("done")
    return str(db.execute(text("SELECT id FROM ext.listing WHERE source = 'setad_tender' AND external_id = :e"),
                          {"e": raw["id"]}).scalar_one())


def refetch(raw):
    store = ListingStore(new_session)
    store.start_run("setad_tender", "quick")
    store.add_tenders([raw])
    store.finish_run("done")


def to_case(client, inquiry_id) -> dict:
    assert decide(client, inquiry_id, feasible_sourcing="yes", exposure_acceptable="yes",
                  requirements_ok="yes").status_code in (200, 201)
    r = client.post(f"/api/inquiries/{inquiry_id}/convert", json={})
    assert r.status_code == 201, r.text
    return r.json()


def setad_tender_case(client, db, **extra):
    """A Setad tender listing -> starred -> converted -> decision -> case (the tender part is created by the hook)."""
    p = tag()
    raw = setad_raw(1, p, **extra)
    lid = setad_listing(db, raw)
    assert client.post(f"/api/listings/{lid}/screen", json={"action": "star"}).status_code == 200
    r = client.post(f"/api/listings/{lid}/convert", json={"create_party": True, "confirm_duplicate": True,
                                                         "without_missing_files": True})
    assert r.status_code == 201, r.text
    case = to_case(client, r.json()["inquiry_id"])
    tender = client.get(f"/api/cases/{case['id']}/tender").json()
    assert tender is not None
    return case, tender, raw, lid


def followups(db, party_id, status="open"):
    return db.execute(text("SELECT id, action, due_on FROM core.followup WHERE party_id = :p AND status = :s ORDER BY due_on"),
                      {"p": party_id, "s": status}).all()


def tender_day(value) -> date:
    return (datetime.fromisoformat(value) if isinstance(value, str) else value).astimezone(TEHRAN).date()


# ---- creation and prefill --------------------------------------------------------------------------------------------

def test_setad_tender_case_is_prefilled(client, db):
    case, t, raw, lid = setad_tender_case(client, db)
    assert t["tender_no"] == raw["number"] and t["tender_type"] == "مناقصه عمومی یک مرحله ای" and t["stages"] == "one_stage"
    assert t["listing_id"] == lid and t["organizer_party_id"] == case["party_id"] and t["stage"] == "screening"
    assert Decimal(t["document_price"]) == Decimal("1500000") and t["document_price_currency"] == "IRR"
    assert Decimal(t["estimate"]) == Decimal("25000000000") and t["estimate_currency"] == "IRR"
    kinds = {d["kind"]: d for d in t["dates"]}
    assert set(kinds) >= {"documents_deadline", "proposal_deadline", "opening"}
    assert all(d["source"] == "setad" for d in t["dates"])
    assert tender_day(kinds["proposal_deadline"]["at"]) == date.today() + timedelta(days=20)
    bid = next(g for g in t["guarantees"] if g["purpose"] == "bid")
    assert Decimal(bid["amount"]) == Decimal("1250000000") and bid["amount_currency"] == "IRR"
    assert bid["status"] == "to_request" and bid["description"] == "ضمانت‌نامه بانکی"
    cost = next(c for c in t["costs"] if c["kind"] == "documents_purchase")
    assert Decimal(cost["amount"]) == Decimal("1500000") and cost["paid_on"] is None
    # the default envelope template was copied, the bid bond item points at the bid bond
    assert t["envelope_progress"]["all"] == [0, 14]
    bond_item = next(i for i in t["envelope_items"] if i["kind"] == "bid_bond")
    assert bond_item["envelope"] == "A" and bond_item["guarantee_id"] == bid["id"]
    assert [e["action"] for e in events(client, "tender", t["id"], "create")] == ["create"]


def test_make_this_a_tender_on_a_normal_case(client):
    case, items = make_case(client, [{"name": "Pump", "quantity": "2"}])
    r = client.post(f"/api/cases/{case['id']}/tender")
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["tender_no"] is None and t["listing_id"] is None and t["dates"] == [] and t["guarantees"] == []
    assert t["envelope_progress"]["all"][1] == 14
    r = client.post(f"/api/cases/{case['id']}/tender")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_a_tender"
    r = client.patch(f"/api/tenders/{t['id']}", json={"tender_no": "1404-55", "participation": "no"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    r = client.patch(f"/api/tenders/{t['id']}", json={"tender_no": "1404-55", "stage": "documents",
                                                     "document_price": "500000"})
    assert r.status_code == 200 and r.json()["document_price_currency"] == "IRR" and r.json()["stage"] == "documents"


def test_refresh_from_setad_shows_a_diff_and_applies_only_on_confirm(client, db):
    case, t, raw, lid = setad_tender_case(client, db)
    assert client.get(f"/api/tenders/{t['id']}/setad-refresh").json()["changes"] == []
    refetch({**raw, "proposalDeadlineDate": jdate(25), "guarantyPrice": 1500000000.0, "tenderDocumentsPrice": 2000000.0})
    diff = {c["field"]: c for c in client.get(f"/api/tenders/{t['id']}/setad-refresh").json()["changes"]}
    assert set(diff) == {"date:proposal_deadline", "guarantee_amount", "document_price"}
    # nothing was applied by looking
    again = client.get(f"/api/tenders/{t['id']}").json()
    assert tender_day(next(d for d in again["dates"] if d["kind"] == "proposal_deadline")["at"]) == date.today() + timedelta(days=20)
    r = client.post(f"/api/tenders/{t['id']}/setad-refresh", json={"fields": ["date:proposal_deadline", "guarantee_amount"]})
    assert r.status_code == 200, r.text
    after = r.json()
    proposal = next(d for d in after["dates"] if d["kind"] == "proposal_deadline")
    assert tender_day(proposal["at"]) == date.today() + timedelta(days=25)
    assert Decimal(next(g for g in after["guarantees"] if g["purpose"] == "bid")["amount"]) == Decimal("1500000000")
    assert Decimal(after["document_price"]) == Decimal("1500000")          # not confirmed: unchanged
    change = next(c for c in after["date_changes"] if c["tender_date_id"] == proposal["id"])
    assert change["reason"] == "به‌روزرسانی از ستاد"
    r = client.post(f"/api/tenders/{t['id']}/setad-refresh", json={"fields": ["estimate"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "nothing_to_apply"


# ---- dates and reminders --------------------------------------------------------------------------------------------

def manual_tender(client):
    case, items = make_case(client, [{"name": "Valve", "quantity": "5"}])
    party = client.post("/api/parties", json={"name_fa": f"برگزارکننده {tag()}", "roles": ["buyer"],
                                              "confirm_duplicate": True}).json()["party"]
    t = client.post(f"/api/cases/{case['id']}/tender").json()
    t = client.patch(f"/api/tenders/{t['id']}", json={"organizer_party_id": party["id"], "tender_no": f"T-{tag()}"}).json()
    return case, t, party


def at(days: int, hour: int = 12) -> str:
    return datetime.combine(date.today() + timedelta(days=days), datetime.min.time().replace(hour=hour), TEHRAN).isoformat()


def test_reminders_per_remind_day_and_none_for_passed_dates(client, db):
    case, t, party = manual_tender(client)
    r = client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "proposal_deadline", "at": at(10)})
    assert r.status_code == 201, r.text
    d = next(x for x in r.json()["dates"] if x["kind"] == "proposal_deadline")
    assert d["remind_days_before"] == [3, 1]                                   # setting tenders.reminder_days
    assert sorted(x["due_on"] for x in d["reminders"]) == [(date.today() + timedelta(days=n)).isoformat() for n in (7, 9)]
    rows = followups(db, party["id"])
    assert any(r.action.startswith("یادآوری: مهلت ارسال پیشنهاد") and t["tender_no"] in r.action for r in rows)
    # 2 days ahead: the 3-day reminder would be in the past; only the 1-day one is created
    r = client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "site_visit", "at": at(2)})
    site = next(x for x in r.json()["dates"] if x["kind"] == "site_visit")
    assert [x["days_before"] for x in site["reminders"]] == [1]
    # passed: none
    r = client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "briefing", "at": at(-3)})
    assert next(x for x in r.json()["dates"] if x["kind"] == "briefing")["reminders"] == []
    r = client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "other", "at": at(5)})
    assert r.status_code == 422                                                # "other" needs a label
    r = client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "proposal_deadline", "at": at(11)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "date_exists"


def test_moving_a_date_moves_its_reminders_and_keeps_history(client, db):
    case, t, party = manual_tender(client)
    d = next(x for x in client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "proposal_deadline", "at": at(10)})
             .json()["dates"] if x["kind"] == "proposal_deadline")
    r = client.patch(f"/api/tender-dates/{d['id']}", json={"at": at(14)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    r = client.patch(f"/api/tender-dates/{d['id']}", json={"at": at(14), "reason": "تمدید به درخواست شرکت‌کنندگان"})
    assert r.status_code == 200, r.text
    moved = next(x for x in r.json()["dates"] if x["id"] == d["id"])
    assert sorted(x["due_on"] for x in moved["reminders"]) == [(date.today() + timedelta(days=n)).isoformat() for n in (11, 13)]
    assert len({x["id"] for x in moved["reminders"]} & {x["id"] for x in d["reminders"]}) == 2   # same follow-ups, moved
    change = r.json()["date_changes"][-1]
    assert change["reason"] == "تمدید به درخواست شرکت‌کنندگان" and tender_day(change["old_at"]) == date.today() + timedelta(days=10)
    # fewer reminder days: the 3-day one is cancelled
    r = client.patch(f"/api/tender-dates/{d['id']}", json={"remind_days_before": [1]})
    assert [x["days_before"] for x in next(x for x in r.json()["dates"] if x["id"] == d["id"])["reminders"]] == [1]
    assert any("tender reminders changed" == row[0] for row in db.execute(text(
        "SELECT done_note FROM core.followup WHERE party_id = :p AND status = 'cancelled'"), {"p": party["id"]}).all())


def test_addendum_extension_applies_linked_date_changes(client, db):
    case, t, party = manual_tender(client)
    d = next(x for x in client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "proposal_deadline", "at": at(10)})
             .json()["dates"] if x["kind"] == "proposal_deadline")
    r = client.post(f"/api/tenders/{t['id']}/addenda", json={
        "number": "2", "received_on": date.today().isoformat(), "kind": "extension", "summary": "تمدید مهلت ارسال پیشنهاد",
        "date_changes": [{"date_id": d["id"], "at": at(17)}, {"kind": "opening", "at": at(18)}]})
    assert r.status_code == 201, r.text
    body = r.json()
    add = body["addenda"][0]
    assert add["kind"] == "extension" and add["number"] == "2"
    change = next(c for c in body["date_changes"] if c["tender_date_id"] == d["id"])
    assert change["addendum_id"] == add["id"] and change["reason"].startswith("تمدید 2")
    moved = next(x for x in body["dates"] if x["id"] == d["id"])
    assert moved["source"] == "addendum" and tender_day(moved["at"]) == date.today() + timedelta(days=17)
    assert sorted(x["due_on"] for x in moved["reminders"]) == [(date.today() + timedelta(days=n)).isoformat() for n in (14, 16)]
    assert any(x["kind"] == "opening" and x["source"] == "addendum" for x in body["dates"])
    # questions and answers
    r = client.post(f"/api/tenders/{t['id']}/addenda", json={
        "received_on": date.today().isoformat(), "kind": "question_answer", "summary": "پرسش دربارهٔ برند",
        "question": "آیا برند معادل قابل قبول است؟", "asked_on": date.today().isoformat()})
    qa = next(a for a in r.json()["addenda"] if a["kind"] == "question_answer")
    r = client.patch(f"/api/tender-addenda/{qa['id']}", json={"answer": "بله با تأیید کارفرما", "answered_on": date.today().isoformat()})
    assert next(a for a in r.json()["addenda"] if a["id"] == qa["id"])["answer"] == "بله با تأیید کارفرما"
    assert client.delete(f"/api/tender-addenda/{add['id']}").status_code == 409     # it changed dates
    # a cancellation needs confirmation
    r = client.post(f"/api/tenders/{t['id']}/addenda", json={"received_on": date.today().isoformat(), "kind": "cancellation",
                                                             "summary": "لغو مناقصه"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "confirmation_required"


def test_setad_date_banner_apply_per_date_and_all(client, db):
    case, t, raw, lid = setad_tender_case(client, db)
    assert client.get(f"/api/tenders/{t['id']}").json()["setad_date_changes"] == []
    refetch({**raw, "proposalDeadlineDate": jdate(24), "documentsDeadlineDate": jdate(12)})
    banner = client.get(f"/api/tenders/{t['id']}").json()["setad_date_changes"]
    assert {c["kind"] for c in banner} == {"proposal_deadline", "documents_deadline"}
    cc = client.get("/api/command-center").json()["tenders"]
    assert t["id"] in [x["tender_id"] for x in cc["setad_changes"]]
    r = client.post(f"/api/tenders/{t['id']}/setad-dates/apply", json={"kind": "proposal_deadline"})
    assert r.status_code == 200, r.text
    assert [c["kind"] for c in r.json()["setad_date_changes"]] == ["documents_deadline"]
    prop = next(d for d in r.json()["dates"] if d["kind"] == "proposal_deadline")
    assert next(c for c in r.json()["date_changes"] if c["tender_date_id"] == prop["id"])["reason"] == "تمدید/تغییر در ستاد"
    assert sorted(x["due_on"] for x in prop["reminders"]) == [(date.today() + timedelta(days=n)).isoformat() for n in (21, 23)]
    r = client.post(f"/api/tenders/{t['id']}/setad-dates/apply", json={})
    assert r.json()["setad_date_changes"] == []
    r = client.post(f"/api/tenders/{t['id']}/setad-dates/apply", json={"kind": "opening"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_setad_change"


def test_setad_date_banner_ignores_dates_the_owner_moved_and_can_be_kept(client, db):
    """An addendum that extends the deadline is not offered back as a Setad change; only a later Setad change is,
    and «keep my dates» dismisses it while "Refresh from Setad" still lists every difference."""
    case, t, raw, lid = setad_tender_case(client, db)
    prop = next(d for d in t["dates"] if d["kind"] == "proposal_deadline")
    later = at(30)
    r = client.post(f"/api/tenders/{t['id']}/addenda", json={"received_on": date.today().isoformat(), "kind": "extension",
                    "summary": "تمدید", "date_changes": [{"date_id": prop["id"], "at": later}]})
    assert r.status_code == 201, r.text
    detail = client.get(f"/api/tenders/{t['id']}").json()
    assert detail["setad_date_changes"] == []
    assert "date:proposal_deadline" in [c["field"] for c in client.get(f"/api/tenders/{t['id']}/setad-refresh").json()["changes"]]
    refetch({**raw, "proposalDeadlineDate": jdate(24)})
    banner = client.get(f"/api/tenders/{t['id']}").json()["setad_date_changes"]
    assert [c["kind"] for c in banner] == ["proposal_deadline"]
    r = client.post(f"/api/tenders/{t['id']}/setad-dates/keep")
    assert r.status_code == 200 and r.json()["setad_date_changes"] == []
    kept = next(d for d in r.json()["dates"] if d["kind"] == "proposal_deadline")
    assert datetime.fromisoformat(kept["at"]) == datetime.fromisoformat(later)
    assert db.execute(text("SELECT count(*) FROM core.event WHERE entity_id = :t AND action = 'setad_dates_kept'"),
                      {"t": t["id"]}).scalar() == 1


def test_new_addenda_on_setad_until_recorded(client, db):
    case, t, raw, lid = setad_tender_case(client, db)
    assert client.get(f"/api/tenders/{t['id']}").json()["new_appendices"] == {}
    refetch({**raw, "renewalAppendixCount": 1})
    assert client.get(f"/api/tenders/{t['id']}").json()["new_appendices"] == {"renewal_appendix_count": 1}
    changes = db.execute(text("SELECT field FROM ext.listing_change WHERE listing_id = :l"), {"l": lid}).scalars().all()
    assert "renewal_appendix_count" in changes
    r = client.post(f"/api/tenders/{t['id']}/addenda", json={"received_on": date.today().isoformat(), "kind": "change",
                                                             "summary": "اصلاحیهٔ ۱"})
    assert r.json()["new_appendices"] == {}


def test_result_and_close_and_case_cancel_cancel_the_reminders(client, db):
    case, t, party = manual_tender(client)
    client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "proposal_deadline", "at": at(10)})
    assert len(followups(db, party["id"])) == 2
    r = client.patch(f"/api/tenders/{t['id']}", json={"stage": "closed"})
    assert r.status_code == 200
    assert followups(db, party["id"]) == []
    # back to an active stage: the reminders come back
    client.patch(f"/api/tenders/{t['id']}", json={"stage": "pricing"})
    assert len(followups(db, party["id"])) == 2
    assert client.patch(f"/api/cases/{case['id']}", json={"status": "cancelled"}).status_code == 200
    assert followups(db, party["id"]) == []
    notes = {r[0] for r in db.execute(text("SELECT done_note FROM core.followup WHERE party_id = :p AND status = 'cancelled'"),
                                      {"p": party["id"]}).all()}
    assert "case cancelled" in notes


@pytest.mark.parametrize("path", ["/api/tenders/00000000-0000-0000-0000-000000000000"])
def test_unknown_fields_are_refused(client, path):
    assert client.patch(path, json={"bogus": 1}).status_code == 422
