"""Unified LLM Router for BharatStat V2 pipeline.

All LLM calls in the pipeline go through this module.
Switch providers by changing environment variables — no code changes needed.

Environment variables
---------------------
VLM_PROVIDER        Vision+text tasks (entity extraction, structure analysis, question gen)
                    Values: qwen (default) | gemini | groq | openai
REASONING_PROVIDER  Text-only tasks (ToC extraction, gap fill, fact extraction, binding)
                    Values: qwen (default) | gemini | groq | openai

Offline / air-gapped:
    LLM_DISABLED=1  Skip ALL LLM/VLM calls; pipeline runs on deterministic
                    pdfplumber + programmatic fallbacks (no key/server needed).

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
    OPENAI_API_KEY    (not required for local servers like Ollama/LM Studio)
    OPENAI_BASE_URL   = https://api.openai.com/v1
    OPENAI_MODEL      = gpt-4o-mini
    OPENAI_VISION_MODEL = gpt-4o-mini
    OPENAI_TIMEOUT    = 120

The 'openai' provider speaks the OpenAI /chat/completions wire format, so a single
provider covers OpenAI, OpenRouter, Together, DeepSeek, Ollama and LM Studio — just
point OPENAI_BASE_URL at the server and set OPENAI_MODEL.

Quick switch examples (set on GPU laptop, no code changes):
    # Use Gemini for everything:
    VLM_PROVIDER=gemini REASONING_PROVIDER=gemini

    # Keep Qwen for vision, Gemini only for reasoning:
    VLM_PROVIDER=qwen REASONING_PROVIDER=gemini

    # Use Groq for reasoning only:
    REASONING_PROVIDER=groq

    # Use a local Ollama model for reasoning (no key, fully offline):
    REASONING_PROVIDER=openai OPENAI_BASE_URL=http://localhost:11434/v1 OPENAI_MODEL=qwen2.5:7b

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
from collections.abc import Callable
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ── Key Pool System ────────────────────────────────────────────────────────────
# Loads KEY_1..KEY_10 from env. Each slot has: provider, value (api key), name.
# Tasks are assigned a key slot via KEY_SLOT_<TASK> env var.
# Logs show: "[KEY_3:groq-fast] used for entity_extraction"


class _KeySlot:
    """One named API key slot from the pool."""
    __slots__ = ("slot_id", "provider", "value", "name")

    def __init__(self, slot_id: int, provider: str, value: str, name: str):
        self.slot_id = slot_id
        self.provider = provider.strip().lower()
        self.value = value.strip()
        self.name = name.strip() or f"key_{slot_id}"

    @property
    def label(self) -> str:
        return f"KEY_{self.slot_id}:{self.name}"

    def is_valid(self) -> bool:
        return bool(self.provider and self.value)

    def __repr__(self) -> str:
        return f"<KeySlot {self.label} provider={self.provider}>"


def _load_key_pool() -> dict[int, _KeySlot]:
    """Load all KEY_1..KEY_10 slots from environment."""
    pool: dict[int, _KeySlot] = {}
    for i in range(1, 11):
        provider = (os.getenv(f"KEY_{i}_PROVIDER") or "").strip().lower()
        value = (os.getenv(f"KEY_{i}_VALUE") or "").strip()
        name = (os.getenv(f"KEY_{i}_NAME") or "").strip()
        if provider and value:
            pool[i] = _KeySlot(i, provider, value, name)
    return pool


# Load once at import time
_KEY_POOL: dict[int, _KeySlot] = _load_key_pool()

# Log loaded keys at startup (values masked)
for _slot in _KEY_POOL.values():
    logger.info("[key_pool] Loaded %s (provider=%s, key=...%s)",
               _slot.label, _slot.provider, _slot.value[-4:] if len(_slot.value) > 4 else "****")


def _resolve_key_for_task(task: str, provider: str) -> _KeySlot | None:
    """Find the assigned key slot for a task, or first matching provider key.

    Priority:
    1. KEY_SLOT_<TASK> env var → use that exact slot
    2. First slot in pool matching the resolved provider
    3. None (fall back to legacy env vars like GEMINI_API_KEY)
    """
    # Check explicit key slot assignment
    task_upper = task.upper()
    slot_num_str = (os.getenv(f"KEY_SLOT_{task_upper}") or "").strip()
    if slot_num_str:
        try:
            slot_num = int(slot_num_str)
            slot = _KEY_POOL.get(slot_num)
            if slot and slot.is_valid():
                return slot
            else:
                logger.warning("[key_pool] KEY_SLOT_%s=%d but slot is empty/invalid",
                              task_upper, slot_num)
        except ValueError:
            logger.warning("[key_pool] KEY_SLOT_%s=%r is not a valid number",
                          task_upper, slot_num_str)

    # Fallback: first pool key matching the provider
    for slot in _KEY_POOL.values():
        if slot.provider == provider and slot.is_valid():
            return slot

    return None


def get_api_key_for_task(task: str, provider: str) -> tuple[str | None, str]:
    """Get the API key and label for a task+provider combination.

    For tasks that make many calls (entity_extraction), rotates across all
    available keys for that provider to avoid rate limits.

    Returns (api_key, label) where label is like "KEY_3:groq-fast" or "legacy:GEMINI_API_KEY".
    """
    slot = _resolve_key_for_task(task, provider)
    if slot:
        logger.info("[key_pool] [%s] used for %s (provider=%s)", slot.label, task, provider)
        return slot.value, slot.label

    # Legacy fallback
    if provider == "gemini":
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        label = "legacy:GEMINI_API_KEY"
    elif provider == "groq":
        key = os.getenv("GROQ_API_KEY") or ""
        label = "legacy:GROQ_API_KEY"
    elif provider == "openai":
        key = os.getenv("OPENAI_API_KEY") or ""
        label = "legacy:OPENAI_API_KEY"
    else:
        key = ""
        label = f"legacy:{provider}"

    if key:
        logger.info("[key_pool] [%s] used for %s (provider=%s, no pool slot)", label, task, provider)
    return key or None, label


# ── Round-robin key rotation for high-volume tasks ─────────────────────────────
_ROTATION_COUNTERS: dict[str, int] = {}


def get_rotated_key_for_task(task: str, provider: str) -> tuple[str | None, str]:
    """Like get_api_key_for_task but rotates across ALL pool keys for the provider.

    Use this for tasks that fire many times per pipeline run (entity_extraction,
    question_generation) to spread load across keys and avoid rate limits.
    """
    # Get all valid pool slots for this provider
    provider_slots = [s for s in _KEY_POOL.values() if s.provider == provider and s.is_valid()]
    if not provider_slots:
        return get_api_key_for_task(task, provider)

    # Round-robin
    counter_key = f"{task}:{provider}"
    idx = _ROTATION_COUNTERS.get(counter_key, 0)
    slot = provider_slots[idx % len(provider_slots)]
    _ROTATION_COUNTERS[counter_key] = idx + 1

    logger.info("[key_pool] [%s] used for %s (provider=%s, rotation %d/%d)",
               slot.label, task, provider, (idx % len(provider_slots)) + 1, len(provider_slots))
    return slot.value, slot.label

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


# ── Provider-aware token budget clamping ───────────────────────────────────────
# Qwen 3B with 2048 context: prompts are 400-1200 tokens, so safe output = 700.
# This prevents "max context 2048" errors even with long prompts (tables, entities).
_PROVIDER_MAX_OUTPUT: dict[str, int] = {
    "qwen":   500,    # 2048 ctx − ~1500 reserved for prompt+image. ONLY use for entity_extraction (256 tok)
    "openai": 4000,   # Ollama default 8192 ctx → ~4000 for output
    "gemini": 8000,   # Gemini Flash supports 8192 output tokens
    "groq":   8000,   # Groq llama-3.3-70b: 32K output, scout-17b: 16K output - safe at 8K
}


def _clamp_tokens_for_provider(provider: str, max_tokens: int) -> int:
    """Clamp max_tokens to the provider's safe output limit."""
    cap = _PROVIDER_MAX_OUTPUT.get(provider, 4000)
    if max_tokens > cap:
        return cap
    return max_tokens


