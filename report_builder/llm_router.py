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
    SGLANG_ENDPOINT   = http://localhost:8002  (local SGLang server)
    SGLANG_MODEL      = <set SGLANG_MODEL in .env>
    SGLANG_TIMEOUT    = 120
    GEMINI_MODEL      = <set GEMINI_MODEL in .env>
    GEMINI_API_KEY    (or GOOGLE_API_KEY)
    GROQ_API_KEY
    GROQ_MODEL        = <set GROQ_MODEL in .env>
    GROQ_VISION_MODEL = <set GROQ_VISION_MODEL in .env>
    OPENAI_API_KEY    (not required for local servers like Ollama/LM Studio)
    OPENAI_BASE_URL   = https://api.openai.com/v1
    OPENAI_MODEL      = <set OPENAI_MODEL in .env>
    OPENAI_VISION_MODEL = <set OPENAI_VISION_MODEL in .env>
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
import time
from collections.abc import Callable
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ── Rate-limit aware POST (large-PDF robustness) ────────────────────────────────
# Cloud providers (Groq free-tier ~30 RPM, Azure, OpenRouter) return HTTP 429/503
# under burst load — exactly what a large multi-hundred-page PDF generates in pass 2/3.
# Without backoff every 429 returns None, counts as a hard failure, and trips the
# pass-2 circuit breaker, silently degrading the rest of the document to pdfplumber.
# A short, bounded, Retry-After-aware backoff lets transient rate limits self-heal so
# big PDFs extract fully. Tunable via env; defaults are conservative.
_RATE_LIMIT_STATUS = frozenset({429, 503})


def _rate_limit_retries() -> int:
    try:
        return max(0, int(os.getenv("LLM_RATE_LIMIT_RETRIES") or "2"))
    except (TypeError, ValueError):
        return 2


def _rate_limit_backoff_base() -> float:
    try:
        return max(0.0, float(os.getenv("LLM_RATE_LIMIT_BACKOFF_SECONDS") or "8"))
    except (TypeError, ValueError):
        return 8.0


def _post_with_retry(url: str, *, label: str = "", **kwargs: Any) -> "requests.Response":
    """``requests.post`` with bounded, Retry-After-aware backoff on HTTP 429/503.

    Returns the final :class:`requests.Response` (caller still inspects status_code).
    Honors the server ``Retry-After`` header when present, else exponential backoff
    capped at 30s. Non-rate-limit responses (200, 400, 500, …) return immediately.
    """
    retries = _rate_limit_retries()
    base = _rate_limit_backoff_base()
    resp = requests.post(url, **kwargs)
    for attempt in range(retries):
        if resp.status_code not in _RATE_LIMIT_STATUS:
            return resp
        retry_after = (resp.headers or {}).get("Retry-After")
        try:
            wait = float(retry_after) if retry_after else base * (2 ** attempt)
        except (TypeError, ValueError):
            wait = base * (2 ** attempt)
        wait = min(max(wait, 0.0), 30.0)
        logger.warning(
            "[llm_router]%s HTTP %d (rate limit) — backing off %.1fs (retry %d/%d)",
            f" [{label}]" if label else "", resp.status_code, wait, attempt + 1, retries,
        )
        time.sleep(wait)
        resp = requests.post(url, **kwargs)
    return resp

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


# ── Gemini multi-key pool (GEMINI_KEY_1 .. GEMINI_KEY_N + legacy GEMINI_API_KEY) ──────────
# Load all Gemini keys at import time; caller rotates via get_rotated_gemini_key().
# Add as many keys as you want in .env: GEMINI_KEY_1=..., GEMINI_KEY_2=..., etc.

def _load_gemini_key_pool() -> list[str]:
    """Load all GEMINI_KEY_1..GEMINI_KEY_N + legacy fallback keys."""
    keys: list[str] = []
    for i in range(1, 25):  # supports up to 24 Gemini keys
        k = (os.getenv(f"GEMINI_KEY_{i}") or "").strip()
        if k:
            keys.append(k)
    for legacy in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        k = (os.getenv(legacy) or "").strip()
        if k and k not in keys:
            keys.append(k)
    return keys


