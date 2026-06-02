"""Confidence aggregation for semantic mapping.

Backwards-compatible: `calculate_confidence(similarity_scores, cluster_support,
graph_consistency)` keeps its original signature so existing callers continue
to work. A new `calculate_calibrated_confidence(...)` accepts the full
multi-signal payload from `SimilarityEngine.compose_signals` and routes the
combine through `analytics.default_calibrator` so weights are tunable.
"""
from __future__ import annotations

from typing import Any

from analytics import default_calibrator


class ConfidenceEngine:

    # ---------------- legacy ----------------

    @staticmethod
    def calculate_confidence(
        similarity_scores: dict,
        cluster_support: float = 0.0,
        graph_consistency: float = 0.0
    ) -> float:
        if not similarity_scores:
            return 0.0
        sorted_scores = sorted(similarity_scores.values(), reverse=True)
        best = sorted_scores[0]
        second = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
        margin = best - second
        embedding_signal = 0.5 * best + 0.5 * margin
        score = default_calibrator.combine(
            "semantic_mapping",
            {
                "cosine": float(embedding_signal),
                "cluster_support": float(cluster_support),
                "graph_consistency": float(graph_consistency),
            },
        )
        return round(score.value, 4)

    # ---------------- new — multi-signal ----------------

    @staticmethod
    def calculate_calibrated_confidence(
        *,
        cosine: float,
        jaccard: float = 0.0,
        keyword_overlap: float = 0.0,
        structural: float = 0.0,
        dtype_alignment: float = 0.6,
        distribution_fit: float = 0.55,
        cluster_support: float = 0.0,
        graph_consistency: float = 0.0,
        runner_up_margin: float = 0.0,
        notes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Compose all signals and return the calibrated audit payload."""
        # The runner-up margin still matters — multiply cosine by (1 + margin/2)
        # so a column that's clearly closer to one domain than the second-best
        # gets a bonus, but capped at 1.0.
        adjusted_cosine = float(min(1.0, cosine + 0.3 * max(0.0, runner_up_margin)))
        score = default_calibrator.combine(
            "semantic_mapping",
            {
                "cosine": adjusted_cosine,
                "jaccard": float(jaccard),
                "keyword_overlap": float(keyword_overlap),
                "structural": float(structural),
                "dtype_alignment": float(dtype_alignment),
                "distribution_fit": float(distribution_fit),
                "cluster_support": float(cluster_support),
                "graph_consistency": float(graph_consistency),
            },
            notes=notes,
        )
        return score.to_dict()

    # ---------------- helpers (kept) ----------------

    @staticmethod
    def compute_cluster_support(column: str, assigned_domain: str,
                                 cluster_domains: dict, clusters: dict) -> float:
        for cluster_id, members in clusters.items():
            if column in members:
                same_domain = sum(1 for m in members if cluster_domains.get(m) == assigned_domain)
                return same_domain / len(members)
        return 0.0

    @staticmethod
    def compute_graph_consistency(column: str, assigned_domain: str,
                                   neighbors: dict, column_domains: dict) -> float:
        col_neighbors = neighbors.get(column, {})
        if not col_neighbors:
            return 0.0
        consistent = 0.0
        total = 0.0
        for neighbor, edge_data in col_neighbors.items():
            weight = edge_data["weight"] if isinstance(edge_data, dict) else float(edge_data)
            total += weight
            neighbor_domain = column_domains.get(neighbor, "")
            if neighbor_domain == assigned_domain:
                consistent += weight
        return consistent / total if total > 0 else 0.0
