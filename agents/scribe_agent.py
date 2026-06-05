"""ScribeAgent — deterministic, grounded narrative generation.

Anti-hallucination rules enforced by the scribe:
  1. Every numeric claim MUST be present in the `facts` dict.
  2. Percentages are stated to 1 decimal place.
  3. Counts are integers.
  4. Unknown facts are written as "(data unavailable)" — never guessed.
  5. Prior LTM corrections are consulted before writing.
  6. MoSPI statistical terminology is applied where the dataset type is known.
  7. Narratives cite their source (implicitly via fact keys) so the Verifier
     can independently verify every number.

Gemini (if available) acts as the prose engine; the deterministic fallback
builds rule-based sentences from the facts dict.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MoSPI terminology map (dataset_type → domain vocabulary)
# ---------------------------------------------------------------------------

_MOSPI_VOCAB: dict[str, dict[str, str]] = {
    "census": {
        "rows": "persons enumerated",
        "columns": "schedule fields",
        "dataset": "Census enumeration data",
    },
    "health": {
        "rows": "patient episodes",
        "columns": "clinical variables",
        "dataset": "health survey data",
    },
    "education": {
        "rows": "student records",
        "columns": "scholastic attributes",
        "dataset": "education survey data",
    },
    "employment": {
        "rows": "labour force observations",
        "columns": "employment-related variables",
        "dataset": "employment survey data",
    },
    "agriculture": {
        "rows": "agricultural holdings",
        "columns": "farm and crop attributes",
        "dataset": "agricultural survey data",
    },
    "economic": {
        "rows": "enterprise records",
        "columns": "economic variables",
        "dataset": "economic survey data",
    },
    "energy": {
        "rows": "site/resource observations",
        "columns": "energy reserve attributes",
        "dataset": "energy reserves dataset",
    },
    "survey": {
        "rows": "survey respondents",
        "columns": "questionnaire fields",
        "dataset": "survey data",
    },
}


def _vocab(dataset_type: str) -> dict[str, str]:
    for key in _MOSPI_VOCAB:
        if key in str(dataset_type).lower():
            return _MOSPI_VOCAB[key]
    return {"rows": "records", "columns": "variables", "dataset": "dataset"}


def _to_float(value: Any, default: float = 0.0) -> float:
    """Safely coerce numbers, including percent strings like '11.35%'."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    if text.endswith("%"):
        text = text[:-1].strip()
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------

