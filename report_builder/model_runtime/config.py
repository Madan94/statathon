"""R0 — RuntimeConfig Contract.

Single source of truth for all model/provider/token/cache/fallback decisions.
Built once at pipeline startup, passed to all extraction phases.

No module outside this package should call os.getenv() for model/provider/token
decisions. They read from RuntimeConfig instead.

Usage:
    from report_builder.model_runtime import build_runtime_config
    config = build_runtime_config()
    # Pass config to pipeline phases
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Contract version
# ─────────────────────────────────────────────────────────────────────────────

RUNTIME_CONTRACT_VERSION = "model.runtime.v1"

# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ProviderHealth:
    """Live health state for one provider."""
    provider: str
    healthy: bool = True
    lastError: str | None = None
    cooldownUntil: float = 0.0
    consecutiveFailures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "healthy": self.healthy,
            "lastError": self.lastError,
            "consecutiveFailures": self.consecutiveFailures,
        }


@dataclass
class TaskConfig:
    """Resolved configuration for one extraction task."""
    task: str
    modality: str = "text"               # "vision" | "text" | "vision_or_text"
    provider: str = "qwen"               # Resolved provider
    modelName: str = ""                  # Resolved model name for this task
    fallbackOrder: list[str] = field(default_factory=list)
    maxOutputTokens: int = 256
    maxInputChars: int = 2500
    temperature: float = 0.1
    cacheable: bool = True
    schemaRequired: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "modality": self.modality,
            "provider": self.provider,
            "modelName": self.modelName,
            "fallbackOrder": self.fallbackOrder,
            "maxOutputTokens": self.maxOutputTokens,
            "maxInputChars": self.maxInputChars,
            "temperature": self.temperature,
            "cacheable": self.cacheable,
            "schemaRequired": self.schemaRequired,
        }


@dataclass
class KeyPoolSummary:
    """Summary of key pool state (no secrets exposed)."""
    totalSlots: int = 0
    validSlots: int = 0
    byProvider: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalSlots": self.totalSlots,
            "validSlots": self.validSlots,
            "byProvider": dict(self.byProvider),
        }


@dataclass
class RuntimeConfig:
    """Central runtime configuration. Built once, read everywhere.

    Resolves all model/provider/token/cache/fallback decisions from env vars
    and model profile presets. Serializable for diagnostics.
    """
    contractVersion: str = RUNTIME_CONTRACT_VERSION

    # Profile
    modelProfile: str = "local_first"

    # Per-task resolved configs
    taskConfigs: dict[str, TaskConfig] = field(default_factory=dict)

    # Provider health
    providerHealth: dict[str, ProviderHealth] = field(default_factory=dict)

    # Key pool
    keyPool: KeyPoolSummary = field(default_factory=KeyPoolSummary)

    # Cache
    cacheMode: str = "fresh"             # fresh | resume | force | debug
    cacheBackend: str = "auto"           # redis | file | disabled | auto
    cachePipelineVersion: str = ""

    # Feature gates
    enrichmentEnabled: bool = False
    enrichmentProvider: str = "gemini"
    visionFallbackEnabled: bool = True
    textFallbackEnabled: bool = True
    guidedJson: bool = True
    selfConsistency: bool = True
    llmDisabled: bool = False

    # Global providers
    vlmProvider: str = "qwen"
    reasoningProvider: str = "qwen"

    # Fallback control
    fallbackOnParseError: bool = True
    fallbackOnRateLimit: bool = True
    fallbackOnContextOverflow: bool = False
    fallbackMaxAttempts: int = 3

    def task(self, name: str) -> TaskConfig:
        """Get resolved task config by name. Returns default if not registered."""
        return self.taskConfigs.get(name, TaskConfig(task=name))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contractVersion,
            "modelProfile": self.modelProfile,
            "taskConfigs": {k: v.to_dict() for k, v in self.taskConfigs.items()},
            "providerHealth": {k: v.to_dict() for k, v in self.providerHealth.items()},
            "keyPool": self.keyPool.to_dict(),
            "cacheMode": self.cacheMode,
            "cacheBackend": self.cacheBackend,
            "cachePipelineVersion": self.cachePipelineVersion,
            "enrichmentEnabled": self.enrichmentEnabled,
            "enrichmentProvider": self.enrichmentProvider,
            "visionFallbackEnabled": self.visionFallbackEnabled,
            "textFallbackEnabled": self.textFallbackEnabled,
            "guidedJson": self.guidedJson,
            "selfConsistency": self.selfConsistency,
            "llmDisabled": self.llmDisabled,
            "vlmProvider": self.vlmProvider,
            "reasoningProvider": self.reasoningProvider,
            "fallbackMaxAttempts": self.fallbackMaxAttempts,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Task profile defaults (declarative — what each task needs)
# ─────────────────────────────────────────────────────────────────────────────

_TASK_PROFILES: dict[str, dict[str, Any]] = {
    "entity_extraction": {
        "modality": "vision",
        "defaultProvider": "qwen",
        "fallbackOrder": ["qwen", "gemini", "groq"],
        "maxOutputTokens": 256,
        "maxInputChars": 2500,
        "temperature": 0.1,
        "schemaRequired": True,
    },
    "question_generation": {
        "modality": "vision",
        "defaultProvider": "qwen",
        "fallbackOrder": ["qwen", "gemini", "groq", "openai"],
        "maxOutputTokens": 600,
        "maxInputChars": 6000,
        "temperature": 0.15,
        "schemaRequired": True,
    },
    "entity_binding": {
        "modality": "text",
        "defaultProvider": "openai",
        "fallbackOrder": ["openai", "gemini", "groq", "qwen"],
        "maxOutputTokens": 384,
        "maxInputChars": 5000,
        "temperature": 0.1,
        "schemaRequired": False,
    },
    "toc_extraction": {
        "modality": "text",
        "defaultProvider": "openai",
        "fallbackOrder": ["openai", "groq", "gemini"],
        "maxOutputTokens": 1000,
        "maxInputChars": 8000,
        "temperature": 0.1,
        "schemaRequired": False,
    },
    "gap_fill": {
        "modality": "text",
        "defaultProvider": "gemini",
        "fallbackOrder": ["gemini", "groq", "openai"],
        "maxOutputTokens": 1000,
        "maxInputChars": 12000,
        "temperature": 0.2,
        "schemaRequired": False,
    },
    "fact_extraction": {
        "modality": "text",
        "defaultProvider": "openai",
        "fallbackOrder": ["openai", "groq", "gemini"],
        "maxOutputTokens": 1200,
        "maxInputChars": 10000,
        "temperature": 0.15,
        "schemaRequired": False,
    },
    "semantic_fallback": {
        "modality": "text",
        "defaultProvider": "openai",
        "fallbackOrder": ["openai", "gemini", "groq"],
        "maxOutputTokens": 2000,
        "maxInputChars": 12000,
        "temperature": 0.2,
        "schemaRequired": False,
    },
    "semantic_enrichment": {
        "modality": "text",
        "defaultProvider": "gemini",
        "fallbackOrder": ["gemini", "openai", "groq"],
        "maxOutputTokens": 2000,
        "maxInputChars": 20000,
        "temperature": 0.1,
        "cacheable": False,
        "schemaRequired": False,
    },
    "entity_classification": {
        "modality": "text",
        "defaultProvider": "openai",
        "fallbackOrder": ["openai", "groq", "gemini"],
        "maxOutputTokens": 600,
        "maxInputChars": 8000,
        "temperature": 0.1,
        "schemaRequired": False,
    },
    "question_repair": {
        "modality": "text",
        "defaultProvider": "groq",
        "fallbackOrder": ["groq", "openai", "gemini"],
        "maxOutputTokens": 800,
        "maxInputChars": 6000,
        "temperature": 0.1,
        "schemaRequired": False,
    },
}

# Vision tasks (use VLM_PROVIDER as global default)
_VISION_TASKS = frozenset({"entity_extraction", "question_generation"})

# Env var that overrides the provider for a specific task
_TASK_PROVIDER_ENVS: dict[str, str] = {
    "entity_extraction": "PROVIDER_ENTITY_EXTRACTION",
    "question_generation": "PROVIDER_QUESTION_GENERATION",
    "entity_binding": "PROVIDER_ENTITY_BINDING",
    "toc_extraction": "PROVIDER_TOC_EXTRACTION",
    "gap_fill": "PROVIDER_GAP_FILL",
    "fact_extraction": "PROVIDER_FACT_EXTRACTION",
    "semantic_fallback": "PROVIDER_SEMANTIC_FALLBACK",
    "semantic_enrichment": "PROVIDER_SEMANTIC_ENRICHMENT",
    "entity_classification": "PROVIDER_ENTITY_CLASSIFICATION",
    "question_repair": "PROVIDER_QUESTION_REPAIR",
}

# Env var for per-task token/temperature overrides
_TASK_TOKEN_ENVS: dict[str, str] = {
    "entity_extraction": "ENTITY_EXTRACTION_MAX_TOKENS",
    "question_generation": "QUESTION_GENERATION_MAX_TOKENS",
    "entity_binding": "ENTITY_BINDING_MAX_TOKENS",
    "toc_extraction": "TOC_EXTRACTION_MAX_TOKENS",
    "gap_fill": "GAP_FILL_MAX_TOKENS",
    "fact_extraction": "FACT_EXTRACTION_MAX_TOKENS",
    "semantic_fallback": "SEMANTIC_FALLBACK_MAX_TOKENS",
    "entity_classification": "ENTITY_CLASSIFICATION_MAX_TOKENS",
}

_TASK_TEMP_ENVS: dict[str, str] = {
    "entity_extraction": "ENTITY_EXTRACTION_TEMPERATURE",
    "question_generation": "QUESTION_GENERATION_TEMPERATURE",
    "entity_binding": "ENTITY_BINDING_TEMPERATURE",
    "toc_extraction": "TOC_EXTRACTION_TEMPERATURE",
    "gap_fill": "GAP_FILL_TEMPERATURE",
    "fact_extraction": "FACT_EXTRACTION_TEMPERATURE",
    "semantic_fallback": "SEMANTIC_FALLBACK_TEMPERATURE",
    "entity_classification": "ENTITY_CLASSIFICATION_TEMPERATURE",
}

# Env var for per-task model name overrides (TASK_<TASK>_MODEL)
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
}


# ─────────────────────────────────────────────────────────────────────────────
# Model capability profiles (what each model can safely handle)
# ─────────────────────────────────────────────────────────────────────────────

MODEL_CAPABILITIES: dict[str, dict[str, Any]] = {
    "qwen_vl_3b": {
        "provider": "qwen",
        "contextWindow": 2048,
        "safeOutput": 256,
        "safeInput": 1800,
        "modalities": ["vision", "text"],
        "bestFor": ["entity_extraction", "question_generation"],
        "avoidFor": ["long_reasoning", "enrichment"],
    },
    "qwen_vl_7b": {
        "provider": "qwen",
        "contextWindow": 4096,
        "safeOutput": 512,
        "safeInput": 3500,
        "modalities": ["vision", "text"],
        "bestFor": ["entity_extraction", "question_generation"],
        "avoidFor": ["enrichment"],
    },
    "qwen_vl_plus": {
        "provider": "openai",  # via OpenRouter
        "contextWindow": 256000,
        "safeOutput": 4000,
        "safeInput": 20000,
        "modalities": ["vision", "text"],
        "bestFor": ["entity_extraction", "question_generation"],
        "avoidFor": [],
        "modelId": "qwen/qwen3-vl-plus",
    },
    "qwen35_flash": {
        "provider": "openai",  # via OpenRouter
        "contextWindow": 1000000,
        "safeOutput": 65500,
        "safeInput": 80000,
        "modalities": ["text"],
        "bestFor": ["entity_binding", "gap_fill", "semantic_fallback", "toc_extraction",
                    "fact_extraction", "entity_classification", "question_repair"],
        "avoidFor": ["vision"],
        "modelId": "qwen/qwen3.5-flash-02-23",
        "supportsReasoning": True,
        "inputPricePerM": 0.065,
        "outputPricePerM": 0.26,
    },
    "gemma2_9b": {
        "provider": "openai",
        "contextWindow": 8192,
        "safeOutput": 1200,
        "safeInput": 6000,
        "modalities": ["text"],
        "bestFor": ["entity_binding", "toc_extraction", "entity_classification"],
        "avoidFor": ["vision"],
    },
    "gemini_flash": {
        "provider": "gemini",
        "contextWindow": 1000000,
        "safeOutput": 4000,
        "safeInput": 20000,
        "modalities": ["vision", "text"],
        "bestFor": ["semantic_enrichment", "gap_fill", "fallback"],
        "avoidFor": ["high_volume_per_page"],
    },
    "groq_llama33_70b": {
        "provider": "groq",
        "contextWindow": 131072,
        "safeOutput": 8000,
        "safeInput": 12000,
        "modalities": ["text"],
        "bestFor": ["fast_text_reasoning", "question_repair", "entity_binding",
                    "toc_extraction", "gap_fill"],
        "avoidFor": ["vision"],
        "modelId": "llama-3.3-70b-versatile",
    },
    "groq_scout": {
        "provider": "groq",
        "contextWindow": 131072,
        "safeOutput": 2000,
        "safeInput": 12000,
        "modalities": ["text"],
        "bestFor": ["fast_text_reasoning", "question_repair", "entity_binding"],
        "avoidFor": ["vision"],
    },
    "gpt4o_mini": {
        "provider": "openai",
        "contextWindow": 128000,
        "safeOutput": 4000,
        "safeInput": 10000,
        "modalities": ["vision", "text"],
        "bestFor": ["entity_binding", "question_repair"],
        "avoidFor": ["high_volume"],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Model profiles (presets)
# ─────────────────────────────────────────────────────────────────────────────

_MODEL_PROFILES: dict[str, dict[str, Any]] = {
    "local_first": {
        "vlmProvider": "qwen",
        "reasoningProvider": "openai",
        "enrichmentEnabled": False,
        "description": "Qwen-VL + Gemma2:9b/Ollama. Zero cloud. Free.",
    },
    "openrouter_cheap_dev": {
        "vlmProvider": "qwen",
        "reasoningProvider": "openai",
        "enrichmentEnabled": False,
        "description": "Qwen-VL local + OpenRouter DeepSeek text. Cheap and strong.",
    },
    "openrouter_balanced": {
        "vlmProvider": "qwen",
        "reasoningProvider": "openai",
        "enrichmentEnabled": True,
        "enrichmentProvider": "openai",
        "description": "Qwen-VL + OpenRouter DeepSeek + enrichment enabled.",
    },
    # ── NEW: Full OpenRouter with Qwen3.5-Flash for all text tasks ─────────────────────────
    "openrouter_qwen35_flash": {
        "vlmProvider": "openai",       # OpenRouter Qwen3-VL-Plus for vision
        "reasoningProvider": "openai", # OpenRouter Qwen3.5-Flash for text (OPENAI_MODEL)
        "enrichmentEnabled": False,
        "visionFallbackEnabled": True,
        "textFallbackEnabled": True,
        "description": "All tasks via OpenRouter: Qwen3-VL-Plus (vision) + Qwen3.5-Flash (text, 1M ctx, cheap).",
        "taskModelHints": {
            "entity_extraction":    "qwen/qwen3-vl-plus",
            "question_generation":  "qwen/qwen3-vl-plus",
            "entity_binding":       "qwen/qwen3.5-flash-02-23",
            "entity_classification":"qwen/qwen3.5-flash-02-23",
            "toc_extraction":       "qwen/qwen3.5-flash-02-23",
            "gap_fill":             "qwen/qwen3.5-flash-02-23",
            "fact_extraction":      "qwen/qwen3.5-flash-02-23",
            "semantic_fallback":    "qwen/qwen3.5-flash-02-23",
            "semantic_enrichment":  "qwen/qwen3.5-flash-02-23",
            "question_repair":      "qwen/qwen3.5-flash-02-23",
        },
    },
    # ── NEW: All text tasks on Groq (llama-3.3-70b OSS, fast free tier) ──────────────────
    "groq_oss_all": {
        "vlmProvider": "openai",       # OpenRouter Qwen3-VL-Plus for vision
        "reasoningProvider": "groq",   # Groq 8-key rotation for text
        "enrichmentEnabled": False,
        "visionFallbackEnabled": True,
        "textFallbackEnabled": True,
        "description": "Vision: OpenRouter Qwen3-VL-Plus. Text: Groq llama-3.3-70b (8-key rotation, free tier).",
        "taskModelHints": {
            "entity_extraction":    "qwen/qwen3-vl-plus",
            "question_generation":  "qwen/qwen3-vl-plus",
            "entity_binding":       "llama-3.3-70b-versatile",
            "entity_classification":"llama-3.3-70b-versatile",
            "toc_extraction":       "llama-3.3-70b-versatile",
            "gap_fill":             "llama-3.3-70b-versatile",
            "fact_extraction":      "llama-3.3-70b-versatile",
            "semantic_fallback":    "llama-3.3-70b-versatile",
            "question_repair":      "llama-3.3-70b-versatile",
        },
    },
    # ── NEW: Fully local ─────────────────────────────────────────────────────────────
    "local_qwen_full": {
        "vlmProvider": "qwen",         # Local SGLang Qwen-VL for vision
        "reasoningProvider": "qwen",   # Local SGLang Qwen for text
        "enrichmentEnabled": False,
        "visionFallbackEnabled": False,
        "textFallbackEnabled": False,
        "description": "100% local SGLang Qwen-VL. Zero cloud. Offline/air-gapped.",
    },
    "qwen_groq_hybrid": {
        "vlmProvider": "qwen",
        "reasoningProvider": "groq",
        "enrichmentEnabled": False,
        "description": "Qwen-VL + Groq free tier. Fast text reasoning.",
    },
    "qwen_gemini_enriched": {
        "vlmProvider": "qwen",
        "reasoningProvider": "gemini",
        "enrichmentEnabled": True,
        "enrichmentProvider": "gemini",
        "description": "Qwen-VL + Gemini Flash. High quality. Uses quota.",
    },
    "cloud_fallback_full": {
        "vlmProvider": "qwen",
        "reasoningProvider": "groq",
        "enrichmentEnabled": True,
        "enrichmentProvider": "gemini",
        "visionFallbackEnabled": True,
        "textFallbackEnabled": True,
        "description": "Full fallback chains. Maximum reliability.",
    },
    # ── UPDATED: EC2 hosted ──────────────────────────────────────────────────────────
    "ec2_hosted_full": {
        "vlmProvider": "openai",        # OpenRouter Qwen3-VL-Plus for vision
        "reasoningProvider": "openai",  # OpenRouter Qwen3.5-Flash for text
        "enrichmentEnabled": False,
        "enrichmentProvider": "groq",
        "visionFallbackEnabled": True,
        "textFallbackEnabled": True,
        "description": "LayoutLM on EC2 + OpenRouter Qwen3-VL-Plus (vision) + Qwen3.5-Flash (text, 1M ctx).",
        "taskModelHints": {
            "entity_extraction":    "qwen/qwen3-vl-plus",
            "question_generation":  "qwen/qwen3-vl-plus",
            "entity_binding":       "qwen/qwen3.5-flash-02-23",
            "entity_classification":"qwen/qwen3.5-flash-02-23",
            "toc_extraction":       "qwen/qwen3.5-flash-02-23",
            "gap_fill":             "qwen/qwen3.5-flash-02-23",
            "fact_extraction":      "qwen/qwen3.5-flash-02-23",
            "semantic_fallback":    "qwen/qwen3.5-flash-02-23",
            "semantic_enrichment":  "llama-3.3-70b-versatile",  # Groq fallback for enrichment
            "question_repair":      "llama-3.3-70b-versatile",  # Groq for quick repairs
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────────────────────────────────────


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _env_bool(key: str, default: bool = False) -> bool:
    val = _env(key).lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off", ""):
        return default
    return default


def _env_int(key: str, default: int = 0) -> int:
    val = _env(key)
    try:
        return int(val) if val else default
    except ValueError:
        return default


def _env_float(key: str, default: float = 0.0) -> float:
    val = _env(key)
    try:
        return float(val) if val else default
    except ValueError:
        return default


def _resolve_task_config(task: str, profile_defaults: dict[str, Any]) -> TaskConfig:
    """Resolve a single task's config from: profile defaults → task env overrides."""
    defaults = _TASK_PROFILES.get(task, {})

    # Provider resolution: per-task env > global VLM/REASONING > profile > task default
    provider_env = _TASK_PROVIDER_ENVS.get(task, "")
    provider_override = _env(provider_env).lower() if provider_env else ""

    if provider_override:
        provider = provider_override
    elif task in _VISION_TASKS:
        provider = profile_defaults.get("vlmProvider", defaults.get("defaultProvider", "qwen"))
    else:
        provider = profile_defaults.get("reasoningProvider", defaults.get("defaultProvider", "qwen"))

    # Model name resolution:
    # 1. TASK_<TASK>_MODEL env var (highest priority — explicit per-task override)
    # 2. Profile taskModelHints (profile preset recommendations)
    # 3. Provider-global env (OPENAI_MODEL / GROQ_MODEL / etc.)
    model_name = ""
    model_env = _TASK_MODEL_ENVS.get(task, "")
    if model_env:
        model_name = _env(model_env)
    if not model_name:
        task_hints = profile_defaults.get("taskModelHints", {})
        model_name = task_hints.get(task, "")
    if not model_name:
        # Fall back to provider global
        is_vision = task in _VISION_TASKS
        if provider == "openai":
            model_name = _env("OPENAI_VISION_MODEL" if is_vision else "OPENAI_MODEL", "")
        elif provider == "groq":
            model_name = _env("GROQ_VISION_MODEL" if is_vision else "GROQ_MODEL", "")
        elif provider == "gemini":
            model_name = _env("GEMINI_MODEL", "gemini-2.5-flash")
        else:
            model_name = _env("SGLANG_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct-AWQ")

    # Token override: per-task env > Qwen model-specific > task default
    token_env = _TASK_TOKEN_ENVS.get(task, "")
    max_tokens = _env_int(token_env) if token_env and _env(token_env) else 0

    # Model-specific override for Qwen (tighter budgets for small model)
    if not max_tokens and provider == "qwen":
        if task == "entity_extraction":
            max_tokens = _env_int("QWEN_ENTITY_MAX_OUTPUT", defaults.get("maxOutputTokens", 256))
        elif task == "question_generation":
            max_tokens = _env_int("QWEN_QUESTION_MAX_OUTPUT", defaults.get("maxOutputTokens", 600))
        else:
            max_tokens = min(defaults.get("maxOutputTokens", 500), 500)

    if not max_tokens:
        max_tokens = defaults.get("maxOutputTokens", 256)

    # Input chars: Qwen-specific override or default
    max_input = defaults.get("maxInputChars", 2500)
    if provider == "qwen":
        max_input = min(max_input, _env_int("QWEN_PROMPT_MAX_CHARS", 2500))

    # Temperature override
    temp_env = _TASK_TEMP_ENVS.get(task, "")
    temperature = _env_float(temp_env) if temp_env and _env(temp_env) else defaults.get("temperature", 0.1)

    # Fallback order: per-task env > task default
    fallback_env = _env(f"FALLBACK_{task.upper()}")
    if fallback_env:
        fallback_order = [p.strip().lower() for p in fallback_env.split(",") if p.strip()]
    else:
        fallback_order = list(defaults.get("fallbackOrder", []))

    return TaskConfig(
        task=task,
        modality=defaults.get("modality", "text"),
        provider=provider,
        modelName=model_name,
        fallbackOrder=fallback_order,
        maxOutputTokens=max_tokens,
        maxInputChars=max_input,
        temperature=temperature,
        cacheable=defaults.get("cacheable", True),
        schemaRequired=defaults.get("schemaRequired", False),
    )


