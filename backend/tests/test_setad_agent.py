"""v0.5.0 Setad agent against the offline fake site (real Playwright, headless): connect with the role page, full
fetch with one captcha pause, quick fetch, details, downloads, tenders with «فراخوان‌های من»; the ``setad`` lane is
isolated; single instance; cancel; heartbeat; no secret in logs, the database or diagnostics.

Nothing here contacts a network host: every request of the agent's browser is answered by tests/connectors/setad/
fakesite.py or aborted, and the browser's proxy is a dead local port.
"""
import json
import os
import threading
import time
import uuid

import pytest
from sqlalchemy import text

os.environ.setdefault("BOMS_SETAD_FAKE_CAPTCHA_MS", "1500")
os.environ.setdefault("BOMS_SETAD_FAKE_LOGIN_MS", "600")

from app.connectors.setad import agent as agent_mod  # noqa: E402
from app.connectors.setad.rows import SOURCE_PURCHASE, SOURCE_TENDER  # noqa: E402
from app.core.config import get_config  # noqa: E402
from app.core.db import new_session  # noqa: E402
from app.modules.listings import service  # noqa: E402
from app.modules.system import jobs  # noqa: E402
from app.worker import runner  # noqa: E402
from tests.connectors.setad import fakesite  # noqa: E402


@pytest.fixture
def agent(monkeypatch, tmp_path):
    monkeypatch.setenv("BOMS_SETAD_FAKE", "tests.connectors.setad.fakesite")
    monkeypatch.setenv("BOMS_SETAD_HEADLESS", "1")
    fakesite.FAKE = fakesite.Fake(needs=75, tenders=120)
    with new_session() as db:
        from app.modules.system import settings
        settings.update(db, {"setad.files_dir": str(tmp_path / "setad-files")}, "script")
        db.execute(text("UPDATE ext.agent_status SET cancel_requested = false, connected = false"))
        db.execute(text("DELETE FROM sys.job WHERE lane = 'setad'"))
        db.commit()
    a = agent_mod.Agent(get_config().data_dir)
    yield a
    a.close()
    with new_session() as db:
        from app.modules.system import settings
        settings.update(db, {"setad.files_dir": None}, "script")
        db.commit()


def run(agent, command: str, **payload):
    """Queue through the service (as the UI does) and let the agent take it from the setad lane."""
    with new_session() as db:
        job = service.command(db, command, payload, "script")
        db.commit()
        job_id = job.id
    with new_session() as db:
        claimed = jobs.claim_next(db, lane="setad")
        assert claimed is not None and claimed.id == job_id
        info = (claimed.id, claimed.type, dict(claimed.payload))
    agent.run_job(*info)
    with new_session() as db:
        row = db.execute(text("SELECT status, last_error FROM sys.job WHERE id = :i"), {"i": job_id}).one()
    assert row[0] == "done", row[1]
    return job_id


def listing_id(db, source, external_id):
    return db.execute(text("SELECT id FROM ext.listing WHERE source = :s AND external_id = :e"),
                      {"s": source, "e": external_id}).scalar()


