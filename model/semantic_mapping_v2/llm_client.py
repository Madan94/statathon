"""LLM client for Semantic V2 — OpenRouter primary, Gemini/Groq fallback."""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable

logger = logging.getLogger(__name__)

_RETRIABLE = (
    "429",
    "413",
    "resource exhausted",
    "quota",
    "rate limit",
    "tokens per minute",
    "request too large",
    "503",
    "unavailable",
    "deadline",
    "timeout",
)


def _gemini_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _groq_key() -> str | None:
    return (
        os.getenv("GROQ_API_KEY")
        or os.getenv("SCRIBE_API_KEY")
        or os.getenv("DEFAULT_LLM_API_KEY")
    )


def _openrouter_base_url() -> str:
    return (
        os.getenv("OPENROUTER_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://openrouter.ai/api/v1"
    ).rstrip("/")


def _openrouter_key() -> str | None:
    explicit = os.getenv("OPENROUTER_API_KEY")
    if explicit:
        return explicit
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        return None
    base = _openrouter_base_url().lower()
    if "openrouter" in base or os.getenv("SEMV2_USE_OPENROUTER", "").lower() in ("1", "true", "yes"):
        return openai_key
    return None


def llm_configured() -> bool:
    """True when any Semantic V2 LLM backend has credentials."""
    return bool(_openrouter_key() or _gemini_key() or _groq_key())


def _groq_model() -> str:
    return os.getenv("GROQ_MODEL") or os.getenv("SCRIBE_MODEL") or "llama-3.1-8b-instant"


def _gemini_model() -> str:
    return os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash")


def _openrouter_model() -> str:
    return (
        os.getenv("SEMV2_OPENROUTER_MODEL")
        or os.getenv("OPENROUTER_MODEL")
        or os.getenv("OPENAI_MODEL")
        or "google/gemini-2.5-flash"
    )


def _is_retriable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(tok in msg for tok in _RETRIABLE)


def _retry_seconds(exc: Exception, default: float = 10.0) -> float:
    text = str(exc)
    for pattern in (
        r"retry in (\d+(?:\.\d+)?)s",
        r"try again in (\d+(?:\.\d+)?)s",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            return min(float(m.group(1)) + 1.0, 65.0)
    return default


def strip_json_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def generate_json(prompt: str, *, system: str = "") -> Any:
    """Return parsed JSON from the configured LLM chain."""
    raw = generate_text(prompt, system=system)
    if not raw:
        raise RuntimeError("LLM returned empty response")
    return json.loads(strip_json_fence(raw))


def generate_text(prompt: str, *, system: str = "") -> str:
    """OpenRouter first (when configured), then Gemini, then Groq."""
    errors: list[str] = []
    primary = (os.getenv("SEMV2_LLM_PRIMARY", "openrouter") or "openrouter").lower()

    providers: list[tuple[str, Callable[[], str]]] = [
        ("openrouter", lambda: _call_openrouter(prompt, system=system, api_key=_openrouter_key() or "")),
        ("gemini", lambda: _call_gemini(prompt, system=system, api_key=_gemini_key() or "")),
        ("groq", lambda: _call_groq(prompt, system=system, api_key=_groq_key() or "")),
    ]
    by_name = {name: fn for name, fn in providers}

    order_names: list[str]
    if primary in by_name:
        order_names = [primary] + [n for n in by_name if n != primary]
    else:
        order_names = ["openrouter", "gemini", "groq"]

    for name in order_names:
        fn = by_name[name]
        if name == "openrouter" and not _openrouter_key():
            continue
        if name == "gemini" and not _gemini_key():
            continue
        if name == "groq" and not _groq_key():
            continue
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            logger.warning("%s LLM failed, trying fallback: %s", name, exc)

    raise RuntimeError(
        "; ".join(errors)
        or "No LLM API key configured (OPENROUTER/OPENAI, GEMINI_API_KEY, or GROQ_API_KEY)"
    )


def _call_openrouter(prompt: str, *, system: str, api_key: str) -> str:
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY / OPENAI_API_KEY not set")

    model = _openrouter_model()
    base = _openrouter_base_url()
    timeout = int(os.getenv("OPENROUTER_REQUEST_TIMEOUT_SEC", os.getenv("OPENAI_TIMEOUT", "120")))
    retries = int(os.getenv("OPENROUTER_LLM_MAX_RETRIES", "3"))
    delay = float(os.getenv("OPENROUTER_LLM_RETRY_BASE", "4"))

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    referer = os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost:3000")
    title = os.getenv("OPENROUTER_APP_TITLE", "Statathon Semantic V2")

    last: Exception | None = None
    for json_mode in (True, False):
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": float(os.getenv("SEMV2_LLM_TEMPERATURE", "0.1")),
            "max_tokens": int(os.getenv("SEMV2_LLM_MAX_TOKENS", os.getenv("OPENAI_MAX_TOKENS", "4096"))),
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": referer,
                "X-Title": title,
                "User-Agent": "statathon-semantic-v2/1.0",
                "Accept": "application/json",
            },
            method="POST",
        )
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                text = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                if text:
                    return text
                raise RuntimeError("empty OpenRouter response")
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")[:400]
                last = RuntimeError(f"OpenRouter HTTP {exc.code}: {err_body}")
                if exc.code in (400, 403, 422) and json_mode:
                    break
                if _is_retriable(str(exc)) and attempt < retries - 1:
                    time.sleep(_retry_seconds(exc, delay))
                    delay = min(delay * 1.5, 45)
                    continue
                raise last from exc
            except Exception as exc:
                last = exc
                if _is_retriable(exc) and attempt < retries - 1:
                    time.sleep(_retry_seconds(exc, delay))
                    delay = min(delay * 1.5, 45)
                    continue
                if json_mode:
                    break
                raise
    raise last or RuntimeError("OpenRouter failed")


