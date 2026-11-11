"""v0.10.0 milestone 0 (carry-over): a provider is local by its endpoint address, not its kind (redaction and
«فقط محلی» follow); the Claude sign-in block (status states, the visible sign-in console, windowless CLI runs,
sign-out); curated locations matched against an official-format UN/LOCODE file with a mismatch report."""
import json
import uuid

import httpx
import pytest
from sqlalchemy import text

from tests.test_parties import make_party, tag
from tests.test_v090_m3 import _ok_body, clean_ai, fake, providers, route, run, setup_provider  # noqa: F401


# ---- 0.2.1 local by endpoint ---------------------------------------------------------------------------------------

@pytest.fixture
def default_addresses(db):
    yield
    db.execute(text("UPDATE ai.provider SET base_url = NULL WHERE kind IN ('ollama', 'openai_compatible')"))
    db.commit()


@pytest.mark.parametrize("url,local", [
    ("http://127.0.0.1:11434", True), ("http://localhost:1234/v1", True), ("http://[::1]:8000", True),
    ("http://10.1.2.3:8000", True), ("http://172.16.0.9", True), ("http://172.31.255.1", True),
    ("http://192.168.1.5:8000", True), ("http://169.254.10.10", True), ("http://[fe80::1]:11434", True),
    ("http://[fd12:3456::1]", True), ("http://[::ffff:192.168.1.5]", True), ("http://api.localhost:8080", True),
    ("https://ollama.example.com", False), ("http://8.8.8.8:11434", False), ("http://172.32.0.1", False),
    ("http://192.169.1.1", False), ("http://100.64.0.1", False), ("https://api.groq.com/openai", False),
    ("http://nas:11434", False), ("http://[2001:db8::1]", False), ("http://192.168.1.5.evil.com", False),
    ("", False), (None, False)])
def test_endpoint_is_local_only_for_loopback_and_private_addresses(url, local):
    from app.modules.ai import service

    assert service.endpoint_is_local(url) is local


def test_ollama_and_compatible_providers_at_a_public_address_are_cloud(client, db, fake, clean_ai, default_addresses):
    """Redaction applies, a local-only case never reaches them, and the API labels them cloud."""
    from app.core.errors import AppError

    remote = setup_provider(client, "ollama", "qwen2.5", price=None, base_url="https://ollama.example.com")
    assert remote["local"] is False
    route(client, "classification", remote, "qwen2.5", privacy="cloud_redacted")
    party = make_party(client, name_en=f"Shanghai Valve {tag()}", roles=["supplier"])
    case = client.post("/api/cases", json={"title": f"AI {tag()}", "party_id": party["id"]}).json()
    note = f"From {party['name_en']}, ali@valve.cn: 2 pumps"
    out = run(db, text_=note, case_id=uuid.UUID(case["id"]))
    sent = json.dumps(fake.last, ensure_ascii=False)
    assert str(fake.requests[-1].url).startswith("https://ollama.example.com/")
    assert party["name_en"] not in sent and "ali@valve.cn" not in sent and "⟦PARTY_1⟧" in sent
    assert out.call.redactions == {"PARTY": 1, "EMAIL": 1}
    # «فقط محلی»: the remote Ollama is skipped, nothing is sent
    client.put(f"/api/ai/cases/{case['id']}/privacy", json={"local_only": True})
    before = len(fake.requests)
    with pytest.raises(AppError) as exc:
        run(db, text_=note, case_id=uuid.UUID(case["id"]))
    assert exc.value.code == "ai_local_only" and len(fake.requests) == before
    skipped = db.execute(text("SELECT status, error FROM ai.call ORDER BY created_at DESC LIMIT 1")).one()
    assert skipped.status == "skipped" and "local_only" in skipped.error
    # the same for an OpenAI-compatible server on the internet
    compat = setup_provider(client, "openai_compatible", "llama", price=None, base_url="https://api.groq.com/openai")
    assert compat["local"] is False