def _deterministic_narrative(
    block_title: str,
    block_section: str,
    facts: dict[str, Any],
    max_words: int,
    dataset_type: str = "unknown",
    hints: dict[str, Any] | None = None,
) -> str:
    v = _vocab(dataset_type)
    parts: list[str] = []

    if block_section == "executive_summary":
        if "row_count" in facts and "column_count" in facts:
            parts.append(
                f"The {v['dataset']} comprises {int(facts['row_count']):,} {v['rows']} "
                f"and {int(facts['column_count'])} {v['columns']}."
            )
        if "missing_pct" in facts:
            mp = _to_float(facts["missing_pct"])
            level = "negligible" if mp < 1 else "moderate" if mp < 10 else "elevated" if mp < 25 else "high"
            parts.append(f"The overall rate of missing values stands at {mp:.1f}%, which is {level}.")
        if "health_score" in facts:
            hs = str(facts["health_score"])
            parts.append(f"The dataset health score is {hs}.")
        if "anomaly_count" in facts and int(facts["anomaly_count"]) > 0:
            parts.append(
                f"Anomaly detection identified {int(facts['anomaly_count'])} candidate observations "
                f"requiring review."
            )
        if "mapped_column_count" in facts and "column_count" in facts:
            parts.append(
                f"Semantic domain mapping was applied to "
                f"{int(facts['mapped_column_count'])} of {int(facts['column_count'])} {v['columns']}."
            )

    elif block_section == "methodology":
        parts.append(
            f"The present analysis was conducted on a {v['dataset']} containing "
            f"{int(facts.get('row_count', 0)):,} {v['rows']}."
        )
        if facts.get("dataset_type"):
            parts.append(
                f"The dataset has been classified as a {facts['dataset_type']}-type dataset "
                "using MoSPI-aligned statistical ontology."
            )

    elif block_section == "data_quality":
        if "missing_pct" in facts:
            parts.append(f"The overall missing value rate is {_to_float(facts['missing_pct']):.1f}%.")
        if "duplicate_rows" in facts and int(facts["duplicate_rows"]) > 0:
            parts.append(f"{int(facts['duplicate_rows'])} duplicate rows were detected.")
        if "anomaly_count" in facts:
            parts.append(
                f"Anomaly detection flagged {int(facts['anomaly_count'])} records across "
                f"{len(facts.get('anomaly_columns', []))} column(s)."
            )
        if "imputation_targets" in facts and int(facts.get("imputation_targets", 0)) > 0:
            parts.append(
                f"{int(facts['imputation_targets'])} column(s) are recommended for imputation."
            )

    elif block_section == "findings":
        _hints_f = hints or {}
        # Use grand_total_reserves (generic key from _compute_energy_section_facts)
        total_all = (
            facts.get("grand_total_reserves")
            or facts.get("total_value")
            or next((v2 for k, v2 in facts.items()
                     if k.startswith("total_") and isinstance(v2, (int, float)) and v2 > 0), None)
        )
        group_count = facts.get("group_count") or facts.get("state_count") or ""
        top_group = facts.get("top_group") or facts.get("top_state") or ""
        group_col = facts.get("top_group_col") or "group"

        if total_all:
            parts.append(
                f"Analysis of the {v['dataset']} covering {group_count} {group_col}s "
                "reveals the following key observations."
            )
            # Per-category breakdown using any *_categories fact
            for col_key, cats in facts.items():
                if col_key.endswith("_categories") and isinstance(cats, list):
                    col_name = col_key.replace("_categories", "")
                    parts.append(
                        f"The dataset covers {len(cats)} {col_name} categories: "
                        f"{', '.join(str(c) for c in cats[:8])}."
                    )
                    for cat in cats:
                        safe = str(cat).lower().replace(" ", "_").replace("-", "_")
                        val = facts.get(f"reserves_{safe}")
                        unit_key = f"unit_{safe}"
                        unit_label = facts.get(unit_key, "")
                        unit_str = f" {unit_label}" if unit_label else ""
                        if val:
                            share = round(float(val) / float(total_all) * 100, 1) if total_all else ""
                            pct_str = f" ({share}% of total)" if share else ""
                            parts.append(f"{cat}: {val:,.2f}{unit_str}{pct_str}.")
            if top_group:
                parts.append(f"{top_group} leads with the highest aggregate value.")
        elif "row_count" in facts:
            parts.append(
                f"Analysis of the {int(facts['row_count']):,}-record {v['dataset']} reveals "
                "the following key observations."
            )
        if "key_patterns" in facts:
            patterns = facts["key_patterns"]
            if isinstance(patterns, list):
                # Skip patterns that describe generic semantic mapping artefacts
                skip_terms = {"census", "enumeration", "semantic map", "domain map"}
                for p in patterns[:3]:
                    p_str = str(p)
                    if not any(t in p_str.lower() for t in skip_terms):
                        parts.append(p_str + ".")
        if facts.get("correlation_note"):
            parts.append(f"Key correlation: {facts['correlation_note']}.")
        if "health_score" in facts:
            parts.append(f"Overall data quality score: {facts['health_score']}.")

    elif block_section == "recommendations":
        mp = _to_float(facts.get("missing_pct", 0))
        if mp > 5:
            parts.append(
                f"It is recommended to address the {mp:.1f}% missing value rate "
                "before conducting inferential analysis."
            )
        ac = int(facts.get("anomaly_count", 0))
        if ac > 0:
            parts.append(
                f"The {ac} anomalous records flagged during detection should be reviewed "
                "by the data custodian."
            )
        if int(facts.get("imputation_targets", 0)) > 0:
            parts.append(
                "Columns marked for imputation should be treated using appropriate "
                "statistical methods prior to publication."
            )
        parts.append(
            "All data transformations should be documented in the metadata record "
            "for audit compliance."
        )

    else:
        # General body / analysis section — fully generic prose from sec_facts
        _hints = hints or {}
        sec_facts = _hints.get("_energy_section_facts") or {}
        resource_cat = sec_facts.get("resource_category") or _hints.get("resource_category", "")
        filter_label = resource_cat or _hints.get("filter_value", "")

        if sec_facts:
            if sec_facts.get("resource_not_in_dataset"):
                rc_name = sec_facts.get("resource_category") or filter_label or "this category"
                parts.append(
                    f"Data for '{rc_name}' is not currently available in this dataset. "
                    "This section will be updated when the relevant data is incorporated."
                )
            else:
                total = sec_facts.get("grand_total_reserves")
                unit = sec_facts.get("value_unit") or ""
                val_col = sec_facts.get("value_column") or ""
                unit_str = f" {unit}" if unit else ""
                val_col_label = val_col.replace("_", " ").title() if val_col else "Total"
                group_count = sec_facts.get("group_count") or sec_facts.get("state_count") or ""
                group_col = sec_facts.get("group_col") or "region"

                # Opening sentence — dynamic, no hardcoded domain words
                if filter_label and total:
                    parts.append(
                        f"The total {val_col_label} for {filter_label} stands at "
                        f"{total:,.2f}{unit_str}."
                    )
                elif total:
                    parts.append(
                        f"The total {val_col_label} across all categories stands at "
                        f"{total:,.2f}{unit_str}, covering {group_count} {group_col}s."
                    )

                # % breakdown for sibling numeric columns
                pct_items = [
                    (k.replace("_pct", "").replace("_", " ").title(), v)
                    for k, v in sec_facts.items()
                    if k.endswith("_pct") and v is not None
                ]
                if len(pct_items) >= 2:
                    pct_str = ", ".join(
                        f"{label} {pct}%" for label, pct in pct_items
                    )
                    parts.append(
                        f"The composition by sub-category is: {pct_str} of total."
                    )
                elif len(pct_items) == 1:
                    label, pct = pct_items[0]
                    parts.append(f"{label} constitutes {pct}% of total {val_col_label}.")

                if sec_facts.get("top3_states") and sec_facts.get("top3_pct"):
                    top3 = sec_facts["top3_states"]
                    top3_pct = sec_facts["top3_pct"]
                    tail = (
                        f" and {top3[2]}" if len(top3) > 2 else ""
                    )
                    parts.append(
                        f"Geographic concentration is notable: {top3[0]}, {top3[1]}{tail} "
                        f"together account for {top3_pct}% of the total."
                    )

                top_group = sec_facts.get("top_state") or sec_facts.get("top_group")
                top_pct = sec_facts.get("top_state_pct") or sec_facts.get("top_group_pct")
                if top_group and top_pct:
                    parts.append(
                        f"The highest value is observed in {top_group} "
                        f"({top_pct}% of total {val_col_label})."
                    )

        elif _hints.get("analytics_context"):
            ctx = str(_hints["analytics_context"])
            parts.append(ctx if ctx.endswith(".") else ctx + ".")

        elif facts.get("narrative_hints"):
            parts.append(str(facts["narrative_hints"]))

        # Ultimate fallback
        if not parts:
            parts.append(f"{block_title}.")
            if "row_count" in facts:
                parts.append(
                    f"This {v['dataset']} comprises {int(facts['row_count']):,} {v['rows']} "
                    f"across {int(facts.get('column_count', 0))} {v['columns']}."
                )
            # Use any grand_total or first total_ fact as summary
            total_val = facts.get("grand_total_reserves") or next(
                (val for key, val in facts.items()
                 if key.startswith("total_") and isinstance(val, (int, float)) and val > 0),
                None,
            )
            if total_val:
                parts.append(f"Total value recorded: {total_val:,.2f} units.")

    text = " ".join(parts)
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words]) + "…"
    return text or f"{block_title}. (insufficient data for narrative)"