_GEMINI_KEY_POOL: list[str] = _load_gemini_key_pool()
_GEMINI_KEY_COUNTER: int = 0

for _i, _gk in enumerate(_GEMINI_KEY_POOL, 1):
    logger.info("[gemini_key_pool] Loaded GEMINI_KEY_%d (...%s)", _i, _gk[-4:] if len(_gk) > 4 else "****")


def get_rotated_gemini_key() -> tuple[str | None, str]:
    """Round-robin across all configured Gemini API keys.

    Rotates through GEMINI_KEY_1..GEMINI_KEY_N on every call so concurrent
    requests spread across keys, staying within each key's free-tier RPM limit.
    """
    global _GEMINI_KEY_COUNTER
    pool = _GEMINI_KEY_POOL
    if not pool:
        return None, "no_gemini_key"
    idx = _GEMINI_KEY_COUNTER % len(pool)
    _GEMINI_KEY_COUNTER += 1
    return pool[idx], f"GEMINI_KEY_{idx + 1}"


def _resolve_key_for_task(task: str, provider: str) -> "_KeySlot | None":
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
    elif provider == "azure":
        key = os.getenv("AZURE_OPENAI_API_KEY") or ""
        label = "legacy:AZURE_OPENAI_API_KEY"
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
    "report_narrative":    "PROVIDER_REPORT_NARRATIVE",
}

_VISION_TASKS = frozenset({"entity_extraction", "question_generation"})

# ── Per-task model env var overrides ─────────────────────────────────────────
# TASK_<TASK>_MODEL overrides the model name used for that specific task,
# regardless of which provider is active.  Set in .env.
_TASK_MODEL_ENVS: dict[str, str] = {
    "entity_extraction":    "TASK_ENTITY_EXTRACTION_MODEL",
    "question_generation":  "TASK_QUESTION_GENERATION_MODEL",
    "entity_binding":       "TASK_ENTITY_BINDING_MODEL",
    "entity_classification":"TASK_ENTITY_CLASSIFICATION_MODEL",
    "toc_extraction":       "TASK_TOC_EXTRACTION_MODEL",
    "gap_fill":             "TASK_GAP_FILL_MODEL",
    "fact_extraction":      "TASK_FACT_EXTRACTION_MODEL",
    "semantic_fallback":    "TASK_SEMANTIC_FALLBACK_MODEL",
    "semantic_enrichment":  "TASK_SEMANTIC_ENRICHMENT_MODEL",
    "question_repair":      "TASK_QUESTION_REPAIR_MODEL",
    "report_narrative":     "TASK_REPORT_NARRATIVE_MODEL",
}