def test_the_same_kinds_at_a_private_address_stay_local(client, db, fake, clean_ai, default_addresses):
    local = setup_provider(client, "ollama", "qwen2.5", price=None)             # default 127.0.0.1
    lan = setup_provider(client, "openai_compatible", "llama", price=None, base_url="http://192.168.1.5:8000")
    assert local["local"] is True and lan["local"] is True
    route(client, "classification", lan, "llama", privacy="cloud_redacted")
    party = make_party(client, name_en=f"Shanghai Valve {tag()}", roles=["supplier"])
    case = client.post("/api/cases", json={"title": f"AI {tag()}", "party_id": party["id"]}).json()
    client.put(f"/api/ai/cases/{case['id']}/privacy", json={"local_only": True})
    out = run(db, text_=f"From {party['name_en']}, ali@valve.cn: 2 pumps", case_id=uuid.UUID(case["id"]))
    sent = json.dumps(fake.last, ensure_ascii=False)
    assert party["name_en"] in sent and "ali@valve.cn" in sent and out.call.redactions in ({}, None)
    assert out.call.privacy == "local_only" and out.call.status == "ok"


# ---- 0.1.2 Claude sign-in ------------------------------------------------------------------------------------------

@pytest.fixture
def cli(monkeypatch):
    """A fake CLI process: records what is started and how (hidden or in a visible console)."""
    from app.modules.ai import claude_cli

    class Fake:
        calls: list = []
        logged_in = False

        def __call__(self, args, visible):
            self.calls.append((args, visible))
            if visible:
                return 0, ""
            if args[1:3] == ["auth", "status"]:
                return (0 if self.logged_in else 1), json.dumps(
                    {"loggedIn": self.logged_in, "authMethod": "claude.ai" if self.logged_in else None,
                     "email": "owner@example.com" if self.logged_in else None, "configDirectory": r"C:\Users\Owner\.claude"})
            if args[1:3] == ["auth", "logout"]:
                self.logged_in = False
                return 0, "Signed out"
            raise AssertionError(args)

    f = Fake()
    f.calls = []
    monkeypatch.setattr(claude_cli, "cli_path", lambda: r"C:\BOMS\app\venv\Lib\site-packages\claude_agent_sdk\_bundled\claude.exe")
    monkeypatch.setattr(claude_cli, "other_accounts", lambda home=None: [])
    claude_cli.set_runner(f, windows=True)
    yield f
    claude_cli.set_runner(None, None)


def test_sign_in_block_states(client, cli, monkeypatch):
    from app.modules.ai import claude_cli

    out = client.get("/api/ai/claude/status").json()
    assert out["state"] == "signed_out" and out["logged_in"] is False and out["can_open_console"] is True
    assert out["account"] and out["config_dir"] == r"C:\Users\Owner\.claude"
    assert cli.calls[-1][1] is False                                   # the status check opens no window
    monkeypatch.setattr(claude_cli, "other_accounts", lambda home=None: ["Admin"])
    other = client.get("/api/ai/claude/status").json()
    assert other["state"] == "other_account" and other["other_accounts"] == ["Admin"]
    cli.logged_in = True
    signed = client.get("/api/ai/claude/status").json()
    assert signed["state"] == "signed_in" and signed["email"] == "owner@example.com" and signed["other_accounts"] == []
    monkeypatch.setattr(claude_cli, "cli_path", lambda: None)
    assert client.get("/api/ai/claude/status").json()["state"] == "no_cli"
    monkeypatch.setattr(claude_cli, "sdk_version", lambda: None)
    assert client.get("/api/ai/claude/status").json()["state"] == "no_sdk"


def test_login_opens_a_visible_console_that_stays_open(client, cli):
    r = client.post("/api/ai/claude/login")
    assert r.status_code == 200 and r.json()["opened"] is True
    command, visible = cli.calls[-1]
    assert visible is True
    assert command == ('cmd.exe /d /k ""C:\\BOMS\\app\\venv\\Lib\\site-packages\\claude_agent_sdk\\_bundled\\claude.exe"'
                       ' auth login --claudeai"')                      # /k keeps the console until the owner closes it


def test_login_off_windows_and_without_cli(client, cli, monkeypatch):
    from app.modules.ai import claude_cli

    claude_cli.set_runner(cli, windows=False)
    r = client.post("/api/ai/claude/login")
    assert r.status_code == 409 and r.json()["error"]["code"] == "claude_login_unavailable"
    assert all(not visible for _, visible in cli.calls)
    monkeypatch.setattr(claude_cli, "cli_path", lambda: None)
    assert client.post("/api/ai/claude/login").json()["error"]["code"] == "claude_cli_missing"


