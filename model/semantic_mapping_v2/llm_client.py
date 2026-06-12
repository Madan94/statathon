"""LLM client for Semantic V2 — Gemini primary, Groq fallback."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

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


def _groq_model() -> str:
    return os.getenv("GROQ_MODEL") or os.getenv("SCRIBE_MODEL") or "llama-3.1-8b-instant"


def _gemini_model() -> str:
    return os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash")


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
    """Return parsed JSON from Gemini; on failure retry with Groq."""
    raw = generate_text(prompt, system=system)
    if not raw:
        raise RuntimeError("LLM returned empty response")
    return json.loads(strip_json_fence(raw))


def generate_text(prompt: str, *, system: str = "") -> str:
    """Gemini first, Groq fallback (or Groq first if SEMV2_LLM_PRIMARY=groq)."""
    errors: list[str] = []
    primary = (os.getenv("SEMV2_LLM_PRIMARY", "gemini") or "gemini").lower()

    def _try_gemini() -> str:
        gkey = _gemini_key()
        if not gkey:
            raise RuntimeError("GEMINI_API_KEY not set")
        return _call_gemini(prompt, system=system, api_key=gkey)

    def _try_groq() -> str:
        gqkey = _groq_key()
        if not gqkey:
            raise RuntimeError("GROQ_API_KEY not set")
        return _call_groq(prompt, system=system, api_key=gqkey)

    order = (_try_groq, _try_gemini) if primary == "groq" else (_try_gemini, _try_groq)
    names = ("groq", "gemini") if primary == "groq" else ("gemini", "groq")

    for fn, name in zip(order, names):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            logger.warning("%s LLM failed, trying fallback: %s", name, exc)

    raise RuntimeError("; ".join(errors) or "No LLM API key configured (GEMINI_API_KEY or GROQ_API_KEY)")


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
    import urllib.error
    import urllib.request

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
                    break  # retry without json_mode
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


def llm_status() -> dict[str, Any]:
    """Non-secret summary for test reports."""
    return {
        "gemini_configured": bool(_gemini_key()),
        "groq_configured": bool(_groq_key()),
        "gemini_model": _gemini_model(),
        "groq_model": _groq_model(),
    }
