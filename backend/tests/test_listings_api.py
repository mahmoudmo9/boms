"""v0.5.0 listings API on a generated dataset of 50,000 rows: filters and counts over the whole result, paging and
sorting, normalized search («كالا» finds «کالا»), timing (target under 300 ms on the owner's PC; measured values
are printed and asserted with a margin for this container), screening actions and bulk selection."""
import time
import uuid

import pytest
from sqlalchemy import text

from app.connectors.setad.rows import SOURCE_PURCHASE
from app.core.db import new_session
from app.modules.listings import service

N = 50_000


@pytest.fixture(scope="module")
def dataset():
    """50,000 purchase calls under one full run (so the 0.9.23 list rule includes them all)."""
    p = uuid.uuid4().hex[:6]
    with new_session() as db:
        run = db.execute(text("INSERT INTO ext.harvest_run (source, kind, status, started_at) "
                              "VALUES ('setad_purchase', 'full', 'done', now() - interval '1 minute') RETURNING id")).scalar()
        db.execute(text(f"""
            INSERT INTO ext.listing (source, external_id, external_no, title, organization, province, city, category,
                                     goods_group, published_at, response_deadline, deadline_exact, first_run_id,
                                     last_full_run_id, first_seen, last_seen, raw)
            SELECT 'setad_purchase', :p || g, (1105000000000000 + g)::text,
                   CASE WHEN g % 10 = 0 THEN 'خرید كالای مصرفی ' || g ELSE 'تأمین تجهیزات ' || g END,
                   'دستگاه ' || (g % 400), (ARRAY['یزد','فارس','تهران','البرز'])[1 + g % 4], 'شهر',
                   CASE WHEN g % 2 = 0 THEN 'کالا' ELSE 'خدمت' END, 'گروه ' || (g % 30),
                   now() - (g % 20) * interval '1 day', now() + ((g % 40) - 10) * interval '1 day', g % 3 = 0,
                   :run, :run, now(), now(), '{{}}'::jsonb
            FROM generate_series(1, {N}) AS g
        """), {"p": p, "run": run})
        # some screening decisions and downloaded files
        db.execute(text("""INSERT INTO ext.listing_screening (listing_id, status, starred_at)
                           SELECT id, 'starred', now() FROM ext.listing WHERE external_id LIKE :p || '%'
                           AND (external_no::bigint % 50) = 0"""), {"p": p})
        db.execute(text("""INSERT INTO ext.listing_screening (listing_id, status, dismiss_reason)
                           SELECT id, 'dismissed', 'خارج از حوزه کاری' FROM ext.listing WHERE external_id LIKE :p || '%'
                           AND (external_no::bigint % 50) = 7"""), {"p": p})
        db.execute(text("""INSERT INTO ext.listing_file (listing_id, group_key, appendix_id, display_name, state,
                                                        local_path, reported_count)
                           SELECT id, 'appendix', '1', 'a.pdf', 'downloaded', '/nonexistent/a.pdf', 2
                           FROM ext.listing WHERE external_id LIKE :p || '%' AND (external_no::bigint % 100) = 3"""),
                   {"p": p})
        db.execute(text("ANALYZE ext.listing; ANALYZE ext.listing_screening; ANALYZE ext.listing_file"))
        db.commit()
    yield p
    with new_session() as db:
        db.execute(text("DELETE FROM ext.listing WHERE external_id LIKE :p || '%'"), {"p": p})
        db.execute(text("DELETE FROM ext.harvest_run WHERE id = :r"), {"r": run})
        db.commit()


def timed(db, params):
    t0 = time.perf_counter()
    result = service.query(db, params)
    return result, (time.perf_counter() - t0) * 1000


