"""v0.9.0 milestone 1: reference data (idempotent imports with reports, display rules, legal forms in the duplicate
check, ISO 6346) and the coding system (gap-free codes, pattern changes, party and product rules, the existing document
numbers unchanged, the backfill and migrations 0016+ up / down / up with no data lost)."""
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tests.test_parties import make_party, tag


# ---- reference data ----------------------------------------------------------------------------------------------------

def test_shipped_imports_are_idempotent_and_report(db):
    from app.modules.reference import importer

    first = importer.run(db, "incoterms")
    again = importer.run(db, "incoterms")
    assert again["inserted"] == 0 and again["updated"] == 0 and again["unchanged"] == first["inserted"] + first["unchanged"] + first["updated"]
    locs = importer.run(db, "locations")
    assert locs["inserted"] == 0 and locs["rejected"] == 0
    count = db.execute(text("SELECT count(*) FROM ref.dataset_import WHERE dataset = 'incoterms'")).scalar()
    assert count >= 2
    assert db.execute(text("SELECT count(*) FROM ref.incoterm WHERE active")).scalar() == 11


def test_import_from_a_local_unlocode_file_with_rejections(db, tmp_path):
    from app.modules.reference import importer

    f = tmp_path / "unlocode-part.csv"
    f.write_text(',"CN","SHA","Shanghai","Shanghai","SH","AI","1-345---","0101",,"3114N 12129E",\n'
                 ',"IR","BUZ","Bushehr","Bushehr","BS","AI","1-3-----","0101",,"2858N 05050E",\n'
                 ',"ZZ","???","Bad","Bad",,,"","",,,\n', encoding="utf-8")
    report = importer.run(db, "unlocode", f, "2024-2")
    assert report["rejected"] == 1 and report["rejections"][0]["reason"]
    row = db.execute(text("SELECT verified, is_port, is_road, latitude FROM ref.location WHERE unlocode = 'CNSHA'")).one()
    assert row.verified is True and row.is_port is True and row.is_road is True and float(row.latitude) == pytest.approx(31.2333, abs=1e-3)
    again = importer.run(db, "unlocode", f, "2024-2")
    assert again["inserted"] == 0 and again["updated"] == 0


def test_display_rules_sea_and_air(db):
    from app.modules.reference import service
    from app.modules.reference.models import Location

    sha = db.query(Location).filter_by(unlocode="CNSHA").one()
    buz = db.query(Location).filter_by(unlocode="IRBUZ").one()
    pvg = db.query(Location).filter(Location.iata == "PVG").first()
    assert service.route_label(db, sha, buz, "sea", "fa") == f"{sha.name_fa} SHA ← {buz.name_fa} BUZ"
    assert service.route_label(db, sha, buz, "sea", "en") == "Shanghai SHA → Bushehr BUZ"
    assert service.location_label(sha, "en", full=True) == "Shanghai CNSHA"
    if pvg is not None:
        assert service.route_label(db, pvg, buz, "air", "en").startswith("PVG → ")
    assert service.route_label(db, sha, buz, "air", "fa").endswith("BUZ")       # IATA code of Bushehr airport
    assert service.incoterm_citation("CFR", "Bandar Abbas") == "CFR Bandar Abbas (Incoterms® 2020)"


def test_iso6346_check_digit():
    from app.core.errors import AppError
    from app.modules.reference import service

    assert service.container_check_digit("CSQU305438") == 3
    assert service.container_number_valid("CSQU3054383")
    assert not service.container_number_valid("CSQU3054384")
    assert service.normalize_container(" csqu 305438-3 ") == "CSQU3054383"
    with pytest.raises(AppError):
        service.normalize_container("MSCU1234560")
    assert service.container_number_valid("MSKU9070323") or not service.container_number_valid("MSKU9070320")


def test_legal_form_normalisation_in_the_duplicate_check(client):
    base = f"Valve{tag()}"
    make_party(client, name_en=f"{base} Co., Ltd.", roles=["supplier"])
    r = client.post("/api/parties", json={"name_en": f"{base} Limited", "roles": ["supplier"]})
    assert r.status_code == 200 and r.json()["created"] is False, r.text
    assert {d["reason"] for d in r.json()["possible_duplicates"]} == {"similar_name_without_legal_form"}


