"""Persist AnalysisState into Neon-backed semantic intelligence tables + checkpoint JSON."""
from __future__ import annotations

from sqlalchemy.orm import Session

from analysis_state.cluster_utils import unify_cluster_record
from core.state import AnalysisState
from api.repositories.intelligence_repository import DatasetIntelligenceRepository
from api.repositories.semantic_repository import (
    DatasetContextRepository,
    PriorityDependencyRepository,
    SchemaGraphRepository,
    SemanticClusterRepository,
    SemanticProfileRepository,
)


class SemanticPersistenceService:
    def __init__(self, db: Session):
        self.db = db
        self.profiles = SemanticProfileRepository(db)
        self.clusters = SemanticClusterRepository(db)
        self.graph = SchemaGraphRepository(db)
        self.priority = PriorityDependencyRepository(db)
        self.context = DatasetContextRepository(db)
        self.intel = DatasetIntelligenceRepository(db)

    def persist_state(self, state: AnalysisState) -> None:
        dataset_id = state.dataset_id
        analysis_id = state.analysis_id

        columns = state.semantic_profile.get("columns") or {}
        profile_rows: list[dict] = []
        for column_name, meta in columns.items():
            if not isinstance(meta, dict):
                continue
            profile_rows.append(
                {
                    "column_name": column_name,
                    "semantic_domain": meta.get("domain"),
                    "confidence": meta.get("confidence"),
                    "cluster_id": meta.get("cluster_id"),
                    "contextual_tags": {
                        "explainability": meta.get("explainability"),
                        "top_domain_scores": meta.get("top_domain_scores"),
                        "normalized_name": meta.get("normalized_name"),
                        "original_name": meta.get("original_name"),
                        "display_name": meta.get("display_name"),
                        "cluster_support": meta.get("cluster_support"),
                        "graph_consistency": meta.get("graph_consistency"),
                        "source": meta.get("source"),
                        "domain_type": meta.get("domain_type"),
                        "signals": meta.get("signals"),
                        "candidates": meta.get("candidates"),
                        "explanation": meta.get("explanation"),
                    },
                }
            )
        self.profiles.replace_for_analysis(dataset_id, analysis_id, profile_rows)

        cluster_rows: list[dict] = []
        for c in state.semantic_clusters or []:
            if not isinstance(c, dict):
                continue
            unified = unify_cluster_record(c)
            cluster_rows.append(
                {
                    "cluster_name": unified.get("cluster_id") or unified.get("cluster_name"),
                    "semantic_domain": unified.get("domain"),
                    "support_score": unified.get("support_score"),
                    "cluster_metadata": {
                        "support": unified.get("support"),
                        "columns": unified.get("columns"),
                        "domain_distribution": unified.get("domain_distribution"),
                        "domain_purity": unified.get("domain_purity"),
                        "embedding_coherence": unified.get("embedding_coherence"),
                        "avg_domain_confidence": unified.get("avg_domain_confidence"),
                        "purity": unified.get("purity"),
                        "cluster_confidence": unified.get("cluster_confidence"),
                        "dominant_domain": unified.get("dominant_domain"),
                        "explainability": unified.get("explainability"),
                    },
                }
            )
        self.clusters.replace_for_analysis(dataset_id, analysis_id, cluster_rows)

        edge_rows: list[dict] = []
        for e in (state.schema_graph or {}).get("edges") or []:
            edge_rows.append(
                {
                    "source_column": e["source"],
                    "target_column": e["target"],
                    "edge_weight": float(e.get("weight", 0)),
                    "relationship_type": e.get("relationship_type"),
                    "owl_type": e.get("owl_type"),
                    "source_domain": e.get("source_domain"),
                    "target_domain": e.get("target_domain"),
                    "semantic_reason": e.get("semantic_reason"),
                }
            )
        self.graph.replace_for_analysis(dataset_id, analysis_id, edge_rows)

        prio_rows: list[dict] = []
        deps = state.dependency_graph or {}
        if isinstance(deps, dict):
            for dependent_column, influencers in deps.items():
                if not isinstance(influencers, list):
                    continue
                for inf in influencers:
                    if not isinstance(inf, dict):
                        continue
                    prio_rows.append(
                        {
                            "source_column": inf["column"],
                            "dependent_column": dependent_column,
                            "influence_score": float(inf.get("score", 0)),
                            "dependency_reason": inf.get("dependency_reason"),
                            "signal_payload": {
                                "embedding_similarity": inf.get("embedding_similarity"),
                                "cluster_strength": inf.get("cluster_strength"),
                                "graph_signal": inf.get("graph_signal"),
                            },
                        }
                    )
        self.priority.replace_for_analysis(dataset_id, analysis_id, prio_rows)

        self.intel.replace_for_analysis(
            dataset_id,
            analysis_id,
            state.dataset_profile,
            state.column_profiles,
        )

        ctx = state.inferred_dataset_context or {}
        prof = dict(state.profiling_summary or {})
        prof["dataset_profile"] = state.dataset_profile
        prof["column_profiles"] = state.column_profiles

        self.context.replace_for_analysis(
            dataset_id,
            analysis_id,
            {
                "inferred_context": ctx.get("dataset_type") or "",
                "domain_scores": ctx.get("domain_scores") or {},
                "semantic_summary": {
                    "legacy_alignment_context": ctx.get("legacy_alignment_context"),
                    "ontology_macro_type_best_hint": ctx.get("ontology_macro_type_best_hint"),
                    "profiling_summary": prof,
                    "dataset_metadata": state.dataset_metadata,
                    "column_profiles": state.column_profiles,
                    "dataset_profile": state.dataset_profile,
                    "static_domains": state.static_domains,
                    "schema_blueprint": state.schema_blueprint,
                    "knowledge_graph": state.knowledge_graph,
                },
            },
        )

        self.db.flush()