def _resolve_model_for_task(task: str, provider: str, is_vision: bool = False) -> str:
    """Resolve the model name for a task+provider.

    Priority:
    1. TASK_<TASK>_MODEL env var   (per-task override, works for any provider)
    2. Provider vision/text global (OPENAI_VISION_MODEL / OPENAI_MODEL / GROQ_VISION_MODEL /
       GROQ_MODEL / GEMINI_VISION_MODEL / GEMINI_MODEL / SGLANG_VISION_MODEL / SGLANG_MODEL)

    NO hardcoded fallbacks. If the env var is not set the model string will be
    empty and the call will be skipped with a logged warning. Configure every
    model explicitly in .env.
    """
    # Priority 1: per-task env override
    model_env = _TASK_MODEL_ENVS.get(task, "")
    if model_env:
        override = (os.getenv(model_env) or "").strip()
        if override:
            return override

    # Priority 2: provider-global env (separate vision / text vars per provider)
    if provider == "azure":
        # Azure uses deployment names (not model IDs) in the URL path
        key = "AZURE_OPENAI_VISION_DEPLOYMENT" if is_vision else "AZURE_OPENAI_TEXT_DEPLOYMENT"
        fallback_key = "AZURE_OPENAI_DEPLOYMENT_NAME" if not is_vision else None
    elif provider == "openai":
        key = "OPENAI_VISION_MODEL" if is_vision else "OPENAI_MODEL"
        fallback_key = "OPENAI_MODEL" if is_vision else None  # vision can fall back to text
    elif provider == "groq":
        key = "GROQ_VISION_MODEL" if is_vision else "GROQ_MODEL"
        fallback_key = "GROQ_MODEL" if is_vision else None
    elif provider == "gemini":
        key = "GEMINI_VISION_MODEL" if is_vision else "GEMINI_MODEL"
        fallback_key = "GEMINI_MODEL" if is_vision else None  # gemini is multimodal
    else:  # qwen / sglang
        key = "SGLANG_VISION_MODEL" if is_vision else "SGLANG_MODEL"
        fallback_key = "SGLANG_MODEL" if is_vision else None  # VL model serves both

    model = (os.getenv(key) or "").strip()
    if not model and fallback_key:
        model = (os.getenv(fallback_key) or "").strip()
    if not model:
        logger.warning(
            "[llm_router] No model configured for task=%s provider=%s is_vision=%s. "
            "Set %s in .env to fix this.",
            task, provider, is_vision, key,
        )
    return model


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
    "qwen":   500,    # local 3B model -- last-resort vision fallback
    "openai": 32500,  # OpenRouter: varies by model; conservative cap
    "gemini": 8000,   # Gemini Flash 8K safe output
    "groq":   16000,  # Groq: most models support 32K+; cap at 16K
    "azure":  16000,  # Azure gpt-5.x reasoning model: reasoning_tokens eat into max_completion_tokens
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

