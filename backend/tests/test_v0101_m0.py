"""v0.10.1 milestone 0: Ollama (cloud models behind a local address, per-request options, the model list and where the
model ran), against a fake Ollama server. Nothing contacts a network host."""
import json
import uuid

import pytest
from sqlalchemy import text

from tests.test_parties import make_party, tag
from tests.test_v090_m3 import clean_ai, fake, route, run, setup_provider  # noqa: F401


# ---- 0.1.1 local or cloud ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,cloud", [
    ("qwen3.5:4b", False), ("qwen2.5:latest", False), ("llama3.2", False), ("hf.co/org/model:Q4_K_M", False),
    ("gpt-oss:120b-cloud", True), ("qwen3-coder:480b-cloud", True), ("kimi-k2:cloud", True), ("deepseek-v3.1:671b-cloud", True),
    ("deepseek-cloud", True), ("glm-4.6:cloud", True), ("cloudy-model:7b", False), ("", True), (None, True)])
def test_cloud_model_names(name, cloud):
    from app.modules.ai import ollama

    assert ollama.is_cloud_name(name) is cloud


def test_model_facts_from_tags_mark_remote_models_as_cloud():
    from app.modules.ai import ollama

    info = ollama.facts_from_tags({"models": [
        {"name": "qwen3.5:4b", "size": 3_400_000_000, "details": {"family": "qwen35", "parameter_size": "4B"}},
        {"name": "gpt-oss:20b", "remote_model": "gpt-oss:20b", "remote_host": "https://ollama.com:443"},
        {"name": "mistral:7b-cloud"}]})
    assert info["qwen3.5:4b"]["cloud"] is False and info["qwen3.5:4b"]["family"] == "qwen35"
    assert info["gpt-oss:20b"]["cloud"] is True                    # a plain name, but the list says it runs remotely
    assert info["mistral:7b-cloud"]["cloud"] is True
    assert ollama.model_is_local("qwen3.5:4b", info) and not ollama.model_is_local("gpt-oss:20b", info)
    assert not ollama.model_is_local("phi4:14b", info)              # not in the list: cannot tell → cloud
    assert ollama.model_is_local("qwen3.5", {"qwen3.5:latest": {"cloud": False}})


def _private_case(client):
    party = make_party(client, name_en=f"Shanghai Valve {tag()}", roles=["supplier"])
    case = client.post("/api/cases", json={"title": f"AI {tag()}", "party_id": party["id"]}).json()
    return party, case


def test_a_cloud_model_through_localhost_is_redacted_and_never_gets_local_only_work(client, db, fake, clean_ai):
    from app.core.errors import AppError

    fake.ollama_tags.append({"name": "gpt-oss:120b-cloud", "remote_host": "https://ollama.com:443"})
    p = setup_provider(client, "ollama", "gpt-oss:120b-cloud", price=None)          # http://127.0.0.1:11434
    assert p["local"] is False and p["model_local"] == {"gpt-oss:120b-cloud": False}
    route(client, "classification", p, "gpt-oss:120b-cloud", privacy="cloud_redacted")
    party, case = _private_case(client)
    note = f"From {party['name_en']}, ali@valve.cn: 2 pumps"
    out = run(db, text_=note, case_id=uuid.UUID(case["id"]))
    sent = json.dumps(fake.last, ensure_ascii=False)
    assert party["name_en"] not in sent and "ali@valve.cn" not in sent and out.call.redactions == {"PARTY": 1, "EMAIL": 1}
    client.put(f"/api/ai/cases/{case['id']}/privacy", json={"local_only": True})
    before = len(fake.requests)
    with pytest.raises(AppError) as exc:
        run(db, text_=note, case_id=uuid.UUID(case["id"]))
    assert exc.value.code == "ai_local_only" and len(fake.requests) == before


def test_a_plain_name_the_list_reports_remote_is_cloud(client, db, fake, clean_ai):
    fake.ollama_tags.append({"name": "gpt-oss:20b", "remote_model": "gpt-oss:20b", "remote_host": "https://ollama.com:443"})
    p = setup_provider(client, "ollama", "gpt-oss:20b", price=None)
    assert p["model_local"] == {"gpt-oss:20b": False}