def test_counts_paging_sorting_and_timing(dataset, db, capsys):
    base = {"source": SOURCE_PURCHASE, "q": None}
    timings = {}
    # the first read after inserting 50,000 rows in one transaction sets their hint bits (cold); reported apart
    _, cold = timed(db, {**base, "page_size": 200})
    all_rows, timings["all, sort by deadline, 200 rows"] = timed(db, {**base, "page_size": 200})
    assert all_rows["total"] >= N - N // 50 and len(all_rows["items"]) == 200
    counts = all_rows["counts"]
    assert counts["starred"] >= N // 50 and counts["dismissed"] >= N // 50
    assert counts["open"] + counts["passed"] == counts["all"]
    # every chip count equals the total of the same filter applied
    for chip, params in (("starred", {"status": "starred"}), ("open", {"deadline": "open"}),
                         ("passed", {"deadline": "passed"}), ("soon", {"deadline": "within", "within_days": 3}),
                         ("downloaded", {"downloaded": True})):
        filtered, timings[f"filter {chip}"] = timed(db, {**base, **params, "page_size": 100})
        assert filtered["total"] == counts[chip], chip
    # province filter + sort by organisation, descending, page 3 of 1000
    page3, timings["province + sort organization desc, page 3 of 1000"] = timed(
        db, {**base, "provinces": ["یزد"], "sort": "organization", "dir": "desc", "page": 3, "page_size": 1000})
    orgs = [r["organization"] for r in page3["items"]]
    assert orgs == sorted(orgs, reverse=True) and {r["province"] for r in page3["items"]} == {"یزد"}
    # normalized search: the data says «كالا» (Arabic kaf); searching «کالا» finds it
    found, timings["search «کالا»"] = timed(db, {**base, "q": "کالا", "page_size": 100})
    assert found["total"] >= N // 10 - N // 500 and all("كالا" in r["title"] for r in found["items"])
    facets_t0 = time.perf_counter()
    orgs = service.facets(db, base, "organization", q="دستگاه 12")
    timings["organization facet with search"] = (time.perf_counter() - facets_t0) * 1000
    assert orgs and all("12" in o["value"] for o in orgs)
    with capsys.disabled():
        print(f"\nfirst (cold) query right after the bulk insert: {cold:.0f} ms")
        print("listing query timings on 50,000 rows (ms):")
        for k, v in timings.items():
            print(f"  {k}: {v:.0f}")
    # target on the owner's PC: < 300 ms; this shared container gets a margin
    assert max(timings.values()) < 1500, timings


def test_screening_and_bulk_over_all_results(dataset, db, client):
    first = db.execute(text("SELECT id FROM ext.listing WHERE external_id = :e"), {"e": f"{dataset}11"}).scalar()
    r = client.post(f"/api/listings/{first}/screen", json={"action": "dismiss"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    r = client.post(f"/api/listings/{first}/screen", json={"action": "dismiss", "reason": "مهلت کافی نیست"})
    assert r.status_code == 200 and r.json()["screening"]["status"] == "dismissed"
    r = client.post(f"/api/listings/{first}/screen", json={"action": "restore"})
    assert r.json()["screening"]["status"] == "new"
    # "select all results": star every Yazd row with «كالا» in the title
    filters = {"source": SOURCE_PURCHASE, "q": "کالا", "provinces": ["یزد"]}
    total = client.post("/api/listings/query", json={**filters, "page_size": 100}).json()["total"]
    r = client.post("/api/listings/bulk", json={"filters": filters, "action": "star"})
    assert r.status_code == 200 and r.json()["done"] + r.json()["skipped"] == total
    starred = client.post("/api/listings/query", json={**filters, "status": "starred", "page_size": 100}).json()
    assert starred["total"] == total
    csv = client.post("/api/listings/bulk", json={"ids": [str(first)], "action": "export_csv"})
    assert csv.status_code == 200 and csv.content.startswith("﻿".encode()) and "شماره".encode() in csv.content
    r = client.post("/api/listings/query", json={"source": SOURCE_PURCHASE, "page_size": 7})
    assert r.status_code == 422
    r = client.post("/api/listings/query", json={"source": SOURCE_PURCHASE, "bogus": 1})
    assert r.status_code == 422
