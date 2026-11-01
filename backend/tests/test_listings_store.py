"""v0.5.0 listings store: change tracking (only tracked fields), idempotent refresh, the 0.9.23 list rule, quick
fetches that never hide older rows, purchase-call details and files."""
import json
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text

from app.connectors.setad.eproc_parser import Need
from app.connectors.setad.rows import SOURCE_PURCHASE, SOURCE_TENDER, TEHRAN
from app.core.db import new_session
from app.modules.listings import service
from app.modules.listings.store import ListingStore


def tag() -> str:
    return uuid.uuid4().hex[:6]


def tender_raw(i: int, prefix: str, **extra):
    return {"id": f"{prefix}{i}", "number": f"2005{prefix}{i}", "title": f"مناقصه {i}", "typeName": "مناقصه عمومی",
            "operationProvinceName": "یزد", "operationCityName": "تفت", "organization": {"id": 1, "name": "شهرداری تفت"},
            "publicNotificationDate": "1405/08/01 10:00:00", "documentsDeadlineDate": "1405/08/20 12:00:00",
            "proposalDeadlineDate": "1405/08/28 12:00:00", "tenderDocumentsPrice": 1500000.0, "recCount": 3664,
            "favoriteCount": None, **extra}


def changes(db, external_id):
    return db.execute(text("""SELECT c.field, c.old_value, c.new_value FROM ext.listing_change c
                              JOIN ext.listing l ON l.id = c.listing_id WHERE l.external_id = :e ORDER BY c.at"""),
                      {"e": external_id}).all()


def test_rec_count_only_change_writes_nothing_and_rerun_is_idempotent(db):
    p = tag()
    store = ListingStore(new_session)
    store.start_run(SOURCE_TENDER, "full")
    assert store.add_tenders([tender_raw(1, p)]) == (1, 0, 0)
    seen = db.execute(text("SELECT last_seen FROM ext.listing WHERE external_id = :e"), {"e": f"{p}1"}).scalar()
    # the fixture again, with only volatile list metadata changed (recCount, favoriteCount, countdown)
    assert store.add_tenders([tender_raw(1, p, recCount=3700, remainingTime="12", favoriteCount=None)]) == (0, 0, 1)
    assert store.add_tenders([tender_raw(1, p)]) == (0, 0, 1)
    assert changes(db, f"{p}1") == []
    db.expire_all()
    later = db.execute(text("SELECT last_seen, raw->>'recCount' FROM ext.listing WHERE external_id = :e"),
                       {"e": f"{p}1"}).one()
    assert later[0] > seen and later[1] == "3664"            # raw refreshed silently, last_seen moved
    assert db.execute(text("SELECT count(*) FROM ext.listing WHERE external_id = :e"), {"e": f"{p}1"}).scalar() == 1
    store.finish_run("done")


def test_proposal_deadline_change_writes_one_row(db):
    p = tag()
    store = ListingStore(new_session)
    run = store.start_run(SOURCE_TENDER, "full")
    store.add_tenders([tender_raw(2, p)])
    assert store.add_tenders([tender_raw(2, p, proposalDeadlineDate="1405/08/30 12:00:00")]) == (0, 1, 0)
    rows = changes(db, f"{p}2")
    assert len(rows) == 1 and rows[0][0] == "proposal_deadline"
    assert rows[0][1] == "2026-11-19T08:30:00+00:00" and rows[0][2] == "2026-11-21T08:30:00+00:00"   # 12:00 Tehran
    store.finish_run("done")
    report = service.run_report(db, run)
    assert report["changed_count"] == 1 and report["new_count"] == 1 and report["status"] == "done"


def needs(prefix: str, n: int, start: int = 0, published="1405/08/05"):
    return [Need(need_no=f"11050{prefix_num(prefix)}{i:05d}", request_id=f"{prefix}{i}", description=f"نیاز {i}",
                 organization="بیمارستان نمونه", province="یزد، تفت", need_type="استعلام", category="کالا",
                 goods_group="تجهیزات", service_group="", published_date=published,
                 response_deadline="۳ روز و ۲ ساعت", detail_url=f"https://eproc.setadiran.ir/eproc/x?requestId={i}")
            for i in range(start, start + n)]


def prefix_num(prefix: str) -> str:
    return str(int(prefix, 16) % 100000).zfill(6)


