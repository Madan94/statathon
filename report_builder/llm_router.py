"""Unified LLM Router for BharatStat V2 pipeline.

All LLM calls in the pipeline go through this module.
Switch providers by changing environment variables — no code changes needed.

Environment variables
---------------------
VLM_PROVIDER        Vision+text tasks (entity extraction, structure analysis, question gen)
                    Values: qwen (default) | gemini | groq
REASONING_PROVIDER  Text-only tasks (ToC extraction, gap fill, fact extraction, binding)
                    Values: qwen (default) | gemini | groq

Per-task overrides (override the provider for a specific task only):
    PROVIDER_ENTITY_EXTRACTION   (pass 2  — image+text entity extraction)
    PROVIDER_QUESTION_GENERATION (pass 3 loop 1 — image+text question gen)
    PROVIDER_ENTITY_BINDING      (pass 3 loop 2 — text-only entity binding)
    PROVIDER_TOC_EXTRACTION      (L3 hybrid ToC — text-only)
    PROVIDER_GAP_FILL            (question gap fill — text-only)
    PROVIDER_FACT_EXTRACTION     (fact extraction — text-only)
    PROVIDER_SEMANTIC_FALLBACK   (semantic fallback — text-only)

Model overrides:
    SGLANG_ENDPOINT   = http://localhost:8002  (Qwen vLLM server)
    SGLANG_MODEL      = Qwen/Qwen2.5-VL-3B-Instruct-AWQ
    SGLANG_TIMEOUT    = 120
    GEMINI_MODEL      = gemini-2.5-flash
    GEMINI_API_KEY    (or GOOGLE_API_KEY)
    GROQ_API_KEY
    GROQ_MODEL        = meta-llama/llama-4-scout-17b-16e-instruct
    GROQ_VISION_MODEL = meta-llama/llama-4-maverick-17b-128e-instruct

Quick switch examples (set on GPU laptop, no code changes):
    # Use Gemini for everything:
    VLM_PROVIDER=gemini REASONING_PROVIDER=gemini

    # Keep Qwen for vision, Gemini only for reasoning:
    VLM_PROVIDER=qwen REASONING_PROVIDER=gemini

    # Use Groq for reasoning only:
    REASONING_PROVIDER=groq

    # Override one specific task:
    PROVIDER_GAP_FILL=gemini

Usage
-----
    from report_builder.llm_router import llm_text_call, llm_vision_call

    # Text-only reasoning
    result = llm_text_call(prompt, task="gap_fill", max_tokens=800)

    # Vision + text (multimodal)
    result = llm_vision_call(prompt, image_bytes=img, task="entity_extraction", max_tokens=400)

Both return a string (the model's raw text output) or None on failure.
The caller is responsible for parsing JSON from the returned string.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ── Task → env-var mapping ─────────────────────────────────────────────────────
_TASK_TO_ENV: dict[str, str] = {
    "entity_extraction":   "PROVIDER_ENTITY_EXTRACTION",
    "question_generation": "PROVIDER_QUESTION_GENERATION",
    "entity_binding":      "PROVIDER_ENTITY_BINDING",
    "toc_extraction":      "PROVIDER_TOC_EXTRACTION",
    "gap_fill":            "PROVIDER_GAP_FILL",
    "fact_extraction":     "PROVIDER_FACT_EXTRACTION",
    "semantic_fallback":   "PROVIDER_SEMANTIC_FALLBACK",
}

_VISION_TASKS = frozenset({"entity_extraction", "question_generation"})


def _resolve_provider(task: str) -> str:
    """Determine which provider to use for a given task.

    Priority: per-task env var → VLM_PROVIDER / REASONING_PROVIDER → 'qwen'
    """
    task_env = _TASK_TO_ENV.get(task, "")
    if task_env:
        override = (os.getenv(task_env) or "").strip().lower()
        if override:
            return override

    if task in _VISION_TASKS:
        return (os.getenv("VLM_PROVIDER") or "qwen").strip().lower()
    return (os.getenv("REASONING_PROVIDER") or "qwen").strip().lower()


def _detect_image_mime(image_bytes: bytes) -> str:
    """Detect image MIME type from magic bytes (PNG or JPEG)."""
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/png"  # safe default for Qwen which prefers PNG


# ── Backend implementations ────────────────────────────────────────────────────

def _call_qwen_text(prompt: str, max_tokens: int, temperature: float) -> str | None:
    endpoint = (os.getenv("SGLANG_ENDPOINT") or "http://localhost:8002").rstrip("/") + "/v1/chat/completions"
    model = os.getenv("SGLANG_MODEL") or "Qwen/Qwen2.5-VL-3B-Instruct-AWQ"
    timeout = int(os.getenv("SGLANG_TIMEOUT") or "120")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        r = requests.post(endpoint, json=payload, timeout=timeout)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        logger.warning("[llm_router][qwen] HTTP %d: %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.warning("[llm_router][qwen] Request failed: %s", exc)
    return None


def _call_qwen_vision(prompt: str, image_bytes: bytes, max_tokens: int, temperature: float) -> str | None:
    endpoint = (os.getenv("SGLANG_ENDPOINT") or "http://localhost:8002").rstrip("/") + "/v1/chat/completions"
    model = os.getenv("SGLANG_MODEL") or "Qwen/Qwen2.5-VL-3B-Instruct-AWQ"
    timeout = int(os.getenv("SGLANG_TIMEOUT") or "120")
    mime = _detect_image_mime(image_bytes)
    img_b64 = base64.b64encode(image_bytes).decode("utf-8")
    content = [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
        {"type": "text", "text": prompt},
    ]
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        r = requests.post(endpoint, json=payload, timeout=timeout)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        logger.warning("[llm_router][qwen-vision] HTTP %d: %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.warning("[llm_router][qwen-vision] Request failed: %s", exc)
    return None


def _call_gemini(prompt: str, image_bytes: bytes | None, max_tokens: int, temperature: float) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.info("[llm_router][gemini] No API key — skipping")
        return None
    model = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
    mime = _detect_image_mime(image_bytes) if image_bytes else "image/png"
    try:
        try:
            from google import genai as _genai  # type: ignore[import]
            client = _genai.Client(api_key=api_key)
            if image_bytes:
                parts: list[Any] = [
                    _genai.types.Part.from_bytes(data=image_bytes, mime_type=mime),
                    prompt,
                ]
                resp = client.models.generate_content(
                    model=model,
                    contents=parts,
                    config=_genai.types.GenerateContentConfig(
                        max_output_tokens=max_tokens,
                        temperature=temperature,
                    ),
                )
            else:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=_genai.types.GenerateContentConfig(
                        max_output_tokens=max_tokens,
                        temperature=temperature,
                    ),
                )
            return (resp.text or "").strip() or None
        except ImportError:
            import google.generativeai as _legacy  # type: ignore[import]
            _legacy.configure(api_key=api_key)
            m = _legacy.GenerativeModel(model)
            if image_bytes:
                import io as _io
                import PIL.Image as _PIL  # type: ignore[import]
                img = _PIL.Image.open(_io.BytesIO(image_bytes))
                resp = m.generate_content([img, prompt])
            else:
                resp = m.generate_content(prompt)
            return (resp.text or "").strip() or None
    except Exception as exc:
        logger.warning("[llm_router][gemini] Call failed: %s", exc)
    return None


def _call_groq(prompt: str, image_bytes: bytes | None, max_tokens: int, temperature: float) -> str | None:
    api_key = os.getenv("GROQ_API_KEY") or ""
    if not api_key:
        logger.info("[llm_router][groq] No GROQ_API_KEY — skipping")
        return None
    if image_bytes:
        model = os.getenv("GROQ_VISION_MODEL") or "meta-llama/llama-4-maverick-17b-128e-instruct"
    else:
        model = os.getenv("GROQ_MODEL") or "meta-llama/llama-4-scout-17b-16e-instruct"
    try:
        from groq import Groq  # type: ignore[import]
        client = Groq(api_key=api_key)
        if image_bytes:
            mime = _detect_image_mime(image_bytes)
            img_b64 = base64.b64encode(image_bytes).decode("utf-8")
            messages: list[dict[str, Any]] = [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                {"type": "text", "text": prompt},
            ]}]
        else:
            messages = [{"role": "user", "content": prompt}]
        resp = client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content
        return content.strip() if content else None
    except ImportError:
        logger.warning("[llm_router][groq] groq package not installed — pip install groq")
    except Exception as exc:
        logger.warning("[llm_router][groq] Call failed: %s", exc)
    return None


# ── Input validation helper ────────────────────────────────────────────────────

def _validated_params(
    prompt: str,
    task: str,
    max_tokens: int,
    temperature: float,
) -> tuple[str, int, float] | None:
    """Clamp/validate inputs. Returns (prompt, max_tokens, temperature) or None if invalid."""
    if not prompt or not prompt.strip():
        logger.warning("[llm_router] Empty prompt for task=%s — skipping", task)
        return None
    max_tokens = max(1, min(32000, max_tokens))
    temperature = max(0.0, min(2.0, temperature))
    return prompt, max_tokens, temperature


# ── Public API ─────────────────────────────────────────────────────────────────

def llm_text_call(
    prompt: str,
    task: str = "reasoning",
    max_tokens: int = 800,
    temperature: float = 0.15,
) -> str | None:
    """Call an LLM with a text-only prompt.

    Args:
        prompt:      Full prompt string.
        task:        Task identifier — controls provider selection via env vars.
        max_tokens:  Maximum tokens to generate (clamped to [1, 32000]).
        temperature: Sampling temperature (clamped to [0, 2]).

    Returns:
        Raw text output string, or None on failure/empty response.

    Provider resolution (first match wins):
        PROVIDER_<TASK_ENV>  →  VLM_PROVIDER / REASONING_PROVIDER  →  'qwen'
    """
    validated = _validated_params(prompt, task, max_tokens, temperature)
    if not validated:
        return None
    prompt, max_tokens, temperature = validated

    provider = _resolve_provider(task)
    logger.info("[llm_router] task=%-22s provider=%s", task, provider)

    if provider == "gemini":
        return _call_gemini(prompt, None, max_tokens, temperature)
    if provider == "groq":
        return _call_groq(prompt, None, max_tokens, temperature)
    # default: qwen
    return _call_qwen_text(prompt, max_tokens, temperature)


def llm_vision_call(
    prompt: str,
    image_bytes: bytes | None = None,
    task: str = "entity_extraction",
    max_tokens: int = 400,
    temperature: float = 0.15,
) -> str | None:
    """Call an LLM with an image + text prompt (or text-only if image_bytes is None).

    Args:
        prompt:      Full prompt string.
        image_bytes: Raw image bytes (PNG/JPEG auto-detected), or None for text-only.
        task:        Task identifier — controls provider selection via env vars.
        max_tokens:  Maximum tokens to generate (clamped to [1, 32000]).
        temperature: Sampling temperature (clamped to [0, 2]).

    Returns:
        Raw text output string, or None on failure/empty response.

    Provider resolution (first match wins):
        PROVIDER_<TASK_ENV>  →  VLM_PROVIDER  →  'qwen'
    """
    validated = _validated_params(prompt, task, max_tokens, temperature)
    if not validated:
        return None
    prompt, max_tokens, temperature = validated

    has_image = bool(image_bytes)
    provider = _resolve_provider(task)
    logger.info("[llm_router] task=%-22s provider=%-8s has_image=%s", task, provider, has_image)

    if provider == "gemini":
        return _call_gemini(prompt, image_bytes if has_image else None, max_tokens, temperature)
    if provider == "groq":
        return _call_groq(prompt, image_bytes if has_image else None, max_tokens, temperature)
    # default: qwen
    if has_image:
        return _call_qwen_vision(prompt, image_bytes, max_tokens, temperature)  # type: ignore[arg-type]
    return _call_qwen_text(prompt, max_tokens, temperature)


def is_provider_available(provider: str, vision: bool = False) -> bool:
    """Check if a provider is reachable/configured for pre-flight health checks.

    For Qwen: performs an actual HTTP health-check against the vLLM /v1/models endpoint.
    For Gemini / Groq: checks whether the API key env var is set (cloud services
    cannot be pinged without a billable call, so key presence is the proxy).

    Note: Returns True for Gemini/Groq even if offline — the actual call will fail
    gracefully and return None, triggering pdfplumber fallback in the pipeline.
    """
    provider = provider.strip().lower()
    if provider == "qwen":
        endpoint = (os.getenv("SGLANG_ENDPOINT") or "http://localhost:8002").rstrip("/") + "/v1/models"
        try:
            r = requests.get(endpoint, timeout=5)
            return r.status_code == 200
        except Exception:
            return False
    if provider == "gemini":
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    if provider == "groq":
        return bool(os.getenv("GROQ_API_KEY"))
    logger.warning("[llm_router] Unknown provider '%s' — treating as unavailable", provider)
    return False
