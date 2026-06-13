"""R4 — Task-Specific Fallback Policy.

Resolves fallback chains per task. Supports both vision and text fallback.

Usage:
    from report_builder.model_runtime.fallback_policy import resolve_fallback_chain, should_fallback

    chain = resolve_fallback_chain("entity_extraction", config)
    # ["qwen", "gemini", "groq"]

    if should_fallback(error_type, config):
        next_provider = chain[attempt_index]
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Fallback trigger classification
# ─────────────────────────────────────────────────────────────────────────────

class FallbackTrigger:
    CONNECTION_ERROR = "connection_error"
    RATE_LIMIT = "rate_limit"
    CONTEXT_OVERFLOW = "context_overflow"
    JSON_PARSE_ERROR = "json_parse_error"
    EMPTY_RESULT = "empty_result"
    TIMEOUT = "timeout"
    QUOTA_EXHAUSTED = "quota_exhausted"
    UNKNOWN_ERROR = "unknown_error"


def should_fallback(trigger: str, config: Any | None = None) -> bool:
    """Decide whether a specific error type should trigger fallback.

    Uses config gates:
    - FALLBACK_ON_PARSE_ERROR
    - FALLBACK_ON_RATE_LIMIT
    - FALLBACK_ON_CONTEXT_OVERFLOW
    """
    # Always fallback on these
    if trigger in (FallbackTrigger.CONNECTION_ERROR, FallbackTrigger.TIMEOUT, FallbackTrigger.QUOTA_EXHAUSTED):
        return True

    if config is None:
        # Default behavior without config
        return trigger != FallbackTrigger.CONTEXT_OVERFLOW

    if trigger == FallbackTrigger.RATE_LIMIT:
        return config.fallbackOnRateLimit
    if trigger == FallbackTrigger.JSON_PARSE_ERROR:
        return config.fallbackOnParseError
    if trigger == FallbackTrigger.CONTEXT_OVERFLOW:
        return config.fallbackOnContextOverflow
    if trigger == FallbackTrigger.EMPTY_RESULT:
        return True

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Fallback chain resolution
# ─────────────────────────────────────────────────────────────────────────────

# Vision tasks (use VLM fallback order as legacy default)
_VISION_TASKS = frozenset({"entity_extraction", "question_generation"})


def resolve_fallback_chain(task: str, config: Any | None = None) -> list[str]:
    """Resolve the ordered fallback chain for a given task.

    Priority:
    1. Explicit env: FALLBACK_<TASK_UPPER>=qwen,gemini,groq
    2. RuntimeConfig task config fallbackOrder
    3. VLM_FALLBACK_ORDER (for vision tasks)
    4. Primary provider only (no fallback)
    """
    task_upper = task.upper()

    # 1. Explicit env override
    env_chain = (os.getenv(f"FALLBACK_{task_upper}") or "").strip()
    if env_chain:
        chain = [p.strip().lower() for p in env_chain.split(",") if p.strip()]
        if chain:
            return chain

    # 2. RuntimeConfig task config
    if config is not None:
        task_cfg = config.task(task)
        if task_cfg.fallbackOrder:
            return list(task_cfg.fallbackOrder)

    # 3. Legacy VLM_FALLBACK_ORDER for vision tasks
    if task in _VISION_TASKS:
        vlm_fallback = (os.getenv("VLM_FALLBACK_ORDER") or "").strip()
        if vlm_fallback:
            return [p.strip().lower() for p in vlm_fallback.split(",") if p.strip()]

    # 4. No fallback (single provider)
    return []


def get_max_attempts(config: Any | None = None) -> int:
    """Get maximum fallback attempts from config or env."""
    if config is not None:
        return config.fallbackMaxAttempts
    val = (os.getenv("FALLBACK_MAX_ATTEMPTS") or "3").strip()
    try:
        return int(val)
    except ValueError:
        return 3


def is_text_fallback_enabled(config: Any | None = None) -> bool:
    """Check if text task fallback is enabled."""
    if config is not None:
        return config.textFallbackEnabled
    return (os.getenv("ENABLE_TEXT_FALLBACK") or "true").strip().lower() in ("1", "true", "yes", "on")


def is_vision_fallback_enabled(config: Any | None = None) -> bool:
    """Check if vision task fallback is enabled."""
    if config is not None:
        return config.visionFallbackEnabled
    return (os.getenv("ENABLE_VISION_FALLBACK") or "true").strip().lower() in ("1", "true", "yes", "on")


def can_fallback_for_task(task: str, config: Any | None = None) -> bool:
    """Check if fallback is allowed for a specific task type."""
    if task in _VISION_TASKS:
        return is_vision_fallback_enabled(config)
    return is_text_fallback_enabled(config)