def _call_azure(prompt: str, image_bytes: bytes | None, max_tokens: int, temperature: float,
                api_key: str | None = None, key_label: str = "",
                task: str = "") -> str | None:
    """Call Azure OpenAI chat/completions (gpt-4o for vision, gpt-5.x for text).

    Uses ``api-key`` header and deployment-in-path URL format required by Azure.
    Activated via AZURE_OPENAI_* env vars; no credentials are hardcoded.
    """
    api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY") or ""
    if not api_key:
        logger.info("[llm_router][azure] No AZURE_OPENAI_API_KEY — skipping")
        return None
    endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
    if not endpoint:
        logger.info("[llm_router][azure] No AZURE_OPENAI_ENDPOINT — skipping")
        return None
    api_version = os.getenv("AZURE_OPENAI_API_VERSION") or "2025-04-01-preview"
    is_vision = bool(image_bytes)
    deployment = _resolve_model_for_task(task, "azure", is_vision=is_vision) if task else (
        os.getenv("AZURE_OPENAI_VISION_DEPLOYMENT", "gpt-4o-graphiti-2") if is_vision
        else os.getenv("AZURE_OPENAI_TEXT_DEPLOYMENT",
                       os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5.2-chat"))
    )
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    timeout = int(os.getenv("AZURE_OPENAI_TIMEOUT") or os.getenv("OPENAI_TIMEOUT") or "120")
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
    payload: dict[str, Any] = {"messages": messages}

    # Deployment-aware parameter selection:
    # - gpt-4o-graphiti-2 (vision) = standard gpt-4o → max_tokens + temperature supported
    # - gpt-5.2-chat (text)        = reasoning model  → max_completion_tokens only,
    #   no temperature, needs a multiplier so reasoning_tokens don't consume all budget
    _text_deploy = os.getenv("AZURE_OPENAI_TEXT_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "")
    _is_reasoning_deploy = (deployment == _text_deploy)

    if _is_reasoning_deploy:
        # gpt-5.x reasoning model: multiply tokens to leave room after internal thinking
        _multiplier = int(os.getenv("AZURE_OPENAI_REASONING_MULTIPLIER") or "8")
        payload["max_completion_tokens"] = max_tokens * _multiplier
        # temperature NOT set — gpt-5.x only accepts the default (1)
    else:
        # gpt-4o (vision deployment): standard params fully supported
        payload["max_tokens"] = max_tokens
        payload["temperature"] = temperature
        # Force strict JSON so the model can't emit markdown fences / prose preamble
        # that eats the (small) token budget and pushes the real JSON past the cap.
        # Azure requires the word "json" in the prompt for json_object mode — the
        # extraction prompts already ask for JSON, so only enable it when present.
        if (os.getenv("AZURE_OPENAI_JSON_MODE", "1").strip().lower() in ("1", "true", "yes", "on")
                and "json" in prompt.lower()):
            payload["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json", "api-key": api_key}

    # Up to 2 attempts: if the first response is cut off by the output-token cap
    # (finish_reason == "length"), retry once with a larger budget so dense pages
    # return complete, parseable JSON instead of a truncated fragment. This is the
    # root-cause fix for "returned text but no valid JSON" on dense table pages.
    _max_retries = 0 if _is_reasoning_deploy else 1
    _hard_cap = int(os.getenv("AZURE_OPENAI_MAX_OUTPUT_CAP") or "1024")
    for _attempt in range(_max_retries + 1):
        try:
            r = _post_with_retry(url, label=key_label or "azure", json=payload, headers=headers, timeout=timeout, verify=_SSL_VERIFY)
        except Exception as exc:
            logger.warning("[llm_router][azure]%s Request failed: %s",
                           f" [{key_label}]" if key_label else "", exc)
            return None
        if r.status_code != 200:
            logger.warning("[llm_router][azure]%s HTTP %d: %s",
                           f" [{key_label}]" if key_label else "", r.status_code, r.text[:300])
            return None
        choice = (r.json().get("choices") or [{}])[0]
        content_out = (choice.get("message") or {}).get("content")
        finish = choice.get("finish_reason")
        if finish == "length" and _attempt < _max_retries and max_tokens < _hard_cap:
            _bumped = min(max_tokens * 2, _hard_cap)
            logger.info("[llm_router][azure]%s response truncated (finish_reason=length @ %d tok) — retrying @ %d tok",
                        f" [{key_label}]" if key_label else "", max_tokens, _bumped)
            payload["max_tokens"] = _bumped
            max_tokens = _bumped
            continue
        if finish == "length":
            logger.warning("[llm_router][azure]%s response still truncated after retry (finish_reason=length @ %d tok)",
                           f" [{key_label}]" if key_label else "", max_tokens)
        return content_out.strip() if content_out else None
    return None


def _call_qwen_text(prompt: str, max_tokens: int, temperature: float,
                    schema: dict | None = None) -> str | None:
    endpoint = (os.getenv("SGLANG_ENDPOINT") or "http://localhost:8002").rstrip("/") + "/v1/chat/completions"
    model = (os.getenv("SGLANG_MODEL") or "").strip()
    if not model:
        logger.warning("[llm_router][qwen] SGLANG_MODEL not set in .env -- skipping")
        return None
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
    # Prefer a dedicated vision model; fall back to general SGLANG_MODEL (e.g. a VL model)
    model = (os.getenv("SGLANG_VISION_MODEL") or os.getenv("SGLANG_MODEL") or "").strip()
    if not model:
        logger.warning("[llm_router][qwen-vision] SGLANG_VISION_MODEL / SGLANG_MODEL not set -- skipping")
        return None
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
                 api_key: str | None = None, key_label: str = "",
                 task: str = "") -> str | None:
    # Use the rotated key pool; caller may supply a specific key for testing
    if not api_key:
        api_key, key_label = get_rotated_gemini_key()
    if not api_key:
        logger.info("[llm_router][gemini] No Gemini key configured (GEMINI_KEY_1..N / GEMINI_API_KEY) -- skipping")
        return None
    model = _resolve_model_for_task(task, "gemini", is_vision=bool(image_bytes)) if task else (
        os.getenv("GEMINI_VISION_MODEL" if image_bytes else "GEMINI_MODEL") or ""
    )
    if not model:
        logger.warning("[llm_router][gemini] GEMINI_MODEL not set in .env -- skipping")
        return None
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


# ── SSL verification ───────────────────────────────────────────────────────────
# Python on Windows often lacks system CA certs. We use certifi's bundle.
# Set SSL_VERIFY=0 to disable verification entirely (not recommended).
def _get_ssl_verify():
    """Resolve SSL verify setting: True, False, or path to CA bundle."""
    val = (os.getenv("SSL_VERIFY") or "1").strip().lower()
    if val in ("0", "false", "no", "off"):
        # Suppress InsecureRequestWarning spam in logs
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        return False
    # Use REQUESTS_CA_BUNDLE or certifi
    ca_bundle = os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("SSL_CERT_FILE") or ""
    if ca_bundle:
        return ca_bundle
    try:
        import certifi
        return certifi.where()
    except ImportError:
        pass
    return True

_SSL_VERIFY = _get_ssl_verify()


def _call_groq(prompt: str, image_bytes: bytes | None, max_tokens: int, temperature: float,
               api_key: str | None = None, key_label: str = "",
               task: str = "") -> str | None:
    """Call Groq via plain HTTP (OpenAI-compatible /chat/completions). No SDK needed."""
    api_key = api_key or os.getenv("GROQ_API_KEY") or ""
    if not api_key:
        logger.info("[llm_router][groq] No GROQ_API_KEY — skipping")
        return None
    model = _resolve_model_for_task(task, "groq", is_vision=bool(image_bytes)) if task else (
        (os.getenv("GROQ_VISION_MODEL") if image_bytes else os.getenv("GROQ_MODEL")) or ""
    )
    if not model:
        logger.warning("[llm_router][groq] %s not set in .env -- skipping",
                       "GROQ_VISION_MODEL" if image_bytes else "GROQ_MODEL")
        return None
    timeout = int(os.getenv("GROQ_TIMEOUT") or "120")
    if image_bytes:
        mime = _detect_image_mime(image_bytes)
        img_b64 = base64.b64encode(image_bytes).decode("utf-8")
        messages: list[dict[str, Any]] = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
            {"type": "text", "text": prompt},
        ]}]
    else:
        messages = [{"role": "user", "content": prompt}]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    groq_base = (os.getenv("GROQ_BASE_URL") or "https://api.groq.com/openai/v1").rstrip("/")
    try:
        r = _post_with_retry(
            f"{groq_base}/chat/completions", label=key_label or "groq",
            json=payload, headers=headers, timeout=timeout, verify=_SSL_VERIFY,
        )
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"]
            return content.strip() if content else None
        logger.warning("[llm_router][groq]%s HTTP %d: %s", f" [{key_label}]" if key_label else "", r.status_code, r.text[:300])
    except Exception as exc:
        logger.warning("[llm_router][groq]%s Request failed: %s", f" [{key_label}]" if key_label else "", exc)
    return None