def test_unknown_model_or_unreachable_ollama_is_cloud(client, db, fake, clean_ai):
    p = setup_provider(client, "ollama", "phi4:14b", price=None)                    # not installed: not in the list
    assert p["model_local"] == {"phi4:14b": False}
    fake.ollama_tags = []
    import httpx

    def down(request):
        raise httpx.ConnectError("refused", request=request)
    from app.modules.ai import adapters
    adapters.set_transport(httpx.MockTransport(down))
    db.execute(text("UPDATE ai.provider SET model_info = '{}'::jsonb WHERE id = :i"), {"i": p["id"]})  # never answered
    db.commit()
    r = client.patch(f"/api/ai/providers/{p['id']}", json={"models": ["qwen2.5"]})
    assert r.status_code == 200 and r.json()["model_local"] == {"qwen2.5": False}     # cannot tell → cloud


def test_an_installed_local_model_stays_local_and_unredacted(client, db, fake, clean_ai):
    fake.ollama_tags.append({"name": "qwen3.5:4b", "size": 3_400_000_000, "details": {"family": "qwen35"}})
    p = setup_provider(client, "ollama", "qwen3.5:4b", price=None)
    assert p["local"] is True and p["model_local"] == {"qwen3.5:4b": True}
    route(client, "classification", p, "qwen3.5:4b", privacy="cloud_redacted")
    party, case = _private_case(client)
    client.put(f"/api/ai/cases/{case['id']}/privacy", json={"local_only": True})
    out = run(db, text_=f"From {party['name_en']}: 2 pumps", case_id=uuid.UUID(case["id"]))
    assert party["name_en"] in json.dumps(fake.last, ensure_ascii=False) and out.call.status == "ok"


# ---- 0.1.2 options per request ----------------------------------------------------------------------------------------

def test_num_ctx_sizing_and_the_cap():
    from app.modules.ai import ollama
    from app.modules.ai.adapters import ProviderError

    assert ollama.num_ctx(1000, 0, 16, 8192) == (2048, 16)                 # small: the 2,048 floor, the whole answer
    size, answer = ollama.num_ctx(10_000, 0, 2048, 8192)                    # ~4,000 prompt tokens + 2,048 + margin
    assert size == 7168 and answer == 2048
    size, answer = ollama.num_ctx(10_000, 1, 8192, 8192)                    # a big answer gets what the cap leaves
    assert size == 8192 and 1024 <= answer < 8192
    with pytest.raises(ProviderError) as exc:
        ollama.num_ctx(30_000, 0, 1024, 8192)                               # ~12,000 tokens: refused, never cut
    assert exc.value.kind == "context_too_long" and "حداکثر طول متن" in str(exc.value)
    assert ollama.num_ctx(30_000, 0, 1024, 16384)[0] == 13312               # a higher cap lets it through


def test_each_request_sends_num_ctx_think_and_keep_alive(client, db, fake, clean_ai):
    fake.ollama_tags.append({"name": "qwen3.5:4b"})
    p = setup_provider(client, "ollama", "qwen3.5:4b", price=None)
    route(client, "classification", p, "qwen3.5:4b", privacy="cloud")
    run(db, text_="2 pumps")
    body = fake.last
    assert body["options"]["num_ctx"] >= 2048 and body["think"] is False and body["keep_alive"] == "10m"
    # thinking per route: the owner turns it on for classification; keep_alive follows the setting
    assert client.patch("/api/ai/routes/classification", json={"think": True}).status_code == 200
    client.patch("/api/settings", json={"ai.ollama.keep_alive_minutes": 30})
    run(db, text_="2 pumps")
    assert fake.last["think"] is True and fake.last["keep_alive"] == "30m"
    routes = {r["task"]: r for r in client.get("/api/ai/routes").json()}
    assert routes["classification"]["think"] is True and routes["extraction"]["think_default"] is True
    client.patch("/api/ai/routes/classification", json={"think": None})
    client.patch("/api/settings", json={"ai.ollama.keep_alive_minutes": 10})


