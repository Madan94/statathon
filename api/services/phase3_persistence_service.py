"""Persist Phase-3 candidate intelligence to relational tables (parallel to checkpoint JSON)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from core.json_safe import make_json_safe
from core.state import AnalysisState
from database.models import (
    Phase3AnomalyIntel,
    Phase3ImputationIntel,
    Phase3ValidationCandidate,
    ValidationResult,
)
from services.analysis_query import (
    VALIDATION_CANDIDATE_PERSIST_LIMIT,
    VALIDATION_DISPLAY_SAMPLE_ENABLED,
    VALIDATION_DISPLAY_SAMPLE_MIN,
    build_display_sample_fields,
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
        raw_candidates = [
            c for c in (state.validation_candidates or []) if isinstance(c, dict)
        ]
        total_candidates = len(raw_candidates)
        slice_end = (
            total_candidates
            if VALIDATION_CANDIDATE_PERSIST_LIMIT <= 0
            else VALIDATION_CANDIDATE_PERSIST_LIMIT
        )
        for cand in raw_candidates[:slice_end]:
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
            self.db.flush()

        val_payload = make_json_safe(state.validation_results or {})
        if total_candidates:
            val_payload = {
                **val_payload,
                "candidate_count": total_candidates,
                "candidates_persisted": len(batch),
                "candidates_truncated": total_candidates > len(batch),
            }
        if batch:
            stored_ids = [
                int(row[0])
                for row in self.db.query(Phase3ValidationCandidate.id)
                .filter(Phase3ValidationCandidate.analysis_id == analysis_id)
                .order_by(Phase3ValidationCandidate.id)
                .all()
            ]
            stored_total = len(stored_ids)
            if VALIDATION_DISPLAY_SAMPLE_ENABLED and stored_total >= VALIDATION_DISPLAY_SAMPLE_MIN:
                val_payload = {
                    **val_payload,
                    **build_display_sample_fields(stored_ids, stored_total),
                }
            else:
                val_payload = {
                    **val_payload,
                    "display_sample_enabled": False,
                    "display_sample_size": stored_total,
                    "display_sample_ids": None,
                }
        self.db.query(ValidationResult).filter(
            ValidationResult.analysis_id == analysis_id
        ).delete(synchronize_session=False)
        if val_payload:
            self.db.add(
                ValidationResult(
                    analysis_id=analysis_id,
                    stage="phase3_validation",
                    payload=val_payload,
                )
            )
        ar = self.db.query(Phase3AnomalyIntel).filter(Phase3AnomalyIntel.analysis_id == analysis_id).first()
        anomaly_payload = make_json_safe(
            {
                "anomaly_results": state.anomaly_results,
                "anomaly_candidates": state.anomaly_candidates,
                "goodness_of_fit": getattr(state, "goodness_of_fit", None) or [],
                "method_selections": getattr(state, "method_selections", None) or {},
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

    def persist_validation_only(self, state: AnalysisState) -> None:
        """Update validation artifacts after column-role confirm (no anomaly/imputation)."""
        analysis_id = state.analysis_id
        dataset_id = state.dataset_id

        self.db.query(Phase3ValidationCandidate).filter(
            Phase3ValidationCandidate.analysis_id == analysis_id
        ).delete(synchronize_session=False)

        batch: list[Phase3ValidationCandidate] = []
        raw_candidates = [
            c for c in (state.validation_candidates or []) if isinstance(c, dict)
        ]
        total_candidates = len(raw_candidates)
        slice_end = (
            total_candidates
            if VALIDATION_CANDIDATE_PERSIST_LIMIT <= 0
            else VALIDATION_CANDIDATE_PERSIST_LIMIT
        )
        for cand in raw_candidates[:slice_end]:
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
            self.db.flush()

        val_payload = make_json_safe(state.validation_results or {})
        if total_candidates:
            val_payload = {
                **val_payload,
                "candidate_count": total_candidates,
                "candidates_persisted": len(batch),
                "candidates_truncated": total_candidates > len(batch),
            }
        self.db.query(ValidationResult).filter(
            ValidationResult.analysis_id == analysis_id
        ).delete(synchronize_session=False)
        if val_payload:
            self.db.add(
                ValidationResult(
                    analysis_id=analysis_id,
                    stage="phase3_validation",
                    payload=val_payload,
                )
            )

        from services.analysis_query import get_analysis_meta, load_analysis_checkpoint

        an = get_analysis_meta(self.db, analysis_id)
        if an:
            checkpoint = dict(an.checkpoint or {})
            phase3 = checkpoint.get("phase3") if isinstance(checkpoint.get("phase3"), dict) else {}
            phase3 = dict(phase3)
            phase3["validation_results"] = make_json_safe(state.validation_results)
            phase3["validation_candidates"] = make_json_safe(state.validation_candidates)
            checkpoint["phase3"] = phase3
            an.checkpoint = make_json_safe(checkpoint)

        self.db.flush()
