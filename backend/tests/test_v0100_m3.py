"""v0.10.0 milestone 3: the change feed behind live page updates. A finished job and a record change reach an open
page through the stream; the polling fallback returns the same notices; the cursor resumes (Last-Event-ID); the
overlap repeats a notice with the same key (the browser drops it); the stream is a background request for the idle
lock; migration 0021 up / down / up."""
import json
import uuid

from sqlalchemy import text

from tests.test_parties import make_party, tag


def _events(body: str) -> list[dict]:
    """The `change` events of a server-sent-events body."""
    out = []
    for block in body.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if lines.get("event") == "change":
            out.append({"id": lines["id"], **json.loads(lines["data"])})
    return out


def test_feed_has_a_finished_job_and_a_record_change(client, db):
    from app.modules.live import service
    from app.modules.system import jobs

    start = service.changes(db, None)["cursor"]
    job = jobs.enqueue(db, "backup.run", {"kind": "manual"})
    db.commit()
    db.execute(text("UPDATE sys.job SET status = 'done', finished_at = now() WHERE id = :i"), {"i": job.id})
    db.commit()
    party = make_party(client, name_en=f"Live {tag()}")
    out = client.get("/api/live/changes", params={"since": start}).json()
    jobs_seen = [n for n in out["notices"] if n["kind"] == "job" and n["id"] == str(job.id)]
    assert jobs_seen and jobs_seen[-1]["status"] == "done" and jobs_seen[-1]["type"] == "backup.run"
    records = [n for n in out["notices"] if n["kind"] == "record" and n["entity_id"] == party["id"]]
    assert records and records[0]["entity_type"] == "party" and records[0]["action"] == "create"
    assert all(set(n) >= {"kind", "key", "at"} for n in out["notices"])
    assert party["name_en"] not in json.dumps(out)                  # a notice names what changed, never its content
    db.execute(text("DELETE FROM sys.job WHERE id = :i"), {"i": job.id})
    db.commit()


def test_overlap_repeats_with_the_same_key_and_a_quiet_cursor_is_empty(client, db):
    from app.modules.live import service

    start = service.changes(db, None)["cursor"]
    party = make_party(client, name_en=f"Live {tag()}")
    first = client.get("/api/live/changes", params={"since": start}).json()
    again = client.get("/api/live/changes", params={"since": first["cursor"]}).json()
    key = next(n["key"] for n in first["notices"] if n.get("entity_id") == party["id"])
    assert key in {n["key"] for n in again["notices"]}              # at least once: the overlap window
    assert first["cursor"] < again["cursor"]
    bad = client.get("/api/live/changes", params={"since": "not a time"})
    assert bad.status_code == 200 and "cursor" in bad.json()


def test_stream_delivers_a_change_to_an_open_page_and_resumes(client, db):
    from app.modules.live import service

    start = service.changes(db, None)["cursor"]
    party = make_party(client, name_en=f"Stream {tag()}")
    with client.stream("GET", "/api/live/stream", params={"since": start, "max_seconds": 1.5, "tick": 0.1}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"].startswith("no-cache")
        body = "".join(r.iter_text())
    assert body.startswith("retry: 2000")
    events = _events(body)
    assert events and any(n.get("entity_id") == party["id"] for e in events for n in e["notices"])
    # the browser reconnects with Last-Event-ID = the last cursor: an older change is not sent again
    last = events[-1]["id"]
    later = make_party(client, name_en=f"Later {tag()}")
    with client.stream("GET", "/api/live/stream", params={"max_seconds": 1, "tick": 0.1}, headers={"Last-Event-ID": last}) as r:
        resumed = _events("".join(r.iter_text()))
    seen = {n.get("entity_id") for e in resumed for n in e["notices"]}
    assert later["id"] in seen


def test_live_requests_do_not_keep_the_session_awake(client):
    from app.core.web import SESSION_COOKIE

    client.get("/api/search", params={"q": "x"})                  # an ordinary request refreshes the activity time
    before = client.cookies.get(SESSION_COOKIE)
    client.get("/api/live/changes")
    assert client.cookies.get(SESSION_COOKIE) == before           # the activity time was not refreshed


def test_unauthenticated_feed_is_refused(anon_client):
    anon_client.cookies.clear()
    assert anon_client.get("/api/live/changes").status_code == 401
    assert anon_client.get("/api/live/stream").status_code == 401


def test_migration_0021_down_up():
    from alembic import command
    from sqlalchemy import create_engine

    from app.cli import alembic_config
    from app.core.config import get_config
    from tests.conftest import create_empty_database

    name = "boms_test_v0100_live_migration"
    create_empty_database(name)
    url = get_config().db_url(name)
    cfg = alembic_config(url)
    engine = create_engine(url)
    q = "SELECT count(*) FROM pg_indexes WHERE indexname IN ('sys_job_updated_at_idx', 'ext_listing_file_updated_at_idx', 'ext_harvest_run_updated_at_idx')"
    try:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO sys.job (type, payload) VALUES ('backup.run', '{}')"))
            assert conn.execute(text(q)).scalar() == 3
        command.downgrade(cfg, "0020")
        with engine.begin() as conn:
            assert conn.execute(text(q)).scalar() == 0
            assert conn.execute(text("SELECT count(*) FROM sys.job WHERE type = 'backup.run'")).scalar() == 1
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            assert conn.execute(text(q)).scalar() == 3
    finally:
        engine.dispose()
