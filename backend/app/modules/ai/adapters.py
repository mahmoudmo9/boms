"""Provider adapters behind one interface: ``adapter.generate(request) -> Result`` (v0.9.0 section 1.1).

- claude_subscription: the Claude Agent SDK driving the Claude Code CLI signed in with the owner's Claude plan. The
  only tool is Read, limited to a per-call temporary folder holding only that call's inputs; no shell, write or web.
- anthropic_api / openai_api / gemini_api: their official REST endpoints through httpx (no vendor SDKs).
- ollama / openai_compatible: local or self-hosted REST endpoints.

Every HTTP adapter uses ``http_client()``, whose transport tests replace with a fake (``set_transport``): the tests never
contact a network host. Errors are mapped to ``ProviderError(kind)`` so routing can decide on a fallback."""
import base64
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

TIMEOUT = httpx.Timeout(120.0, connect=10.0)
_TRANSPORT: httpx.BaseTransport | None = None
DEFAULT_URLS = {"anthropic_api": "https://api.anthropic.com", "openai_api": "https://api.openai.com",
                "gemini_api": "https://generativelanguage.googleapis.com", "ollama": "http://127.0.0.1:11434"}
LOCAL_KINDS = {"ollama", "openai_compatible"}
API_KINDS = {"anthropic_api", "openai_api", "gemini_api"}


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests: route every adapter request to a fake transport."""
    global _TRANSPORT
    _TRANSPORT = transport


def http_client() -> httpx.Client:
    return httpx.Client(transport=_TRANSPORT, timeout=TIMEOUT, trust_env=_TRANSPORT is None)


class ProviderError(Exception):
    """``kind``: timeout, rate_limit, quota, auth, unavailable, bad_request, server, not_configured."""

    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status

    @property
    def may_fall_back(self) -> bool:
        return self.kind in ("timeout", "rate_limit", "quota", "unavailable", "server", "auth", "not_configured")


@dataclass
class Attachment:
    name: str
    mime: str
    data: bytes


@dataclass
class Request:
    task: str
    model: str
    system: str
    text: str                                   # the user message (already redacted when required)
    images: list[Attachment] = field(default_factory=list)
    schema: dict | None = None
    max_tokens: int = 4096


@dataclass
class Result:
    text: str
    data: Any = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    duration_ms: int = 0
    subscription: bool = False


def _status_error(resp: httpx.Response) -> ProviderError:
    code = resp.status_code
    try:
        body = resp.json()
        message = json.dumps(body.get("error", body), ensure_ascii=False)[:500]
    except ValueError:
        message = resp.text[:500]
    if code in (401, 403):
        return ProviderError("auth", message, code)
    if code == 429:
        return ProviderError("rate_limit", message, code)
    if code == 402:
        return ProviderError("quota", message, code)
    if code in (400, 404, 413, 422):
        return ProviderError("bad_request", message, code)
    return ProviderError("server" if code >= 500 else "bad_request", message, code)


def _post(url: str, headers: dict, body: dict) -> dict:
    try:
        with http_client() as client:
            resp = client.post(url, headers=headers, json=body)
    except httpx.TimeoutException as exc:
        raise ProviderError("timeout", str(exc) or "timeout") from None
    except httpx.HTTPError as exc:
        raise ProviderError("unavailable", str(exc) or type(exc).__name__) from None
    if resp.status_code >= 400:
        raise _status_error(resp)
    try:
        return resp.json()
    except ValueError:
        raise ProviderError("server", "the provider did not return JSON") from None


def _instructions(req: Request) -> str:
    if not req.schema:
        return req.system
    return (req.system + "\n\nAnswer with one JSON object only (no prose, no code fence) that validates against this "
            "JSON schema:\n" + json.dumps(req.schema, ensure_ascii=False))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class Adapter:
    kind = ""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or DEFAULT_URLS.get(self.kind) or "").rstrip("/")
        self.api_key = api_key

    def generate(self, req: Request) -> Result:  # pragma: no cover - interface
        raise NotImplementedError

    def _need_key(self) -> None:
        if not self.api_key:
            raise ProviderError("not_configured", "no API key in Credential Manager for this provider")


class AnthropicAPI(Adapter):
    kind = "anthropic_api"
    VERSION = "2026-10-21"          # the Messages API version header

    def generate(self, req: Request) -> Result:
        self._need_key()
        content: list[dict] = [{"type": "image", "source": {"type": "base64", "media_type": a.mime, "data": _b64(a.data)}}
                               for a in req.images]
        content.append({"type": "text", "text": req.text})
        payload: dict = {"model": req.model, "max_tokens": req.max_tokens, "system": _instructions(req),
                         "messages": [{"role": "user", "content": content}]}
        if req.schema:   # structured outputs; the answer is still validated by BOMS
            payload["output_config"] = {"format": {"type": "json_schema", "schema": req.schema}}
        start = time.monotonic()
        body = _post(f"{self.base_url}/v1/messages",
                     {"x-api-key": self.api_key, "anthropic-version": self.VERSION, "content-type": "application/json"},
                     payload)
        if body.get("stop_reason") == "refusal":
            raise ProviderError("bad_request", "the model declined the request")
        text = "".join(part.get("text", "") for part in body.get("content", []) if part.get("type") == "text")
        usage = body.get("usage") or {}
        return Result(text, tokens_in=usage.get("input_tokens"), tokens_out=usage.get("output_tokens"),
                      duration_ms=int((time.monotonic() - start) * 1000))


class OpenAIAPI(Adapter):
    kind = "openai_api"

    def _headers(self) -> dict:
        return {"authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def generate(self, req: Request) -> Result:
        if self.kind == "openai_api":
            self._need_key()
        content: list[dict] = [{"type": "text", "text": req.text}]
        content += [{"type": "image_url", "image_url": {"url": f"data:{a.mime};base64,{_b64(a.data)}"}} for a in req.images]
        payload: dict = {"model": req.model, "max_tokens": req.max_tokens,
                         "messages": [{"role": "system", "content": _instructions(req)},
                                      {"role": "user", "content": content}]}
        if req.schema:
            payload["response_format"] = {"type": "json_object"}
        start = time.monotonic()
        body = _post(f"{self.base_url}/v1/chat/completions", self._headers(), payload)
        choice = (body.get("choices") or [{}])[0]
        usage = body.get("usage") or {}
        return Result((choice.get("message") or {}).get("content") or "", tokens_in=usage.get("prompt_tokens"),
                      tokens_out=usage.get("completion_tokens"), duration_ms=int((time.monotonic() - start) * 1000))


class OpenAICompatible(OpenAIAPI):
    kind = "openai_compatible"


class GeminiAPI(Adapter):
    kind = "gemini_api"

    def generate(self, req: Request) -> Result:
        self._need_key()
        parts: list[dict] = [{"text": req.text}]
        parts += [{"inline_data": {"mime_type": a.mime, "data": _b64(a.data)}} for a in req.images]
        config: dict = {"maxOutputTokens": req.max_tokens}
        if req.schema:
            config["responseMimeType"] = "application/json"
        start = time.monotonic()
        body = _post(f"{self.base_url}/v1beta/models/{req.model}:generateContent",
                     {"x-goog-api-key": self.api_key},
                     {"systemInstruction": {"parts": [{"text": _instructions(req)}]},
                      "contents": [{"role": "user", "parts": parts}], "generationConfig": config})
        cand = (body.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
        usage = body.get("usageMetadata") or {}
        return Result(text, tokens_in=usage.get("promptTokenCount"), tokens_out=usage.get("candidatesTokenCount"),
                      duration_ms=int((time.monotonic() - start) * 1000))


class Ollama(Adapter):
    kind = "ollama"

    def generate(self, req: Request) -> Result:
        user: dict = {"role": "user", "content": req.text}
        if req.images:
            user["images"] = [_b64(a.data) for a in req.images]
        payload: dict = {"model": req.model, "stream": False, "options": {"num_predict": req.max_tokens},
                         "messages": [{"role": "system", "content": _instructions(req)}, user]}
        if req.schema:
            payload["format"] = req.schema
        start = time.monotonic()
        body = _post(f"{self.base_url}/api/chat", {}, payload)
        return Result((body.get("message") or {}).get("content") or "", tokens_in=body.get("prompt_eval_count"),
                      tokens_out=body.get("eval_count"), duration_ms=int((time.monotonic() - start) * 1000))


# ---- Claude subscription (Claude Agent SDK) ---------------------------------------------------------------------------

READ_ONLY_TOOLS = ["Read"]
DENIED_TOOLS = ["Bash", "BashOutput", "KillShell", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch",
                "Glob", "Grep", "Task", "Agent", "TodoWrite", "Skill", "SlashCommand", "ExitPlanMode"]
_SDK_RUNNER: Callable | None = None      # tests replace the SDK call (no CLI, no network)


def set_sdk_runner(fn: Callable | None) -> None:
    global _SDK_RUNNER
    _SDK_RUNNER = fn


def cli_status() -> dict:
    """Whether the Claude Code CLI the SDK drives is present (bundled with the SDK wheel, or installed separately)."""
    try:
        import claude_agent_sdk
    except ImportError:
        return {"sdk": False, "cli": None, "steps": "install_sdk"}
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / ("claude.exe" if os.name == "nt" else "claude")
    path = str(bundled) if bundled.exists() else shutil.which("claude")
    return {"sdk": True, "sdk_version": getattr(claude_agent_sdk, "__version__", None), "cli": path,
            "steps": None if path else "install_cli"}


class ClaudeSubscription(Adapter):
    """The SDK runs in a temporary folder that holds only this call's inputs and is removed afterwards."""
    kind = "claude_subscription"

    def generate(self, req: Request) -> Result:
        folder = Path(tempfile.mkdtemp(prefix="boms-ai-"))
        try:
            names = []
            for i, a in enumerate(req.images, start=1):
                name = f"input-{i}{Path(a.name).suffix or '.bin'}"
                (folder / name).write_bytes(a.data)
                names.append(name)
            prompt = req.text
            if names:
                prompt += "\n\nInput files in the working folder (read them with the Read tool): " + ", ".join(names)
            start = time.monotonic()
            out = (_SDK_RUNNER or _run_sdk)(prompt=prompt, system=_instructions(req), model=req.model, folder=folder,
                                            schema=req.schema)
            return Result(out.get("text") or "", data=out.get("data"), tokens_in=out.get("tokens_in"),
                          tokens_out=out.get("tokens_out"), duration_ms=int((time.monotonic() - start) * 1000),
                          subscription=True)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


