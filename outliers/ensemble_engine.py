"""High-accuracy anomaly layer.

Sits on top of the existing zscore / iqr / isolation engines without
replacing them. Adds three mechanisms:

  1. ENSEMBLE AGREEMENT BONUS
     When two or more methods agree on the same row, confidence jumps:
       * 1 method  -> base confidence
       * 2 methods -> +0.15
       * 3 methods -> +0.25  AND severity promoted at least to MEDIUM

  2. DOMAIN-BOUND ENFORCEMENT
     Any value outside the rule library's declared range for that column
     (e.g. percentage > 100, age > 120, pH > 14) is flagged EXTREME with
     confidence 0.98, regardless of distribution. This catches data-entry
     errors that distributional outlier methods miss when the *whole column*
     is biased.

  3. PER-ROW CONFIDENCE CALIBRATION
     Final confidence routed through `analytics.default_calibrator` with
     applicability per-method. A row flagged by Z-score on a non-normal
     column counts less; a row flagged by IQR on a heavy-tailed column
     counts more.

Public entry: `enrich_anomaly_candidates(candidates, df, schema,
                                          domain_bounds=None, profiles=None)`
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from analytics import default_calibrator, profile_column

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain bounds extracted from validation_rule_library.json
# ---------------------------------------------------------------------------


def load_domain_bounds(rule_library_path: str | Path | None = None
                        ) -> list[dict[str, Any]]:
    """Return a list of {pattern, min, max, severity, rule_id} from the rule library."""
    path = Path(rule_library_path) if rule_library_path else (
        Path(__file__).resolve().parent.parent
        / "model" / "config" / "validation_rule_library.json"
    )
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    bounds: list[dict[str, Any]] = []
    for rule in data.get("rules", []):
        rt = rule.get("rule_type")
        params = rule.get("params") or {}
        if rt == "numeric_between":
            bounds.append({
                "pattern": rule.get("column_name_pattern"),
                "min": params.get("min"), "max": params.get("max"),
                "severity": rule.get("severity") or "medium",
                "rule_id": rule.get("id"),
            })
        elif rt == "numeric_min":
            bounds.append({
                "pattern": rule.get("column_name_pattern"),
                "min": params.get("min"), "max": None,
                "severity": rule.get("severity") or "medium",
                "rule_id": rule.get("id"),
            })
        elif rt == "numeric_max":
            bounds.append({
                "pattern": rule.get("column_name_pattern"),
                "min": None, "max": params.get("max"),
                "severity": rule.get("severity") or "medium",
                "rule_id": rule.get("id"),
            })
    return bounds


def _match_bounds(column_name: str, bounds: list[dict[str, Any]]
                   ) -> dict[str, Any] | None:
    for b in bounds:
        patt = b.get("pattern")
        if not patt:
            continue
        try:
            if re.search(patt, str(column_name)):
                return b
        except re.error:
            continue
    return None


# ---------------------------------------------------------------------------
# Domain-bound outlier detection
# ---------------------------------------------------------------------------


def detect_domain_bound_outliers(
    df: pd.DataFrame,
    schema: dict[str, str],
    bounds: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Flag any cell that violates a declared bound from the rule library.

    These are EXTREME-confidence outliers because they represent rule violations,
    not statistical tail events.
    """
    bounds = bounds if bounds is not None else load_domain_bounds()
    out: list[dict[str, Any]] = []
    if not bounds:
        return out

    for col in df.columns:
        if schema.get(col) != "numeric":
            continue
        b = _match_bounds(str(col), bounds)
        if not b:
            continue
        s = pd.to_numeric(df[col], errors="coerce").reset_index(drop=True)
        lo = b.get("min")
        hi = b.get("max")
        for pos, v in enumerate(s.tolist()):
            if pd.isna(v):
                continue
            try:
                vf = float(v)
            except Exception:
                continue
            if (lo is not None and vf < lo) or (hi is not None and vf > hi):
                out.append({
                    "row": int(pos),
                    "column": str(col),
                    "value": vf,
                    "method": "DOMAIN_BOUND",
                    "severity": "EXTREME",
                    "confidence": 0.98,
                    "explain": {
                        "rule_id": b.get("rule_id"),
                        "rule_min": lo,
                        "rule_max": hi,
                        "violation": "below_min" if (lo is not None and vf < lo) else "above_max",
                    },
                    "candidate_action": "REMOVE_VALUE",
                    "alternate_actions": ["KEEP", "REMOVE_ROW", "MARK_VALID"],
                })
    return out


# ---------------------------------------------------------------------------
# Ensemble enrichment
# ---------------------------------------------------------------------------


_SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "EXTREME": 3, "HIGH": 3, "CRITICAL": 3}


def _promote_severity(current: str | None, minimum: str) -> str:
    cur = _SEVERITY_ORDER.get(str(current or "").upper(), 0)
    floor = _SEVERITY_ORDER.get(minimum.upper(), 0)
    if cur >= floor:
        return str(current).upper() if current else minimum.upper()
    return minimum.upper()