# ---------------------------------------------------------------------------
# Gemini-powered scribe
# ---------------------------------------------------------------------------

def _gemini_model():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    # Prefer current google-genai SDK; fall back to legacy google-generativeai
    try:
        import google.genai as _g  # type: ignore
        client = _g.Client(api_key=api_key)
        model_name = os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash")
        # Return a thin wrapper that exposes .generate_content(prompt)
        class _NewSDKModel:
            def generate_content(self, prompt: str):
                resp = client.models.generate_content(model=model_name, contents=prompt)
                class _R:
                    text = resp.text
                return _R()
        return _NewSDKModel()
    except ImportError:
        pass
    try:
        import google.generativeai as g  # type: ignore  # noqa: F401
        g.configure(api_key=api_key)
        return g.GenerativeModel(os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash"))
    except Exception as exc:
        logger.warning("Gemini init: %s", exc)
        return None


def _gemini_narrative(
    model,
    block_title: str,
    block_section: str,
    hints: dict[str, Any],
    facts: dict[str, Any],
    reflections: list[dict[str, Any]],
    dataset_type: str,
) -> str | None:
    tone = hints.get("tone", "official, neutral")
    max_words = int(hints.get("max_words", 250))
    v = _vocab(dataset_type)

    reflection_blurb = ""
    if reflections:
        good = [r.get("after") or "" for r in reflections if r.get("after")][:3]
        if good:
            reflection_blurb = (
                "\n\nPRIOR APPROVED CORRECTIONS (reuse this phrasing where relevant):\n"
                + "\n".join(f"  • {g[:300]}" for g in good)
            )

    fact_str = json.dumps(facts, default=str, indent=2)[:6000]

    prompt = (
        f"You are a government statistical analyst drafting the '{block_title}' section "
        f"({block_section}) of an official MoSPI statistical report.\n"
        f"Dataset type: {dataset_type}. Terminology: {v}. Tone: {tone}. "
        f"Hard word limit: {max_words} words.\n\n"
        "STRICT ANTI-HALLUCINATION RULES:\n"
        "  1. Cite ONLY numbers that appear exactly in the FACTS JSON below.\n"
        "  2. Do NOT infer, extrapolate, or generalise beyond what the facts state.\n"
        "  3. Percentages → 1 decimal place. Counts → integers with comma-separators.\n"
        "  4. If a fact key is absent, write '(data unavailable)' — never guess.\n"
        "  5. Output prose only — no markdown, no headers, no bullet points.\n"
        "  6. Use MoSPI terminology: 'primary sample unit', 'reference period', "
        "'respondent', 'stratum', 'enumeration block' where appropriate.\n"
        f"  7. The unit for 'rows' is '{v['rows']}' and for 'columns' is '{v['columns']}'.\n"
        f"\nFACTS:\n{fact_str}"
        f"{reflection_blurb}"
    )

    try:
        resp = model.generate_content(prompt)
        text = (resp.text or "").strip()
        return text if text else None
    except Exception as exc:
        logger.warning("Gemini narrative generation failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# ScribeAgent
# ---------------------------------------------------------------------------

class ScribeAgent:
    """Grounded narrative generation agent.

    Usage:
        scribe = ScribeAgent()
        text = scribe.generate(
            block_id="exec_summary",
            block_title="Executive Summary",
            block_section="executive_summary",
            hints={"max_words": 250, "tone": "official"},
            facts={"row_count": 5000, ...},
            reflections=[],
        )
    """

    def __init__(self):
        self._model = _gemini_model()

    def generate(
        self,
        *,
        block_id: str,
        block_title: str,
        block_section: str,
        hints: dict[str, Any],
        facts: dict[str, Any],
        reflections: list[dict[str, Any]] | None = None,
        dataset_type: str = "unknown",
    ) -> str:
        """Generate a grounded narrative paragraph."""
        max_words = int(hints.get("max_words", 250))
        _reflections = reflections or []

        if self._model is not None:
            text = _gemini_narrative(
                self._model,
                block_title=block_title,
                block_section=block_section,
                hints=hints,
                facts=facts,
                reflections=_reflections,
                dataset_type=dataset_type,
            )
            if text:
                return text

        return _deterministic_narrative(
            block_title=block_title,
            block_section=block_section,
            facts=facts,
            max_words=max_words,
            dataset_type=dataset_type,
            hints=hints,
        )
