"""v0.9.0 milestone 3: the AI layer. Every provider is exercised through a fake transport (no network host is ever
contacted): request shape, the key from the secret store, usage parsing and errors per adapter; routing and fallback;
the cap (estimate, warnings, ai_cap_reached with local tasks continuing); prices before enabling; redaction round
trip; local-only cases; the privacy log never holds document text; schema validation with one retry; the subscription
adapter's temporary folder; drafts (accept confident, edit, reject, «ثبت» through a committer, corrections reused)."""
import json
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from tests.test_parties import make_party, tag

SCHEMA = {"type": "object", "required": ["items"], "additionalProperties": False,
          "properties": {"items": {"type": "array", "items": {"type": "object", "required": ["name", "quantity"],
                                                              "properties": {"name": {"type": "string"},
                                                                             "quantity": {"type": "number"}}}}}}
SECRET_TEXT = "CONFIDENTIAL-SPEC-PUMP-120m3h line 4711"


class Fake:
    """A fake HTTP transport per provider kind: records the requests and answers like the real API."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.answers: list = []          # queue of (status, body) or callables

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if self.answers else (200, None)
        if callable(answer):
            return answer(request)
        status, body = answer
        if status == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(status, json=body if body is not None else _ok_body(request, '{"items": []}'))

    @property
    def last(self) -> dict:
        return json.loads(self.requests[-1].content)


def _ok_body(request: httpx.Request, answer: str) -> dict:
    url = str(request.url)
    if "/v1/messages" in url:
        return {"content": [{"type": "text", "text": answer}], "stop_reason": "end_turn",
                "usage": {"input_tokens": 1200, "output_tokens": 300}}
    if "/chat/completions" in url:
        return {"choices": [{"message": {"content": answer}}], "usage": {"prompt_tokens": 1200, "completion_tokens": 300}}
    if "generateContent" in url:
        return {"candidates": [{"content": {"parts": [{"text": answer}]}}],
                "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 300}}
    if "/api/chat" in url:
        return {"message": {"content": answer}, "prompt_eval_count": 1200, "eval_count": 300}
    raise AssertionError(url)


def ok(answer: dict | str):
    text_ = answer if isinstance(answer, str) else json.dumps(answer)
    return lambda request: httpx.Response(200, json=_ok_body(request, text_))


@pytest.fixture
def fake(monkeypatch):
    from app.modules.ai import adapters

    f = Fake()
    adapters.set_transport(httpx.MockTransport(f))
    monkeypatch.setenv("BOMS_SECRET_AI_TEST_ANTHROPIC", "sk-ant-test-123")
    monkeypatch.setenv("BOMS_SECRET_AI_TEST_OPENAI", "sk-openai-test-456")
    monkeypatch.setenv("BOMS_SECRET_AI_TEST_GEMINI", "gm-test-789")
    yield f
    adapters.set_transport(None)
    adapters.set_sdk_runner(None)


def providers(client) -> dict:
    return {p["kind"]: p for p in client.get("/api/ai/providers").json()}


def setup_provider(client, kind, model, price=("3", "15"), secret=None, base_url=None):
    p = providers(client)[kind]
    body = {"models": [model]}
    if secret:
        body["secret_name"] = secret
    if base_url:
        body["base_url"] = base_url
    assert client.patch(f"/api/ai/providers/{p['id']}", json=body).status_code == 200
    if price:
        client.put("/api/ai/prices", json={"provider_id": p["id"], "model": model, "input_per_mtok": price[0],
                                           "output_per_mtok": price[1]})
    r = client.patch(f"/api/ai/providers/{p['id']}", json={"enabled": True})
    assert r.status_code == 200, r.text
    return r.json()


def route(client, task, primary, model, fallback=None, fallback_model=None, privacy="cloud"):
    r = client.patch(f"/api/ai/routes/{task}", json={"primary_provider_id": primary["id"], "primary_model": model,
                                                     "fallback_provider_id": fallback["id"] if fallback else None,
                                                     "fallback_model": fallback_model, "privacy": privacy})
    assert r.status_code == 200, r.text


def _reset(db):
    db.execute(text("UPDATE ai.route SET primary_provider_id = NULL, fallback_provider_id = NULL WHERE task = 'classification'"))
    db.execute(text("DELETE FROM ai.price"))
    db.execute(text("UPDATE ai.provider SET enabled = false, models = '{}', secret_name = NULL, status = 'unknown', "
                    "status_detail = NULL"))
    db.execute(text("UPDATE ai.route SET primary_provider_id = (SELECT id FROM ai.provider WHERE kind = 'ollama') "
                    "WHERE task = 'classification'"))


@pytest.fixture
def clean_ai(db):
    """Each test starts with every provider disabled and unconfigured, and the month's spending cleared."""
    _reset(db)
    db.commit()
    yield
    _reset(db)
    db.execute(text("DELETE FROM ai.call WHERE task IN ('classification', 'extraction', 'drafting', 'party_parse', 'ping')"))
    db.execute(text("UPDATE sys.setting SET value = '20' WHERE key = 'ai.monthly_cap_usd'"))
    db.commit()


