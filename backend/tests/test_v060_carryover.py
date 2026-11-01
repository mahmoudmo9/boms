"""v0.6.0 section 0: carry-over fixes from v0.5.0 (Setad guarantee/estimate keys, apply-deadline report, agent
launch message, one-page quote PDF, exact-time deadline filter, download/detail results, deduplication, agent log)."""
import os
import re
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.connectors.setad import agent as agent_mod
from app.connectors.setad.rows import SOURCE_PURCHASE, SOURCE_TENDER, guarantee_hint_amount, tender_row
from app.core.db import new_session
from app.core.time import utcnow
from app.modules.listings import service
from app.modules.listings.store import ListingStore

from tests.test_listings_store import tag, tender_raw


# ---- 1. guarantee and estimate from the real Setad keys --------------------------------------------------------

def test_tender_row_reads_the_real_guarantee_and_estimate_keys():
    raw = tender_raw(1, "g", guarantyPrice=1250000000.0, guarantyPriceCurrency="ریال",
                     guarantyDescription="ضمانت‌نامه بانکی", tndaFinancialEstimatesPrice=25000000000.0,
                     tndaFinancialEstimatesPriceCurrencyStr="ریال")
    row = tender_row(raw)
    assert row["guarantee_amount"] == "1250000000.0" and row["guarantee_currency"] == "ریال"
    assert row["guarantee_description"] == "ضمانت‌نامه بانکی"
    assert row["estimate"] == "25000000000.0" and row["estimate_currency"] == "ریال"
    # the earlier guesses stay as fallbacks; an empty row leaves the fields out
    old = tender_row(tender_raw(2, "g", guaranteeAmount=5000.0, estimatePrice=9000.0))
    assert old["guarantee_amount"] == "5000.0" and old["estimate"] == "9000.0"
    none = tender_row(tender_raw(3, "g", guarantyPrice=None))
    assert "guarantee_amount" not in none and "estimate" not in none
    for key in ("financialEstimatePrice", "elvFinancialEstimatePrice"):
        assert tender_row(tender_raw(4, "g", **{key: 7.0, f"{key}CurrencyStr": "IRR"}))["estimate_currency"] == "IRR"


def test_guarantee_from_the_detail_page_when_the_list_has_none(db):
    p = tag()
    store = ListingStore(new_session)
    store.start_run(SOURCE_TENDER, "full")
    store.add_tenders([tender_raw(1, p, guarantyPrice=None)])
    store.save_detail(f"{p}1", "...", [["مدت اعتبار تضمین", "۹۰ روز"], ["مبلغ تضمین", "۱۲۰,۰۰۰,۰۰۰ ریال"]])
    row = db.execute(text("SELECT guarantee_amount, guarantee_currency FROM ext.listing WHERE external_id = :e"),
                     {"e": f"{p}1"}).one()
    assert int(row[0]) == 120_000_000 and row[1] == "ریال"
    # a later list row without a guarantee does not wipe the detail value, and writes no change row
    store.add_tenders([tender_raw(1, p, guarantyPrice=None)])
    store.finish_run("done")
    db.expire_all()
    assert int(db.execute(text("SELECT guarantee_amount FROM ext.listing WHERE external_id = :e"),
                          {"e": f"{p}1"}).scalar()) == 120_000_000
    assert db.execute(text("SELECT count(*) FROM ext.listing_change c JOIN ext.listing l ON l.id = c.listing_id "
                           "WHERE l.external_id = :e"), {"e": f"{p}1"}).scalar() == 0
    assert guarantee_hint_amount([["مدت اعتبار تضمین", "۹۰ روز"]]) == (None, "")


# ---- 2. "Apply deadline" reports the dates it really applied -----------------------------------------------------

def test_apply_deadline_reports_old_and_new_followup_dates(client, db, tmp_path):
    from datetime import date

    from tests.test_setad_convert import DETAIL_FIELDS, convert, make_listing, new_buyer, star

    client.patch("/api/settings", json={"setad.files_dir": str(tmp_path)})
    try:
        org = f"اداره {tag()}"
        party = new_buyer(client, org)
        lid = make_listing(db, tmp_path, organization=org, files=())
        star(client, lid)
        inquiry_id = convert(client, lid).json()["inquiry_id"]
        f = client.post("/api/followups", json={"party_id": party["id"], "action": "پیش‌فاکتور", "due_on": "2026-11-08"}).json()
        external_id = db.execute(text("SELECT external_id FROM ext.listing WHERE id = :l"), {"l": lid}).scalar_one()
        ListingStore(new_session).save_need_detail(external_id, {"info": {
            "fields": [["مهلت ارسال پاسخ", "1405/08/23 ساعت 14:00"]] + DETAIL_FIELDS[1:]}, "attachments": []})
        r = client.post(f"/api/listings/by-inquiry/{inquiry_id}/apply-deadline")
        assert r.status_code == 200, r.text
        assert r.json()["followups_moved"] == [{"id": f["id"], "old": "2026-11-08", "new": "2026-11-11"}]
        event = db.execute(text("SELECT data FROM core.event WHERE entity_type = 'inquiry' AND entity_id = :i AND "
                                "action = 'deadline_apply'"), {"i": inquiry_id}).scalar_one()
        assert event["followups_moved"] == [{"id": f["id"], "old": "2026-11-08", "new": "2026-11-11"}]
        assert db.execute(text("SELECT due_on FROM core.followup WHERE id = :i"), {"i": f["id"]}).scalar() == date(2026, 11, 11)
    finally:
        client.patch("/api/settings", json={"setad.files_dir": None})