def test_logout_signs_out_and_resets_the_provider_status(client, db, cli):
    cli.logged_in = True
    db.execute(text("UPDATE ai.provider SET status = 'ok' WHERE kind = 'claude_subscription'"))
    db.commit()
    out = client.post("/api/ai/claude/logout")
    assert out.status_code == 200 and out.json()["state"] == "signed_out"
    assert (cli.calls[-2][0][1:3], cli.calls[-2][1]) == (["auth", "logout"], False)
    db.expire_all()
    assert db.execute(text("SELECT status FROM ai.provider WHERE kind = 'claude_subscription'")).scalar() == "unknown"


def test_other_accounts_are_found_by_their_credentials_file(tmp_path):
    from app.modules.ai import claude_cli

    for name, signed in (("Owner", False), ("Admin", True), ("Guest", False)):
        (tmp_path / name / ".claude").mkdir(parents=True)
        if signed:
            (tmp_path / name / ".claude" / ".credentials.json").write_text("{}")
    assert claude_cli.other_accounts(tmp_path / "Owner") == ["Admin"]
    assert claude_cli.other_accounts(tmp_path / "Admin") == []


def test_cli_processes_of_the_sdk_get_no_window():
    """The SDK's transport starts the CLI through anyio.open_process; on Windows the stand-in adds CREATE_NO_WINDOW."""
    import anyio

    from app.modules.ai import claude_cli

    seen = {}

    class Real:
        sleep = "kept"

        async def open_process(self, command, **kwargs):
            seen.update(kwargs, command=command)
            return "process"

    proxy = claude_cli.NoWindowAnyio(Real(), claude_cli.CREATE_NO_WINDOW)
    assert anyio.run(lambda: proxy.open_process(["claude"], stdin=1)) == "process"
    assert seen["creationflags"] == 0x08000000 and seen["stdin"] == 1 and proxy.sleep == "kept"
    claude_cli.set_runner(None, windows=False)
    assert claude_cli.hide_sdk_windows() is False and claude_cli.hidden_flags() == 0
    claude_cli.set_runner(None, windows=True)
    try:
        from claude_agent_sdk._internal.transport import subprocess_cli

        original = subprocess_cli.anyio
        assert claude_cli.hide_sdk_windows() is True and claude_cli.hide_sdk_windows() is True      # idempotent
        assert isinstance(subprocess_cli.anyio, claude_cli.NoWindowAnyio) and claude_cli.hidden_flags() == 0x08000000
        assert subprocess_cli.anyio._real is original
        subprocess_cli.anyio = original
    finally:
        claude_cli.set_runner(None, None)


# ---- 0.2.2 curated locations against the official file -----------------------------------------------------------------

def test_curated_locations_are_at_least_150_and_well_formed():
    import csv
    import re
    from pathlib import Path

    import app.modules.reference as ref

    rows = list(csv.DictReader((Path(ref.__file__).parent / "data" / "locations_curated.csv").open(encoding="utf-8")))
    codes = [r["unlocode"] for r in rows]
    assert len(rows) >= 150 and len(set(codes)) == len(codes)
    assert all(re.fullmatch(r"[A-Z]{2}[A-Z2-9]{3}", c) for c in codes) and all(r["name"] and r["name_fa"] for r in rows)
    assert not {"IRCHB", "RUAST", "RUOLY", "KZAKT", "TMTMZ"} & set(codes)          # the wrong codes of v0.9.0