def run(db, task="classification", text_="Pump 2 pcs", **kw):
    from app.modules.ai import service

    out = service.run(db, task, text=text_, schema=SCHEMA, prompt_task="generic", **kw)
    db.commit()
    return out


# ---- adapters -------------------------------------------------------------------------------------------------------

def test_each_adapter_request_shape_auth_usage_and_errors(fake, monkeypatch):
    from app.modules.ai import adapters
    from app.modules.ai.adapters import Attachment, ProviderError, Request

    req = Request("t", "m-1", "SYS", "hello", [Attachment("p.png", "image/png", b"\x89PNG")], SCHEMA, 500)
    cases = [("anthropic_api", "sk-ant-test-123", "https://api.anthropic.com/v1/messages"),
             ("openai_api", "sk-openai-test-456", "https://api.openai.com/v1/chat/completions"),
             ("gemini_api", "gm-test-789", "https://generativelanguage.googleapis.com/v1beta/models/m-1:generateContent"),
             ("ollama", None, "http://127.0.0.1:11434/api/chat"),
             ("openai_compatible", None, "http://192.168.1.5:8000/v1/chat/completions")]
    for kind, key, url in cases:
        fake.answers.append(ok({"items": [{"name": "Pump", "quantity": 2}]}))
        base = "http://192.168.1.5:8000" if kind == "openai_compatible" else None
        result = adapters.for_provider(kind, base, key).generate(req)
        sent = fake.requests[-1]
        assert str(sent.url) == url
        assert (result.tokens_in, result.tokens_out) == (1200, 300)
        assert json.loads(result.text)["items"][0]["name"] == "Pump"
        body = json.loads(sent.content)
        if kind == "anthropic_api":
            assert sent.headers["x-api-key"] == key and sent.headers["anthropic-version"] == "2026-10-21"
            assert body["messages"][0]["content"][0]["type"] == "image" and body["system"].startswith("SYS")
            assert body["output_config"]["format"]["type"] == "json_schema" and body["max_tokens"] == 500
        elif kind in ("openai_api",):
            assert sent.headers["authorization"] == f"Bearer {key}"
            assert body["response_format"] == {"type": "json_object"}
            assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
        elif kind == "gemini_api":
            assert sent.headers["x-goog-api-key"] == key
            assert body["generationConfig"]["responseMimeType"] == "application/json"
            assert body["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "image/png"
        elif kind == "ollama":
            assert body["stream"] is False and body["format"] == SCHEMA and body["messages"][1]["images"]
        assert "authorization" not in {k.lower() for k in sent.headers} or kind in ("openai_api",)
    # errors -> kinds
    a = adapters.for_provider("anthropic_api", None, "k")
    for answer, kind in (((401, {"error": {"type": "authentication_error"}}), "auth"),
                         ((429, {"error": {"type": "rate_limit_error"}}), "rate_limit"),
                         ((529, {"error": {"type": "overloaded_error"}}), "server"),
                         (("timeout", None), "timeout"), ((400, {"error": {"type": "invalid_request_error"}}), "bad_request")):
        fake.answers.append(answer)
        with pytest.raises(ProviderError) as exc:
            a.generate(req)
        assert exc.value.kind == kind
    with pytest.raises(ProviderError) as exc:
        adapters.for_provider("openai_api", None, None).generate(req)
    assert exc.value.kind == "not_configured"
    fake.answers.append(lambda r: httpx.Response(200, json={"content": [], "stop_reason": "refusal", "usage": {}}))
    with pytest.raises(ProviderError):
        a.generate(req)


def test_subscription_adapter_uses_a_private_folder_that_is_removed(fake):
    from app.modules.ai import adapters
    from app.modules.ai.adapters import Attachment, Request

    seen = {}

    def runner(*, prompt, system, model, folder: Path, schema):
        seen["files"] = sorted(p.name for p in folder.iterdir())
        seen["folder"] = folder
        seen["prompt"] = prompt
        return {"text": "", "data": {"items": [{"name": "Valve", "quantity": 3}]}, "tokens_in": 10, "tokens_out": 5}

    adapters.set_sdk_runner(runner)
    result = adapters.for_provider("claude_subscription", None, None).generate(
        Request("t", "", "S", "read it", [Attachment("offer.pdf", "application/pdf", b"%PDF-1.4"),
                                         Attachment("page.png", "image/png", b"x")], SCHEMA))
    assert seen["files"] == ["input-1.pdf", "input-2.png"]          # only the inputs of this call
    assert not seen["folder"].exists()                              # removed afterwards
    assert result.subscription and result.data["items"][0]["name"] == "Valve"
    assert "Bash" in adapters.DENIED_TOOLS and adapters.READ_ONLY_TOOLS == ["Read"]
    status = adapters.cli_status()
    assert status["sdk"] is True


# ---- prices, routing, fallback, cap ----------------------------------------------------------------------------------

def test_prices_are_required_before_an_api_provider_is_enabled(client, clean_ai):
    p = providers(client)["openai_api"]
    client.patch(f"/api/ai/providers/{p['id']}", json={"models": ["gpt-x"]})
    r = client.patch(f"/api/ai/providers/{p['id']}", json={"enabled": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "prices_required"
    assert r.json()["error"]["details"]["models"] == ["gpt-x"]
    client.put("/api/ai/prices", json={"provider_id": p["id"], "model": "gpt-x", "input_per_mtok": "2",
                                       "output_per_mtok": "8"})
    assert client.patch(f"/api/ai/providers/{p['id']}", json={"enabled": True}).status_code == 200
    r = client.patch(f"/api/ai/providers/{p['id']}", json={"models": ["gpt-x", "gpt-y"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "prices_required"
    assert client.patch(f"/api/ai/providers/{p['id']}", json={"bogus": 1}).status_code == 422


def test_routing_falls_back_and_logs_both_attempts(client, db, fake, clean_ai):
    anth = setup_provider(client, "anthropic_api", "claude-opus-5-5", secret="ai.test_anthropic")
    oai = setup_provider(client, "openai_api", "gpt-x", secret="ai.test_openai")
    route(client, "classification", anth, "claude-opus-5-5", oai, "gpt-x")
    fake.answers += [(429, {"error": {"type": "rate_limit_error"}}), ok({"items": [{"name": "Pump", "quantity": 2}]})]
    out = run(db)
    assert out.data == {"items": [{"name": "Pump", "quantity": 2}]}
    first, second = out.attempts
    assert (first.status, first.provider_kind, second.status, second.provider_kind) == ("error", "anthropic_api", "ok", "openai_api")
    assert second.fallback_of_id == first.id and second.attempt == 2
    assert second.cost_usd == Decimal("0.008100")        # (1200 × 3 + 300 × 15) per million
    assert "rate_limit" in first.error


def test_cap_estimate_warnings_and_cap_reached_with_local_tasks_continuing(client, db, fake, clean_ai):
    anth = setup_provider(client, "anthropic_api", "claude-opus-5-5", price=("4", "20"), secret="ai.test_anthropic")
    local = setup_provider(client, "ollama", "qwen2.5", price=None)
    route(client, "classification", anth, "claude-opus-5-5")
    client.patch("/api/settings", json={"ai.monthly_cap_usd": 0.5})
    # spend about 0.42 USD (50 % and 80 % warnings)
    db.execute(text("INSERT INTO ai.call (task, status, cost_usd, provider_kind) VALUES ('classification', 'ok', 0.42, 'anthropic_api')"))
    db.commit()
    u = client.get("/api/ai/usage").json()
    assert u["warning"] == 80 and u["reached"] is False and Decimal(u["spent_usd"]) == Decimal("0.42")
    # the next call's estimate (4096 output tokens × 20 / M ≈ 0.08) does not fit -> 409, nothing sent
    before = len(fake.requests)
    from app.core.errors import AppError

    with pytest.raises(AppError) as exc:
        run(db)
    assert exc.value.code == "ai_cap_reached" and exc.value.status == 409
    assert len(fake.requests) == before
    assert db.execute(text("SELECT status FROM ai.call ORDER BY created_at DESC LIMIT 1")).scalar() == "cap_reached"
    # a local task continues
    route(client, "classification", local, "qwen2.5", privacy="local_only")
    fake.answers.append(ok({"items": []}))
    assert run(db).call.provider_kind == "ollama"
    # cap 0 disables the API fallback altogether
    client.patch("/api/settings", json={"ai.monthly_cap_usd": 0})
    assert client.get("/api/ai/usage").json()["api_fallback_enabled"] is False
    cc = client.get("/api/command-center").json()
    assert cc["ai"]["api_fallback_enabled"] is False


def test_redaction_round_trip_and_local_only_cases(client, db, fake, clean_ai):
    from app.core.errors import AppError
    from app.modules.ai import service

    anth = setup_provider(client, "anthropic_api", "claude-opus-5-5", secret="ai.test_anthropic")
    route(client, "classification", anth, "claude-opus-5-5", privacy="cloud_redacted")
    party = make_party(client, name_en=f"Shanghai Valve {tag()}", roles=["supplier"])
    case = client.post("/api/cases", json={"title": f"AI {tag()}", "party_id": party["id"]}).json()
    note = f"From {party['name_en']}, ali@valve.cn, +86 21 5555 0101: {party['name_en']} offers 2 pumps"
    fake.answers.append(lambda request: httpx.Response(200, json=_ok_body(request, json.dumps(
        {"items": [{"name": "Pump from " + _placeholder(request), "quantity": 2}]}))))
    out = run(db, text_=note, case_id=uuid.UUID(case["id"]))
    sent = json.dumps(fake.last, ensure_ascii=False)
    assert party["name_en"] not in sent and "ali@valve.cn" not in sent and "⟦PARTY_1⟧" in sent and "⟦EMAIL_1⟧" in sent
    assert out.data["items"][0]["name"] == f"Pump from {party['name_en']}"     # restored in the result
    assert out.call.redactions == {"PARTY": 1, "EMAIL": 1, "PHONE": 1}
    # «فقط محلی»: the cloud route is skipped and nothing is sent
    assert client.put(f"/api/ai/cases/{case['id']}/privacy", json={"local_only": True}).json()["local_only"] is True
    before = len(fake.requests)
    with pytest.raises(AppError) as exc:
        run(db, case_id=uuid.UUID(case["id"]))
    assert exc.value.code == "ai_local_only" and len(fake.requests) == before
    assert service.case_local_only(db, uuid.UUID(case["id"]))


def _placeholder(request) -> str:
    body = request.content.decode()
    return "⟦PARTY_1⟧" if "⟦PARTY_1⟧" in body else "?"


def test_the_privacy_log_never_holds_the_content(client, db, fake, clean_ai):
    anth = setup_provider(client, "anthropic_api", "claude-opus-5-5", secret="ai.test_anthropic")
    route(client, "classification", anth, "claude-opus-5-5")
    fake.answers.append(ok({"items": []}))
    out = run(db, text_=SECRET_TEXT * 3, input_desc={"files": ["spec.pdf"], "pages": 2})
    row = db.execute(text("SELECT row_to_json(c)::text FROM ai.call c WHERE id = :i"), {"i": out.call.id}).scalar()
    assert SECRET_TEXT not in row and "CONFIDENTIAL" not in row
    assert out.call.input == {"characters": len(SECRET_TEXT) * 3, "images": 0, "files": ["spec.pdf"], "pages": 2}
    audit = db.execute(text("SELECT count(*) FROM core.audit WHERE table_name = 'ai.call' AND row_id = :i"),
                       {"i": str(out.call.id)}).scalar()
    assert audit >= 1
    listed = client.get("/api/ai/calls", params={"task": "classification"}).json()
    assert listed["items"][0]["prompt_version"] == "generic/v1" and SECRET_TEXT not in json.dumps(listed)


def test_schema_validation_retries_once_then_fails(client, db, fake, clean_ai):
    from app.core.errors import AppError

    anth = setup_provider(client, "anthropic_api", "claude-opus-5-5", secret="ai.test_anthropic")
    route(client, "classification", anth, "claude-opus-5-5")
    fake.answers += [ok("not json at all"), ok({"items": [{"name": "Pump", "quantity": 2}]})]
    out = run(db)
    assert out.data["items"][0]["quantity"] == 2
    assert "Your previous answer was not valid" in fake.last["messages"][0]["content"][-1]["text"]
    assert out.call.tokens_in == 2400                       # both attempts counted
    fake.answers += [ok({"items": [{"name": 5}]}), ok({"wrong": True})]
    with pytest.raises(AppError) as exc:
        run(db)
    assert exc.value.code == "ai_failed"
    last = db.execute(text("SELECT status, error FROM ai.call ORDER BY created_at DESC LIMIT 1")).one()
    assert last.status == "invalid_output" and "required" in last.error


def test_test_connection_and_no_provider_configured(client, db, fake, clean_ai):
    from app.core.errors import AppError

    p = providers(client)["anthropic_api"]
    r = client.post("/api/ai/providers/" + p["id"] + "/test").json()
    assert r["status"] == "error" and "not_configured" in r["detail"]
    with pytest.raises(AppError) as exc:
        run(db)
    assert exc.value.code == "ai_not_configured"
    anth = setup_provider(client, "anthropic_api", "claude-opus-5-5", secret="ai.test_anthropic")
    fake.answers.append(ok("OK"))
    r = client.post(f"/api/ai/providers/{anth['id']}/test").json()
    assert r["status"] == "ok" and r["latency_ms"] is not None
    assert providers(client)["anthropic_api"]["status"] == "ok"
    assert providers(client)["anthropic_api"]["has_key"] is True
    key = client.put(f"/api/ai/providers/{anth['id']}/key", json={"value": "sk-ant-xxxxxxxx"})
    assert key.status_code == 409 and key.json()["error"]["code"] == "credential_store_unavailable"


# ---- drafts ---------------------------------------------------------------------------------------------------------

def test_drafts_accept_edit_reject_commit_and_corrections(client, db, fake, clean_ai):
    from app.modules.ai import drafts, tasks

    written = []

    def committer(db_, draft, values, source, actor):
        written.append((values, source))
        return {"created": len(values)}

    drafts.register_committer("test_target", committer)

    def build(db_, draft, payload, job_id):
        drafts.fill(db_, draft, [
            {"path": "items[0].name", "label": "Name", "value": "Pump", "confidence": "high", "source": {"page": 1}},
            {"path": "items[0].quantity", "label": "Qty", "value": 2, "confidence": "high", "source": {"page": 1}},
            {"path": "items[0].unit", "label": "Unit", "value": "pcs", "confidence": "low", "source": {"page": 1}},
        ])

    tasks.register("test_task", "classification", build)
    local = setup_provider(client, "ollama", "qwen2.5", price=None)
    draft = tasks.start(db, "test_task", target_type="test_target", target_id="x1")
    db.commit()
    job = db.execute(text("SELECT lane, type FROM sys.job WHERE id = :i"), {"i": draft.job_id}).one()
    assert tuple(job) == ("ai", "ai.task")
    assert client.get(f"/api/ai/drafts/{draft.id}").json()["status"] == "pending"
    tasks.run_job(db, {"task": "test_task", "draft_id": str(draft.id)})
    db.commit()
    d = client.get(f"/api/ai/drafts/{draft.id}").json()
    assert d["status"] == "ready" and [f["confidence"] for f in d["fields"]] == ["high", "high", "low"]
    assert written == []                                           # nothing written before «ثبت»
    r = client.post(f"/api/ai/drafts/{draft.id}/accept-confident").json()
    assert r["accepted"] == 2
    unit = d["fields"][2]["id"]
    client.patch(f"/api/ai/drafts/{draft.id}/fields/{unit}", json={"decision": "edited", "value": "set"})
    assert written == []
    r = client.post(f"/api/ai/drafts/{draft.id}/commit")
    assert r.status_code == 200, r.text
    assert written == [({"items[0].name": "Pump", "items[0].quantity": 2, "items[0].unit": "set"}, "ai_draft")]
    assert r.json()["status"] == "accepted" and r.json()["result"] == {"created": 3}
    assert "items[].unit" in drafts.examples(db, "test_task") and '"set"' in drafts.examples(db, "test_task")
    assert client.post(f"/api/ai/drafts/{draft.id}/commit").json()["error"]["code"] == "draft_not_open"
    # a second draft: reject; a third: nothing accepted -> 422
    other = tasks.start(db, "test_task", target_type="test_target", target_id="x2")
    tasks.run_job(db, {"task": "test_task", "draft_id": str(other.id)})
    db.commit()
    third = tasks.start(db, "test_task", target_type="test_target", target_id="x2")   # supersedes the open one
    db.commit()
    assert client.get(f"/api/ai/drafts/{other.id}").json()["status"] == "superseded"
    tasks.run_job(db, {"task": "test_task", "draft_id": str(third.id)})
    db.commit()
    assert client.post(f"/api/ai/drafts/{third.id}/commit").json()["error"]["code"] == "nothing_accepted"
    assert client.post(f"/api/ai/drafts/{third.id}/reject").json()["status"] == "rejected"
    ev = db.execute(text("SELECT action FROM core.event WHERE entity_type = 'ai_draft' AND entity_id = :i ORDER BY id"),
                    {"i": str(draft.id)}).scalars().all()
    assert ev == ["create", "commit"]
    assert local["enabled"]


def test_case_cascade_removes_drafts_and_privacy(client, db, clean_ai):
    from app.modules.ai import drafts

    case = client.post("/api/cases", json={"title": f"Cascade {tag()}"}).json()
    client.put(f"/api/ai/cases/{case['id']}/privacy", json={"local_only": True})
    drafts.create(db, task="t", target_type="case", target_id=case["id"], case_id=uuid.UUID(case["id"]))
    db.commit()
    r = client.request("DELETE", f"/api/cases/{case['id']}", params={"cascade": "true"}, json={"confirm_title": case["title"]})
    assert r.status_code in (200, 204), r.text
    left = db.execute(text("SELECT (SELECT count(*) FROM ai.draft WHERE case_id = :c) + "
                           "(SELECT count(*) FROM ai.case_setting WHERE case_id = :c)"), {"c": case["id"]}).scalar()
    assert left == 0


def test_migration_0019_down_up_keeps_the_owner_setup():
    from alembic import command
    from sqlalchemy import create_engine

    from app.cli import alembic_config
    from app.core.config import get_config
    from tests.conftest import create_empty_database

    name = "boms_test_v090_ai_migration"
    create_empty_database(name)
    url = get_config().db_url(name)
    cfg = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            conn.execute(text("UPDATE ai.provider SET models = '{claude-opus-5-5}', enabled = true, "
                              "secret_name = 'ai.mine' WHERE kind = 'anthropic_api'"))
            conn.execute(text("INSERT INTO ai.price (provider_id, model, input_per_mtok, output_per_mtok) "
                              "SELECT id, 'claude-opus-5-5', 4, 20 FROM ai.provider WHERE kind = 'anthropic_api'"))
            conn.execute(text("UPDATE ai.route SET privacy = 'cloud' WHERE task = 'drafting'"))
            conn.execute(text("INSERT INTO ai.correction (task, field, proposed, final) VALUES ('extraction', 'items[].unit', "
                              "'\"pcs\"', '\"set\"')"))
        command.downgrade(cfg, "0018")
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            p = conn.execute(text("SELECT enabled, models, secret_name FROM ai.provider WHERE kind = 'anthropic_api'")).one()
            assert p.enabled is True and p.models == ["claude-opus-5-5"] and p.secret_name == "ai.mine"
            assert conn.execute(text("SELECT input_per_mtok FROM ai.price")).scalar() == 4
            assert conn.execute(text("SELECT privacy FROM ai.route WHERE task = 'drafting'")).scalar() == "cloud"
            assert conn.execute(text("SELECT final FROM ai.correction")).scalar() == "set"
    finally:
        engine.dispose()