def _call_gemini(prompt: str, *, system: str, api_key: str) -> str:
    import google.generativeai as genai

    timeout = int(os.getenv("GEMINI_REQUEST_TIMEOUT_SEC", "90"))
    retries = int(os.getenv("GEMINI_LLM_MAX_RETRIES", "3"))
    delay = float(os.getenv("GEMINI_LLM_RETRY_BASE", "8"))
    model_name = _gemini_model()

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = model.generate_content(
                full_prompt,
                request_options={"timeout": timeout},
            )
            text = (resp.text or "").strip()
            if text:
                return text
            raise RuntimeError("empty Gemini response")
        except Exception as exc:
            last = exc
            if _is_retriable(exc) and attempt < retries - 1:
                time.sleep(_retry_seconds(exc, delay))
                delay = min(delay * 1.5, 60)
                continue
            raise
    raise last or RuntimeError("Gemini failed")


def _call_groq(prompt: str, *, system: str, api_key: str) -> str:
    model = _groq_model()
    timeout = int(os.getenv("GROQ_REQUEST_TIMEOUT_SEC", "90"))
    retries = int(os.getenv("GROQ_LLM_MAX_RETRIES", "3"))
    delay = float(os.getenv("GROQ_LLM_RETRY_BASE", "4"))

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last: Exception | None = None
    for json_mode in (True, False):
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": int(os.getenv("GROQ_MAX_TOKENS", "4096")),
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "statathon-semantic-v2/1.0",
                "Accept": "application/json",
            },
            method="POST",
        )
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                text = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                if text:
                    return text
                raise RuntimeError("empty Groq response")
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")[:300]
                last = RuntimeError(f"Groq HTTP {exc.code}: {err_body}")
                if exc.code in (400, 403, 422) and json_mode:
                    break
                if _is_retriable(str(exc)) and attempt < retries - 1:
                    time.sleep(delay)
                    delay = min(delay * 1.5, 45)
                    continue
                raise last from exc
            except Exception as exc:
                last = exc
                if _is_retriable(exc) and attempt < retries - 1:
                    time.sleep(delay)
                    delay = min(delay * 1.5, 45)
                    continue
                if json_mode:
                    break
                raise
    raise last or RuntimeError("Groq failed")


def resolve_llm_provider() -> str:
    """Non-secret label for pipeline meta (openrouter | gemini | groq | none)."""
    if not llm_configured():
        return "none"
    primary = (os.getenv("SEMV2_LLM_PRIMARY", "openrouter") or "openrouter").lower()
    if primary == "openrouter" and _openrouter_key():
        return "openrouter"
    if primary == "groq" and _groq_key():
        return "groq"
    if primary == "gemini" and _gemini_key():
        return "gemini"
    if _openrouter_key():
        return "openrouter"
    if _gemini_key():
        return "gemini"
    if _groq_key():
        return "groq"
    return "none"


def llm_status() -> dict[str, Any]:
    """Non-secret summary for test reports."""
    return {
        "openrouter_configured": bool(_openrouter_key()),
        "gemini_configured": bool(_gemini_key()),
        "groq_configured": bool(_groq_key()),
        "primary": os.getenv("SEMV2_LLM_PRIMARY", "openrouter"),
        "openrouter_model": _openrouter_model(),
        "gemini_model": _gemini_model(),
        "groq_model": _groq_model(),
        "resolved_provider": resolve_llm_provider(),
    }