def test_reference_api_and_shipment_with_route_and_container(client):
    from tests.test_execution_m3 import deal

    s = client.get("/api/reference/summary").json()
    assert {d["dataset"] for d in s["datasets"]} >= {"locations", "airports", "legal_forms", "containers", "incoterms"}
    sha = client.get("/api/reference/locations", params={"q": "CNSHA"}).json()[0]
    buz = client.get("/api/reference/locations", params={"q": "BUZ", "country": "IR"}).json()[0]
    assert sha["unlocode"] == "CNSHA" and buz["unlocode"] == "IRBUZ"
    assert any(c["code"] == "45G1" for c in client.get("/api/reference/containers").json())
    assert client.get("/api/reference/incoterms").json()[0]["citation_example"].endswith("(Incoterms® 2020)")
    case, party, so, pos = deal(client)
    r = client.post("/api/shipments", json={"purchase_order_id": pos["USD"]["id"], "mode": "sea", "origin_location_id": sha["id"],
                                            "destination_location_id": buz["id"],
                                            "container_units": [{"number": "CSQU3054383", "container_type": "45G1"}]})
    assert r.status_code == 201, r.text
    sh = r.json()
    assert sh["code"].startswith("SH-")
    assert sh["route"]["en"].startswith("Shanghai SHA → ") and sh["container_units"][0]["container_type"] == "45G1"
    bad = client.post("/api/shipments", json={"purchase_order_id": pos["USD"]["id"], "mode": "sea",
                                              "container_units": [{"number": "CSQU3054384"}]})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "container_number_invalid"


# ---- codes ---------------------------------------------------------------------------------------------------------------

def test_codes_are_gap_free_under_concurrency():
    from app.core.db import new_session
    from app.modules.codes import service

    kind, ctx = "inquiry", {"yyyy": 2999}
    out, errors = [], []

    def worker():
        try:
            with new_session() as db:
                for _ in range(5):
                    out.append(service.next(db, kind, ctx))
                    db.commit()
        except Exception as exc:   # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    numbers = sorted(int(c.rsplit("-", 1)[1]) for c in out)
    assert numbers == list(range(numbers[0], numbers[0] + 30)) and len(set(out)) == 30
    with new_session() as db:     # a rolled-back creation gives its number back
        first = service.next(db, kind, ctx)
        db.rollback()
        assert service.next(db, kind, ctx) == first
        db.rollback()


def test_pattern_change_applies_to_new_codes_only(client):
    a = client.post("/api/cases", json={"title": f"A {tag()}"})
    assert a.status_code == 201, a.text
    old = a.json()["code"]
    assert old.startswith("CS-")
    assert client.patch("/api/settings", json={"codes.pattern.case": "DEAL-{yyyy}-{000}"}).status_code == 200
    try:
        ex = client.get("/api/codes/patterns").json()
        case_row = next(p for p in ex if p["kind"] == "case")
        assert case_row["example"].startswith("DEAL-") and case_row["default"] == "CS-{yyyy}-{0000}"
        b = client.post("/api/cases", json={"title": f"B {tag()}"}).json()
        assert b["code"].startswith("DEAL-") and len(b["code"].rsplit("-", 1)[1]) == 3
        assert client.get(f"/api/cases/{a.json()['id']}").json()["code"] == old
        bad = client.post("/api/codes/preview", json={"kind": "case", "pattern": "X-{foo}-{00}"})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "code_pattern_invalid"
        assert client.patch("/api/settings", json={"codes.pattern.case": "NOSEQ"}).status_code == 422
    finally:
        client.patch("/api/settings", json={"codes.pattern.case": "CS-{yyyy}-{0000}"})
    hit = client.get(f"/api/codes/resolve/{old}").json()
    assert hit["kind"] == "case" and hit["id"] == a.json()["id"]
    found = client.get("/api/search", params={"q": old}).json()
    first = found["groups"][0]
    assert first["items"][0]["title"] == old or first["items"][0].get("code") == old