def _run_sdk(*, prompt: str, system: str, model: str | None, folder: Path, schema: dict | None) -> dict:
    import anyio

    try:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
    except ImportError:
        raise ProviderError("not_configured", "the Claude Agent SDK is not installed") from None

    async def deny_outside(tool_name, tool_input, _context):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        target = Path(str(tool_input.get("file_path") or tool_input.get("path") or "")).resolve()
        if tool_name in READ_ONLY_TOOLS and (target == folder.resolve() or folder.resolve() in target.parents):
            return PermissionResultAllow()
        return PermissionResultDeny(message="only the input files of this call can be read")

    options = ClaudeAgentOptions(
        tools=READ_ONLY_TOOLS, allowed_tools=[], disallowed_tools=DENIED_TOOLS, can_use_tool=deny_outside,
        cwd=str(folder), system_prompt=system, model=model or None, max_turns=4, setting_sources=[],
        output_format={"type": "json_schema", "schema": schema} if schema else None)

    async def run() -> dict:
        result: dict = {}
        async def prompts():
            yield {"type": "user", "message": {"role": "user", "content": prompt}}
        async for message in query(prompt=prompts(), options=options):
            if isinstance(message, ResultMessage):
                if message.is_error:
                    text = " ".join(message.errors or []) or (message.result or "error")
                    kind = "quota" if "limit" in text.lower() else "server"
                    raise ProviderError(kind, text[:500])
                usage = message.usage or {}
                result = {"text": message.result or "", "data": message.structured_output,
                          "tokens_in": usage.get("input_tokens"), "tokens_out": usage.get("output_tokens")}
        return result

    try:
        return anyio.run(run)
    except ProviderError:
        raise
    except Exception as exc:   # CLI missing, not signed in, process failure
        text = str(exc)
        kind = "not_configured" if "not found" in text.lower() or "login" in text.lower() else "unavailable"
        raise ProviderError(kind, text[:500]) from None


ADAPTERS = {cls.kind: cls for cls in (AnthropicAPI, OpenAIAPI, OpenAICompatible, GeminiAPI, Ollama, ClaudeSubscription)}


def for_provider(kind: str, base_url: str | None, api_key: str | None) -> Adapter:
    return ADAPTERS[kind](base_url, api_key)
