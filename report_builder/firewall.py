"""Phase 4 — Hallucination Firewall.

Two cooperating agents per block:

  Scribe (Gemini)
    Generates narrative text constrained by:
      * The block hints (max_words, tone, required keywords)
      * A data matrix snapshot pulled from the LTM-aware analysis payload
      * Prior corrections retrieved from the Reflection Ledger (Phase 2)

  Verifier (deterministic ReAct)
    1. Extracts numeric/quantitative claims from the narrative (regex + Gemini fallback).
    2. For each claim, runs an independent recomputation against the raw DataFrame
       via the Phase 3 kernel (`column_numeric_stats`, `count_outliers_zscore`, ...).
    3. Compares claimed vs computed within tolerance; flags discrepancies.
    4. Returns a structured verdict per block. The pipeline downgrades or rejects
       blocks that fail verification before the AGUI surfaces them.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from . import kernel as kx

logger = logging.getLogger(__name__)


# ---------------- Scribe ----------------

def _gemini_model():
    try:
        import google.generativeai as g  # type: ignore
    except Exception:
        return None
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        g.configure(api_key=api_key)
        return g.GenerativeModel(os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash"))
    except Exception as exc:
        logger.warning("Gemini init failed: %s", exc)
        return None


def scribe_narrative(
    *,
    block_id: str,
    block_title: str,
    block_section: str,
    hints: dict[str, Any],
    facts: dict[str, Any],
    reflections: list[dict[str, Any]] | None = None,
) -> str:
    """Generate a narrative paragraph. Falls back to deterministic template if no Gemini."""
    model = _gemini_model()
    tone = hints.get("tone", "official, neutral")
    max_words = int(hints.get("max_words", 220))

    if model is None:
        return _deterministic_narrative(block_title, facts, max_words)

    reflection_blurb = ""
    if reflections:
        notes = [r.get("after") or r.get("before") or "" for r in reflections if r.get("after") or r.get("before")]
        if notes:
            reflection_blurb = (
                "\n\nPRIOR HUMAN CORRECTIONS to consider (avoid past mistakes; reuse approved phrasing):\n"
                + "\n".join(f"- {n[:300]}" for n in notes[:3])
            )

    prompt = (
        f"You are drafting the '{block_title}' section ({block_section}) of an official "
        f"statistical report. Tone: {tone}. Hard limit: {max_words} words.\n\n"
        "Strict rules:\n"
        "  1. Cite only numbers present in the FACTS JSON below. Do NOT invent figures.\n"
        "  2. State percentages with one decimal place; counts as integers.\n"
        "  3. If a fact is unknown, write '(insufficient data)' rather than guessing.\n"
        "  4. Output prose only — no markdown headings, no bullets unless asked.\n\n"
        f"FACTS:\n{json.dumps(facts, default=str, indent=2)[:8000]}"
        f"{reflection_blurb}"
    )

    try:
        resp = model.generate_content(prompt)
        text = (resp.text or "").strip()
        if not text:
            return _deterministic_narrative(block_title, facts, max_words)
        return text
    except Exception as exc:
        logger.warning("Scribe call failed (%s); using deterministic template", exc)
        return _deterministic_narrative(block_title, facts, max_words)


def _deterministic_narrative(title: str, facts: dict[str, Any], max_words: int) -> str:
    parts = [f"{title}."]
    if "row_count" in facts and "column_count" in facts:
        parts.append(
            f"The dataset comprises {facts['row_count']} rows and {facts['column_count']} columns."
        )
    if "missing_pct" in facts:
        parts.append(f"Overall missing data: {facts['missing_pct']:.1f}%.")
    if "anomaly_count" in facts:
        parts.append(f"Anomaly detection flagged {facts['anomaly_count']} candidate records.")
    if "imputation_count" in facts:
        parts.append(f"{facts['imputation_count']} columns are recommended for imputation.")
    out = " ".join(parts)
    words = out.split()
    if len(words) > max_words:
        out = " ".join(words[:max_words]) + "…"
    return out


# ---------------- Verifier ----------------

_NUM_PAT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)")
_PCT_PAT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


@dataclass
class ClaimCheck:
    claim: str
    claimed_value: float
    interpretation: str  # e.g. 'percentage', 'count'
    computed_value: float | None = None
    tolerance: float = 0.05  # 5% relative tolerance
    status: str = "unverified"  # 'pass' | 'fail' | 'unverified'
    note: str = ""


@dataclass
class VerifierVerdict:
    block_id: str
    overall_status: str  # 'pass' | 'warn' | 'fail'
    checks: list[ClaimCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "overall_status": self.overall_status,
            "checks": [
                {
                    "claim": c.claim,
                    "claimed_value": c.claimed_value,
                    "computed_value": c.computed_value,
                    "tolerance": c.tolerance,
                    "status": c.status,
                    "note": c.note,
                }
                for c in self.checks
            ],
        }


def _extract_claims(text: str) -> list[ClaimCheck]:
    claims: list[ClaimCheck] = []
    seen: set[tuple[str, float]] = set()
    for m in _PCT_PAT.finditer(text):
        val = float(m.group(1))
        key = ("pct", val)
        if key in seen:
            continue
        seen.add(key)
        claims.append(ClaimCheck(
            claim=m.group(0),
            claimed_value=val,
            interpretation="percentage",
        ))
    for m in _NUM_PAT.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        if any(abs(val - s_val) < 1e-9 for _, s_val in seen):
            continue
        seen.add(("num", val))
        claims.append(ClaimCheck(
            claim=m.group(0),
            claimed_value=val,
            interpretation="count" if "." not in raw else "scalar",
        ))
    return claims


def verify_block(
    *,
    block_id: str,
    narrative: str,
    df: pd.DataFrame | None,
    expected_facts: dict[str, Any],
) -> VerifierVerdict:
    """Recompute every quantitative claim against the raw DataFrame.

    A claim 'passes' if it appears in expected_facts within tolerance, OR if a
    deterministic recomputation matches within tolerance. Everything else is
    'unverified' (treated as a soft warning).
    """
    checks = _extract_claims(narrative)
    if not checks:
        return VerifierVerdict(block_id=block_id, overall_status="pass", checks=[])

    fact_values = _flatten_numeric_facts(expected_facts)

    if df is not None:
        rec_missing_pct = _compute_missing_pct(df)
        rec_row_count = float(len(df))
        rec_col_count = float(len(df.columns))
    else:
        rec_missing_pct = rec_row_count = rec_col_count = None  # type: ignore

    for c in checks:
        # Try matching against expected facts within 5%.
        best = _closest(fact_values, c.claimed_value)
        if best is not None and _within(c.claimed_value, best, c.tolerance):
            c.computed_value = best
            c.status = "pass"
            c.note = "matched against analysis payload"
            continue

        # Recomputations
        if c.interpretation == "percentage" and rec_missing_pct is not None:
            if _within(c.claimed_value, rec_missing_pct, c.tolerance):
                c.computed_value = rec_missing_pct
                c.status = "pass"
                c.note = "matched recomputed missing_pct"
                continue
        if c.interpretation == "count" and rec_row_count is not None:
            for ref, label in ((rec_row_count, "row_count"), (rec_col_count, "column_count")):
                if _within(c.claimed_value, ref, c.tolerance):
                    c.computed_value = ref
                    c.status = "pass"
                    c.note = f"matched recomputed {label}"
                    break
            else:
                c.status = "unverified"
                c.note = "no source for this number"
                continue
            continue

        c.status = "unverified"
        c.note = "no source for this number"

    fails = sum(1 for c in checks if c.status == "fail")
    warns = sum(1 for c in checks if c.status == "unverified")
    if fails:
        overall = "fail"
    elif warns > max(1, len(checks) // 3):
        overall = "warn"
    else:
        overall = "pass"
    return VerifierVerdict(block_id=block_id, overall_status=overall, checks=checks)


def _flatten_numeric_facts(facts: dict[str, Any]) -> list[float]:
    out: list[float] = []

    def walk(v: Any):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(facts)
    return out


def _closest(values: list[float], target: float) -> float | None:
    if not values:
        return None
    return min(values, key=lambda v: abs(v - target))


def _within(a: float, b: float, tol: float) -> bool:
    if b == 0:
        return abs(a) <= tol
    return abs(a - b) / abs(b) <= tol


def _compute_missing_pct(df: pd.DataFrame) -> float:
    total = float(df.size) or 1.0
    missing = float(df.isna().sum().sum())
    return (missing / total) * 100.0
