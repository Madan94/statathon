"""
Optional Gemini-assisted domain score refinement.
Never replaces deterministic scores wholesale — only nudges ambiguous columns when configured.
"""
from __future__ import annotations

import json
import os
from typing import Any


def apply_gemini_domain_adjustment(
    column_name: str,
    scores: dict[str, float],
    archetype: str,
) -> dict[str, float] | None:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top, second = sorted_scores[0], sorted_scores[1] if len(sorted_scores) > 1 else ("", 0.0)
    margin = float(top[1]) - float(second[1])
    if margin >= 0.08:
        return None

    try:
        from core.gemini_client import get_generative_model
    except ImportError:
        return None

    model = get_generative_model(os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash"))
    if model is None:
        return None

    prompt = f"""You assist official statistical metadata governance.
Column name: {column_name}
Dataset archetype hint: {archetype}
Current domain score distribution (JSON): {json.dumps(dict(sorted_scores[:12]), ensure_ascii=True)}

Return ONLY valid JSON object mapping domain_key -> float weight in [0,1].
Rules:
- Keys MUST be a subset of the domain keys provided above.
- Adjustments must be small (max delta 0.04 per domain vs input).
- Preserve ranking unless evidence strongly favors swap.
- Do not invent new domain keys.
"""
    resp = model.generate_content(prompt)
    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    adjusted = json.loads(text)
    if not isinstance(adjusted, dict):
        return None

    out = dict(scores)
    for k, v in adjusted.items():
        if k not in scores:
            continue
        try:
            delta = float(v) - scores[k]
            delta = max(-0.04, min(0.04, delta))
            out[k] = max(0.0, min(1.0, scores[k] + delta))
        except (TypeError, ValueError):
            continue
    return out
