"""
Central pipeline state for STATATHON semantic intelligence.
Single source of truth between orchestration, persistence, and APIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class AnalysisState:
    """Mutable pipeline state; all semantic modules read/write through this object."""

    dataset_id: int
    analysis_id: int
    dataset_metadata: dict[str, Any] = field(default_factory=dict)
    semantic_profile: dict[str, Any] = field(default_factory=dict)
    semantic_clusters: list[dict[str, Any]] = field(default_factory=list)
    schema_graph: dict[str, Any] = field(default_factory=dict)
    dependency_graph: dict[str, Any] = field(default_factory=dict)
    audit_logs: list[dict[str, Any]] = field(default_factory=list)
    profiling_summary: dict[str, Any] = field(default_factory=dict)
    column_profiles: dict[str, Any] = field(default_factory=dict)
    column_normalization: list[dict[str, Any]] = field(default_factory=list)
    dataset_profile: dict[str, Any] = field(default_factory=dict)
    static_domains: dict[str, Any] = field(default_factory=dict)
    schema_blueprint: dict[str, Any] = field(default_factory=dict)
    inferred_dataset_context: dict[str, Any] = field(default_factory=dict)
    embedding_cache_refs: dict[str, Any] = field(default_factory=dict)
    knowledge_graph: dict[str, Any] = field(default_factory=dict)
    domain_registry: dict[str, Any] = field(default_factory=dict)
    validation_results: dict[str, Any] = field(default_factory=dict)
    validation_candidates: list[dict[str, Any]] = field(default_factory=list)
    anomaly_results: list[dict[str, Any]] = field(default_factory=list)
    anomaly_candidates: list[dict[str, Any]] = field(default_factory=list)
    imputation_results: list[dict[str, Any]] = field(default_factory=list)
    imputation_candidates: list[dict[str, Any]] = field(default_factory=list)
    user_decisions: dict[str, Any] = field(default_factory=dict)
    weighted_profile: dict[str, Any] = field(default_factory=dict)
    derived_dataset_path: str | None = None
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def touch(self) -> None:
        self.updated_at = _utc_now_iso()

    def to_api_payload(self) -> dict[str, Any]:
        """Normalized frontend-ready response shape."""
        mapping = self.semantic_profile.get("columns") or self.semantic_profile.get("semantic_mapping") or {}
        if isinstance(mapping, dict):
            semantic_mapping = [
                {"column": col, **(meta if isinstance(meta, dict) else {"value": meta})}
                for col, meta in mapping.items()
            ]
        else:
            semantic_mapping = list(mapping) if isinstance(mapping, list) else []

        return {
            "dataset_context": self.inferred_dataset_context,
            "semantic_mapping": semantic_mapping,
            "clusters": self.semantic_clusters,
            "schema_graph": self._normalize_graph(),
            "priority_dependencies": self._normalize_dependencies(),
            "profiling_summary": self.profiling_summary,
            "column_profiles": self.column_profiles,
            "column_normalization": self.column_normalization,
            "domain_registry": self.domain_registry,
            "dataset_profile": self.dataset_profile,
            "static_domains": self.static_domains,
            "schema_blueprint": self.schema_blueprint,
            "audit_logs": self.audit_logs,
            "embedding_cache_refs": self.embedding_cache_refs,
            "dataset_metadata": self.dataset_metadata,
            "knowledge_graph": self.knowledge_graph,
            "weighted_profile": self.weighted_profile,
            "derived_dataset_path": self.derived_dataset_path,
            "phase3": {
                "validation_results": self.validation_results,
                "validation_candidates": self.validation_candidates,
                "anomaly_results": self.anomaly_results,
                "anomaly_candidates": self.anomaly_candidates,
                "imputation_results": self.imputation_results,
                "imputation_candidates": self.imputation_candidates,
                "user_decisions": self.user_decisions,
            },
            "meta": {
                "dataset_id": self.dataset_id,
                "analysis_id": self.analysis_id,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            },
        }

    def _normalize_graph(self) -> dict[str, Any]:
        sg = self.schema_graph or {}
        edges = sg.get("edges") or []
        nodes = sg.get("nodes") or []
        if edges and isinstance(edges[0], dict) and "source" in edges[0]:
            return {"nodes": nodes, "edges": edges}
        return {"nodes": nodes, "edges": edges}

    def _normalize_dependencies(self) -> list[dict[str, Any]]:
        """
        Flatten dependency_graph dict[column -> list[influencers]] to edge list for graphs/cards.
        """
        raw = self.dependency_graph or {}
        if isinstance(raw, list):
            return raw
        out: list[dict[str, Any]] = []
        if not isinstance(raw, dict):
            return out
        for dependent_column, influencers in raw.items():
            if not isinstance(influencers, list):
                continue
            for inf in influencers:
                if not isinstance(inf, dict):
                    continue
                src = inf.get("column") or inf.get("source_column")
                if not src:
                    continue
                out.append(
                    {
                        "source_column": src,
                        "dependent_column": dependent_column,
                        "influence_score": inf.get("score") or inf.get("influence_score"),
                        "dependency_reason": inf.get("dependency_reason"),
                        "signals": {
                            "embedding_similarity": inf.get("embedding_similarity"),
                            "cluster_strength": inf.get("cluster_strength"),
                            "graph_signal": inf.get("graph_signal"),
                        },
                    }
                )
        return out
