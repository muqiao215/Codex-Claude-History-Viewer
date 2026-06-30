"""OpenAI-compatible LLM client (stdlib only — urllib.request).

Works with any provider that speaks the ``/v1/chat/completions`` schema:
OpenAI, DeepSeek, ollama, OpenRouter, LM Studio, vLLM, Zhipu GLM, etc.

Provider is resolved from CLI flags (highest priority) then env vars, then a
local-ollama fallback. No provider is wired unless explicitly configured.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from urllib import error, request

DEFAULT_TIMEOUT = 60
DEFAULT_OLLAMA_BASE = "http://localhost:11434/v1"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"


class LLMError(Exception):
    """Raised when the LLM call fails (network, HTTP, or response shape)."""


def detect_provider(
    *,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve an LLM config from explicit args > env > ollama fallback.

    Returns ``None`` when no provider can be reached (no key + ollama down).
    Callers fall back to the heuristic path in that case.
    """
    if base_url and model:
        return {
            "base_url": base_url.rstrip("/"),
            "model": model,
            "api_key": api_key,
        }

    env_map = (
        ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o-mini"),
        ("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek-chat"),
    )
    for var, url, default_model in env_map:
        key = os.environ.get(var, "").strip()
        if key:
            return {
                "base_url": (base_url or url).rstrip("/"),
                "model": model or default_model,
                "api_key": key,
            }

    # Ollama local fallback — only if reachable.
    if base_url or _ollama_reachable():
        return {
            "base_url": (base_url or DEFAULT_OLLAMA_BASE).rstrip("/"),
            "model": model or DEFAULT_OLLAMA_MODEL,
            "api_key": api_key or "ollama",
        }
    return None


def _ollama_reachable(timeout: float = 1.5) -> bool:
    try:
        req = request.Request(f"{DEFAULT_OLLAMA_BASE.rsplit('/', 1)[0]}/api/tags", method="GET")
        request.urlopen(req, timeout=timeout).close()
        return True
    except Exception:
        return False


def call_chat_completions(
    config: Dict[str, Any],
    messages: List[Dict[str, str]],
    *,
    timeout: int = DEFAULT_TIMEOUT,
    temperature: float = 0.2,
    json_mode: bool = True,
) -> str:
    """POST to ``{base_url}/chat/completions`` and return the assistant content.

    Raises :class:`LLMError` on any failure (network, HTTP status, bad shape).
    """
    base_url = str(config.get("base_url") or "").rstrip("/")
    model = str(config.get("model") or "")
    api_key = config.get("api_key")
    if not base_url or not model:
        raise LLMError("incomplete LLM config: base_url and model required")

    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{base_url}/chat/completions"
    payload = json.dumps(body).encode("utf-8")
    req = request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise LLMError(f"LLM HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise LLMError(f"LLM connection failed: {exc.reason}") from exc
    except Exception as exc:
        raise LLMError(f"LLM call failed: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"LLM returned non-JSON body: {raw[:200]!r}") from exc

    choices = data.get("choices") or []
    if not choices or not isinstance(choices, list):
        raise LLMError("LLM response missing choices[]")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if not content or not isinstance(content, str):
        raise LLMError("LLM response missing message.content")
    return content