def test_a_prompt_over_the_cap_fails_with_a_clear_message(client, db, fake, clean_ai):
    from app.core.errors import AppError

    fake.ollama_tags.append({"name": "qwen3.5:4b"})
    p = setup_provider(client, "ollama", "qwen3.5:4b", price=None)
    route(client, "classification", p, "qwen3.5:4b", privacy="cloud")
    client.patch("/api/settings", json={"ai.ollama.max_context": 2048})
    try:
        before = len(fake.requests)
        with pytest.raises(AppError) as exc:
            run(db, text_="pump " * 2000)
        assert exc.value.details["reason"] == "context_too_long" and len(fake.requests) == before
        err = db.execute(text("SELECT error FROM ai.call ORDER BY created_at DESC LIMIT 1")).scalar()
        assert "حداکثر طول متن" in err
    finally:
        client.patch("/api/settings", json={"ai.ollama.max_context": 8192})


# ---- 0.1.3 the settings card: installed models and where the model ran ------------------------------------------------

def test_model_list_and_vram_placement(client, db, fake, clean_ai):
    fake.ollama_tags = [{"name": "qwen3.5:4b", "size": 3_400_000_000, "details": {"family": "qwen35", "parameter_size": "4B"}},
                        {"name": "qwen3-coder:480b-cloud", "remote_host": "https://ollama.com:443"}]
    p = setup_provider(client, "ollama", "qwen3.5:4b", price=None)
    models = client.post(f"/api/ai/providers/{p['id']}/models/refresh").json()
    assert [(m["name"], m["local"], m["family"]) for m in models] == [
        ("qwen3-coder:480b-cloud", False, None), ("qwen3.5:4b", True, "qwen35")]
    assert models[1]["size"] == 3_400_000_000
    fake.ollama_ps = [{"name": "qwen3.5:4b", "size": 5_000_000_000, "size_vram": 5_000_000_000, "context_length": 8192}]
    out = client.post(f"/api/ai/providers/{p['id']}/test").json()
    assert out["status"] == "ok" and out["placement"]["gpu_share"] == 1.0 and out["placement"]["fits"] is True
    fake.ollama_ps = [{"name": "qwen3.5:4b", "size": 10_000_000_000, "size_vram": 6_500_000_000}]
    out = client.post(f"/api/ai/providers/{p['id']}/test").json()
    assert out["placement"]["gpu_share"] == 0.65 and out["placement"]["fits"] is False
    other = setup_provider(client, "openai_compatible", "llama", price=None, base_url="http://192.168.1.5:8000")
    assert client.post(f"/api/ai/providers/{other['id']}/models/refresh").status_code == 422


# ---- 0.2 reference import --------------------------------------------------------------------------------------------

FIX = __import__("pathlib").Path(__file__).parent / "fixtures" / "reference"
ELF_FILE = FIX / "2026-02-19-elf-code-list-v1.6.csv"


def _loc_row(code: str, name: str, fn="1-------", change="", iata=""):
    return f'"{change}","{code[:2]}","{code[2:]}","{name}","{name}","","AI","{fn}","2401","{iata}","",""\r\n'


def unlocode_zip(rows_by_part: dict[int, list[str]], encoding="utf-8", subdivisions=True) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, rows in rows_by_part.items():
            heading = f'"","{rows[0].split(",")[1].strip(chr(34))}","",".COUNTRY","","","","","","","",""\r\n' if rows else ""
            z.writestr(f"2025-1 UNLOCODE CodeListPart{n}.csv", (heading + "".join(rows)).encode(encoding))
        if subdivisions:
            z.writestr("2025-1 SubdivisionCodes.csv", '"ZZ","01","Somewhere","Province"\r\n'.encode(encoding))
    return buf.getvalue()


def test_format_detection_encodings_and_version():
    from app.modules.reference import bulk

    assert bulk.release_from_name("loc251csv.zip") == "2025-1" and bulk.release_from_name("loc242csv.zip") == "2024-2"
    assert bulk.release_from_name("2026-02-19-elf-code-list-v1.6.csv") == "1.6" and bulk.release_from_name("x.csv") is None
    assert bulk.decode("Zürich".encode("utf-8")) == ("Zürich", "utf-8")
    assert bulk.decode("Zürich".encode("cp1252")) == ("Zürich", "windows-1252")
    assert bulk.decode(b"\xef\xbb\xbfabc") == ("abc", "utf-8 (BOM)")
    assert bulk.detect(bulk.file_parts(ELF_FILE.name, ELF_FILE.read_bytes())) == "elf"
    z = unlocode_zip({1: [_loc_row("ZZAAA", "Alpha")], 2: [_loc_row("ZZBBB", "Beta")], 3: [_loc_row("ZZCCC", "Gamma")]})
    assert bulk.detect(bulk.file_parts("loc251csv.zip", z)) == "unlocode"
    assert bulk.detect({"notes.csv": b"a,b,c\n1,2,3\n"}) is None