# ---- 4. a browser that cannot be launched is not "a closed window" ------------------------------------------------

def test_launch_failure_keeps_its_message_and_a_real_close_says_closed(tmp_path):
    from app.connectors.setad.bridge import SetadBrowser, SiteError

    browser = SetadBrowser(tmp_path / "profile", headless=True, channels=("no-such-channel", "msedge-nope"))
    with pytest.raises(SiteError) as exc:
        browser.open()
    text_ = agent_mod.status_text(exc.value)
    assert text_.startswith("مرورگر قابل اجرا پیدا نشد") and "no-such-channel" in text_ and "msedge-nope" in text_
    assert "بسته شد" not in text_
    # Playwright's launch errors often say "has been closed": still the launch message
    launch = SiteError("مرورگر قابل اجرا پیدا نشد. Microsoft Edge یا Google Chrome را نصب کنید.\n"
                       "msedge: Target page, context or browser has been closed")
    assert agent_mod.status_text(launch).startswith("مرورگر قابل اجرا پیدا نشد")
    assert agent_mod.status_text("Target page, context or browser has been closed").startswith("پنجره مرورگر ستاد بسته شد")


# ---- 5. a one-page quote prints on one page ---------------------------------------------------------------------

def _pdf_pages(data: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


def test_one_page_quote_pdf_has_one_page_with_or_without_footer(client):
    from app.modules.quotes import output

    from tests.test_quotes import new_quote, ready_case

    browser = os.environ.get("BOMS_TEST_PDF_BROWSER") or next(
        (p for p in output._candidates() + ["/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/"
                                             "chrome-headless-shell"] if os.path.isfile(p)), None)
    if browser is None:
        pytest.skip("no Chromium for PDF on this machine")
    client.patch("/api/settings", json={"pdf.browser_path": browser})
    try:
        case, items, party, sheet = ready_case(client, country="IR")
        quote = new_quote(client, case)
        for footer in ("", 'تهران، خیابان "ولیعصر"\nتلفن ۰۲۱-۱۲۳۴'):
            client.patch("/api/settings", json={"company.footer": {"fa": footer, "en": footer}})
            r = client.post(f"/api/quotes/{quote['id']}/outputs", json={"format": "pdf"})
            assert r.status_code == 201, r.text
            with new_session() as db:
                from app.modules.documents import service as documents

                doc = documents.get(db, uuid.UUID(r.json()["document_id"]))
                data = documents.file_path(doc).read_bytes()
            assert _pdf_pages(data) == 1, (footer, _pdf_pages(data))
        html = client.get(f"/api/quotes/{quote['id']}/print").text
        assert "@bottom-center" in html and "bottom: -12mm" not in html
    finally:
        client.patch("/api/settings", json={"pdf.browser_path": None, "company.footer": {"fa": "", "en": ""}})


# ---- 6.1 "within N days" uses the exact time --------------------------------------------------------------------

def test_within_one_day_uses_the_exact_time(db):
    p = tag()
    store = ListingStore(new_session)
    store.start_run(SOURCE_PURCHASE, "full")
    from tests.test_listings_store import needs

    store.upsert_needs(needs(p, 2))
    store.finish_run("done")
    ids = [r[0] for r in db.execute(text("SELECT id FROM ext.listing WHERE external_id IN (:a, :b) ORDER BY external_id"),
                                    {"a": f"{p}0", "b": f"{p}1"}).all()]
    now = utcnow()
    db.execute(text("UPDATE ext.listing SET response_deadline = :d WHERE id = :i"), {"d": now + timedelta(hours=20), "i": ids[0]})
    db.execute(text("UPDATE ext.listing SET response_deadline = :d WHERE id = :i"), {"d": now + timedelta(hours=30), "i": ids[1]})
    db.commit()
    page = service.query(db, {"source": SOURCE_PURCHASE, "deadline": "within", "within_days": 1,
                              "include_old": True, "page_size": 1000})
    found = {r["id"] for r in page["items"]}
    assert ids[0] in found and ids[1] not in found


# ---- 6.2 (c) the same command for the same listing is not queued twice ------------------------------------------

def test_duplicate_listing_commands_are_not_queued_again(db):
    db.execute(text("DELETE FROM sys.job WHERE lane = 'setad'"))
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    for lid in (a, b):
        db.execute(text("INSERT INTO ext.listing (id, source, external_id, first_seen, last_seen) VALUES "
                        "(:i, 'setad_purchase', :e, now(), now())"), {"i": lid, "e": f"dedup-{lid[:8]}"})
    first = service.command(db, "download_files", {"listing_ids": [a]}, "script")
    again = service.command(db, "download_files", {"listing_ids": [a]}, "script")
    assert again.id == first.id
    bulk = service.command(db, "download_files", {"listing_ids": [a, b]}, "script")
    assert bulk.id != first.id and bulk.payload["listing_ids"] == [b]          # only the new listing is queued
    detail = service.command(db, "fetch_detail", {"listing_ids": [a]}, "script")
    assert detail.id != first.id                                              # another command is not a duplicate
    assert service.command(db, "fetch_detail", {"listing_ids": [a]}, "script").id == detail.id
    jobs = service.agent_status(db)["jobs"]
    assert {(j["command"], tuple(j["listing_ids"])) for j in jobs} >= {("download_files", (a,)), ("download_files", (b,)),
                                                                      ("fetch_detail", (a,))}
    fetch = service.command(db, "full_fetch", {"source": SOURCE_PURCHASE}, "script")
    assert service.command(db, "full_fetch", {"source": SOURCE_PURCHASE}, "script").id == fetch.id
    db.rollback()


# ---- 6.2 (a, e, f) real download / detail results, written to the job, an event and the log ----------------------

from tests.test_setad_agent import agent, listing_id, run  # noqa: E402,F401  (the fake-host agent fixture)


def test_download_and_detail_results_per_listing_with_a_failing_file(agent, db, client):  # noqa: F811
    from app.core.config import get_config
    from tests.connectors.setad import fakesite

    import logging

    logs = get_config().data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = agent_mod.setup_logging(logs / "setad-agent.log")   # as main() does
    run(agent, "connect", role="EPROC")
    run(agent, "full_fetch", source=SOURCE_PURCHASE)
    good, bad = fakesite.FAKE.needs[3], fakesite.FAKE.needs[6]
    fakesite.FAKE.waf_files = {bad["files"][1][0]}                     # the 2nd attachment of `bad` is blocked
    ids = [listing_id(db, SOURCE_PURCHASE, n["request_id"]) for n in (good, bad)]
    detail_job = run(agent, "fetch_detail", listing_ids=[str(i) for i in ids])
    r = client.get(f"/api/setad/jobs/{detail_job}").json()
    assert r["status"] == "done" and [x["result"] for x in r["result"]["listings"]] == ["fetched", "fetched"]
    job_id = run(agent, "download_files", listing_ids=[str(i) for i in ids])
    result = client.get(f"/api/setad/jobs/{job_id}").json()["result"]
    by_no = {x["external_no"]: x for x in result["listings"]}
    assert by_no[good["no"]]["result"] == "ok" and by_no[good["no"]]["counts"]["downloaded"] == 2
    assert by_no[bad["no"]]["result"] == "partial" and by_no[bad["no"]]["counts"]["downloaded"] == 1
    assert by_no[bad["no"]]["counts"]["failed"] == 1 and "HTML" in by_no[bad["no"]]["failures"][0]
    assert result["totals"]["downloaded"] == 3 and result["totals"]["failed"] == 1
    # (f) the files are in the API right after the job
    db.expire_all()
    states = sorted(f["state"] for f in service.detail(db, ids[1])["files"])
    assert states.count("downloaded") == 1
    # an event per listing carries the result
    ev = db.execute(text("SELECT data FROM core.event WHERE entity_type = 'listing' AND entity_id = :i AND "
                         "action = 'download_result' ORDER BY id DESC LIMIT 1"), {"i": str(ids[1])}).scalar_one()
    assert ev["result"] == "partial"
    # (e) the log has the command's lines (filtered by job id) without secrets
    lines = client.get("/api/setad/log", params={"job_id": str(job_id)}).json()["lines"]
    assert any("download_files" in line and "done" in line for line in lines)
    assert any("دانلود شد" in line for line in lines)
    logging.getLogger().removeHandler(handler)
    handler.close()
    fakesite.FAKE.waf_files = set()
