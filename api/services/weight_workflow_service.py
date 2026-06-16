"""Weight application workflow — detect, validate, recommend, apply, ignore."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from core.ingestion import infer_schema
from database.models import WeightApplication, WeightAuditLog, WeightProfile
from review.dataset_snapshot_service import DatasetSnapshotService
from services.analysis_query import get_analysis_meta, load_analysis_checkpoint
from services.analysis_payload_cache import invalidate_analysis_cache
from services.phase_audit_service import PhaseAuditService
from services.phase_snapshot_service import PhaseSnapshotService, refresh_downstream_with_status
from services.phase_status_service import PhaseStatusService
from weights.weight_applier import apply_weight_to_dataset
from weights.weight_audit import build_audit_record
from weights.weight_detector import detect_weight_columns
from weights.weight_profiles import build_weight_profile
from weights.weight_recommender import recommend_weight
from weights.weight_statistics import compare_weighted_unweighted
from weights.weight_validator import validate_weight_column

logger = logging.getLogger(__name__)


def _semantic_mapping_dict(db: Session, analysis_id: int) -> dict[str, Any]:
    checkpoint = load_analysis_checkpoint(db, analysis_id) or {}
    mapping = checkpoint.get("semantic_mapping") or {}
    if isinstance(mapping, list):
        out: dict[str, Any] = {}
        for row in mapping:
            if isinstance(row, dict) and row.get("column"):
                out[str(row["column"])] = row
        return out
    if isinstance(mapping, dict):
        return mapping
    return {}


class WeightWorkflowService:
    def __init__(self, db: Session):
        self.db = db
        self.snapshots = DatasetSnapshotService(db)

    def _load_imputed_df(self, analysis_id: int) -> pd.DataFrame:
        ps = PhaseStatusService(self.db)
        row = ps.get_or_create(analysis_id)
        if not row.missing_value_completed:
            imputation = ps.recompute_imputation_columns(analysis_id)
            if not imputation.get("complete"):
                raise ValueError("Complete Missing Value Intelligence before weight application")
        snap = self.snapshots._latest_snapshot(analysis_id, "imputed")
        if snap:
            df = self.snapshots._read_snapshot_df(snap)
            if df is not None:
                return df
        from services.phase_snapshot_service import PhaseSnapshotService

        PhaseSnapshotService(self.db).snapshot_imputation(analysis_id)
        self.db.flush()
        snap = self.snapshots._latest_snapshot(analysis_id, "imputed")
        if snap:
            df = self.snapshots._read_snapshot_df(snap)
            if df is not None:
                return df
        raise ValueError("Imputed dataset snapshot unavailable")

    def _persist_profiles(
        self,
        analysis_id: int,
        dataset_id: int,
        detections: list[dict[str, Any]],
        validations: dict[str, dict[str, Any]],
    ) -> list[WeightProfile]:
        self.db.query(WeightProfile).filter(WeightProfile.analysis_id == analysis_id).delete(
            synchronize_session=False
        )
        rows: list[WeightProfile] = []
        for det in detections:
            col = str(det.get("column") or "")
            val = validations.get(col) or {}
            profile = build_weight_profile(det, val)
            row = WeightProfile(
                analysis_id=analysis_id,
                dataset_id=dataset_id,
                column_name=col,
                confidence=float(profile.get("confidence") or 0.0),
                signals=profile.get("signals"),
                quality_score=profile.get("quality_score"),
                coverage=profile.get("coverage"),
                missing_pct=profile.get("missing_pct"),
                variance=profile.get("variance"),
                valid=bool(profile.get("valid")),
                checks=profile.get("checks"),
            )
            rows.append(row)
            self.db.add(row)
        self.db.flush()
        return rows

    def _audit(
        self,
        analysis_id: int,
        *,
        weight_column: str | None,
        quality_score: float | None,
        user_action: str,
        payload: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> None:
        record = build_audit_record(
            analysis_id=analysis_id,
            weight_column=weight_column,
            quality_score=quality_score,
            user_action=user_action,
            payload=payload,
        )
        self.db.add(
            WeightAuditLog(
                analysis_id=analysis_id,
                weight_column=weight_column,
                quality_score=quality_score,
                user_action=user_action,
                payload=record,
            )
        )
        PhaseAuditService(self.db).record(
            analysis_id=analysis_id,
            phase="weight_application",
            action=user_action,
            user_id=user_id,
            payload=record,
        )

    def get_payload(self, analysis_id: int) -> dict[str, Any]:
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        df = self._load_imputed_df(analysis_id)
        schema = infer_schema(df)
        semantic = _semantic_mapping_dict(self.db, analysis_id)

        detections = detect_weight_columns(df, schema, semantic_mapping=semantic)
        validations = {
            str(d["column"]): validate_weight_column(df, str(d["column"])) for d in detections
        }
        self._persist_profiles(analysis_id, an.dataset_id, detections, validations)
        recommendation = recommend_weight(detections, validations)

        application = (
            self.db.query(WeightApplication)
            .filter(WeightApplication.analysis_id == analysis_id)
            .first()
        )
        selected = application.weight_column if application else None
        comparison = None
        if selected and application and application.comparison:
            comparison = application.comparison
        elif recommendation:
            rec_col = str(recommendation.get("recommended") or "")
            if rec_col:
                comparison = compare_weighted_unweighted(df, rec_col, schema)

        phase_row = PhaseStatusService(self.db).get_or_create(analysis_id)
        self.db.commit()

        return {
            "analysis_id": analysis_id,
            "detected_columns": detections,
            "validations": validations,
            "recommendation": recommendation,
            "application": {
                "weight_column": application.weight_column if application else None,
                "applied": bool(application.applied) if application else False,
                "ignored": bool(application.ignored) if application else False,
                "quality_score": application.quality_score if application else None,
            },
            "comparison": comparison,
            "columns": [str(c) for c in df.columns],
            "weight_application_completed": bool(phase_row.weight_application_completed),
        }

    def compare_metrics(self, analysis_id: int, weight_column: str) -> dict[str, Any]:
        df = self._load_imputed_df(analysis_id)
        schema = infer_schema(df)
        return compare_weighted_unweighted(df, weight_column, schema)

    def apply_weight(
        self,
        analysis_id: int,
        weight_column: str,
        *,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        df = self._load_imputed_df(analysis_id)
        schema = infer_schema(df)
        validation = validate_weight_column(df, weight_column)
        if not validation.get("valid"):
            raise ValueError(f"Weight column failed validation: {weight_column}")

        weighted_df, apply_meta = apply_weight_to_dataset(df, weight_column)
        comparison = compare_weighted_unweighted(df, weight_column, schema)

        application = (
            self.db.query(WeightApplication)
            .filter(WeightApplication.analysis_id == analysis_id)
            .first()
        )
        if not application:
            application = WeightApplication(analysis_id=analysis_id, dataset_id=an.dataset_id)
            self.db.add(application)

        application.weight_column = weight_column
        application.applied = True
        application.ignored = False
        application.quality_score = validation.get("quality_score")
        application.comparison = comparison
        application.meta = apply_meta
        application.updated_at = datetime.utcnow()

        snapshot_meta = {
            **apply_meta,
            "phase": "v6_weight_application",
            "quality_score": validation.get("quality_score"),
        }
        from database.models import Dataset
        from object_storage.object_store import try_build_default_store
        from services.apply_service import _persist_snapshot

        ds = self.db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
        store = try_build_default_store() if ds and ds.object_key else None
        snap = _persist_snapshot(
            self.db,
            analysis_id=analysis_id,
            dataset_id=an.dataset_id,
            stage="weighted",
            df=weighted_df,
            store=store,
            meta=snapshot_meta,
        )

        phase_row = PhaseStatusService(self.db).get_or_create(analysis_id)
        phase_row.weight_application_completed = True
        phase_row.updated_at = datetime.utcnow()

        checkpoint = load_analysis_checkpoint(self.db, analysis_id) or {}
        checkpoint = dict(checkpoint)
        checkpoint["weighted_profile"] = {
            "applied": True,
            "weight_column": weight_column,
            "quality_score": validation.get("quality_score"),
            "comparison": comparison,
            "working_dataset_weighted": True,
        }
        an_obj = get_analysis_meta(self.db, analysis_id)
        if an_obj:
            an_obj.checkpoint = checkpoint

        self._audit(
            analysis_id,
            weight_column=weight_column,
            quality_score=float(validation.get("quality_score") or 0.0),
            user_action="apply_weight",
            payload={"snapshot": snap},
            user_id=user_id,
        )
        invalidate_analysis_cache(analysis_id)
        self.db.commit()

        return {
            "success": True,
            "analysis_id": analysis_id,
            "weight_column": weight_column,
            "applied": True,
            "quality_score": validation.get("quality_score"),
            "comparison": comparison,
            "snapshot": snap,
            "weight_application_completed": True,
        }

    def ignore_weight(self, analysis_id: int, *, user_id: int | None = None) -> dict[str, Any]:
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        self._load_imputed_df(analysis_id)

        application = (
            self.db.query(WeightApplication)
            .filter(WeightApplication.analysis_id == analysis_id)
            .first()
        )
        if not application:
            application = WeightApplication(analysis_id=analysis_id, dataset_id=an.dataset_id)
            self.db.add(application)

        application.weight_column = None
        application.applied = False
        application.ignored = True
        application.updated_at = datetime.utcnow()

        phase_row = PhaseStatusService(self.db).get_or_create(analysis_id)
        phase_row.weight_application_completed = True
        phase_row.updated_at = datetime.utcnow()

        checkpoint = load_analysis_checkpoint(self.db, analysis_id) or {}
        checkpoint = dict(checkpoint)
        checkpoint["weighted_profile"] = {
            "applied": False,
            "weight_column": None,
            "ignored": True,
        }
        an_obj = get_analysis_meta(self.db, analysis_id)
        if an_obj:
            an_obj.checkpoint = checkpoint

        self._audit(
            analysis_id,
            weight_column=None,
            quality_score=None,
            user_action="ignore_weight",
            user_id=user_id,
        )
        invalidate_analysis_cache(analysis_id)
        self.db.commit()

        return {
            "success": True,
            "analysis_id": analysis_id,
            "applied": False,
            "ignored": True,
            "weight_application_completed": True,
        }