def test_elf_v16_exact_format_imports_with_zero_rejections(db):
    from app.modules.reference import bulk
    from app.modules.reference.models import LegalForm

    try:
        out = bulk.apply(db, "elf", bulk.file_parts(ELF_FILE.name, ELF_FILE.read_bytes()), "1.6")
        assert out["rejected"] == 0 and out["inserted"] == 7 and out["encodings"] == {ELF_FILE.name: "utf-8 (BOM)"}
        assert out["notes"]["special"] == ["8888", "9999"] and out["notes"]["inactive"] == 1
        bv = db.query(LegalForm).filter_by(code="ELF-6QQB").one()          # three language rows → one legal form
        assert bv.country_iso2 == "BE" and [n["lang"] for n in bv.names] == ["nl", "fr", "de"]
        assert bv.abbreviations == ["BV", "SRL", "GmbH"] and bv.active
        assert db.query(LegalForm).filter_by(code="ELF-XLWA").one().name_fa == "شرکت سهامی خاص"
        assert db.query(LegalForm).filter_by(code="ELF-ZZ00").one().active is False             # INAC
        assert db.query(LegalForm).filter_by(code="ELF-8888").one().country_iso2 == "XX"         # special, not rejected
        assert db.query(LegalForm).filter_by(code="ELF-H0PO").one().abbreviations == ["AG", "SA"]
        again = bulk.apply(db, "elf", bulk.file_parts(ELF_FILE.name, ELF_FILE.read_bytes()), "1.6")
        assert again["inserted"] == 0 and again["updated"] == 0 and again["unchanged"] == 7
    finally:
        db.rollback()


def test_an_elf_file_with_the_wrong_header_is_mostly_rejected_in_the_preview(db):
    from app.modules.reference import bulk

    data = ELF_FILE.read_bytes().replace(b'"ELF Code"', b'"Elf Kode"', 1)
    try:
        out = bulk.preview(db, "elf", {"elf.csv": data}, None)
        assert "mostly_rejected" in out["warnings"] and out["records"] == 0
        assert out["reasons"] == [{"reason": "column ELF Code not found", "count": 9}]
        assert len(out["examples"]) == 9 and out["insert"] == 0
    finally:
        db.rollback()


def test_complete_release_deactivates_missing_rows_partial_is_upsert_only(db):
    from app.modules.reference import bulk
    from app.modules.reference.models import Location

    try:
        full = unlocode_zip({1: [_loc_row("ZZAAA", "Alpha"), _loc_row("ZZBBB", "Béta")], 2: [_loc_row("ZZCCC", "Gamma")],
                             3: [_loc_row("ZZDDD", "Delta", change="X")]}, encoding="cp1252")
        out = bulk.apply(db, "unlocode", bulk.file_parts("loc251csv.zip", full), "2025-1")
        assert out["complete"] and out["inserted"] == 4 and out["rejected"] == 0
        encodings = out["encodings"]          # ASCII-only parts are valid UTF-8; the part with «Béta» is Windows-1252
        assert encodings["2025-1 UNLOCODE CodeListPart1.csv"] == "windows-1252" and encodings["2025-1 UNLOCODE CodeListPart2.csv"] == "utf-8"
        assert out["notes"]["subdivisions"] == 1
        assert db.query(Location).filter_by(unlocode="ZZBBB").one().name == "Béta"
        assert db.query(Location).filter_by(unlocode="ZZDDD").one().active is False            # «X»: to be removed
        # a later complete release without ZZCCC deactivates it
        later = unlocode_zip({1: [_loc_row("ZZAAA", "Alpha"), _loc_row("ZZBBB", "Béta")], 2: [_loc_row("ZZEEE", "Echo")],
                              3: [_loc_row("ZZDDD", "Delta", change="X")]})
        out = bulk.apply(db, "unlocode", bulk.file_parts("loc252csv.zip", later), "2025-2")
        assert out["deactivated"] >= 1 and db.query(Location).filter_by(unlocode="ZZCCC").one().active is False
        # a single part never deactivates, and says so
        part = unlocode_zip({2: [_loc_row("ZZFFF", "Foxtrot")]}, subdivisions=False)
        out = bulk.apply(db, "unlocode", bulk.file_parts("part2.zip", part), "2025-2")
        assert not out["complete"] and "partial_release" in out["warnings"] and out["deactivated"] == 0
        assert db.query(Location).filter_by(unlocode="ZZAAA").one().active is True
    finally:
        db.rollback()