def llm_disabled() -> bool:
    """Air-gapped / offline switch: when set, ALL LLM calls are skipped.

    Set ``LLM_DISABLED=1`` to run the pipeline with no network/model access at all.
    Every ``llm_text_call`` / ``llm_vision_call`` returns ``None`` immediately and
    ``is_provider_available`` reports ``False``, so the pipeline takes its
    deterministic pdfplumber + programmatic-fallback paths. Useful for air-gapped
    deployments, CI without GPUs, and reproducible offline simulations.
    """
    return (os.getenv("LLM_DISABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def _detect_image_mime(image_bytes: bytes) -> str:
    """Detect image MIME type from magic bytes (PNG or JPEG)."""
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/png"  # safe default for Qwen which prefers PNG


def guided_json_enabled() -> bool:
    """Q20: whether to send vLLM ``guided_json`` schema-constrained decoding.

    Default ON. Set ``GUIDED_JSON=0`` to disable globally (e.g. for backends that
    do not support vLLM's structured-outputs extension).
    """
    return (os.getenv("GUIDED_JSON") or "1").strip().lower() not in ("0", "false", "no", "off")


def _apply_guided_json(payload: dict, schema: dict | None) -> None:
    """Attach a vLLM ``guided_json`` constraint to a chat-completions payload.

    vLLM reads ``extra_body.guided_json``; we set it at the top level of the JSON
    body (the OpenAI server merges ``extra_body`` into the request) and also under
    ``response_format`` as a json_schema for OpenAI-compatible servers that prefer it.
    No-op when schema is falsy or the feature is disabled.
    """
    if not schema or not guided_json_enabled():
        return
    payload["guided_json"] = schema
    payload["guided_decoding_backend"] = os.getenv("GUIDED_JSON_BACKEND") or "outlines"


# ── Backend implementations ────────────────────────────────────────────────────

def _call_qwen_text(prompt: str, max_tokens: int, temperature: float,
                    schema: dict | None = None) -> str | None:
    endpoint = (os.getenv("SGLANG_ENDPOINT") or "http://localhost:8002").rstrip("/") + "/v1/chat/completions"
    model = os.getenv("SGLANG_MODEL") or "Qwen/Qwen2.5-VL-3B-Instruct-AWQ"
    timeout = int(os.getenv("SGLANG_TIMEOUT") or "120")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    _apply_guided_json(payload, schema)
    try:
        r = requests.post(endpoint, json=payload, timeout=timeout)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        logger.warning("[llm_router][qwen] HTTP %d: %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.warning("[llm_router][qwen] Request failed: %s", exc)
    return None


def _call_qwen_vision(prompt: str, image_bytes: bytes, max_tokens: int, temperature: float,
                      schema: dict | None = None) -> str | None:
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
    _apply_guided_json(payload, schema)
    try:
        r = requests.post(endpoint, json=payload, timeout=timeout)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        # Auto-retry with reduced tokens on context overflow (400 "maximum context length")
        if r.status_code == 400 and "maximum context length" in (r.text or ""):
            reduced = max(64, max_tokens // 2)
            logger.warning("[llm_router][qwen-vision] Context overflow (max_tok=%d) — retrying with %d", max_tokens, reduced)
            payload["max_tokens"] = reduced
            r2 = requests.post(endpoint, json=payload, timeout=timeout)
            if r2.status_code == 200:
                return r2.json()["choices"][0]["message"]["content"].strip()
            logger.warning("[llm_router][qwen-vision] Retry also failed: HTTP %d", r2.status_code)
        else:
            logger.warning("[llm_router][qwen-vision] HTTP %d: %s", r.status_code, (r.text or "")[:300])
    except Exception as exc:
        logger.warning("[llm_router][qwen-vision] Request failed: %s", exc)

    # ── Auto-fallback is handled by the caller (llm_vision_call fallback chain) ──
    # No inline fallback here — the vision call loop handles retries with configurable order.
    return None


def _call_gemini(prompt: str, image_bytes: bytes | None, max_tokens: int, temperature: float,
                 api_key: str | None = None, key_label: str = "") -> str | None:
    api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
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
        logger.warning("[llm_router][gemini]%s Call failed: %s", f" [{key_label}]" if key_label else "", exc)
    return None


def _call_groq(prompt: str, image_bytes: bytes | None, max_tokens: int, temperature: float,
               api_key: str | None = None, key_label: str = "") -> str | None:
    api_key = api_key or os.getenv("GROQ_API_KEY") or ""
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
        logger.warning("[llm_router][groq]%s Call failed: %s", f" [{key_label}]" if key_label else "", exc)
    return None


def _call_openai(prompt: str, image_bytes: bytes | None, max_tokens: int, temperature: float,
                 api_key: str | None = None, key_label: str = "") -> str | None:
    """Call any OpenAI-compatible /chat/completions endpoint (OpenAI, OpenRouter, Ollama, LM Studio).

    Uses plain HTTP (no openai package needed). A key is only required when talking to
    api.openai.com; local servers (Ollama/LM Studio) work without one.
    """
    base = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    api_key = api_key or os.getenv("OPENAI_API_KEY") or ""
    if not api_key and "api.openai.com" in base:
        logger.info("[llm_router][openai] No OPENAI_API_KEY for api.openai.com — skipping")
        return None
    if image_bytes:
        model = os.getenv("OPENAI_VISION_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    else:
        model = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    timeout = int(os.getenv("OPENAI_TIMEOUT") or "120")
    if image_bytes:
        mime = _detect_image_mime(image_bytes)
        img_b64 = base64.b64encode(image_bytes).decode("utf-8")
        content: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
            {"type": "text", "text": prompt},
        ]
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "user", "content": prompt}]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        r = requests.post(f"{base}/chat/completions", json=payload, headers=headers, timeout=timeout)
        if r.status_code == 200:
            content_out = r.json()["choices"][0]["message"]["content"]
            return content_out.strip() if content_out else None
        logger.warning("[llm_router][openai] HTTP %d: %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.warning("[llm_router][openai] Request failed: %s", exc)
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
    schema: dict | None = None,
) -> str | None:
    """Call an LLM with a text-only prompt.

    Args:
        prompt:      Full prompt string.
        task:        Task identifier — controls provider selection via env vars.
        max_tokens:  Maximum tokens to generate (clamped to [1, 32000]).
        temperature: Sampling temperature (clamped to [0, 2]).
        schema:      Optional JSON schema for vLLM ``guided_json`` constrained decoding
                     (qwen path only; ignored by other providers).

    Returns:
        Raw text output string, or None on failure/empty response.

    Provider resolution (first match wins):
        PROVIDER_<TASK_ENV>  →  VLM_PROVIDER / REASONING_PROVIDER  →  'qwen'
    """
    if llm_disabled():
        return None
    validated = _validated_params(prompt, task, max_tokens, temperature)
    if not validated:
        return None
    prompt, max_tokens, temperature = validated

    provider = _resolve_provider(task)
    max_tokens = _clamp_tokens_for_provider(provider, max_tokens)

    # Resolve key from pool (rotation for high-volume tasks)
    _HIGH_VOLUME_TASKS = frozenset({"entity_extraction", "question_generation", "entity_binding", "fact_extraction"})
    if task in _HIGH_VOLUME_TASKS:
        api_key, key_label = get_rotated_key_for_task(task, provider)
    else:
        api_key, key_label = get_api_key_for_task(task, provider)
    logger.info("[llm_router] task=%-22s provider=%-8s key=%-20s max_tok=%d", task, provider, key_label, max_tokens)

    if provider == "gemini":
        return _call_gemini(prompt, None, max_tokens, temperature, api_key=api_key, key_label=key_label)
    if provider == "groq":
        return _call_groq(prompt, None, max_tokens, temperature, api_key=api_key, key_label=key_label)
    if provider == "openai":
        return _call_openai(prompt, None, max_tokens, temperature, api_key=api_key, key_label=key_label)
    # default: qwen
    return _call_qwen_text(prompt, max_tokens, temperature, schema=schema)


def llm_vision_call(
    prompt: str,
    image_bytes: bytes | None = None,
    task: str = "entity_extraction",
    max_tokens: int = 400,
    temperature: float = 0.15,
    schema: dict | None = None,
) -> str | None:
    """Call an LLM with an image + text prompt (or text-only if image_bytes is None).

    Args:
        prompt:      Full prompt string.
        image_bytes: Raw image bytes (PNG/JPEG auto-detected), or None for text-only.
        task:        Task identifier — controls provider selection via env vars.
        max_tokens:  Maximum tokens to generate (clamped to [1, 32000]).
        temperature: Sampling temperature (clamped to [0, 2]).
        schema:      Optional JSON schema for vLLM ``guided_json`` constrained decoding
                     (qwen path only; ignored by other providers).

    Returns:
        Raw text output string, or None on failure/empty response.

    Provider resolution (first match wins):
        PROVIDER_<TASK_ENV>  →  VLM_PROVIDER  →  'qwen'
    """
    if llm_disabled():
        return None
    validated = _validated_params(prompt, task, max_tokens, temperature)
    if not validated:
        return None
    prompt, max_tokens, temperature = validated

    has_image = bool(image_bytes)
    provider = _resolve_provider(task)
    max_tokens = _clamp_tokens_for_provider(provider, max_tokens)

    # Resolve key from pool (rotation for high-volume vision tasks)
    _HIGH_VOLUME_TASKS = frozenset({"entity_extraction", "question_generation", "entity_binding", "fact_extraction"})
    if task in _HIGH_VOLUME_TASKS:
        api_key, key_label = get_rotated_key_for_task(task, provider)
    else:
        api_key, key_label = get_api_key_for_task(task, provider)
    logger.info("[llm_router] task=%-22s provider=%-8s key=%-20s has_image=%s max_tok=%d", task, provider, key_label, has_image, max_tokens)

    # Build fallback chain: primary → alternatives (resilient routing)
    # When the primary provider crashes (HTTP 500, connection reset), try next available
    # Configurable via VLM_FALLBACK_ORDER env (comma-separated). Default: openai first (local gemma2)
    _fallback_env = (os.getenv("VLM_FALLBACK_ORDER") or "openai,gemini,groq,qwen").strip()
    _FALLBACK_ORDER = [p.strip().lower() for p in _fallback_env.split(",") if p.strip()]
    fallback_chain = [provider] + [p for p in _FALLBACK_ORDER if p != provider]

    for attempt_provider in fallback_chain:
        attempt_max_tokens = _clamp_tokens_for_provider(attempt_provider, max_tokens)
        # Resolve key for the attempt provider (may differ from primary)
        if attempt_provider == provider:
            attempt_key, attempt_label = api_key, key_label
        else:
            attempt_key, attempt_label = get_api_key_for_task(task, attempt_provider)
        result = None
        try:
            if attempt_provider == "gemini":
                result = _call_gemini(prompt, image_bytes if has_image else None, attempt_max_tokens, temperature, api_key=attempt_key, key_label=attempt_label)
            elif attempt_provider == "groq":
                result = _call_groq(prompt, image_bytes if has_image else None, attempt_max_tokens, temperature, api_key=attempt_key, key_label=attempt_label)
            elif attempt_provider == "openai":
                result = _call_openai(prompt, image_bytes if has_image else None, attempt_max_tokens, temperature, api_key=attempt_key, key_label=attempt_label)
            else:  # qwen
                if has_image:
                    result = _call_qwen_vision(prompt, image_bytes, attempt_max_tokens, temperature, schema=schema)  # type: ignore[arg-type]
                else:
                    result = _call_qwen_text(prompt, attempt_max_tokens, temperature, schema=schema)
        except Exception as _fallback_exc:
            logger.warning("[llm_router] [%s] %s failed for task=%s: %s", attempt_label, attempt_provider, task, _fallback_exc)

        if result:
            if attempt_provider != provider:
                logger.info("[llm_router] ✓ Fallback %s→%s succeeded for task=%s", provider, attempt_provider, task)
            return result

        # Only try fallback for vision tasks (entity_extraction, question_gen) — they're critical
        if not has_image:
            break  # text-only tasks: don't cascade, just return None

        # Check if fallback provider is available before trying
        if attempt_provider == provider:
            logger.warning("[llm_router] Primary provider '%s' failed for task=%s — trying fallbacks", provider, task)

    logger.warning("[llm_router] All providers exhausted for task=%s (has_image=%s)", task, has_image)
    return None


def self_consistency_enabled() -> bool:
    """Q21: whether confidence-gated self-consistency re-sampling is active.

    Default ON. Set ``SELF_CONSISTENCY=0`` to disable (single-pass everywhere).
    Because the local vLLM runs ``--max-num-seqs 1`` (serialized), re-sampling is
    gated on low confidence so the common case stays single-pass.
    """
    return (os.getenv("SELF_CONSISTENCY") or "1").strip().lower() not in ("0", "false", "no", "off")


def _confidence_threshold(default: float = 0.6) -> float:
    try:
        return float(os.getenv("SELF_CONSISTENCY_THRESHOLD") or default)
    except (TypeError, ValueError):
        return default


def llm_consistent_call(
    prompt: str,
    parse: Callable[[str], tuple[Any, float] | None],
    *,
    task: str = "reasoning",
    image_bytes: bytes | None = None,
    max_tokens: int = 800,
    temperature: float = 0.15,
    schema: dict | None = None,
    threshold: float | None = None,
    resample_temperature: float = 0.7,
) -> tuple[Any, dict[str, Any]]:
    """Q21: confidence-gated self-consistency wrapper around a single LLM call.

    Runs one pass. ``parse`` maps the raw response to ``(value, confidence)`` or
    ``None`` on parse failure. If confidence ≥ threshold (or self-consistency is
    disabled), the first result is returned unchanged — the common, cheap path.
    Otherwise a second pass is sampled at ``resample_temperature`` and the higher-
    confidence of the two parsed results wins. Falls back gracefully to whichever
    pass parsed successfully.

    Returns ``(value, meta)`` where ``meta`` records ``passes``, ``confidence`` and
    ``resampled``. ``value`` is ``None`` only if every pass failed to parse.
    """
    thr = _confidence_threshold() if threshold is None else threshold
    meta: dict[str, Any] = {"passes": 0, "confidence": 0.0, "resampled": False}

    def _one(temp: float) -> tuple[Any, float] | None:
        meta["passes"] += 1
        raw = llm_vision_call(
            prompt, image_bytes=image_bytes, task=task,
            max_tokens=max_tokens, temperature=temp, schema=schema,
        )
        if not raw:
            return None
        try:
            return parse(raw)
        except Exception as exc:  # parser must never crash the pipeline
            logger.debug("[llm_router][consistency] parse error: %s", exc)
            return None

    first = _one(temperature)
    if first is not None:
        meta["confidence"] = first[1]
    # Accept first pass when confident enough or feature disabled.
    if first is not None and (first[1] >= thr or not self_consistency_enabled()):
        return first[0], meta

    second = _one(resample_temperature)
    meta["resampled"] = True
    candidates = [c for c in (first, second) if c is not None]
    if not candidates:
        return None, meta
    best = max(candidates, key=lambda c: c[1])
    meta["confidence"] = best[1]
    return best[0], meta


def is_provider_available(provider: str, vision: bool = False) -> bool:
    """Check if a provider is reachable/configured for pre-flight health checks.

    For Qwen: performs an actual HTTP health-check against the vLLM /v1/models endpoint.
    For Gemini / Groq: checks whether the API key env var is set (cloud services
    cannot be pinged without a billable call, so key presence is the proxy).

    Note: Returns True for Gemini/Groq even if offline — the actual call will fail
    gracefully and return None, triggering pdfplumber fallback in the pipeline.
    """
    if llm_disabled():
        return False
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
    if provider == "openai":
        base = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        if "api.openai.com" in base:
            return bool(os.getenv("OPENAI_API_KEY"))
        # Local/proxy server (Ollama, LM Studio, vLLM): ping the models endpoint.
        try:
            r = requests.get(f"{base}/models", timeout=5)
            return r.status_code == 200
        except Exception:
            return False
    logger.warning("[llm_router] Unknown provider '%s' — treating as unavailable", provider)
    return False