def test_quick_fetch_never_hides_older_and_full_fetch_rule(db):
    """0.9.23: the list is what was seen since the start of the last FULL fetch; a quick fetch adds rows only."""
    p = tag()
    store = ListingStore(new_session)
    store.start_run(SOURCE_PURCHASE, "full")
    store.upsert_needs(needs(p, 5))
    store.finish_run("done")
    store.start_run(SOURCE_PURCHASE, "quick")
    store.upsert_needs(needs(p, 2, start=5))          # two new ones; the five older are not seen
    store.finish_run("done")
    listed = {r["external_no"] for r in service.query(db, {"source": SOURCE_PURCHASE, "q": "نمونه",
                                                            "page_size": 1000})["items"]}
    mine = {n.need_no for n in needs(p, 7)}
    assert mine <= listed                              # nothing hidden by the quick fetch
    new_now = service.query(db, {"source": SOURCE_PURCHASE, "new_only": True, "page_size": 1000})["items"]
    assert {r["external_no"] for r in new_now} & mine == {n.need_no for n in needs(p, 2, start=5)}
    # a later full fetch that no longer sees two of them: they leave the list (unless kept by screening)
    store.start_run(SOURCE_PURCHASE, "full")
    store.upsert_needs(needs(p, 5, start=2))
    store.finish_run("done")
    kept = db.execute(text("SELECT id FROM ext.listing WHERE external_id = :e"), {"e": f"{p}1"}).scalar()
    service.screen(db, kept, "star", {}, "script")
    db.commit()
    listed = {r["external_no"] for r in service.query(db, {"source": SOURCE_PURCHASE, "page_size": 1000})["items"]}
    assert needs(p, 1)[0].need_no not in listed                     # not seen since the last full fetch
    assert needs(p, 2)[1].need_no in listed                          # starred: always listed
    old = service.query(db, {"source": SOURCE_PURCHASE, "include_old": True, "page_size": 1000})["items"]
    assert needs(p, 1)[0].need_no in {r["external_no"] for r in old}


def test_purchase_estimate_is_silent_and_exact_deadline_is_tracked(db):
    p = tag()
    store = ListingStore(new_session)
    store.start_run(SOURCE_PURCHASE, "full")
    store.upsert_needs(needs(p, 1))
    store.upsert_needs([needs(p, 1)[0].__class__(**{**needs(p, 1)[0].as_dict(), "response_deadline": "۲ روز"})])
    assert changes(db, f"{p}0") == []                                # the countdown estimate moved silently
    detail = {"info": {"fields": [["مهلت ارسال پاسخ", "1405/08/12 ساعت 14:00"],
                                  ["حداقل تاریخ اعتبار قیمت", "1405/09/10 ساعت 11:00"],
                                  ["شهر محل تحویل", "تفت"]],
                       "buyer_note": "تسویه سه ماهه", "items": {"headers": ["نام کالا"], "rows": [["پمپ"]]}},
              "content": "...", "attachments": ["شرایط.pdf", "نقشه.pdf"]}
    store.save_need_detail(f"{p}0", detail)
    row = db.execute(text("SELECT response_deadline, deadline_exact, price_valid_until FROM ext.listing "
                          "WHERE external_id = :e"), {"e": f"{p}0"}).one()
    assert row[1] is True and row[0].astimezone(TEHRAN).isoformat().startswith("2026-11-03T14:00")
    assert row[2].astimezone(TEHRAN).date().isoformat() == "2026-12-01"
    assert changes(db, f"{p}0") == []                                # first exact value: not a change
    detail["info"]["fields"][0] = ["مهلت ارسال پاسخ", "1405/08/14 ساعت 14:00"]
    store.save_need_detail(f"{p}0", detail)
    assert [c[0] for c in changes(db, f"{p}0")] == ["response_deadline"]
    files = db.execute(text("SELECT display_name, state, reported_count FROM ext.listing_file f JOIN ext.listing l "
                            "ON l.id = f.listing_id WHERE l.external_id = :e ORDER BY 1"), {"e": f"{p}0"}).all()
    assert [tuple(f) for f in files] == [("شرایط.pdf", "pending", 2), ("نقشه.pdf", "pending", 2)]
    store.finish_run("done")


def test_need_files_from_the_download_manifest(db, tmp_path):
    from app.connectors.setad.eproc_storage import need_folder, record_attachment_total, record_download

    p = tag()
    store = ListingStore(new_session)
    store.start_run(SOURCE_PURCHASE, "full")
    need = needs(p, 1)[0]
    store.upsert_needs([need])
    store.save_need_detail(f"{p}0", {"info": {}, "attachments": ["شرایط.pdf", "نقشه.pdf"]})
    folder = need_folder(tmp_path, need.need_no)
    record_attachment_total(folder, 2)
    (folder / "شرایط.pdf").write_bytes(b"%PDF-1.4 a")
    record_download(folder, {}, "61", "شرایط.pdf", "شرایط.pdf")
    assert store.record_need_files(f"{p}0", folder) == 1
    files = db.execute(text("SELECT appendix_id, display_name, state, sha256 IS NOT NULL, reported_count FROM "
                            "ext.listing_file f JOIN ext.listing l ON l.id = f.listing_id WHERE l.external_id = :e "
                            "ORDER BY 2"), {"e": f"{p}0"}).all()
    assert [tuple(f) for f in files] == [("61", "شرایط.pdf", "downloaded", True, 2), ("name:2", "نقشه.pdf", "pending", False, 2)]
    store.finish_run("done")
    _ = (json, datetime, timedelta)