def test_official_file_matches_curated_rows_and_reports_mismatches(db, tmp_path):
    from app.modules.reference import importer
    from app.modules.reference.models import Location

    db.execute(text("UPDATE ref.location SET source = 'boms-curated', verified = false "
                    "WHERE unlocode IN ('IRBUZ', 'CNSHA', 'TMKRW', 'DEHAM', 'IRZBR')"))       # as shipped, before any official import
    importer.run(db, "locations")
    assert db.query(Location).filter_by(unlocode="IRBUZ").one().verified is False
    f = tmp_path / "2024-2 UNLOCODE CodeListPart1.csv"
    f.write_text(
        ',"IR","BUZ","Bushehr","Bushehr","06","AI","1-34----","0212","BUZ","2858N 05050E",\n'
        ',"CN","SHA","Shanghai Hongqiao International Apt","Shanghai Hongqiao International Apt","SH","AS","---4----","1601",,,\n'
        ',"TM","KRW","Termez","Termez","B","AI","1234----","0501",,,\n'
        ',"DE","HAM","Hamburg","Hamburg","HH","AF","12345---","0501","HAM","5333N 00959E",\n', encoding="utf-8")
    report = importer.run(db, "unlocode", f, "2024-2")
    notes = report["notes"]
    assert notes["curated_matched"] == 4
    by = {(m["unlocode"], m["field"]): m for m in notes["curated_mismatches"]}
    assert set(by) == {("CNSHA", "functions"), ("TMKRW", "name")}
    assert by[("TMKRW", "name")] == {"unlocode": "TMKRW", "field": "name", "curated": "Turkmenbashi", "official": "Termez"}
    assert "p" in by[("CNSHA", "functions")]["curated"] and by[("CNSHA", "functions")]["official"] == "---4----"
    assert "IRZBR" in notes["curated_not_in_file"] and "IRBUZ" not in notes["curated_not_in_file"]
    db.expire_all()
    buz = db.query(Location).filter_by(unlocode="IRBUZ").one()
    assert buz.verified is True and buz.source == "unece" and buz.name_fa == "بوشهر" and buz.subdivision == "06"
    sha = db.query(Location).filter_by(unlocode="CNSHA").one()
    assert sha.verified is True and sha.is_port is True and sha.is_airport is True      # the recorded use is kept
    assert db.query(Location).filter_by(unlocode="IRZBR").one().verified is False
    again = importer.run(db, "unlocode", f, "2024-2")                # the same answer and no change on a second import
    assert again["notes"]["curated_matched"] == 4 and again["notes"]["curated_mismatches"] == notes["curated_mismatches"]
    assert again["inserted"] == 0 and again["updated"] == 0


def test_a_corrected_curated_code_is_deactivated_not_deleted(db):
    from app.modules.reference import importer

    db.execute(text("INSERT INTO ref.location (id, unlocode, country_iso2, code, name, name_ascii, source, active) "
                    "VALUES (gen_random_uuid(), 'IRCHB', 'IR', 'CHB', 'Chabahar', 'Chabahar', 'boms-curated', true) "
                    "ON CONFLICT (unlocode) DO UPDATE SET active = true, source = 'boms-curated'"))
    report = importer.run(db, "locations")
    assert report["deactivated"] >= 1
    old = db.execute(text("SELECT active FROM ref.location WHERE unlocode = 'IRCHB'")).scalar()
    new = db.execute(text("SELECT active, name_fa FROM ref.location WHERE unlocode = 'IRZBR'")).one()
    assert old is False and new.active is True and new.name_fa == "چابهار"


# ---- 0.2.3 the source of a field in focus ----------------------------------------------------------------------------

def _two_page_pdf() -> bytes:
    import pymupdf

    pdf = pymupdf.open()
    first = pdf.new_page()
    first.insert_text((72, 100), "General conditions of the inquiry", fontsize=11)
    second = pdf.new_page()
    second.insert_text((72, 200), "1  Gate valve 6 inch class 300 WCB   4 pcs", fontsize=11)
    second.insert_text((72, 400), "2  Centrifugal pump API 610, Q=120 m3/h, H=85 m   2 sets", fontsize=11)
    return pdf.tobytes()


def test_pdf_region_of_the_wording_is_found_on_its_page():
    from app.modules.ai import locate

    data = _two_page_pdf()
    exact = locate.pdf_regions(data, 2, "Gate valve 6 inch class 300 WCB")
    assert exact["found"] and exact["pages"] == 2 and len(exact["rects"]) == 1
    r = exact["rects"][0]                                     # A4 is 595 x 842 pt: the line sits at x >= 72, y ~ 200
    assert 0.10 < r["x"] < 0.20 and 0.21 < r["y"] < 0.25 and 0.2 < r["w"] < 0.6 and r["h"] < 0.03
    # the model's wording differs from the layout (punctuation, order): the words find the line, not the valve line
    loose = locate.pdf_regions(data, 2, "Centrifugal pump API 610 — Q=120 m3/h; H=85 m (2 sets)")
    assert loose["found"] and all(0.44 < x["y"] < 0.49 for x in loose["rects"])
    assert locate.pdf_regions(data, 2, "Mechanical seal plan 53B")["found"] is False
    assert locate.pdf_regions(data, 1, "Gate valve 6 inch class 300 WCB")["found"] is False       # not on page 1
    assert locate.pdf_regions(data, 9, "Gate valve")["rects"] == []