def _start(client, name: str, data: bytes, dataset=None):
    files = {"file": (name, data, "application/octet-stream")}
    return client.post("/api/reference/imports", files=files, data={"dataset": dataset} if dataset else {})


def _job(db, run_id: str, mode: str):
    from app.modules.reference import imports

    return imports.run_job(db, {"run_id": run_id, "mode": mode})


def test_preview_changes_nothing_then_confirm_imports(client, db):
    part = unlocode_zip({1: [_loc_row("ZZQAA", "Quebec Alpha"), _loc_row("ZZQBB", "Quebec Bravo")]})
    r = _start(client, "loc261csv.zip", part, dataset="elf")              # the owner picked the wrong dataset
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["dataset"] == "unlocode" and run["release"] == "2026-1" and run["status"] == "previewing"
    assert _start(client, "loc261csv.zip", part).status_code == 409        # one import of a dataset at a time
    before = db.execute(text("SELECT count(*), max(updated_at) FROM ref.location")).one()
    _job(db, run["id"], "preview")
    run = client.get(f"/api/reference/imports/{run['id']}").json()
    p = run["preview"]
    assert run["status"] == "preview_ready" and p["insert"] == 2 and p["deactivate"] == 0 and p["chosen_other"] == "elf"
    assert "partial_release" in p["warnings"]
    assert db.execute(text("SELECT count(*), max(updated_at) FROM ref.location")).one() == before     # nothing changed
    assert client.post(f"/api/reference/imports/{run['id']}/confirm", json={}).status_code == 200
    _job(db, run["id"], "import")
    run = client.get(f"/api/reference/imports/{run['id']}").json()
    assert run["status"] == "done" and run["report"]["inserted"] == 2
    assert db.execute(text("SELECT count(*) FROM ref.location WHERE unlocode IN ('ZZQAA', 'ZZQBB')")).scalar() == 2
    feed = client.get("/api/live/changes").json()
    assert any(n.get("entity_type") == "reference_import" and n["entity_id"] == run["id"] for n in feed["notices"])


def test_cancel_and_failure_mid_import_leave_the_data_unchanged(client, db, monkeypatch):
    from app.modules.reference import bulk

    part = unlocode_zip({1: [_loc_row(f"ZZ{a}{b}{c}", f"Row {a}{b}{c}") for a in "RST" for b in "ABCDEFGH" for c in "ABCDEFGH"]})
    run = _start(client, "loc262csv.zip", part).json()
    _job(db, run["id"], "preview")
    client.post(f"/api/reference/imports/{run['id']}/confirm", json={})
    before = db.execute(text("SELECT count(*) FROM ref.location WHERE unlocode LIKE 'ZZR%'")).scalar()
    # «لغو» while the rows are loaded: the merge never commits
    monkeypatch.setattr(bulk, "BATCH", 50)
    db.execute(text("UPDATE ref.import_run SET cancel_requested = true WHERE id = :i"), {"i": run["id"]})
    db.commit()
    _job(db, run["id"], "import")
    assert client.get(f"/api/reference/imports/{run['id']}").json()["status"] == "cancelled"
    assert db.execute(text("SELECT count(*) FROM ref.location WHERE unlocode LIKE 'ZZR%'")).scalar() == before
    # a failure in the merge: rolled back, recorded on the run
    run = _start(client, "loc262csv.zip", part).json()
    _job(db, run["id"], "preview")
    client.post(f"/api/reference/imports/{run['id']}/confirm", json={})

    def broken(*_a, **_k):
        raise RuntimeError("disk full")
    monkeypatch.setitem(bulk.MERGE, "unlocode", broken)
    _job(db, run["id"], "import")
    out = client.get(f"/api/reference/imports/{run['id']}").json()
    assert out["status"] == "failed" and "disk full" in out["error"]
    assert db.execute(text("SELECT count(*) FROM ref.location WHERE unlocode LIKE 'ZZR%'")).scalar() == before