def _call_openai(prompt: str, image_bytes: bytes | None, max_tokens: int, temperature: float,
                 api_key: str | None = None, key_label: str = "",
                 task: str = "") -> str | None:
    """Call any OpenAI-compatible /chat/completions endpoint (OpenAI, OpenRouter, Ollama, LM Studio).

    Uses plain HTTP (no openai package needed). A key is only required when talking to
    api.openai.com; local servers (Ollama/LM Studio) work without one.
    """
    base = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    api_key = api_key or os.getenv("OPENAI_API_KEY") or ""
    if not api_key and "api.openai.com" in base:
        logger.info("[llm_router][openai] No OPENAI_API_KEY for api.openai.com — skipping")
        return None
    model = _resolve_model_for_task(task, "openai", is_vision=bool(image_bytes)) if task else (
        os.getenv("OPENAI_VISION_MODEL" if image_bytes else "OPENAI_MODEL") or ""
    )
    if not model:
        logger.warning("[llm_router][openai] %s not set in .env -- skipping",
                       "OPENAI_VISION_MODEL" if image_bytes else "OPENAI_MODEL")
        return None
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
        r = _post_with_retry(f"{base}/chat/completions", label=key_label or "openai", json=payload, headers=headers, timeout=timeout, verify=_SSL_VERIFY)
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

    Token budget enforcement (R3):
        Prompts exceeding task budget are truncated before request.
        max_tokens clamped to provider+task safe limits.

    Fallback cascade (R4):
        When ENABLE_TEXT_FALLBACK=true, tries fallback providers on failure.
    """
    if llm_disabled():
        return None
    validated = _validated_params(prompt, task, max_tokens, temperature)
    if not validated:
        return None
    prompt, max_tokens, temperature = validated

    provider = _resolve_provider(task)

    # ── R3: Token budget enforcement ──
    try:
        from report_builder.model_runtime.token_budget import resolve_budget, truncate_prompt
        budget = resolve_budget(task, provider, requested_max_tokens=max_tokens)
        max_tokens = budget.maxOutputTokens
        prompt = truncate_prompt(prompt, budget)
    except Exception as _budget_exc:
        logger.debug("[llm_router] Budget resolution failed (using legacy clamp): %s", _budget_exc)
        max_tokens = _clamp_tokens_for_provider(provider, max_tokens)

    # Resolve key from pool (rotation for all Groq tasks to spread across 8 keys)
    _ROTATE_TASKS = frozenset({"entity_extraction", "question_generation", "entity_binding", "fact_extraction", "gap_fill", "toc_extraction", "semantic_fallback", "entity_classification"})
    if task in _ROTATE_TASKS or provider == "groq":
        api_key, key_label = get_rotated_key_for_task(task, provider)
    else:
        api_key, key_label = get_api_key_for_task(task, provider)
    logger.info("[llm_router] task=%-22s provider=%-8s key=%-20s max_tok=%d prompt_len=%d", task, provider, key_label, max_tokens, len(prompt))

    # ── R4: Text fallback cascade ──
    try:
        from report_builder.model_runtime.fallback_policy import (
            resolve_fallback_chain, can_fallback_for_task, get_max_attempts,
        )
        text_fallback_enabled = can_fallback_for_task(task)
        fallback_chain = resolve_fallback_chain(task) if text_fallback_enabled else []
        max_attempts = get_max_attempts()
    except Exception:
        text_fallback_enabled = False
        fallback_chain = []
        max_attempts = 1

    # Build attempt list: primary first, then fallback chain (deduplicated)
    attempt_providers = [provider]
    if text_fallback_enabled and fallback_chain:
        for p in fallback_chain:
            if p not in attempt_providers:
                attempt_providers.append(p)
    attempt_providers = attempt_providers[:max_attempts]

    for attempt_provider in attempt_providers:
        attempt_max_tokens = _clamp_tokens_for_provider(attempt_provider, max_tokens)
        if attempt_provider == provider:
            attempt_key, attempt_label = api_key, key_label
        elif attempt_provider == "gemini":
            attempt_key, attempt_label = get_rotated_gemini_key()
            if not attempt_key:
                continue
            logger.info("[llm_router] Fallback %s->gemini for task=%s [%s]", provider, task, attempt_label)
        else:
            attempt_key, attempt_label = get_api_key_for_task(task, attempt_provider)
            if not attempt_key:
                continue  # Skip providers without keys
            logger.info("[llm_router] Fallback %s->%s for task=%s", provider, attempt_provider, task)

        try:
            if attempt_provider == "azure":
                result = _call_azure(prompt, None, attempt_max_tokens, temperature, api_key=attempt_key, key_label=attempt_label, task=task)
            elif attempt_provider == "gemini":
                result = _call_gemini(prompt, None, attempt_max_tokens, temperature, api_key=attempt_key, key_label=attempt_label, task=task)
            elif attempt_provider == "groq":
                result = _call_groq(prompt, None, attempt_max_tokens, temperature, api_key=attempt_key, key_label=attempt_label, task=task)
            elif attempt_provider == "openai":
                result = _call_openai(prompt, None, attempt_max_tokens, temperature, api_key=attempt_key, key_label=attempt_label, task=task)
            else:  # qwen
                result = _call_qwen_text(prompt, attempt_max_tokens, temperature, schema=schema)

            if result:
                if attempt_provider != provider:
                    logger.info("[llm_router] Text fallback %s->%s succeeded for task=%s", provider, attempt_provider, task)
                return result
        except Exception as _exc:
            logger.warning("[llm_router] [%s] %s text call failed for task=%s: %s", attempt_label, attempt_provider, task, _exc)

        # If text fallback not enabled, break after first attempt
        if not text_fallback_enabled:
            break

    return None


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

    Token budget enforcement (R3):
        Prompts exceeding task budget are truncated before request.
        max_tokens clamped to provider+task safe limits.

    Fallback cascade (R4):
        Uses fallback_policy.resolve_fallback_chain() instead of hardcoded VLM_FALLBACK_ORDER.
    """
    if llm_disabled():
        return None
    validated = _validated_params(prompt, task, max_tokens, temperature)
    if not validated:
        return None
    prompt, max_tokens, temperature = validated

    has_image = bool(image_bytes)
    provider = _resolve_provider(task)

    # ── R3: Token budget enforcement ──
    try:
        from report_builder.model_runtime.token_budget import resolve_budget, truncate_prompt
        budget = resolve_budget(task, provider, requested_max_tokens=max_tokens)
        max_tokens = budget.maxOutputTokens
        prompt = truncate_prompt(prompt, budget)
    except Exception as _budget_exc:
        logger.debug("[llm_router] Budget resolution failed (using legacy clamp): %s", _budget_exc)
        max_tokens = _clamp_tokens_for_provider(provider, max_tokens)

    # Resolve key from pool (rotation for all Groq tasks to spread across 8 keys)
    _ROTATE_TASKS = frozenset({"entity_extraction", "question_generation", "entity_binding", "fact_extraction", "gap_fill", "toc_extraction", "semantic_fallback", "entity_classification"})
    if task in _ROTATE_TASKS or provider == "groq":
        api_key, key_label = get_rotated_key_for_task(task, provider)
    else:
        api_key, key_label = get_api_key_for_task(task, provider)
    logger.info("[llm_router] task=%-22s provider=%-8s key=%-20s has_image=%s max_tok=%d prompt_len=%d", task, provider, key_label, has_image, max_tokens, len(prompt))

    # ── R4: Fallback chain via fallback_policy ──
    try:
        from report_builder.model_runtime.fallback_policy import (
            resolve_fallback_chain, can_fallback_for_task, get_max_attempts,
        )
        vision_fallback_enabled = can_fallback_for_task(task)
        fallback_chain = resolve_fallback_chain(task) if vision_fallback_enabled else []
        max_attempts = get_max_attempts()
    except Exception:
        # Legacy fallback: use VLM_FALLBACK_ORDER env directly
        _fallback_env = (os.getenv("VLM_FALLBACK_ORDER") or "openai,gemini,groq,qwen").strip()
        fallback_chain = [p.strip().lower() for p in _fallback_env.split(",") if p.strip()]
        vision_fallback_enabled = True
        max_attempts = len(fallback_chain) + 1

    # Build attempt list: primary first, then fallback (deduplicated, capped)
    attempt_providers = [provider]
    if vision_fallback_enabled:
        for p in fallback_chain:
            if p not in attempt_providers:
                attempt_providers.append(p)
    attempt_providers = attempt_providers[:max_attempts]

    for attempt_provider in attempt_providers:
        attempt_max_tokens = _clamp_tokens_for_provider(attempt_provider, max_tokens)
        # Resolve key for the attempt provider
        if attempt_provider == provider:
            attempt_key, attempt_label = api_key, key_label
        elif attempt_provider == "gemini":
            attempt_key, attempt_label = get_rotated_gemini_key()
            if not attempt_key:
                continue
        else:
            attempt_key, attempt_label = get_api_key_for_task(task, attempt_provider)
            if not attempt_key and attempt_provider not in ("qwen",):
                continue  # Skip cloud providers without keys
        result = None
        try:
            if attempt_provider == "azure":
                result = _call_azure(prompt, image_bytes if has_image else None, attempt_max_tokens, temperature, api_key=attempt_key, key_label=attempt_label, task=task)
            elif attempt_provider == "gemini":
                result = _call_gemini(prompt, image_bytes if has_image else None, attempt_max_tokens, temperature, api_key=attempt_key, key_label=attempt_label, task=task)
            elif attempt_provider == "groq":
                result = _call_groq(prompt, image_bytes if has_image else None, attempt_max_tokens, temperature, api_key=attempt_key, key_label=attempt_label, task=task)
            elif attempt_provider == "openai":
                result = _call_openai(prompt, image_bytes if has_image else None, attempt_max_tokens, temperature, api_key=attempt_key, key_label=attempt_label, task=task)
            else:  # qwen
                if has_image:
                    result = _call_qwen_vision(prompt, image_bytes, attempt_max_tokens, temperature, schema=schema)  # type: ignore[arg-type]
                else:
                    result = _call_qwen_text(prompt, attempt_max_tokens, temperature, schema=schema)
        except Exception as _fallback_exc:
            logger.warning("[llm_router] [%s] %s failed for task=%s: %s", attempt_label, attempt_provider, task, _fallback_exc)

        if result:
            if attempt_provider != provider:
                logger.info("[llm_router] Fallback %s->%s succeeded for task=%s", provider, attempt_provider, task)
            return result

        # For text-only calls without fallback enabled, don't cascade
        if not has_image and not vision_fallback_enabled:
            break

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
    if provider == "azure":
        # Key-presence check (same pattern as groq/gemini — no billable ping needed)
        return bool(os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"))
    logger.warning("[llm_router] Unknown provider '%s' — treating as unavailable", provider)
    return False


def summarize_provider_call_ledger(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a list of provider-call records into a provider trace.

    Each call record may carry: ``status``, ``task``, ``actualProvider``,
    ``schemaRequired``, ``schemaEnforced``, ``fallbackUsed``. The summary preserves the
    ``schemaRequiredCalls`` / ``schemaEnforcedCalls`` semantics consumed by the S3.5
    diagnostics gate (a schema-required call that was not API-enforced is a warning, not
    a blocker, outside strict enterprise mode).
    """
    status_counts: dict[str, int] = {}
    task_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    fallback_calls = 0
    schema_required = 0
    schema_enforced = 0

    for call in calls or []:
        if not isinstance(call, dict):
            continue
        status = str(call.get("status") or "")
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1
        task = str(call.get("task") or "")
        if task:
            task_counts[task] = task_counts.get(task, 0) + 1
        provider = str(call.get("actualProvider") or call.get("provider") or "")
        if provider:
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
        if call.get("fallbackUsed"):
            fallback_calls += 1
        if call.get("schemaRequired"):
            schema_required += 1
            if call.get("schemaEnforced"):
                schema_enforced += 1

    return {
        "totalCalls": len([c for c in (calls or []) if isinstance(c, dict)]),
        "statusCounts": status_counts,
        "taskCounts": task_counts,
        "providerCounts": provider_counts,
        "fallbackCalls": fallback_calls,
        "schemaRequiredCalls": schema_required,
        "schemaEnforcedCalls": schema_enforced,
    }