def _build_key_pool_summary() -> KeyPoolSummary:
    """Summarize key pool state without exposing secrets."""
    summary = KeyPoolSummary()
    for i in range(1, 11):
        provider = _env(f"KEY_{i}_PROVIDER").lower()
        value = _env(f"KEY_{i}_VALUE")
        if provider and value:
            summary.totalSlots += 1
            summary.validSlots += 1
            summary.byProvider[provider] = summary.byProvider.get(provider, 0) + 1
    # Also count legacy keys
    if _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY"):
        summary.byProvider.setdefault("gemini", 0)
        summary.byProvider["gemini"] += 1
        summary.totalSlots += 1
        summary.validSlots += 1
    if _env("GROQ_API_KEY"):
        summary.byProvider.setdefault("groq", 0)
        summary.byProvider["groq"] += 1
        summary.totalSlots += 1
        summary.validSlots += 1
    if _env("OPENAI_API_KEY"):
        summary.byProvider.setdefault("openai", 0)
        summary.byProvider["openai"] += 1
        summary.totalSlots += 1
        summary.validSlots += 1
    return summary


def build_runtime_config() -> RuntimeConfig:
    """Build the complete RuntimeConfig from environment.

    Resolution order:
    1. MODEL_PROFILE env → load preset defaults
    2. Explicit env overrides (VLM_PROVIDER, REASONING_PROVIDER, etc.)
    3. Per-task env overrides (PROVIDER_X, X_MAX_TOKENS, etc.)
    4. Key pool availability
    → Final RuntimeConfig
    """
    # 1. Load profile
    profile_name = _env("MODEL_PROFILE", "local_first")
    profile = _MODEL_PROFILES.get(profile_name, _MODEL_PROFILES["local_first"])

    # 2. Global provider overrides (env > profile > default)
    vlm_provider = _env("VLM_PROVIDER") or profile.get("vlmProvider", "qwen")
    reasoning_provider = _env("REASONING_PROVIDER") or profile.get("reasoningProvider", "qwen")

    profile_defaults = {
        "vlmProvider": vlm_provider,
        "reasoningProvider": reasoning_provider,
        # Forward profile-level task model hints so _resolve_task_config can use them
        "taskModelHints": profile.get("taskModelHints", {}),
    }

    # 3. Resolve all task configs
    all_tasks = list(_TASK_PROFILES.keys())
    task_configs = {task: _resolve_task_config(task, profile_defaults) for task in all_tasks}

    # 4. Feature gates
    enrichment_enabled = _env_bool("ENRICHMENT_ENABLED", profile.get("enrichmentEnabled", False))
    enrichment_provider = _env("ENRICHMENT_PROVIDER") or profile.get("enrichmentProvider", "gemini")

    # 5. Cache
    cache_mode = _env("CHECKPOINT_MODE", "fresh")
    cache_backend = _env("CHECKPOINT_BACKEND", "auto")
    cache_pipeline_version = _env("CHECKPOINT_PIPELINE_VERSION", "extraction_v2")

    # 6. Fallback globals
    vision_fallback = _env_bool("ENABLE_VISION_FALLBACK", profile.get("visionFallbackEnabled", True))
    text_fallback = _env_bool("ENABLE_TEXT_FALLBACK", profile.get("textFallbackEnabled", True))
    fallback_on_parse = _env_bool("FALLBACK_ON_PARSE_ERROR", True)
    fallback_on_rate = _env_bool("FALLBACK_ON_RATE_LIMIT", True)
    fallback_on_overflow = _env_bool("FALLBACK_ON_CONTEXT_OVERFLOW", False)
    fallback_max = _env_int("FALLBACK_MAX_ATTEMPTS", 3)

    # 7. Other gates
    guided_json = _env_bool("GUIDED_JSON", True)
    self_consistency = _env_bool("SELF_CONSISTENCY", True)
    llm_disabled = _env("LLM_DISABLED").lower() in ("1", "true", "yes", "on")

    # 8. Key pool summary
    key_pool = _build_key_pool_summary()

    # 9. Provider health (initialized healthy, updated at runtime)
    providers = {"qwen", "gemini", "groq", "openai"}
    provider_health = {p: ProviderHealth(provider=p) for p in providers}

    config = RuntimeConfig(
        modelProfile=profile_name,
        taskConfigs=task_configs,
        providerHealth=provider_health,
        keyPool=key_pool,
        cacheMode=cache_mode,
        cacheBackend=cache_backend,
        cachePipelineVersion=cache_pipeline_version,
        enrichmentEnabled=enrichment_enabled,
        enrichmentProvider=enrichment_provider,
        visionFallbackEnabled=vision_fallback,
        textFallbackEnabled=text_fallback,
        guidedJson=guided_json,
        selfConsistency=self_consistency,
        llmDisabled=llm_disabled,
        vlmProvider=vlm_provider,
        reasoningProvider=reasoning_provider,
        fallbackOnParseError=fallback_on_parse,
        fallbackOnRateLimit=fallback_on_rate,
        fallbackOnContextOverflow=fallback_on_overflow,
        fallbackMaxAttempts=fallback_max,
    )

    logger.info(
        "[runtime-config] Built: profile=%s vlm=%s reasoning=%s enrichment=%s cache=%s tasks=%d keys=%d",
        config.modelProfile,
        config.vlmProvider,
        config.reasoningProvider,
        "ON" if config.enrichmentEnabled else "OFF",
        config.cacheMode,
        len(config.taskConfigs),
        config.keyPool.validSlots,
    )

    return config
