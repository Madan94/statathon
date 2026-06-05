"""PLFS style rules engine — applies domain-specific sentence patterns.

Loads patterns from plfs_style_rules.json and provides:
  - Pattern selection based on question type / comparison context
  - Precision formatting per metric type
  - Indian numbering format
  - Hedging logic for small changes
"""
from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RULES_PATH = Path(__file__).parent / "patterns" / "plfs_style_rules.json"
_rules_cache: dict[str, Any] | None = None


def _load_rules() -> dict[str, Any]:
    """Load style rules from JSON file."""
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache
    if _RULES_PATH.exists():
        with open(_RULES_PATH, "r", encoding="utf-8") as f:
            _rules_cache = json.load(f)
    else:
        _rules_cache = {}
    return _rules_cache


def get_precision_format(metric_type: str) -> dict[str, Any]:
    """Get precision formatting rules for a metric type (percentage, count, ratio, index)."""
    rules = _load_rules()
    return rules.get("precision_rules", {}).get(metric_type, {})


def format_value(value: float, metric_type: str = "percentage") -> str:
    """Format a numeric value according to PLFS precision rules."""
    rules = _load_rules()
    precision = rules.get("precision_rules", {}).get(metric_type, {})
    fmt = precision.get("format", "{value}")
    try:
        return fmt.format(value=value)
    except (ValueError, KeyError):
        return str(value)


def format_indian_number(value: float) -> str:
    """Format number in Indian numbering system (lakhs/crores)."""
    rules = _load_rules()
    threshold = rules.get("formatting_rules", {}).get("lakh_crore_threshold", 100000)
    if abs(value) < threshold:
        return f"{value:,.0f}"
    if abs(value) >= 10_000_000:
        return f"{value / 10_000_000:.2f} crore"
    if abs(value) >= 100_000:
        return f"{value / 100_000:.2f} lakh"
    return f"{value:,.0f}"


def select_pattern(
    pattern_type: str,
    context: dict[str, str] | None = None,
) -> str:
    """Select a sentence pattern for the given type, optionally filling placeholders.

    Args:
        pattern_type: e.g. "trend_increase", "comparison_higher", "composition"
        context: dict of placeholder values to fill

    Returns:
        Formatted sentence or raw pattern template.
    """
    rules = _load_rules()
    patterns = rules.get("sentence_patterns", {}).get(pattern_type, [])
    if not patterns:
        return ""

    # Pick a pattern (deterministic for same context, else random)
    if context:
        idx = hash(frozenset(context.items())) % len(patterns)
    else:
        idx = random.randint(0, len(patterns) - 1)

    template = patterns[idx]
    if context:
        try:
            return template.format(**context)
        except KeyError:
            return template
    return template


def get_comparison_template(comparison_type: str) -> dict[str, Any]:
    """Get comparison template for rural_urban, male_female, quarterly, annual."""
    rules = _load_rules()
    return rules.get("comparison_templates", {}).get(comparison_type, {})


def get_hedge_qualifier(change: float) -> str:
    """Get hedging qualifier for a given change magnitude.

    Returns empty string if change is significant, otherwise a hedge phrase.
    """
    rules = _load_rules()
    hedging = rules.get("hedging_rules", {})
    threshold = hedging.get("significant_change_threshold", 1.0)

    if abs(change) < threshold:
        phrases = hedging.get("hedge_phrases", ["broadly stable"])
        idx = int(abs(change) * 10) % len(phrases)
        return phrases[idx]
    return ""


def resolve_terminology(abbreviation: str) -> str:
    """Resolve a PLFS abbreviation to its full term."""
    rules = _load_rules()
    terminology = rules.get("terminology", {})
    return terminology.get(abbreviation, abbreviation)


def get_source_citation() -> str:
    """Get the standard PLFS source citation line."""
    rules = _load_rules()
    return rules.get("formatting_rules", {}).get(
        "source_citation",
        "Source: Periodic Labour Force Survey (PLFS), MoSPI, GoI",
    )
