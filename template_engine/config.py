"""Pipeline configuration — all tuneable thresholds in one place.

Every hardcoded constant from the template engine is exposed here as an
environment-variable-configurable option with sensible defaults.

Usage:
    from template_engine.config import PipelineConfig
    cfg = PipelineConfig.from_env()
    # Use cfg.entity_similarity_threshold instead of magic 0.85
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _str(key: str, default: str) -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class VLMConfig:
    """VLM parsing configuration."""
    backend: str = ""                       # auto-detect if empty
    colpali_endpoint: str = "http://localhost:8080"
    page_timeout_s: float = 60.0
    max_retries: int = 2
    default_page_width: float = 595.0       # A4 points
    default_page_height: float = 842.0

    @classmethod
    def from_env(cls) -> VLMConfig:
        return cls(
            backend=_str("VLM_BACKEND", ""),
            colpali_endpoint=_str("COLPALI_ENDPOINT", "http://localhost:8080"),
            page_timeout_s=_float("VLM_PAGE_TIMEOUT", 60.0),
            max_retries=_int("VLM_MAX_RETRIES", 2),
        )


@dataclass(frozen=True)
class SGLangConfig:
    """SGLang grammar-constrained generation configuration."""
    backend: str = ""                       # auto-detect if empty
    endpoint: str = "http://localhost:30000"
    model: str = "default"
    timeout_s: float = 300.0
    max_retries: int = 3
    max_tokens: int = 8192
    temperature: float = 0.1
    decomposed: bool = True                 # Use 3-call decomposed generation

    @classmethod
    def from_env(cls) -> SGLangConfig:
        return cls(
            backend=_str("SGLANG_BACKEND", ""),
            endpoint=_str("SGLANG_ENDPOINT", "http://localhost:30000"),
            model=_str("SGLANG_MODEL", "default"),
            timeout_s=_float("SGLANG_TIMEOUT", 300.0),
            max_retries=_int("SGLANG_MAX_RETRIES", 3),
            max_tokens=_int("SGLANG_MAX_TOKENS", 8192),
            temperature=_float("SGLANG_TEMPERATURE", 0.1),
            decomposed=_str("SGLANG_DECOMPOSED", "true").lower() in ("1", "true", "yes"),
        )


@dataclass(frozen=True)
class EntityConfig:
    """Entity extraction and deduplication configuration."""
    similarity_threshold: float = 0.85      # Fuzzy match threshold for dedup
    min_entity_length: int = 2
    max_entity_length: int = 80
    confidence_boost_per_source: float = 0.05
    max_confidence_boost: float = 0.15

    @classmethod
    def from_env(cls) -> EntityConfig:
        return cls(
            similarity_threshold=_float("ENTITY_SIMILARITY_THRESHOLD", 0.85),
            min_entity_length=_int("ENTITY_MIN_LENGTH", 2),
            max_entity_length=_int("ENTITY_MAX_LENGTH", 80),
            confidence_boost_per_source=_float("ENTITY_CONFIDENCE_BOOST", 0.05),
            max_confidence_boost=_float("ENTITY_MAX_BOOST", 0.15),
        )


@dataclass(frozen=True)
class InferenceConfig:
    """Question inference cascade configuration."""
    confidence_threshold: float = 0.30      # Minimum to accept any question
    vlm_direct_min_confidence: float = 0.85
    pattern_min_confidence: float = 0.65
    hybrid_min_confidence: float = 0.60
    stub_confidence: float = 0.30

    @classmethod
    def from_env(cls) -> InferenceConfig:
        return cls(
            confidence_threshold=_float("INFERENCE_CONFIDENCE_THRESHOLD", 0.30),
            vlm_direct_min_confidence=_float("INFERENCE_VLM_MIN_CONF", 0.85),
            pattern_min_confidence=_float("INFERENCE_PATTERN_MIN_CONF", 0.65),
            hybrid_min_confidence=_float("INFERENCE_HYBRID_MIN_CONF", 0.60),
            stub_confidence=_float("INFERENCE_STUB_CONF", 0.30),
        )


@dataclass(frozen=True)
class ReviewConfig:
    """Template reviewer configuration."""
    min_topics: int = 2
    min_questions: int = 3
    min_entities: int = 5
    min_confidence: float = 0.4

    @classmethod
    def from_env(cls) -> ReviewConfig:
        return cls(
            min_topics=_int("REVIEW_MIN_TOPICS", 2),
            min_questions=_int("REVIEW_MIN_QUESTIONS", 3),
            min_entities=_int("REVIEW_MIN_ENTITIES", 5),
            min_confidence=_float("REVIEW_MIN_CONFIDENCE", 0.4),
        )


@dataclass(frozen=True)
class VerifierConfig:
    """Verifier agent tolerance configuration."""
    default_tolerance: float = 0.05         # ±5% default
    domain_tolerance_path: str = ""         # Optional JSON file with per-domain overrides

    @classmethod
    def from_env(cls) -> VerifierConfig:
        return cls(
            default_tolerance=_float("VERIFIER_DEFAULT_TOLERANCE", 0.05),
            domain_tolerance_path=_str("VERIFIER_DOMAIN_TOLERANCE_PATH", ""),
        )

    def get_tolerance(self, domain: str = "", entity_type: str = "") -> float:
        """Get effective tolerance for a domain + entity-type combination.

        Cascade: entity_type override > domain override > default.
        """
        tolerances = self._load_domain_tolerances()
        if not tolerances:
            return self.default_tolerance

        domain_cfg = tolerances.get(domain, {})
        # Entity-type override within domain
        if entity_type and entity_type in domain_cfg:
            return float(domain_cfg[entity_type])
        # Domain default
        if "default" in domain_cfg:
            return float(domain_cfg["default"])
        return self.default_tolerance

    def _load_domain_tolerances(self) -> dict[str, Any]:
        if not self.domain_tolerance_path:
            return {}
        p = Path(self.domain_tolerance_path)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}


@dataclass(frozen=True)
class CheckpointConfig:
    """Checkpoint/resume configuration."""
    enabled: bool = False
    backend: str = "auto"                   # auto | file | db
    file_dir: str = "./checkpoints"

    @classmethod
    def from_env(cls) -> CheckpointConfig:
        return cls(
            enabled=_str("CHECKPOINT_ENABLED", "false").lower() in ("1", "true", "yes"),
            backend=_str("CHECKPOINT_BACKEND", "auto"),
            file_dir=_str("CHECKPOINT_DIR", "./checkpoints"),
        )


@dataclass(frozen=True)
class PipelineConfig:
    """Top-level configuration aggregating all sub-configs."""
    vlm: VLMConfig = field(default_factory=VLMConfig)
    sglang: SGLangConfig = field(default_factory=SGLangConfig)
    entity: EntityConfig = field(default_factory=EntityConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    verifier: VerifierConfig = field(default_factory=VerifierConfig)
    checkpoint: CheckpointConfig = field(default_factory=CheckpointConfig)

    @classmethod
    def from_env(cls) -> PipelineConfig:
        """Load full pipeline configuration from environment variables."""
        return cls(
            vlm=VLMConfig.from_env(),
            sglang=SGLangConfig.from_env(),
            entity=EntityConfig.from_env(),
            inference=InferenceConfig.from_env(),
            review=ReviewConfig.from_env(),
            verifier=VerifierConfig.from_env(),
            checkpoint=CheckpointConfig.from_env(),
        )


# Singleton — loaded once per process
_config: PipelineConfig | None = None


def get_config() -> PipelineConfig:
    """Get or create the global pipeline configuration."""
    global _config
    if _config is None:
        _config = PipelineConfig.from_env()
    return _config


def reset_config() -> None:
    """Reset singleton (for tests that modify env vars)."""
    global _config
    _config = None
