"""
Gemini-backed generalized domain title generation for Semantic Mapping V2.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger(__name__)


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "429" in msg
        or "rate limit" in msg
        or "resource exhausted" in msg
        or "quota" in msg
    )


def _strip_markdown_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def generate_domain_titles(
    dataset_archetype: str,
    column_names: list[str],
    datatypes: dict[str, str] | None = None,
    column_metadata: dict[str, Any] | None = None,
) -> list[dict[str, str]] | None:
    """
    Generate generalized semantic domains covering the dataset columns.

    Returns:
        List of {"domain_name", "data_value_summary"} dicts, or None on failure.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None

    try:
        import google.generativeai as genai
    except ImportError:
        return None

    model_name = os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash")
    payload = {
        "dataset_archetype": dataset_archetype,
        "column_names": column_names,
        "datatypes": datatypes or {},
        "column_metadata": column_metadata or {},
    }

    prompt = f"""
You are a strict Data Taxonomy Engine for an enterprise pipeline. Your objective is to categorize a list of database columns into unified Semantic Domains and profile their literal data signatures.

INPUT DATA:
{json.dumps(payload, ensure_ascii=True)}

INSTRUCTIONS & CONSTRAINTS:
1. GENERALIZATION: Group logically related columns under a single, highly specific `domain_name` (e.g., "Space and Aerospace Engineering", "Labor and Wage Statistics"). Do NOT create a unique domain for every column.
2. THE DATA SIGNATURE: For each domain, generate a `data_value_summary`.
   - CONSTRAINT 1: Maximum 10 words.
   - CONSTRAINT 2: Summarize ONLY the literal sample values and datatypes provided in the input. 
   - CONSTRAINT 3: Do NOT infer business purpose, add external context, or write a "description".
   - GOOD Example: "Numerical weights (0-5000) and categorical identifiers."
   - BAD Example: "Data used to track satellite payload metrics." (Violation: Hallucinated context).

OUTPUT FORMAT:
You must output ONLY a valid, parseable JSON object with no markdown formatting or extra text.
{{
  "domains": [
    {{
      "domain_name": "String",
      "data_value_summary": "String"
    }}
  ]
}}
"""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    timeout_sec = int(os.getenv("GEMINI_REQUEST_TIMEOUT_SEC", "90"))

    parsed: dict[str, Any] | None = None
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                prompt,
                request_options={"timeout": timeout_sec},
            )
            raw = (response.text or "").strip()
            if not raw:
                logger.warning("Gemini returned empty response for domain titles")
                return None
            loaded = json.loads(_strip_markdown_json_fence(raw))
            if isinstance(loaded, dict):
                parsed = loaded
            break
        except Exception as exc:
            if _is_rate_limit_error(exc) and attempt < max_retries - 1:
                wait_seconds = 5 * (2 ** attempt)
                logger.warning("Gemini rate limit; retrying in %ss", wait_seconds)
                time.sleep(wait_seconds)
                continue
            logger.warning("Gemini domain title generation failed: %s", exc)
            return None

    if not isinstance(parsed, dict):
        return None

    domains = parsed.get("domains")
    if not isinstance(domains, list):
        return None

    parsed_domains: list[dict[str, str]] = []
    for entry in domains:
        if not isinstance(entry, dict):
            continue
        domain_name = str(entry.get("domain_name") or "").strip()
        if not domain_name:
            continue
        parsed_domains.append(
            {
                "domain_name": domain_name,
                "data_value_summary": str(entry.get("data_value_summary") or "").strip(),
            }
        )

    if not parsed_domains:
        return None
    return parsed_domains


__all__ = ["generate_domain_titles"]