def test_purchase_calls_connect_full_fetch_with_captcha_quick_detail_download(agent, db):
    run(agent, "connect", role="EPROC")
    assert agent.browser.role == "EPROC" and fakesite.FAKE.role == "EPROC"   # role page filled by itself
    status = service.agent_status(db)
    assert status["role"] == "EPROC" and status["browser_channel"] is None   # Playwright Chromium offline
    # full fetch: 75 needs on 3 pages, page 2 asks once for a captcha (solved "by the owner" after 1.5 s)
    captcha_seen = []
    orig = agent.status.set
    agent.status.set = lambda **v: (captcha_seen.append(v["captcha_message"]) if v.get("captcha_waiting") else None,
                                    orig(**v))[1]
    run(agent, "full_fetch", source=SOURCE_PURCHASE)
    agent.status.set = orig
    assert fakesite.FAKE.captchas_shown == 1 and captcha_seen and "کپچا" in captcha_seen[0]
    db.expire_all()
    run_info = service.agent_status(db)["runs"][SOURCE_PURCHASE]
    assert run_info["status"] == "done" and run_info["new_count"] == 75 and run_info["pages_done"] == 3
    assert service.agent_status(db)["captcha_waiting"] is False
    page = service.query(db, {"source": SOURCE_PURCHASE, "page_size": 100, "q": "نیاز"})
    assert page["total"] >= 75
    # quick fetch: from the newest announcement minus 3 days; nothing older disappears
    run(agent, "quick_fetch", source=SOURCE_PURCHASE)
    db.expire_all()
    quick = service.agent_status(db)["runs"][SOURCE_PURCHASE]
    assert quick["kind"] == "quick" and quick["status"] == "done" and quick["new_count"] == 0 and 0 < quick["rows_seen"] < 75
    assert service.query(db, {"source": SOURCE_PURCHASE, "page_size": 100, "q": "نیاز"})["total"] == page["total"]
    # detail and attachments of one need
    need = fakesite.FAKE.needs[4]
    lid = listing_id(db, SOURCE_PURCHASE, need["request_id"])
    run(agent, "fetch_detail", listing_ids=[str(lid)])
    detail = service.detail(db, lid)
    assert detail["listing"]["deadline_exact"] is True and detail["listing"]["price_valid_until"] is not None
    assert detail["detail"]["items"]["rows"][0][2] == need["title"].split(" - ")[0]
    assert "تسویه سه ماهه" in detail["detail"]["buyer_note"]
    run(agent, "download_files", listing_ids=[str(lid)])
    db.expire_all()
    files = service.detail(db, lid)["files"]
    assert sorted(f["name"] for f in files) == ["مشخصات فنی 1.pdf", "مشخصات فنی 2.pdf"]
    assert all(f["state"] == "downloaded" and f["sha256"] for f in files)
    folder = service.files_dir(db) / need["no"]
    assert json.loads((folder / ".download_info.json").read_text())["attachment_total"] == 2
    page = service.query(db, {"source": SOURCE_PURCHASE, "page_size": 100, "q": need["no"]})
    assert page["items"][0]["documents"] == {"downloaded": 2, "total": 2}
    # a file deleted by hand shows as missing (disk and database stay in sync)
    next(folder.glob("*1.pdf")).unlink()
    page = service.query(db, {"source": SOURCE_PURCHASE, "page_size": 100, "q": need["no"]})
    assert page["items"][0]["documents"] == {"downloaded": 1, "total": 2}
    # clear cache removes only connector files
    (folder / "my-own-note.txt").write_text("keep me")
    left = list(folder.glob("*.pdf"))
    assert len(left) == 1 and service.clear_cache(db, "script")["files"] >= 1   # every connector file, not only these
    db.commit()
    assert not left[0].exists() and not (folder / ".download_manifest.json").exists()
    assert (folder / "my-own-note.txt").exists()                               # the owner's own file stays


