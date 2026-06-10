"""Model Runtime — centralized governance for all LLM/VLM calls.

Submodules:
    config          RuntimeConfig contract (R0)
    token_budget    Model-aware token budget manager (R3)
    fallback_policy Task-specific fallback policy (R4)
    key_manager     Quota-aware key rotation (R2)
    call_ledger     Model call observability (R7)
"""
from report_builder.model_runtime.config import (
    RuntimeConfig,
    TaskConfig,
    ProviderHealth,
    build_runtime_config,
)

__all__ = [
    "RuntimeConfig",
    "TaskConfig",
    "ProviderHealth",
    "build_runtime_config",
]
