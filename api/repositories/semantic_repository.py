"""Persistence accessors for semantic intelligence tables."""
from __future__ import annotations

from sqlalchemy.orm import Session

from api.database.models import (
    DatasetContextRecord,
    PriorityDependency,
    SchemaGraphEdge,
    SemanticCluster,
    SemanticProfile,
)


class SemanticProfileRepository:
    def __init__(self, db: Session):
        self.db = db

    def replace_for_analysis(self, dataset_id: int, analysis_id: int, rows: list[dict]) -> None:
        self.db.query(SemanticProfile).filter(SemanticProfile.analysis_id == analysis_id).delete()
        for row in rows:
            self.db.add(
                SemanticProfile(
                    dataset_id=dataset_id,
                    analysis_id=analysis_id,
                    column_name=row["column_name"],
                    semantic_domain=row.get("semantic_domain"),
                    confidence=row.get("confidence"),
                    cluster_id=row.get("cluster_id"),
                    contextual_tags=row.get("contextual_tags"),
                )
            )


class SemanticClusterRepository:
    def __init__(self, db: Session):
        self.db = db

    def replace_for_analysis(self, dataset_id: int, analysis_id: int, rows: list[dict]) -> None:
        self.db.query(SemanticCluster).filter(SemanticCluster.analysis_id == analysis_id).delete()
        for row in rows:
            self.db.add(
                SemanticCluster(
                    dataset_id=dataset_id,
                    analysis_id=analysis_id,
                    cluster_name=row["cluster_name"],
                    semantic_domain=row.get("semantic_domain"),
                    support_score=row.get("support_score"),
                    cluster_metadata=row.get("cluster_metadata"),
                )
            )


class SchemaGraphRepository:
    def __init__(self, db: Session):
        self.db = db

    def replace_for_analysis(self, dataset_id: int, analysis_id: int, edges: list[dict]) -> None:
        self.db.query(SchemaGraphEdge).filter(SchemaGraphEdge.analysis_id == analysis_id).delete()
        for edge in edges:
            self.db.add(
                SchemaGraphEdge(
                    dataset_id=dataset_id,
                    analysis_id=analysis_id,
                    source_column=edge["source_column"],
                    target_column=edge["target_column"],
                    edge_weight=float(edge["edge_weight"]),
                    relationship_type=edge.get("relationship_type"),
                    semantic_reason=edge.get("semantic_reason"),
                )
            )


class PriorityDependencyRepository:
    def __init__(self, db: Session):
        self.db = db

    def replace_for_analysis(self, dataset_id: int, analysis_id: int, rows: list[dict]) -> None:
        self.db.query(PriorityDependency).filter(PriorityDependency.analysis_id == analysis_id).delete()
        for row in rows:
            self.db.add(
                PriorityDependency(
                    dataset_id=dataset_id,
                    analysis_id=analysis_id,
                    source_column=row["source_column"],
                    dependent_column=row["dependent_column"],
                    influence_score=float(row["influence_score"]),
                    dependency_reason=row.get("dependency_reason"),
                    signal_payload=row.get("signal_payload"),
                )
            )


class DatasetContextRepository:
    def __init__(self, db: Session):
        self.db = db

    def replace_for_analysis(self, dataset_id: int, analysis_id: int, payload: dict) -> None:
        self.db.query(DatasetContextRecord).filter(DatasetContextRecord.analysis_id == analysis_id).delete()
        self.db.add(
            DatasetContextRecord(
                dataset_id=dataset_id,
                analysis_id=analysis_id,
                inferred_context=str(payload.get("inferred_context", "")),
                domain_scores=payload.get("domain_scores") or {},
                semantic_summary=payload.get("semantic_summary") or {},
            )
        )
