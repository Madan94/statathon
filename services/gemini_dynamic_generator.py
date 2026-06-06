"""
Gemini-backed semantic anchor generation for dynamic latent domains.

Ingests mathematically clustered column cohorts (with Phase 1 static proximity
hints) and returns a strict JSON title/description pair for use as a dynamic
domain bullseye in the semantic mapping pipeline.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "429" in msg
        or "rate limit" in msg
        or "resource exhausted" in msg
        or "quota" in msg
    )

def _dynamic_anchor_enabled() -> bool:
    raw = os.getenv("GEMINI_DYNAMIC_ANCHOR_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _strip_markdown_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def generate_semantic_anchor(
    dataset_archetype: str,
    cohort_data: list[dict[str, Any]],
) -> dict[str, str] | None:
    """
    Generate a deterministic semantic title and description for a latent domain cohort.

    Args:
        dataset_archetype: Global dataset domain (e.g. ``economic_survey``).
        cohort_data: Column objects with ``column_name`` and ``phase_1_correlations``
            (static domain name → score, values > 0.50).

    Returns:
        ``{"title": str, "description": str}`` on success, else ``None`` when the API
        is unavailable, the model response is invalid, or parsing fails.
    """
    if not _dynamic_anchor_enabled():
        return None

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("⚠️ DEBUG: API Key is missing from environment!")
        return None

    try:
        import google.generativeai as genai
    except ImportError:
        return None

    model_name = os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash")
    cohort_json = json.dumps(cohort_data, ensure_ascii=True)

    prompt = f"""You are an official statistical metadata governor for national survey data.

Dataset archetype: {dataset_archetype}

Cohort payload (column names and Phase 1 latent-space correlation coordinates):
{cohort_json}

Analyze the column names and their phase_1_correlations scores (proximity to static
sub-domains) to deduce the specific statistical sub-domain this cohort represents.

Return ONLY a raw, parsable JSON object with exactly two keys:
- "title": A 2-to-3 word specific domain name (e.g. "Agricultural Subsidies").
- "description": A comma-separated list of exactly 5 hyper-specific keywords (no full sentences, no filler words). This string is embedded as the dynamic-domain bullseye and compared via cosine similarity to each column name vector.

No markdown, no commentary, no extra keys."""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    parsed: dict[str, Any] | None = None
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            raw = (response.text or "").strip()
            if not raw:
                return None
            loaded = json.loads(_strip_markdown_json_fence(raw))
            if isinstance(loaded, dict):
                parsed = loaded
            break
        except Exception as e:
            if _is_rate_limit_error(e) and attempt < max_retries - 1:
                wait_seconds = 5 * (2 ** attempt)
                print(
                    f"⚠️ DEBUG: Gemini rate limit (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait_seconds}s: {e}"
                )
                time.sleep(wait_seconds)
                continue
            print(f"⚠️ DEBUG: LLM API Error: {e}")
            return None

    if not isinstance(parsed, dict):
        return None

    title = parsed.get("title")
    description = parsed.get("description")
    if not isinstance(title, str) or not isinstance(description, str):
        return None

    title = title.strip()
    description = description.strip()
    if not title or not description:
        return None

    return {"title": title, "description": description}


__all__ = ["generate_semantic_anchor"]