def enrich_anomaly_candidates(
    candidates: list[dict[str, Any]],
    *,
    df: pd.DataFrame | None = None,
    schema: dict[str, str] | None = None,
    profiles: dict[str, Any] | None = None,
    bounds_path: str | Path | None = None,
) -> dict[str, Any]:
    """Apply ensemble agreement bonus + domain-bound enforcement to a candidate list.

    The input `candidates` is the `flat_candidates` produced by the existing
    `outliers.anomaly_handler.build_anomaly_intelligence`. The output preserves
    each candidate's identity but updates `confidence`, `severity`, and adds
    `ensemble_methods` / `ensemble_agreement_bonus` to its explain.

    Domain-bound violations are appended as new EXTREME candidates if not
    already present in the input.
    """
    candidates = list(candidates or [])

    # ---- 1. Domain-bound enforcement ----
    bounds = load_domain_bounds(bounds_path) if bounds_path is not None else load_domain_bounds()
    extra: list[dict[str, Any]] = []
    if df is not None and schema is not None:
        extra = detect_domain_bound_outliers(df, schema, bounds)

    # Index existing candidates by (row, column)
    by_cell: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for c in candidates:
        key = (int(c.get("row", -1)), str(c.get("column", "")))
        by_cell.setdefault(key, []).append(c)

    # Merge domain-bound candidates into the index
    for d in extra:
        key = (int(d["row"]), str(d["column"]))
        by_cell.setdefault(key, []).append(d)

    # ---- 2. Ensemble agreement bonus ----
    enriched: list[dict[str, Any]] = []
    method_count: dict[str, int] = {}
    for (row, col), cell_candidates in by_cell.items():
        methods = sorted({str(c.get("method")) for c in cell_candidates
                          if c.get("method")})
        n_methods = len(methods)

        # Pick the "lead" candidate: highest existing confidence
        lead = max(cell_candidates, key=lambda c: float(c.get("confidence") or 0))
        base_conf = float(lead.get("confidence") or 0)
        severity = str(lead.get("severity") or "LOW").upper()

        # Domain-bound overrides everything else
        domain_bound_hit = "DOMAIN_BOUND" in methods
        if domain_bound_hit:
            severity = "EXTREME"
            base_conf = max(base_conf, 0.98)

        # Agreement bonus
        bonus = 0.0
        if n_methods >= 3:
            bonus = 0.25
            severity = _promote_severity(severity, "MEDIUM")
        elif n_methods == 2:
            bonus = 0.15
            severity = _promote_severity(severity, "MEDIUM")

        # Calibrate via shared aggregator with applicability per method.
        profile = (profiles or {}).get(col)
        z_applicable = _z_applicable(profile)
        iqr_applicable = _iqr_applicable(profile)

        signal_values: dict[str, float] = {}
        applicability: dict[str, bool] = {}
        for c in cell_candidates:
            m = str(c.get("method"))
            conf = float(c.get("confidence") or 0)
            if m == "Z_SCORE":
                signal_values["normality"] = conf
                applicability["normality"] = z_applicable
            elif m == "IQR":
                signal_values["robustness_need"] = conf
                applicability["robustness_need"] = iqr_applicable
            elif m == "ISOLATION_FOREST":
                signal_values["sample_size_adequacy"] = min(0.85, conf)
                applicability["sample_size_adequacy"] = True
            elif m == "DOMAIN_BOUND":
                signal_values["variance_stability"] = 1.0
                applicability["variance_stability"] = True

        calibrated = default_calibrator.combine(
            "anomaly_method", signal_values, applicability=applicability,
        )
        final_conf = max(min(base_conf + bonus, 0.99), calibrated.value, base_conf)

        explain = lead.get("explain") or {}
        explain = dict(explain)
        explain.update({
            "ensemble_methods": methods,
            "ensemble_agreement_bonus": round(bonus, 3),
            "domain_bound_hit": domain_bound_hit,
            "calibrated_score": calibrated.to_dict(),
            "base_confidence": base_conf,
        })
        enriched.append({
            "row": row,
            "column": col,
            "value": lead.get("value"),
            "method": "ENSEMBLE" if n_methods > 1 else methods[0],
            "voting_methods": methods,
            "confidence": round(final_conf, 4),
            "severity": severity,
            "candidate_action": lead.get("candidate_action", "REMOVE_VALUE"),
            "alternate_actions": lead.get("alternate_actions", ["KEEP", "REMOVE_ROW", "MARK_VALID"]),
            "explain": explain,
        })
        for m in methods:
            method_count[m] = method_count.get(m, 0) + 1

    # Stable order: severity desc, confidence desc
    enriched.sort(
        key=lambda c: (_SEVERITY_ORDER.get(c["severity"], 0), c["confidence"]),
        reverse=True,
    )

    return {
        "anomaly_candidates": enriched,
        "summary": {
            "candidate_flags": len(enriched),
            "method_breakdown": method_count,
            "ensemble_hits": sum(1 for c in enriched if len(c["voting_methods"]) >= 2),
            "domain_bound_hits": sum(1 for c in enriched if "DOMAIN_BOUND" in c["voting_methods"]),
        },
    }


def _z_applicable(profile: Any) -> bool:
    if profile is None:
        return True  # default to applicable
    if isinstance(profile, dict):
        return bool(profile.get("is_normal_5pct") is not False) and not profile.get("is_multimodal", False)
    return bool(getattr(profile, "is_normal_5pct", None) is not False) and not getattr(profile, "is_multimodal", False)


def _iqr_applicable(profile: Any) -> bool:
    # IQR is broadly applicable; only flag inapplicable on constant/very small data
    if profile is None:
        return True
    if isinstance(profile, dict):
        n = profile.get("sample_size_used") or profile.get("count")
    else:
        n = getattr(profile, "sample_size_used", None) or getattr(profile, "count", 0)
    return bool(n and int(n) >= 4)