def test_tenders_full_fetch_my_calls_with_confirmation(agent, db, client):
    run(agent, "connect", role="ETEND")
    assert agent.browser.role == "ETEND"
    run(agent, "full_fetch", source=SOURCE_TENDER)
    db.expire_all()
    run_info = service.agent_status(db)["runs"][SOURCE_TENDER]
    assert run_info["status"] == "done" and run_info["rows_seen"] == 120
    tender = fakesite.FAKE.tenders[7]
    lid = listing_id(db, SOURCE_TENDER, str(tender["id"]))
    # site write actions: refused without confirmation, recorded with it
    r = client.post("/api/setad/commands", json={"command": "add_my_call", "listing_id": str(lid)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "confirmation_required"
    assert fakesite.FAKE.add_requests == []
    run(agent, "add_my_call", listing_id=str(lid), confirmed=True)
    assert fakesite.FAKE.add_requests[0]["tenderId"] == str(tender["id"])
    db.expire_all()
    assert service.detail(db, lid)["listing"]["in_my_calls"] is True
    logged = db.execute(text("SELECT action FROM core.event WHERE entity_type = 'listing' AND entity_id = :i "
                             "ORDER BY id"), {"i": str(lid)}).scalars().all()
    assert "add_my_call" in logged and "site_action" in logged
    run(agent, "sync_my_calls")
    db.expire_all()
    assert service.detail(db, lid)["listing"]["site_state"] == "ADD_TO_MY_FAVORITE"
    run(agent, "remove_my_call", listing_id=str(lid), confirmed=True)
    assert fakesite.FAKE.delete_requests == [str(tender["id"])]
    db.expire_all()
    assert service.detail(db, lid)["listing"]["in_my_calls"] is False


def test_setad_lane_is_isolated_while_a_fetch_waits_for_captcha(agent, db, monkeypatch):
    """A backup job (default lane) runs to the end while the agent waits for a captcha on the setad lane."""
    from app.worker.registry import load_handlers

    load_handlers()
    monkeypatch.setattr(fakesite, "CAPTCHA_MS", 6000)
    run(agent, "connect", role="EPROC")
    with new_session() as s:
        setad_job = service.command(s, "full_fetch", {"source": SOURCE_PURCHASE}, "script")
        backup_job = jobs.enqueue(s, "backup.run", {"kind": "manual"}, source="script")
        s.commit()
        setad_id, backup_id = setad_job.id, backup_job.id
    # the normal worker never takes the setad command
    assert runner.run_until_idle() >= 1
    with new_session() as s:
        states = dict(s.execute(text("SELECT id, status FROM sys.job WHERE id IN (:a, :b)"),
                                {"a": setad_id, "b": backup_id}).all())
    assert states[backup_id] == "done" and states[setad_id] == "queued"
    # now the agent takes it; while it waits for the captcha, another backup runs to the end
    with new_session() as s:
        job = jobs.claim_next(s, lane="setad")
        info = (job.id, job.type, dict(job.payload))
    finished = {}

    def backup_while_waiting():
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with new_session() as s:
                if s.execute(text("SELECT captcha_waiting FROM ext.agent_status")).scalar():
                    break
            time.sleep(0.2)
        with new_session() as s:
            finished["captcha_waiting_at_start"] = s.execute(text("SELECT captcha_waiting FROM ext.agent_status")).scalar()
            jobs.enqueue(s, "backup.run", {"kind": "manual"}, source="script")
            s.commit()
        finished["ran"] = runner.run_until_idle()
        with new_session() as s:
            finished["still_waiting"] = s.execute(text("SELECT captcha_waiting FROM ext.agent_status")).scalar()

    helper = threading.Thread(target=backup_while_waiting)
    helper.start()
    agent.run_job(*info)                      # Playwright stays on this (main) thread
    helper.join(30)
    assert finished["captcha_waiting_at_start"] is True and finished["ran"] == 1 and finished["still_waiting"] is True


def test_cancel_stops_a_fetch_cleanly(agent, db, monkeypatch):
    monkeypatch.setattr(fakesite, "CAPTCHA_MS", 60000)        # the captcha is never solved: the owner cancels
    run(agent, "connect", role="EPROC")
    stop = threading.Event()
    beat = threading.Thread(target=agent.heartbeat, args=(stop,), daemon=True)
    beat.start()

    def cancel_soon():
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with new_session() as s:
                if s.execute(text("SELECT captcha_waiting FROM ext.agent_status")).scalar():
                    service.cancel(s, "script")
                    s.commit()
                    return
            time.sleep(0.2)

    t = threading.Thread(target=cancel_soon)
    t.start()
    started = time.monotonic()
    run(agent, "full_fetch", source=SOURCE_PURCHASE)
    t.join(5)
    stop.set()
    db.expire_all()
    assert time.monotonic() - started < 30
    assert service.agent_status(db)["runs"][SOURCE_PURCHASE]["status"] == "cancelled"
    # the heartbeat was written meanwhile
    hb = db.execute(text("SELECT heartbeat_at FROM ext.agent_status")).scalar()
    assert hb is not None


def test_single_instance_lock(tmp_path):
    a, b = agent_mod.InstanceLock(tmp_path / "agent.lock"), agent_mod.InstanceLock(tmp_path / "agent.lock")
    assert a.acquire() is True
    assert b.acquire() is False
    a.release()
    assert b.acquire() is True
    b.release()


def test_no_secret_in_logs_database_or_diagnostics(agent, db, caplog):
    secret = "csrf_token=SuperSecretToken1234567890abcdefXYZ"
    agent.status.set(last_error=f"site said: HTTP 500 for /etend/x?{secret}", message=f"JSESSIONID=abc123; {secret}")
    row = db.execute(text("SELECT last_error, message FROM ext.agent_status")).one()
    assert "SuperSecretToken" not in (row[0] + row[1]) and "abc123" not in row[1]
    # a failing command: the stored error and the log are redacted
    with new_session() as s:
        job = jobs.enqueue(s, "setad.fetch_detail", {"listing_ids": [str(uuid.uuid4())]}, lane="setad", source="script")
        s.commit()
        job_id = job.id

    def boom(_p):
        raise RuntimeError(f"failed at https://etend.setadiran.ir/etend/a.action?{secret}")
    agent.cmd_fetch_detail = boom
    with caplog.at_level("INFO"):
        agent.run_job(job_id, "setad.fetch_detail", {})
    stored = db.execute(text("SELECT last_error FROM sys.job WHERE id = :i"), {"i": job_id}).scalar()
    assert "SuperSecretToken" not in stored and "SuperSecretToken" not in caplog.text
    # site-flow recording (diagnostics file): parameters with secret names are removed
    run(agent, "connect", role="ETEND")
    run(agent, "record_start")
    agent.browser.work_page().goto("https://etend.setadiran.ir/etend/indexPage.action?csrf_token=SuperSecretToken1234567890abcdefXYZ")
    agent.browser.pump(500)
    run(agent, "record_stop")
    files = list((get_config().data_dir / "connectors" / "setad" / "diagnostics").glob("setad-recording-*.json"))
    assert files and all("SuperSecretToken" not in f.read_text(encoding="utf-8") for f in files)
