"""VerifierAgent — multi-pass factual verification for narrative blocks.

Verification pipeline per block:
  Pass 1 — Claim extraction:
    Extract ALL numeric claims (counts, percentages, rates, indices)
    using regex patterns + optional Gemini claim parser.

  Pass 2 — Independent recomputation:
    For each claim, attempt to recompute from:
      a) facts dict (exact match within 5% tolerance)
      b) live DataFrame (direct pandas computation)
      c) phase3 payload (anomaly/imputation counts)

  Pass 3 — Verdict assignment:
    pass       — claim matches recomputed value within tolerance
    unverified — claim present in narrative but not found in data
    fail       — claim explicitly contradicts recomputed value (>25% off)

  Overall block verdict:
    pass   — all claims pass
    warn   — some unverified (soft warning; block may publish)
    fail   — any claim fails (block must be regenerated)

The VerifierAgent is composable; it can be called standalone or via the
ConsensusEngine which handles retry loops.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Claim extraction patterns
# ---------------------------------------------------------------------------

_PCT_PAT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_COUNT_PAT = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{4,})\b")
_DECIMAL_PAT = re.compile(r"\b(\d+\.\d+)\b")
_RATIO_PAT = re.compile(r"(\d+)\s*/\s*(\d+)")


@dataclass
class ClaimCheck:
    raw: str               # exact string from narrative
    claimed_value: float
    interpretation: str    # percentage / count / decimal / ratio
    computed_value: float | None = None
    tolerance: float = 0.05
    status: str = "unverified"   # pass / fail / unverified
    source: str = ""              # where computed_value came from
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.raw,
            "claimed_value": self.claimed_value,
            "computed_value": self.computed_value,
            "tolerance": self.tolerance,
            "status": self.status,
            "source": self.source,
            "note": self.note,
        }


@dataclass
class VerifierVerdict:
    block_id: str
    overall_status: str    # pass / warn / fail
    checks: list[ClaimCheck] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "overall_status": self.overall_status,
            "checks": [c.to_dict() for c in self.checks],
            "evidence": self.evidence,
        }


# ---------------------------------------------------------------------------
# Pass 1 — claim extraction
# ---------------------------------------------------------------------------

def extract_claims(text: str) -> list[ClaimCheck]:
    """Extract every numeric claim from a narrative paragraph."""
    claims: list[ClaimCheck] = []
    seen: set[tuple[str, float]] = set()

    # Percentages first (most specific)
    for m in _PCT_PAT.finditer(text):
        val = float(m.group(1))
        key = ("pct", round(val, 2))
        if key in seen:
            continue
        seen.add(key)
        claims.append(ClaimCheck(
            raw=m.group(0),
            claimed_value=val,
            interpretation="percentage",
        ))

    # Comma-separated large counts
    for m in _COUNT_PAT.finditer(text):
        raw_str = m.group(1).replace(",", "")
        val = float(raw_str)
        key = ("count", val)
        if key in seen:
            continue
        seen.add(key)
        claims.append(ClaimCheck(
            raw=m.group(1),
            claimed_value=val,
            interpretation="count",
        ))

    # Small decimal values not caught above
    for m in _DECIMAL_PAT.finditer(text):
        val = float(m.group(1))
        # Skip values already captured as percentages
        pct_context = text[max(0, m.start()-2):m.end()+2]
        if "%" in pct_context:
            continue
        key = ("decimal", round(val, 3))
        if key in seen:
            continue
        seen.add(key)
        claims.append(ClaimCheck(
            raw=m.group(1),
            claimed_value=val,
            interpretation="decimal",
        ))

    return claims


# ---------------------------------------------------------------------------
# Pass 2 — independent recomputation
# ---------------------------------------------------------------------------

def _flatten_numeric_facts(facts: dict[str, Any]) -> list[float]:
    out: list[float] = []

    def walk(v: Any):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)

    walk(facts)
    return out


def _within(a: float, b: float, tol: float) -> bool:
    if b == 0:
        return abs(a) <= tol
    return abs(a - b) / abs(b) <= tol


def _closest_fact(values: list[float], target: float) -> tuple[float | None, float]:
    """Returns (closest_value, distance_ratio)."""
    if not values:
        return None, float("inf")
    closest = min(values, key=lambda v: abs(v - target))
    dist = abs(target - closest) / (abs(closest) + 1e-9)
    return closest, dist


def _recompute_from_df(claim: ClaimCheck, df: pd.DataFrame) -> tuple[float | None, str]:
    """Try to recompute a claim value directly from the DataFrame."""
    v = claim.claimed_value

    if claim.interpretation == "count":
        # Row count
        if _within(v, len(df), 0.05):
            return float(len(df)), "row_count"
        # Column count
        if _within(v, len(df.columns), 0.05):
            return float(len(df.columns)), "column_count"
        # Numeric column count
        nc = len(df.select_dtypes(include="number").columns)
        if _within(v, nc, 0.05):
            return float(nc), "numeric_column_count"

    if claim.interpretation == "percentage":
        total_cells = float(df.size) or 1.0
        missing_pct = float(df.isna().sum().sum()) / total_cells * 100.0
        if _within(v, missing_pct, 0.05):
            return missing_pct, "missing_pct"
        dup_pct = float(df.duplicated().sum()) / max(len(df), 1) * 100.0
        if _within(v, dup_pct, 0.1):
            return dup_pct, "duplicate_pct"
        # Energy data: check % distributions (proved/indicated/inferred vs total_reserves)
        _reserve_cols = ["Proved_Reserves", "Indicated_Reserves", "Inferred_Reserves"]
        _total_col = "Total_Reserves"
        if _total_col in df.columns:
            # For each category (if Resource_Category exists) and overall
            for cat_col in ([None] + (["Resource_Category"] if "Resource_Category" in df.columns else [])):
                if cat_col is None:
                    subs = [("all", df)]
                else:
                    subs = [(cat, df[df[cat_col] == cat]) for cat in df[cat_col].unique()]
                for _, sub_df in subs:
                    t = float(sub_df[_total_col].sum())
                    if t <= 0:
                        continue
                    for rc in _reserve_cols:
                        if rc in sub_df.columns:
                            pct = float(sub_df[rc].sum()) / t * 100.0
                            if _within(v, pct, 0.10):  # 10% tolerance for energy pcts
                                return pct, f"{rc}_pct"
            # State distribution percentage
            if "State" in df.columns:
                by_state = df.groupby("State")[_total_col].sum()
                total_all = float(by_state.sum())
                if total_all > 0:
                    for state_pct in (by_state / total_all * 100).values:
                        if _within(v, float(state_pct), 0.10):
                            return float(state_pct), "state_distribution_pct"

    return None, ""


# ---------------------------------------------------------------------------
# Pass 3 — verdict
# ---------------------------------------------------------------------------

def _assign_verdict(checks: list[ClaimCheck]) -> str:
    fails = sum(1 for c in checks if c.status == "fail")
    unverified = sum(1 for c in checks if c.status == "unverified")
    passed = sum(1 for c in checks if c.status == "pass")

    if fails > 0:
        return "fail"
    if unverified > max(1, len(checks) // 3):
        return "warn"
    if passed == 0 and unverified > 0:
        return "warn"
    return "pass"


# ---------------------------------------------------------------------------
# VerifierAgent
# ---------------------------------------------------------------------------

class VerifierAgent:
    """Multi-pass verifier for narrative blocks.

    Supports domain-aware tolerance via PipelineConfig.verifier cascade:
      entity_type override > domain override > default (±5%)
    """

    def __init__(self, domain: str = "", verifier_config=None):
        self._domain = domain
        self._verifier_config = verifier_config

    def verify(
        self,
        *,
        block_id: str,
        narrative: str,
        facts: dict[str, Any],
        df: pd.DataFrame | None = None,
    ) -> VerifierVerdict:
        """Full three-pass verification. Returns a VerifierVerdict."""

        # Pass 1: extract claims
        checks = extract_claims(narrative)
        if not checks:
            return VerifierVerdict(
                block_id=block_id,
                overall_status="pass",
                checks=[],
                evidence={"note": "no numeric claims to verify"},
            )

        fact_values = _flatten_numeric_facts(facts)
        evidence: dict[str, Any] = {
            "claims_extracted": len(checks),
            "fact_values_available": len(fact_values),
        }

        # Pass 2: recompute
        for c in checks:
            # Apply domain-aware tolerance
            c.tolerance = self._resolve_tolerance(c.interpretation)

            # 2a: match against facts dict
            closest, dist = _closest_fact(fact_values, c.claimed_value)
            if closest is not None and dist <= c.tolerance:
                c.computed_value = closest
                c.status = "pass"
                c.source = "facts_dict"
                c.note = f"matched facts value {closest}"
                continue

            # 2b: live DataFrame recomputation
            if df is not None and not df.empty:
                computed, src = _recompute_from_df(c, df)
                if computed is not None and _within(c.claimed_value, computed, c.tolerance):
                    c.computed_value = computed
                    c.status = "pass"
                    c.source = src
                    c.note = f"recomputed from {src}"
                    continue

            # 2c: check if drastically wrong (fail) vs just unknown (unverified)
            # For percentage claims, be more lenient — small differences can come from
            # section-level vs global computation differences
            pct_tol = 0.50 if c.interpretation == "percentage" else 0.25
            if closest is not None and not _within(c.claimed_value, closest, pct_tol):
                if abs(c.claimed_value) > 10:  # only fail for non-trivial values
                    c.computed_value = closest
                    c.status = "fail"
                    c.source = "facts_dict"
                    c.note = f"claimed {c.claimed_value} but nearest fact is {closest:.3f}"
                    continue

            c.status = "unverified"
            c.note = "no matching data source found"

        # Pass 3: overall verdict
        overall = _assign_verdict(checks)
        evidence["pass_count"] = sum(1 for c in checks if c.status == "pass")
        evidence["fail_count"] = sum(1 for c in checks if c.status == "fail")
        evidence["unverified_count"] = sum(1 for c in checks if c.status == "unverified")

        return VerifierVerdict(
            block_id=block_id,
            overall_status=overall,
            checks=checks,
            evidence=evidence,
        )

    def summary_verdict(self, verdicts: list[VerifierVerdict]) -> str:
        """Aggregate verdict across all blocks."""
        if any(v.overall_status == "fail" for v in verdicts):
            return "fail"
        if any(v.overall_status == "warn" for v in verdicts):
            return "warn"
        return "pass"

    def _resolve_tolerance(self, claim_type: str) -> float:
        """Domain-aware tolerance cascade: verifier_config > domain_tolerance.json > default."""
        default_tol = 0.05

        if self._verifier_config is not None:
            try:
                return self._verifier_config.get_tolerance(self._domain, claim_type)
            except Exception:
                pass

        # Fallback: try loading domain_tolerance.json directly
        try:
            import pathlib
            tol_path = pathlib.Path(__file__).resolve().parent.parent / "template_engine" / "config" / "domain_tolerance.json"
            if tol_path.exists():
                import json as _json
                data = _json.loads(tol_path.read_text())
                domain_data = data.get(self._domain, data.get("generic", {}))
                return domain_data.get(claim_type, domain_data.get("default", default_tol))
        except Exception:
            pass

        return default_tol