def test_party_code_rule(client):
    sup = make_party(client, name_en=f"S {tag()}", roles=["supplier"], country_iso2="CN")
    cus = make_party(client, name_en=f"C {tag()}", roles=["buyer"], country_iso2="IR")
    both = make_party(client, name_en=f"B {tag()}", roles=["buyer", "supplier"], country_iso2="AE")
    none = make_party(client, name_en=f"N {tag()}")
    assert sup["code"].startswith("SUP-CN-") and cus["code"].startswith("CUS-IR-") and both["code"].startswith("BP-AE-")
    assert none["code"].startswith("BP-XX-")
    r = client.post(f"/api/parties/{sup['id']}/roles", json={"role": "buyer"})
    assert r.status_code in (200, 201), r.text
    assert client.get(f"/api/parties/{sup['id']}").json()["code"] == sup["code"]


def test_product_code_with_and_without_hs(client):
    with_hs = client.post("/api/products", json={"name_en": f"Pump {tag()}", "hs_code": "84137010", "confirm_duplicate": True})
    without = client.post("/api/products", json={"name_en": f"Thing {tag()}", "confirm_duplicate": True})
    assert with_hs.status_code == 201, with_hs.text
    assert with_hs.json()["product"]["code"].startswith("PRD-8413-")
    assert without.json()["product"]["code"].startswith("PRD-0000-")


def test_existing_document_numbers_continue_unchanged(client, db):
    from tests.test_execution_m2 import create_pos
    from tests.test_execution_m1 import confirmed_order

    case, items, party, quote, so = confirmed_order(client)
    assert quote["number"].startswith("PI-")
    assert so["number"].startswith("SO-")
    pos = create_pos(client, so)["created"]
    assert pos and all(p["number"].startswith("PO-") for p in pos)
    scope = "SO-" + so["number"].split("-")[1] + "-#"
    last = db.execute(text("SELECT last_number FROM core.code_sequence WHERE kind = 'sales_order' AND scope = :s"),
                      {"s": scope}).scalar()
    assert last == int(so["number"].rsplit("-", 1)[1])


# ---- migrations 0016+ on Phase 9 data -------------------------------------------------------------------------------------