def test_sheet_rows_and_pasted_span():
    from app.modules.ai import locate

    preview = [["Item", "Qty", "Unit"], ["Gate valve 6\" class 300 WCB", "4", "pcs"], ["شیر توپی ۲ اینچ", "۱۰", "عدد"]]
    assert locate.sheet_rows(preview, None, 'Gate valve 6" class 300 WCB') == [2]
    assert locate.sheet_rows(preview, None, "شير توپي 2 اينچ") == [3]            # Arabic letters and Latin digits
    assert locate.sheet_rows(preview, 3, "something the model reworded entirely") == [3]     # the row it named
    assert locate.sheet_rows(preview, None, "nothing like it") == []
    mail = "Dear supplier,\nPars Oil needs 10 ball valves 2\" class 150.\nRegards"
    start, end = locate.text_span(mail, '10 ball  valves 2" class 150')
    assert mail[start:end] == '10 ball valves 2" class 150'
    assert locate.text_span(mail, "pumps") is None


def test_field_source_api_for_pdf_sheet_and_pasted(client, db):
    from tests.conftest import upload
    from tests.test_v090_m4 import ITEM, Recorder, fields, run_draft
    from tests.test_v090_m3 import _reset
    from app.modules.ai import adapters, builtin, tasks

    _reset(db)
    db.commit()
    rec = Recorder()
    adapters.set_transport(httpx.MockTransport(rec))
    try:
        local = setup_provider(client, "ollama", "qwen2.5-vl", price=None)
        route(client, "extraction", local, "qwen2.5-vl", privacy="cloud_redacted")
        if "extract_items" not in tasks.TASKS:
            builtin.register()
        case = client.post("/api/cases", json={"title": f"Highlight {tag()}"}).json()
        doc = upload(client, f"rfq-{tag()}.pdf", _two_page_pdf()).json()
        rec.answers.append({"items": [{**ITEM, "page": 2}], "terms": {"incoterm": "CFR"}, "column_mapping": None})
        r = client.post("/api/ai/extract", json={"target_type": "case", "target_id": case["id"], "document_ids": [doc["id"]]})
        run_draft(db, r.json())
        draft_id = r.json()["id"]
        f = fields(client, draft_id)
        src = client.get(f"/api/ai/drafts/{draft_id}/fields/{f['items[0].name']['id']}/source").json()
        assert src["kind"] == "pdf" and src["found"] is True and src["page"] == 2 and src["source_index"] == 0
        assert all(0.44 < x["y"] < 0.49 for x in src["rects"]) and src["image"].endswith("/sources/0/pages/2")
        png = client.get(src["image"])
        assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert client.get(f"/api/ai/drafts/{draft_id}/sources/0/pages/7").status_code == 404
        assert client.get(f"/api/ai/drafts/{draft_id}/sources/3/pages/1").status_code == 404
        # a field with no source (the terms) has nothing to highlight
        none = client.get(f"/api/ai/drafts/{draft_id}/fields/{f['terms.incoterm']['id']}/source").json()
        assert none["kind"] is None and none["found"] is False
        assert client.get(f"/api/ai/drafts/{draft_id}/fields/{uuid.uuid4()}/source").status_code == 404
        # pasted text
        mail = 'Dear supplier,\nwe need 10 ball valves 2" class 150.\nRegards'
        rec.answers.append({"items": [{**ITEM, "original": '10 ball valves 2" class 150', "page": None}], "terms": None,
                            "column_mapping": None})
        r = client.post("/api/ai/extract", json={"target_type": "case", "target_id": case["id"], "text": mail})
        run_draft(db, r.json())
        f = fields(client, r.json()["id"])
        src = client.get(f"/api/ai/drafts/{r.json()['id']}/fields/{f['items[0].name']['id']}/source").json()
        assert src["kind"] == "pasted" and mail[src["start"]:src["end"]] == '10 ball valves 2" class 150'
    finally:
        adapters.set_transport(None)
        _reset(db)
        db.commit()
