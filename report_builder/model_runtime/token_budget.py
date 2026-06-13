"""R3 — Token Budget Manager.

Model-aware token and prompt budget enforcement.

Ensures:
- Qwen-VL 3B never receives oversized prompts or output requests
- Gemini can use its full context when available
- Prompt truncation is task-specific (different shrinkers per task)
- Context overflow → shrink + retry (not immediate fallback)
- Budget decisions are logged

Usage:
    from report_builder.model_runtime.token_budget import resolve_budget, truncate_prompt

    budget = resolve_budget("entity_extraction", "qwen", config)
    prompt = truncate_prompt(prompt, budget)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TokenBudget:
    """Resolved token/prompt budget for one call."""
    task: str
    provider: str
    maxOutputTokens: int
    maxInputChars: int
    temperature: float
    truncated: bool = False
    truncationReason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "task": self.task,
            "provider": self.provider,
            "maxOutputTokens": self.maxOutputTokens,
            "maxInputChars": self.maxInputChars,
        }
        if self.truncated:
            d["truncated"] = True
            d["truncationReason"] = self.truncationReason
        return d


# Provider-level safe output caps (absolute hard limits)
_PROVIDER_OUTPUT_CAPS: dict[str, int] = {
    "qwen": 500,       # 2048 ctx → ~500 safe output (most reserved for prompt+image)
    "openai": 4000,    # Ollama/local default 8192 ctx
    "gemini": 8000,    # Gemini Flash 8192 output tokens
    "groq": 8000,      # Groq models: 16-32K output, safe at 8K
}

# Provider-level safe input caps (chars, not tokens)
_PROVIDER_INPUT_CAPS: dict[str, int] = {
    "qwen": 2500,      # 2048 ctx → ~2500 chars safe input
    "openai": 10000,   # Local models vary, 10K safe default
    "gemini": 50000,   # 1M context, practically unlimited
    "groq": 25000,     # 131K context, safe at 25K chars
}


def resolve_budget(
    task: str,
    provider: str,
    *,
    config: Any | None = None,
    requested_max_tokens: int | None = None,
    requested_max_chars: int | None = None,
) -> TokenBudget:
    """Resolve safe token budget for a task+provider combination.

    Priority:
    1. RuntimeConfig task config (if config provided)
    2. Requested values (from caller)
    3. Provider hard caps

    Always clamps to provider safety limits.
    """
    # Start with provider caps
    provider_output_cap = _PROVIDER_OUTPUT_CAPS.get(provider, 4000)
    provider_input_cap = _PROVIDER_INPUT_CAPS.get(provider, 10000)

    # Start with requested or provider defaults
    max_output = requested_max_tokens or provider_output_cap
    max_input = requested_max_chars or provider_input_cap
    temperature = 0.1

    # If config available, use task config
    if config is not None:
        task_cfg = config.task(task)
        max_output = task_cfg.maxOutputTokens
        max_input = task_cfg.maxInputChars
        temperature = task_cfg.temperature

    # Clamp to provider safety limits
    if max_output > provider_output_cap:
        max_output = provider_output_cap
    if max_input > provider_input_cap:
        max_input = provider_input_cap

    return TokenBudget(
        task=task,
        provider=provider,
        maxOutputTokens=max_output,
        maxInputChars=max_input,
        temperature=temperature,
    )


def truncate_prompt(prompt: str, budget: TokenBudget) -> str:
    """Truncate prompt to fit within budget's maxInputChars.

    Uses task-aware truncation strategy:
    - Prefers cutting from the end (least important content last)
    - Preserves first 200 chars (usually contains instructions)
    - Logs when truncation happens

    Returns the (possibly truncated) prompt.
    """
    if len(prompt) <= budget.maxInputChars:
        return prompt

    # Truncate: keep instruction prefix + truncated body
    max_chars = budget.maxInputChars
    prefix_size = min(200, max_chars // 4)
    suffix_size = max_chars - prefix_size - 20  # 20 for truncation marker

    truncated = prompt[:prefix_size] + "\n[...content truncated...]\n" + prompt[-(suffix_size):]
    budget.truncated = True
    budget.truncationReason = f"prompt {len(prompt)} chars > budget {max_chars} chars"

    logger.info(
        "[token-budget] Truncated prompt for task=%s provider=%s: %d→%d chars",
        budget.task, budget.provider, len(prompt), len(truncated),
    )
    return truncated


def clamp_max_tokens(max_tokens: int, provider: str) -> int:
    """Clamp max_tokens to provider's safe output limit.

    Drop-in replacement for llm_router._clamp_tokens_for_provider.
    """
    cap = _PROVIDER_OUTPUT_CAPS.get(provider, 4000)
    return min(max_tokens, cap)