def test_migrations_0016_up_down_up_backfill_and_no_data_lost():
    from alembic import command

    from app.cli import alembic_config
    from app.core.config import get_config
    from app.core.db import Session as _S  # noqa: F401
    from tests.conftest import create_empty_database

    name = "boms_test_v090_migrations"
    create_empty_database(name)
    url = get_config().db_url(name)
    cfg = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "0016")
        with engine.begin() as conn:
            def q(sql, **p):
                result = conn.execute(text(sql), p)
                return result.scalar() if result.returns_rows else None

            def party(name_, roles, country, at):
                pid = q("INSERT INTO core.party (name_en, country_iso2, created_at) VALUES (:n, :c, :t) RETURNING id",
                        n=name_, c=country, t=at)
                for role in roles:
                    q("INSERT INTO core.party_role (party_id, role, stage, created_at) VALUES (:p, :r, "
                      "(SELECT code FROM core.funnel_stage WHERE role = :r ORDER BY sort_order LIMIT 1), :t)", p=pid, r=role, t=at)
                return pid
            q("INSERT INTO sys.country (iso2, iso3, name_fa, name_en) VALUES ('CN', 'CHN', 'چین', 'China'), "
              "('IR', 'IRN', 'ایران', 'Iran'), ('AE', 'ARE', 'امارات', 'UAE')")
            q("INSERT INTO sys.app_user (username, password_hash, calendar) VALUES ('owner', 'x', 'gregorian')")
            s1 = party("Sup One", ["supplier"], "CN", "2025-01-02")
            party("Cus One", ["buyer"], "IR", "2025-01-03")
            party("Both", ["buyer", "supplier"], "AE", "2025-01-04")
            party("Sup Two", ["supplier"], "CN", "2025-01-05")
            q("INSERT INTO core.product (name_en, hs_code, created_at) VALUES ('Pump', '84137010', '2025-01-02')")
            q("INSERT INTO core.product (name_en, created_at) VALUES ('Misc', '2025-01-03')")
            for i, at in enumerate(("2025-02-01", "2025-03-01", "2026-02-01")):
                q("INSERT INTO ops.\"case\" (title, party_id, created_at) VALUES (:t, :p, :a)", t=f"Case {i}", p=s1, a=at)
            q("INSERT INTO ops.quote_sequence (year, last_number) VALUES (2025, 7)")
            q("INSERT INTO ops.invoice_sequence (key, last_number) VALUES ('INV-2025', 3)")
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            codes = dict(conn.execute(text("SELECT name_en, code FROM core.party")).all())
            assert codes == {"Sup One": "SUP-CN-0001", "Cus One": "CUS-IR-0001", "Both": "BP-AE-0001", "Sup Two": "SUP-CN-0002"}
            assert sorted(conn.execute(text("SELECT code FROM core.product")).scalars()) == ["PRD-0000-0001", "PRD-8413-0001"]
            assert sorted(conn.execute(text('SELECT code FROM ops."case"')).scalars()) == ["CS-2025-0001", "CS-2025-0002", "CS-2026-0001"]
            counts = conn.execute(text("SELECT data FROM core.event WHERE entity_type = 'codes' AND action = 'backfill'")).scalar()
            assert counts["party"] == 4 and counts["product"] == 2 and counts["case"] == 3
            seq = dict(conn.execute(text("SELECT kind || ':' || scope, last_number FROM core.code_sequence")).all())
            assert seq["quote:PI-2025-#"] == 7 and seq["sales_invoice:INV-2025-#"] == 3 and seq["case:CS-2025-#"] == 2
            # a reference on a business row and a shipment container survive the round trip
            conn.execute(text("INSERT INTO ref.legal_form (code, country_iso2, local_name, source) VALUES ('IR-PJS', 'IR', 'سهامی خاص', 'test')"))
            conn.execute(text("UPDATE core.party SET legal_form_id = (SELECT id FROM ref.legal_form WHERE code = 'IR-PJS') WHERE name_en = 'Both'"))
            conn.execute(text("UPDATE ops.\"case\" SET code = 'CS-2025-0099' WHERE title = 'Case 2'"))   # an edited code stays
        before = _counts(engine)
        command.downgrade(cfg, "0015")
        with engine.begin() as conn:
            assert conn.execute(text("SELECT last_number FROM ops.quote_sequence WHERE year = 2025")).scalar() == 7
            assert conn.execute(text("SELECT count(*) FROM sys.downgrade_archive WHERE migration IN ('0017', '0018')")).scalar() > 0
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            assert dict(conn.execute(text("SELECT name_en, code FROM core.party")).all()) == codes
            assert conn.execute(text("SELECT code FROM ops.\"case\" WHERE title = 'Case 2'")).scalar() == "CS-2025-0099"
            assert conn.execute(text("SELECT last_number FROM core.code_sequence WHERE kind = 'case' AND scope = 'CS-2025-#'")).scalar() == 2
        from sqlalchemy.orm import Session

        from app.modules.reference import importer
        with Session(engine) as s:
            importer.run(s, "legal_forms")
            s.commit()
        with engine.begin() as conn:
            assert conn.execute(text("SELECT l.code FROM core.party p JOIN ref.legal_form l ON l.id = p.legal_form_id "
                                     "WHERE p.name_en = 'Both'")).scalar() == "IR-PJS"
        after = _counts(engine)
        assert {k: v for k, v in after.items() if v < before.get(k, 0)} == {}
    finally:
        engine.dispose()


def _counts(engine) -> dict:
    with engine.begin() as conn:
        tables = conn.execute(text("SELECT table_schema || '.' || quote_ident(table_name) FROM information_schema.tables "
                                   "WHERE table_schema IN ('core', 'ops', 'sys') AND table_type = 'BASE TABLE' "
                                   "AND table_name NOT IN ('event', 'audit_log', 'downgrade_archive')")).scalars().all()
        return {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}


def test_data_sources_documented():
    data = Path(__file__).resolve().parents[1] / "app" / "modules" / "reference" / "data"
    assert (data / "SOURCE.md").exists() and (data / "airports.csv.gz").exists()
