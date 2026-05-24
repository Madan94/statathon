"""Persist Phase-3 candidate intelligence to relational tables (parallel to checkpoint JSON)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from core.json_safe import make_json_safe
from core.state import AnalysisState
from database.models import (
    Phase3AnomalyIntel,
    Phase3ImputationIntel,
    Phase3ValidationCandidate,
)


class Phase3PersistenceService:
    def __init__(self, db: Session):
        self.db = db

    def persist_state(self, state: AnalysisState) -> None:
        analysis_id = state.analysis_id
        dataset_id = state.dataset_id

        self.db.query(Phase3ValidationCandidate).filter(
            Phase3ValidationCandidate.analysis_id == analysis_id
        ).delete(synchronize_session=False)

        batch: list[Phase3ValidationCandidate] = []
        for cand in state.validation_candidates or []:
            if not isinstance(cand, dict):
                continue
            batch.append(
                Phase3ValidationCandidate(
                    dataset_id=dataset_id,
                    analysis_id=analysis_id,
                    kind=str(cand.get("kind") or "validation"),
                    column_name=(str(cand["column"]) if cand.get("column") is not None else None),
                    row_index=(int(cand["row"]) if cand.get("row") is not None else None),
                    severity=(str(cand["severity"]) if cand.get("severity") is not None else None),
                    candidate_action=str(cand.get("candidate_action") or "REVIEW"),
                    detail=make_json_safe(cand),
                )
            )
        if batch:
            self.db.add_all(batch)
        ar = self.db.query(Phase3AnomalyIntel).filter(Phase3AnomalyIntel.analysis_id == analysis_id).first()
        anomaly_payload = make_json_safe(
            {
                "anomaly_results": state.anomaly_results,
                "anomaly_candidates": state.anomaly_candidates,
            }
        )
        if ar:
            ar.payload = anomaly_payload
            ar.dataset_id = dataset_id
        else:
            self.db.add(
                Phase3AnomalyIntel(
                    dataset_id=dataset_id,
                    analysis_id=analysis_id,
                    payload=anomaly_payload,
                )
            )

        ir = (
            self.db.query(Phase3ImputationIntel).filter(Phase3ImputationIntel.analysis_id == analysis_id).first()
        )
        imputation_payload = make_json_safe(
            {
                "imputation_results": state.imputation_results,
                "imputation_candidates": state.imputation_candidates,
                "user_decisions": state.user_decisions,
            }
        )
        if ir:
            ir.payload = imputation_payload
            ir.dataset_id = dataset_id
        else:
            self.db.add(
                Phase3ImputationIntel(
                    dataset_id=dataset_id,
                    analysis_id=analysis_id,
                    payload=imputation_payload,
                )
            )

        self.db.flush()
