"""Create versioned dataset snapshots after each review phase completes."""
from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from core.ingestion import infer_schema
from core.rule_validator import normalize_schema
from database.models import Dataset, ImputationRowDecision, OutlierDecision, ValidationDecision
from object_storage.object_store import try_build_default_store
from pipelines.validation_gate import apply_user_decisions
from services.analysis_dataframe_service import load_analysis_dataframe, load_snapshot_dataframe
from services.analysis_query import get_analysis_meta, load_analysis_checkpoint
from services.apply_service import (
    _apply_imputation,
    _apply_outlier_decisions,
    _column_maps,
    _persist_snapshot,
    _validation_decisions,
)

STAGE_PRIORITY = ("imputed", "anomaly_reviewed", "validated", "original")


def latest_snapshot_stage(db: Session, analysis_id: int) -> str | None:
    for stage in STAGE_PRIORITY:
        snap_df = load_snapshot_dataframe(db, analysis_id, stage)
        if snap_df is not None:
            return stage
    return None


class PhaseSnapshotService:
    def __init__(self, db: Session):
        self.db = db

    def _base_df(self, analysis_id: int) -> tuple[pd.DataFrame, Any, Dataset]:
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        ds = self.db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
        if not ds:
            raise ValueError("Dataset not found")
        store = try_build_default_store() if ds.object_key else None

        snap_df = load_snapshot_dataframe(self.db, analysis_id)
        if snap_df is not None:
            schema = infer_schema(snap_df)
            return normalize_schema(snap_df, schema), store, ds

        df, schema = load_analysis_dataframe(self.db, analysis_id)
        return df, store, ds

    def snapshot_validation(self, analysis_id: int) -> dict[str, Any]:
        df, store, ds = self._base_df(analysis_id)
        decisions = _validation_decisions(self.db, analysis_id)
        if not decisions:
            checkpoint = load_analysis_checkpoint(self.db, analysis_id) or {}
            phase3 = checkpoint.get("phase3") if isinstance(checkpoint.get("phase3"), dict) else {}
            raw = phase3.get("validation_user_decisions")
            if isinstance(raw, list):
                decisions = [
                    {
                        "rule_id": d.get("rule_id"),
                        "column": d.get("column"),
                        "row_id": d.get("row_index"),
                        "user_action": d.get("decision"),
                        "new_value": d.get("new_value"),
                    }
                    for d in raw
                ]
        out = apply_user_decisions(df, decisions) if decisions else df.copy()
        meta = {"validation_decisions": len(decisions)}
        return _persist_snapshot(
            self.db,
            analysis_id=analysis_id,
            dataset_id=ds.id,
            stage="validated",
            df=out,
            store=store,
            meta=meta,
        )

    def snapshot_anomaly(self, analysis_id: int) -> dict[str, Any]:
        validated = load_snapshot_dataframe(self.db, analysis_id, "validated")
        if validated is None:
            self.snapshot_validation(analysis_id)
            validated = load_snapshot_dataframe(self.db, analysis_id, "validated")
        if validated is None:
            df, store, ds = self._base_df(analysis_id)
        else:
            an = get_analysis_meta(self.db, analysis_id)
            ds = self.db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
            store = try_build_default_store() if ds and ds.object_key else None
            df = validated

        ui_to_physical, _ = _column_maps(self.db, analysis_id)
        decisions = (
            self.db.query(OutlierDecision).filter(OutlierDecision.analysis_id == analysis_id).all()
        )
        out, stats = _apply_outlier_decisions(df, decisions, ui_to_physical)
        return _persist_snapshot(
            self.db,
            analysis_id=analysis_id,
            dataset_id=ds.id,
            stage="anomaly_reviewed",
            df=out,
            store=store,
            meta={"outlier_stats": stats},
        )

    def snapshot_imputation(self, analysis_id: int) -> dict[str, Any]:
        base = load_snapshot_dataframe(self.db, analysis_id, "anomaly_reviewed")
        if base is None:
            self.snapshot_anomaly(analysis_id)
            base = load_snapshot_dataframe(self.db, analysis_id, "anomaly_reviewed")
        if base is None:
            df, store, ds = self._base_df(analysis_id)
        else:
            an = get_analysis_meta(self.db, analysis_id)
            ds = self.db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
            store = try_build_default_store() if ds and ds.object_key else None
            df = base

        ui_to_physical, _ = _column_maps(self.db, analysis_id)
        checkpoint = load_analysis_checkpoint(self.db, analysis_id) or {}
        phase3 = checkpoint.get("phase3") if isinstance(checkpoint.get("phase3"), dict) else {}
        imputation_rows = (
            self.db.query(ImputationRowDecision)
            .filter(ImputationRowDecision.analysis_id == analysis_id)
            .all()
        )
        out, applied = _apply_imputation(df, phase3, imputation_rows, ui_to_physical)
        return _persist_snapshot(
            self.db,
            analysis_id=analysis_id,
            dataset_id=ds.id,
            stage="imputed",
            df=out,
            store=store,
            meta={"imputation": applied},
        )
