"""Weight application workflow — detect, validate, recommend, apply, ignore."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from core.ingestion import infer_schema
from database.models import DatasetLineageSnapshot, WeightApplication, WeightAuditLog, WeightProfile
from review.dataset_snapshot_service import DatasetSnapshotService
from services.analysis_query import get_analysis_meta, load_analysis_checkpoint
from services.analysis_payload_cache import invalidate_analysis_cache
from services.analysis_results_service import build_semantic_results_from_db
from services.phase_audit_service import PhaseAuditService
from services.phase_status_service import PhaseStatusService
from weights.weight_applier import apply_weight_to_dataset
from weights.weight_audit import build_audit_record
from weights.weight_detector import detect_weight_columns
from weights.weight_profiles import build_weight_profile
from weights.weight_recommender import recommend_weight
from weights.weight_statistics import compare_weighted_unweighted
from weights.weight_validator import validate_weight_column

logger = logging.getLogger(__name__)


def semantic_mapping_dict(db: Session, analysis_id: int) -> dict[str, Any]:
    """Load semantic column metadata DB-first, checkpoint fallback."""
    built = build_semantic_results_from_db(db, analysis_id)
    if built:
        mapping = built.get("semantic_mapping") or []
        if isinstance(mapping, list):
            out: dict[str, Any] = {}
            for row in mapping:
                if isinstance(row, dict) and row.get("column"):
                    out[str(row["column"])] = row
            if out:
                return out

    checkpoint = load_analysis_checkpoint(db, analysis_id) or {}
    mapping = checkpoint.get("semantic_mapping") or {}
    if isinstance(mapping, list):
        out = {}
        for row in mapping:
            if isinstance(row, dict) and row.get("column"):
                out[str(row["column"])] = row
        return out
    if isinstance(mapping, dict):
        return mapping
    return {}


def invalidate_weight_after_upstream_refresh(db: Session, analysis_id: int) -> str | None:
    """
    Clear weighted snapshots and phase flags after imputed data changes.
    Returns weight column to auto-reapply, if any.
    """
    app = (
        db.query(WeightApplication)
        .filter(WeightApplication.analysis_id == analysis_id)
        .first()
    )
    reapply_column: str | None = None
    if app and app.applied and app.weight_column and not app.ignored:
        reapply_column = str(app.weight_column)

    db.query(DatasetLineageSnapshot).filter(
        DatasetLineageSnapshot.analysis_id == analysis_id,
        DatasetLineageSnapshot.stage == "weighted",
    ).delete(synchronize_session=False)
    db.query(DatasetLineageSnapshot).filter(
        DatasetLineageSnapshot.analysis_id == analysis_id,
        DatasetLineageSnapshot.stage == "final",
    ).delete(synchronize_session=False)

    phase_row = PhaseStatusService(db).get_or_create(analysis_id)
    phase_row.weight_application_completed = False
    phase_row.dataset_review_completed = False
    phase_row.updated_at = datetime.utcnow()

    if app and app.applied:
        meta = dict(app.meta or {})
        meta["stale"] = True
        app.meta = meta
        app.applied = False
        app.comparison = None
        app.updated_at = datetime.utcnow()

    db.flush()
    return reapply_column


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

    def _latest_imputed_snapshot_meta(self, analysis_id: int) -> dict[str, Any]:
        snap = self.snapshots._latest_snapshot(analysis_id, "imputed")
        if not snap:
            return {}
        return {
            "source_imputed_snapshot_id": snap.id,
            "source_imputed_snapshot_version": snap.version,
        }

    def _is_stale(self, analysis_id: int, application: WeightApplication | None) -> bool:
        if not application or not application.meta:
            return False
        if application.meta.get("stale"):
            return True
        expected_id = application.meta.get("source_imputed_snapshot_id")
        if not expected_id:
            return False
        snap = self.snapshots._latest_snapshot(analysis_id, "imputed")
        return snap is not None and snap.id != expected_id

    def _profiles_to_detections(self, profiles: list[WeightProfile]) -> list[dict[str, Any]]:
        detections: list[dict[str, Any]] = []
        for profile in profiles:
            detections.append(
                {
                    "column": profile.column_name,
                    "confidence": float(profile.confidence or 0.0),
                    "signals": profile.signals or {},
                }
            )
        detections.sort(key=lambda item: item["confidence"], reverse=True)
        return detections

    def _profiles_to_validations(self, profiles: list[WeightProfile]) -> dict[str, dict[str, Any]]:
        validations: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            validations[str(profile.column_name)] = {
                "column": profile.column_name,
                "quality_score": profile.quality_score,
                "coverage": profile.coverage,
                "missing_pct": profile.missing_pct,
                "variance": profile.variance,
                "valid": bool(profile.valid),
                "checks": profile.checks or {},
            }
        return validations

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

    def _build_payload(
        self,
        analysis_id: int,
        *,
        df: pd.DataFrame | None = None,
        detections: list[dict[str, Any]] | None = None,
        validations: dict[str, dict[str, Any]] | None = None,
        recommendation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        if df is None:
            df = self._load_imputed_df(analysis_id)

        profiles = (
            self.db.query(WeightProfile)
            .filter(WeightProfile.analysis_id == analysis_id)
            .order_by(WeightProfile.confidence.desc())
            .all()
        )
        if detections is None:
            detections = self._profiles_to_detections(profiles)
        if validations is None:
            validations = self._profiles_to_validations(profiles)
        if recommendation is None and detections:
            recommendation = recommend_weight(detections, validations)

        application = (
            self.db.query(WeightApplication)
            .filter(WeightApplication.analysis_id == analysis_id)
            .first()
        )
        if application and application.recommendation and recommendation is None:
            recommendation = application.recommendation

        selected = application.weight_column if application else None
        comparison = None
        if application and application.comparison:
            comparison = application.comparison
        elif recommendation:
            rec_col = str(recommendation.get("recommended") or "")
            if rec_col and rec_col in df.columns:
                schema = infer_schema(df)
                comparison = compare_weighted_unweighted(df, rec_col, schema)

        phase_row = PhaseStatusService(self.db).get_or_create(analysis_id)
        stale = self._is_stale(analysis_id, application)

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
            "stale": stale,
        }

    def detect_weights(self, analysis_id: int, *, user_id: int | None = None) -> dict[str, Any]:
        """Run detection, validate candidates, persist profiles (explicit mutation)."""
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        df = self._load_imputed_df(analysis_id)
        schema = infer_schema(df)
        semantic = semantic_mapping_dict(self.db, analysis_id)

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
        if not application:
            application = WeightApplication(analysis_id=analysis_id, dataset_id=an.dataset_id)
            self.db.add(application)
        application.recommendation = recommendation
        application.updated_at = datetime.utcnow()

        self._audit(
            analysis_id,
            weight_column=recommendation.get("recommended") if recommendation else None,
            quality_score=None,
            user_action="detect_weights",
            payload={"detected_count": len(detections)},
            user_id=user_id,
        )
        self.db.commit()

        return self._build_payload(
            analysis_id,
            df=df,
            detections=detections,
            validations=validations,
            recommendation=recommendation,
        )

    def get_payload(self, analysis_id: int) -> dict[str, Any]:
        """Read persisted weight state without mutating profiles."""
        payload = self._build_payload(analysis_id)
        self.db.commit()
        return payload

    def compare_metrics(self, analysis_id: int, weight_column: str) -> dict[str, Any]:
        df = self._load_imputed_df(analysis_id)
        schema = infer_schema(df)
        comparison = compare_weighted_unweighted(df, weight_column, schema)
        validation = validate_weight_column(df, weight_column)
        return {**comparison, "validation": validation}

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
        semantic = semantic_mapping_dict(self.db, analysis_id)
        validation = validate_weight_column(df, weight_column)
        if not validation.get("valid"):
            raise ValueError(f"Weight column failed validation: {weight_column}")

        imputed_meta = self._latest_imputed_snapshot_meta(analysis_id)
        weighted_df, apply_meta = apply_weight_to_dataset(
            df,
            weight_column,
            semantic_mapping=semantic,
            schema=schema,
        )
        apply_meta = {**apply_meta, **imputed_meta}
        comparison = compare_weighted_unweighted(df, weight_column, schema)
        recommendation = recommend_weight(
            detect_weight_columns(df, schema, semantic_mapping=semantic),
            {weight_column: validation},
        )

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
        application.recommendation = recommendation
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
            "weighted_columns": apply_meta.get("weighted_columns"),
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
            "weighted_columns": apply_meta.get("weighted_columns"),
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

    def try_auto_reapply(self, analysis_id: int, weight_column: str | None) -> None:
        if not weight_column:
            return
        try:
            self.apply_weight(analysis_id, weight_column)
        except Exception as exc:
            logger.warning(
                "Auto-reapply weight failed for analysis %s column %s: %s",
                analysis_id,
                weight_column,
                exc,
            )