def test_a_curated_dataset_cannot_be_uploaded_as_if_it_were_official(client):
    r = client.post("/api/reference/import", files={"file": (ELF_FILE.name, ELF_FILE.read_bytes(), "text/csv")},
                    data={"dataset": "legal_forms"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "curated_dataset"


def test_full_unlocode_release_in_under_60_seconds(db):
    """116,000 rows in the official format, three parts: parse, COPY, merge (rolled back afterwards)."""
    import random
    import string
    import time

    from app.modules.reference import bulk

    rng = random.Random(7)
    letters = string.ascii_uppercase
    countries = [a + b for a in letters for b in letters][:240]
    codes = set()
    while len(codes) < 116_000:
        codes.add(rng.choice(countries) + "".join(rng.choice(letters + "23456789") for _ in range(3)))
    rows = [_loc_row(c, f"Place {c}", fn="1234----", iata="") for c in sorted(codes)]
    third = len(rows) // 3
    data = unlocode_zip({1: rows[:third], 2: rows[third:2 * third], 3: rows[2 * third:]})
    started = time.monotonic()
    try:
        out = bulk.apply(db, "unlocode", bulk.file_parts("loc251csv.zip", data), "2025-1")
        seconds = time.monotonic() - started
        print(f"\n116,000-row UN/LOCODE import: {seconds:.1f} s (parse {out['seconds']} s inside apply)")
        assert out["records"] == 116_000 and out["rejected"] == 0 and seconds < 60
    finally:
        db.rollback()


# ---- 0.3.1 party KPI tiles, 0.3.2 tracking link ------------------------------------------------------------------------

def _kpi_data(client, db):
    """S1 has enough history for every tile; S2 one data point each (too few)."""
    s1 = make_party(client, name_en=f"Supplier One {tag()}", roles=["supplier"])
    s2 = make_party(client, name_en=f"Supplier Two {tag()}", roles=["supplier"])
    case = client.post("/api/cases", json={"title": f"KPI {tag()}"}).json()
    c = case["id"]
    q = lambda sql, **p: db.execute(text(sql), p).scalar()   # noqa: E731
    po = lambda party, due, confirmed, ready: q(                 # noqa: E731
        "INSERT INTO ops.purchase_order (case_id, number, supplier_party_id, language, currency, status, ready_due_on, "
        "confirmed_ready_on, ready_on) VALUES (:c, :n, :p, 'en', 'USD', 'received', :due, :conf, :ready) RETURNING id",
        c=c, n=f"PO-T-{tag()}", p=party, due=due, conf=confirmed, ready=ready)
    a = po(s1["id"], "2026-03-01", None, "2026-02-27")                    # on time
    b = po(s1["id"], "2026-03-01", "2026-03-10", "2026-03-09")            # on time against the confirmed date
    late = po(s1["id"], "2026-04-01", None, None)                          # late by receipt (ready date not recorded)
    q("INSERT INTO ops.receipt (purchase_order_id, received_on) VALUES (:p, '2026-04-05') RETURNING id", p=late)
    po(s1["id"], None, None, "2026-05-01")                                 # no due date: not counted
    single = po(s2["id"], "2026-03-01", None, "2026-03-03")
    for po_id, result in ((a, "pass"), (b, "pass"), (late, "fail"), (single, "pass")):
        q("INSERT INTO ops.inspection (case_id, purchase_order_id, kind, result) VALUES (:c, :p, 'pre_shipment', :r) RETURNING id",
          c=c, p=po_id, r=result)
    rfq = q("INSERT INTO ops.rfq (case_id, title) VALUES (:c, 'RFQ') RETURNING id", c=c)
    items = [q("INSERT INTO ops.line_item (case_id, name) VALUES (:c, :n) RETURNING id", c=c, n=f"Item {i}") for i in range(3)]

    def offer(party, sent, received, prices, rfq_id=None):
        rr = q("INSERT INTO ops.rfq_recipient (rfq_id, party_id, channel, status, sent_at) VALUES (:r, :p, 'email', 'sent', :s) "
               "RETURNING id", r=rfq_id or rfq, p=party, s=sent)
        o = q("INSERT INTO ops.supplier_offer (case_id, party_id, rfq_recipient_id, received_at, channel, currency) "
              "VALUES (:c, :p, :rr, :at, 'email', 'USD') RETURNING id", c=c, p=party, rr=rr, at=received)
        for item, price in zip(items, prices):
            if price is not None:
                q("INSERT INTO ops.offer_item (offer_id, line_item_id, unit_price) VALUES (:o, :i, :u) RETURNING id",
                  o=o, i=item, u=price)
    offer(s1["id"], "2026-02-01T08:00:00Z", "2026-02-02T08:00:00Z", [100, 50, 70])      # 24 h
    rfq2 = q("INSERT INTO ops.rfq (case_id, title) VALUES (:c, 'RFQ 2') RETURNING id", c=c)
    offer(s1["id"], "2026-02-10T08:00:00Z", "2026-02-12T08:00:00Z", [None, None, None], rfq2)  # 48 h (no prices)
    offer(s2["id"], "2026-02-01T08:00:00Z", "2026-02-01T20:00:00Z", [120, 40, 90])       # 12 h
    db.commit()
    return s1, s2


def test_party_kpi_tiles_with_their_sample_size(client, db):
    s1, s2 = _kpi_data(client, db)
    one = client.get(f"/api/parties/{s1['id']}/scorecard").json()
    assert one["on_time"] == {"value": 67, "n": 3, "enough": True, "on_time": 2, "avg_late_days": 4.0}
    assert one["inspection"]["value"] == 67 and one["inspection"]["n"] == 3 and one["inspection"]["failed"] == 1
    assert one["response_time"]["value"] == 36.0 and one["response_time"]["n"] == 2
    assert one["price_position"] == {"value": 2, "n": 3, "enough": True, "cheapest": 2, "compared": 3}
    two = client.get(f"/api/parties/{s2['id']}/scorecard").json()
    for tile in ("on_time", "inspection", "response_time"):            # one data point: «دادهٔ کافی نیست»
        assert two[tile]["n"] == 1 and two[tile]["enough"] is False and two[tile]["value"] is None
    assert two["price_position"]["n"] == 3 and two["price_position"]["cheapest"] == 1


def test_tracking_link_from_the_carrier_template(client, db):
    from app.modules.execution import logistics
    from app.modules.execution.models import Shipment

    bad = make_party(client, name_en=f"Carrier {tag()}", roles=["supplier"])
    r = client.patch(f"/api/parties/{bad['id']}", json={"tracking_url_template": "https://track.example/no-placeholder"})
    assert r.status_code == 422
    carrier = make_party(client, name_en=f"Carrier {tag()}", roles=["supplier"])
    r = client.patch(f"/api/parties/{carrier['id']}", json={"tracking_url_template": "https://track.example/t?no={number}"})
    assert r.status_code == 200 and r.json()["tracking_url_template"].endswith("{number}")
    s = Shipment(case_id=client.post("/api/cases", json={"title": f"T {tag()}"}).json()["id"], mode="sea",
                 carrier_party_id=carrier["id"], transport_doc_no="MSKU 123/45", code=f"SH-T-{tag()}")   # not saved
    assert logistics.tracking(db, s) == {"number": "MSKU 123/45", "url": "https://track.example/t?no=MSKU%20123%2F45",
                                         "carrier_has_template": True}
    s.tracking_number = "BL-9"
    assert logistics.tracking(db, s)["url"] == "https://track.example/t?no=BL-9"
    s.carrier_party_id = None
    assert logistics.tracking(db, s) == {"number": "BL-9", "url": None, "carrier_has_template": False}
    db.rollback()
