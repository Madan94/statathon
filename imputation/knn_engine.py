"""KNN imputation fitness from graph + correlation + KS-test donor validation.

Public API:
  * knn_graph_support(column, kg_edges) -> float
  * score_knn(corr_max_abs, graph_support, donor_quality=0.5, mechanism="UNKNOWN") -> float
  * validate_knn_donors(numeric_matrix, target_column) -> float  (NEW)
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------- legacy helpers ----------------


def knn_graph_support(column: str, kg_edges: list[dict]) -> float:
    rels = [e for e in kg_edges if column in (e.get("source_column"), e.get("target_column"))]
    if not rels:
        return 0.35
    w = sum(abs(float(e.get("weight") or 0.0)) for e in rels) / max(len(rels), 1)
    return float(max(0.0, min(1.0, w)))


def score_knn(
    corr_max_abs: float,
    graph_support: float,
    donor_quality: float = 0.5,
    mechanism: str = "UNKNOWN",
) -> float:
    """KNN fitness score with optional donor-quality boost and mechanism awareness."""
    corr = max(0.0, min(1.0, abs(float(corr_max_abs))))
    gs = max(0.0, min(1.0, float(graph_support)))
    dq = max(0.0, min(1.0, float(donor_quality)))

    # Base blend (legacy 0.55/0.45) then weighted up/down by donor quality + mechanism.
    base = 0.45 * corr + 0.35 * gs + 0.20 * dq

    # Mechanism adjustment: KNN shines under MAR, loses under MNAR.
    if mechanism == "MAR":
        base = min(1.0, base * 1.15)
    elif mechanism == "MNAR_SUSPECTED":
        base *= 0.7
    elif mechanism == "MCAR":
        base *= 0.95  # KNN works but offers little advantage

    return round(max(0.0, min(1.0, base)), 4)


# ---------------- donor validation via KS-test ----------------


def validate_knn_donors(numeric_matrix: pd.DataFrame, target_column: str,
                        top_k: int = 5) -> float:
    """0..1 — how reliable the top-K correlated donor columns are.

    For each candidate donor column we run a Kolmogorov-Smirnov test on the
    *observed* portion of (donor[notna(target)] vs donor[notna(target)==False]).
    If the donor's distribution is the same whether or not target is missing,
    we have evidence that the donor is a good MAR-style predictor (its
    information content is independent of target's missingness pattern).

    Result is the mean (1 - ks_pvalue) clipped to [0.1, 1.0]: high values
    mean donors carry strong signal; low values mean donors look identical
    in both halves and would barely move the imputation.
    """
    if target_column not in numeric_matrix.columns:
        return 0.5
    target = pd.to_numeric(numeric_matrix[target_column], errors="coerce")
    target_missing = target.isna()
    if target_missing.sum() < 5 or (~target_missing).sum() < 5:
        return 0.5

    # Rank donors by absolute correlation with target
    abs_corr = numeric_matrix.corr().abs().get(target_column)
    if abs_corr is None:
        return 0.5
    abs_corr = abs_corr.drop(labels=[target_column], errors="ignore")
    abs_corr = abs_corr.fillna(0.0).sort_values(ascending=False)
    donor_columns = abs_corr.head(top_k).index.tolist()
    if not donor_columns:
        return 0.5

    try:
        from scipy import stats
    except Exception:
        return 0.5

    scores: list[float] = []
    for d in donor_columns:
        donor = pd.to_numeric(numeric_matrix[d], errors="coerce")
        a = donor[~target_missing].dropna().to_numpy()
        b = donor[target_missing].dropna().to_numpy()
        if a.size < 5 or b.size < 5:
            continue
        try:
            _, p = stats.ks_2samp(a, b)
            # If p is *low*, distributions differ between observed/missing rows
            # of the target — that's exactly the MAR predictor signature we want.
            scores.append(min(1.0, 1.0 - float(p)))
        except Exception as exc:
            logger.debug("KS donor test failed for %s vs %s: %s",
                         target_column, d, exc)

    if not scores:
        return 0.5
    return float(np.clip(np.mean(scores), 0.1, 1.0))
