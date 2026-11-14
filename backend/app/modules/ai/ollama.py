"""v0.10.1 section 0.1: Ollama.

Ollama can serve cloud models through its local address (``http://127.0.0.1:11434``): models named ``…:cloud`` or
``…-cloud`` run on ollama.com after ``ollama signin``. A local address is therefore not enough to call a model local.
The rule here is fail-safe — a model is local only when BOMS can show it is:

- the endpoint is loopback or private (``service.endpoint_is_local``), AND
- the name has no ``cloud`` tag or suffix, AND
- (Ollama) the provider's own model list (``/api/tags``, cached in ``provider.model_info``) lists the model without a
  remote host or remote model.

A model the list does not mention, or a list that cannot be read, counts as cloud: redacted, never given ``local_only``
work, labelled «ابری».

Per request BOMS sends ``options.num_ctx`` sized to the prompt (never the server default of 4096, which truncates
silently), ``think`` per route and ``keep_alive`` from the settings.
"""
import math
import re
from typing import Any

import httpx

from app.modules.ai import adapters
from app.modules.ai.adapters import ProviderError

#: tasks whose answer is short: thinking only adds time (classification, triage, tagging, the connection test)
SHORT_TASKS = {"classification", "triage", "tagging", "ping"}
CTX_STEP = 1024
CTX_MIN = 2048
IMAGE_TOKENS = 768                     # a vision model's cost of one page image, conservatively


def is_cloud_name(model: str | None) -> bool:
    """``qwen3-coder:480b-cloud``, ``gpt-oss:120b-cloud``, ``kimi-k2:cloud``, ``deepseek-cloud`` → cloud."""
    if not model:
        return True
    name, _, tag = model.strip().lower().partition(":")
    words = re.split(r"[-_.]", tag) + [name.rsplit("/", 1)[-1].rsplit("-", 1)[-1]]
    return "cloud" in words


def facts_from_tags(body: dict) -> dict[str, dict[str, Any]]:
    """``/api/tags`` → {model name: size, family, parameter size, quantization, cloud}."""
    out: dict[str, dict[str, Any]] = {}
    for m in body.get("models") or []:
        name = m.get("name") or m.get("model")
        if not name:
            continue
        details = m.get("details") or {}
        remote = bool(m.get("remote_host") or m.get("remote_model"))
        out[name] = {"size": m.get("size"), "family": details.get("family"), "parameter_size": details.get("parameter_size"),
                     "quantization": details.get("quantization_level"), "remote_host": m.get("remote_host"),
                     "cloud": remote or is_cloud_name(name)}
    return out


def _get(base_url: str, path: str) -> dict:
    try:
        with adapters.http_client() as client:
            resp = client.get(f"{base_url.rstrip('/')}{path}")
    except httpx.HTTPError as exc:
        raise ProviderError("unavailable", str(exc) or type(exc).__name__) from None
    if resp.status_code >= 400:
        raise ProviderError("unavailable", f"{path}: HTTP {resp.status_code}", resp.status_code)
    try:
        return resp.json()
    except ValueError:
        raise ProviderError("server", f"{path} did not return JSON") from None


def list_models(base_url: str) -> dict[str, dict[str, Any]]:
    return facts_from_tags(_get(base_url, "/api/tags"))


def model_is_local(model: str | None, model_info: dict | None) -> bool:
    """For a provider at a local address: local only when the cached model list shows a model that is not cloud."""
    if not model or is_cloud_name(model):
        return False
    facts = (model_info or {}).get(model)
    if facts is None and ":" not in model:                     # «qwen3.5» is listed as «qwen3.5:latest»
        facts = (model_info or {}).get(f"{model}:latest")
    return facts is not None and not facts.get("cloud", True)


def placement(base_url: str, model: str) -> dict | None:
    """Where the loaded model sits (``/api/ps``): the share of it in GPU memory. None when it is not loaded."""
    body = _get(base_url, "/api/ps")
    for m in body.get("models") or []:
        if (m.get("name") or m.get("model")) in (model, f"{model}:latest"):
            size, vram = m.get("size") or 0, m.get("size_vram") or 0
            share = round(vram / size, 3) if size else None
            return {"size": size, "size_vram": vram, "gpu_share": share, "fits": share is not None and share >= 0.999,
                    "context_length": m.get("context_length")}
    return None


def estimate_tokens(chars: int, images: int = 0) -> int:
    """A conservative estimate: Persian and mixed text run near 2.5 characters per token."""
    return math.ceil(chars / 2.5) + images * IMAGE_TOKENS


MIN_ANSWER = 1024
MARGIN = 256


def num_ctx(chars: int, images: int, answer_tokens: int, cap: int) -> tuple[int, int]:
    """The context window for one request and the answer room inside it: the prompt plus the task's answer size and a
    margin, in steps of 1,024, at most the cap. The answer gets what the cap leaves (at least 1,024 tokens); a prompt
    that cannot fit with that minimum is refused (``context_too_long``) — never sent to be cut silently."""
    prompt = estimate_tokens(chars, images)
    if prompt + MIN_ANSWER + MARGIN > cap:
        raise ProviderError("context_too_long",
                            f"the text needs about {prompt + MIN_ANSWER + MARGIN} tokens; the limit «حداکثر طول متن» is {cap}")
    size = min(cap, max(CTX_MIN, math.ceil((prompt + answer_tokens + MARGIN) / CTX_STEP) * CTX_STEP))
    return size, min(answer_tokens, size - prompt - MARGIN)


def think_for(task: str, route_think: bool | None) -> bool:
    return route_think if route_think is not None else task not in SHORT_TASKS
