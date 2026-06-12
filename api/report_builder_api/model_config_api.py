"""Model Configuration API.

Exposes the active RuntimeConfig so the frontend (and developers) can see
exactly which model/provider/token-budget is live for every task — no guessing
from .env files.

Endpoints
---------
GET  /model-config/active      Full resolved config: profile + per-task model/provider/tokens
GET  /model-config/profiles    All available profiles with descriptions
POST /model-config/reload      Reload config from env (no restart needed after .env edit)
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends
from deps import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/model-config", tags=["model-config"])

# Module-level cache — built once, invalidated by /reload
_cached_config: dict[str, Any] | None = None


def _build_active_config() -> dict[str, Any]:
    """Build a safe (no secrets) snapshot of the active RuntimeConfig."""
    from report_builder.model_runtime.config import (
        build_runtime_config,
        _MODEL_PROFILES,
    )
    cfg = build_runtime_config()

    task_table = []
    for task_name, tc in sorted(cfg.taskConfigs.items()):
        task_table.append({
            "task": tc.task,
            "provider": tc.provider,
            "modelName": tc.modelName,
            "modality": tc.modality,
            "maxOutputTokens": tc.maxOutputTokens,
            "maxInputChars": tc.maxInputChars,
            "temperature": tc.temperature,
            "fallbackOrder": tc.fallbackOrder,
            "schemaRequired": tc.schemaRequired,
        })

    return {
        "activeProfile": cfg.modelProfile,
        "vlmProvider": cfg.vlmProvider,
        "reasoningProvider": cfg.reasoningProvider,
        "enrichmentEnabled": cfg.enrichmentEnabled,
        "enrichmentProvider": cfg.enrichmentProvider,
        "llmDisabled": cfg.llmDisabled,
        "cacheMode": cfg.cacheMode,
        "keyPool": cfg.keyPool.to_dict(),
        "fallback": {
            "visionFallbackEnabled": cfg.visionFallbackEnabled,
            "textFallbackEnabled": cfg.textFallbackEnabled,
            "fallbackOnParseError": cfg.fallbackOnParseError,
            "fallbackOnRateLimit": cfg.fallbackOnRateLimit,
            "fallbackMaxAttempts": cfg.fallbackMaxAttempts,
        },
        "tasks": task_table,
        "openrouterBase": os.getenv("OPENAI_BASE_URL", ""),
        "groqBase": os.getenv("GROQ_BASE_URL", ""),
    }


def _get_profiles_info() -> dict[str, Any]:
    """Return all available profiles with descriptions (no secrets)."""
    from report_builder.model_runtime.config import _MODEL_PROFILES
    active = (os.getenv("MODEL_PROFILE") or "local_first").strip()
    profiles = {}
    for name, p in _MODEL_PROFILES.items():
        profiles[name] = {
            "name": name,
            "description": p.get("description", ""),
            "vlmProvider": p.get("vlmProvider", ""),
            "reasoningProvider": p.get("reasoningProvider", ""),
            "enrichmentEnabled": p.get("enrichmentEnabled", False),
            "taskModelHints": p.get("taskModelHints", {}),
            "active": name == active,
        }
    return {"activeProfile": active, "profiles": profiles}


@router.get("/active")
def get_active_config(_: int = Depends(get_current_user_id)) -> dict[str, Any]:
    """Return the fully resolved model config (profile + per-task model/provider/tokens).

    Call this from the frontend to display which model is active for each task.
    No secrets are returned — API keys are never included.
    """
    global _cached_config
    if _cached_config is None:
        _cached_config = _build_active_config()
    return _cached_config


@router.get("/profiles")
def get_profiles(_: int = Depends(get_current_user_id)) -> dict[str, Any]:
    """Return all available MODEL_PROFILE values with their descriptions.

    Useful for a UI dropdown that lets admins see which profile is active
    and what each profile does.
    """
    return _get_profiles_info()


@router.post("/reload")
def reload_config(_: int = Depends(get_current_user_id)) -> dict[str, Any]:
    """Re-read all model config from environment variables without restarting.

    Call after editing .env and reloading environment (e.g. via dotenv reload or
    after the process manager updates env vars). Returns the newly built config.
    """
    global _cached_config
    _cached_config = _build_active_config()
    logger.info("[model-config] Config reloaded: profile=%s", _cached_config.get("activeProfile"))
    return {"reloaded": True, "config": _cached_config}
