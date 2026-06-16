"""Read lineage snapshots and paginate dataset rows for review (no reprocessing)."""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from database.models import DatasetLineageSnapshot

STAGE_LABELS: dict[str, str] = {
    "original": "v1_upload",
    "normalized": "v2_normalization",
    "validated": "v3_rule_validation",
    "anomaly_reviewed": "v4_anomaly",
    "imputed": "v5_missing_value",
    "weighted": "v6_weight_application",
    "final": "v7_dataset_review",
}

WORKING_STAGE = "imputed"
FINAL_STAGE = "final"


def resolve_working_stage(db: Session, analysis_id: int) -> str:
    from database.models import WeightApplication

    app = (
        db.query(WeightApplication)
        .filter(WeightApplication.analysis_id == analysis_id, WeightApplication.applied.is_(True))
        .first()
    )
    if app:
        return "weighted"
    return WORKING_STAGE


def resolve_processed_stage(db: Session, analysis_id: int) -> str:
    """Return canonical processed stage: approved final snapshot, else latest working."""
    from services.phase_status_service import PhaseStatusService

    row = PhaseStatusService(db).get_or_create(analysis_id)
    if row.dataset_review_completed:
        snap = (
            db.query(DatasetLineageSnapshot)
            .filter(
                DatasetLineageSnapshot.analysis_id == analysis_id,
                DatasetLineageSnapshot.stage == FINAL_STAGE,
            )
            .order_by(DatasetLineageSnapshot.version.desc())
            .first()
        )
        if snap is not None:
            return FINAL_STAGE
    return resolve_working_stage(db, analysis_id)


class DatasetSnapshotService:
    def __init__(self, db: Session):
        self.db = db

    def list_snapshots(self, analysis_id: int) -> list[dict[str, Any]]:
        rows = (
            self.db.query(DatasetLineageSnapshot)
            .filter(DatasetLineageSnapshot.analysis_id == analysis_id)
            .order_by(DatasetLineageSnapshot.created_at.asc())
            .all()
        )
        out: list[dict[str, Any]] = []
        for snap in rows:
            out.append(
                {
                    "analysis_id": analysis_id,
                    "phase": STAGE_LABELS.get(snap.stage, snap.stage),
                    "stage": snap.stage,
                    "version": snap.version,
                    "row_count": snap.row_count or 0,
                    "column_count": snap.column_count or 0,
                    "dataset_path": snap.storage_path,
                    "object_key": snap.object_key,
                    "created_at": snap.created_at.isoformat() if snap.created_at else None,
                    "meta": snap.meta or {},
                }
            )
        return out

    def _latest_snapshot(self, analysis_id: int, stage: str) -> DatasetLineageSnapshot | None:
        return (
            self.db.query(DatasetLineageSnapshot)
            .filter(
                DatasetLineageSnapshot.analysis_id == analysis_id,
                DatasetLineageSnapshot.stage == stage,
            )
            .order_by(DatasetLineageSnapshot.version.desc())
            .first()
        )

    def _read_snapshot_df(self, snap: DatasetLineageSnapshot) -> pd.DataFrame | None:
        if snap.storage_path:
            try:
                return pd.read_parquet(snap.storage_path)
            except Exception:
                pass
        if snap.object_key:
            from object_storage.object_store import try_build_default_store

            store = try_build_default_store()
            if store:
                try:
                    body = store.download_object_body(snap.object_key)
                    return pd.read_parquet(io.BytesIO(body))
                except Exception:
                    pass
        return None

    def load_original_dataframe(self, analysis_id: int) -> tuple[pd.DataFrame, DatasetLineageSnapshot | None]:
        """Immutable upload snapshot — persisted once, never transformed."""
        from services.normalization_transform_service import ensure_original_snapshot

        snap = self._latest_snapshot(analysis_id, "original")
        if snap:
            df = self._read_snapshot_df(snap)
            if df is not None:
                return df, snap

        ensure_original_snapshot(self.db, analysis_id)
        self.db.flush()
        snap = self._latest_snapshot(analysis_id, "original")
        if snap:
            df = self._read_snapshot_df(snap)
            if df is not None:
                return df, snap

        raise ValueError("Original dataset snapshot unavailable")

    def load_working_processed_dataframe(
        self, analysis_id: int
    ) -> tuple[pd.DataFrame, DatasetLineageSnapshot | None]:
        """Pre-approval working snapshot — weighted if applied, else imputed."""
        stage = resolve_working_stage(self.db, analysis_id)
        snap = self._latest_snapshot(analysis_id, stage)
        if snap:
            df = self._read_snapshot_df(snap)
            if df is not None:
                return df, snap

        from services.phase_snapshot_service import PhaseSnapshotService

        PhaseSnapshotService(self.db).snapshot_imputation(analysis_id)
        self.db.flush()
        stage = resolve_working_stage(self.db, analysis_id)
        snap = self._latest_snapshot(analysis_id, stage)
        if snap:
            df = self._read_snapshot_df(snap)
            if df is not None:
                return df, snap

        raise ValueError("Working dataset snapshot unavailable — complete missing value review first")

    def load_processed_dataframe(self, analysis_id: int) -> tuple[pd.DataFrame, DatasetLineageSnapshot | None]:
        """Canonical processed dataset — approved final snapshot when present, else working."""
        stage = resolve_processed_stage(self.db, analysis_id)
        if stage == FINAL_STAGE:
            snap = self._latest_snapshot(analysis_id, FINAL_STAGE)
            if snap:
                df = self._read_snapshot_df(snap)
                if df is not None:
                    return df, snap
        return self.load_working_processed_dataframe(analysis_id)

    def persist_final_approved_snapshot(
        self,
        analysis_id: int,
        *,
        user_id: int | None = None,
        approved_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Materialize the approved processed dataset as the single canonical final snapshot."""
        from services.analysis_query import get_analysis_meta
        from services.apply_service import _derived_dir, _persist_snapshot
        from object_storage.object_store import try_build_default_store

        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")

        existing = self._latest_snapshot(analysis_id, FINAL_STAGE)
        if existing:
            df = self._read_snapshot_df(existing)
            if df is not None:
                return {
                    "stage": FINAL_STAGE,
                    "version": existing.version,
                    "storage_path": existing.storage_path,
                    "object_key": existing.object_key,
                    "row_count": existing.row_count,
                    "column_count": existing.column_count,
                    "phase": STAGE_LABELS[FINAL_STAGE],
                    "already_exists": True,
                }

        df, source_snap = self.load_working_processed_dataframe(analysis_id)
        from database.models import Dataset

        ds = self.db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
        store = try_build_default_store() if ds and ds.object_key else None
        source_stage = source_snap.stage if source_snap else resolve_working_stage(self.db, analysis_id)
        approved_at = approved_at or datetime.utcnow()

        meta: dict[str, Any] = {
            "phase": STAGE_LABELS[FINAL_STAGE],
            "approved_at": approved_at.isoformat(),
            "source_stage": source_stage,
            "source_snapshot_id": source_snap.id if source_snap else None,
            "source_snapshot_version": source_snap.version if source_snap else None,
            "approved_by_user_id": user_id,
        }
        snap_meta = _persist_snapshot(
            self.db,
            analysis_id=analysis_id,
            dataset_id=an.dataset_id,
            stage=FINAL_STAGE,
            df=df,
            store=store,
            meta=meta,
        )

        final_csv = _derived_dir() / f"analysis_{analysis_id}_final.csv"
        df.to_csv(final_csv, index=False)
        snap_meta["csv_export"] = str(final_csv)
        snap_meta["phase"] = STAGE_LABELS[FINAL_STAGE]
        snap_meta["already_exists"] = False
        return snap_meta

    @staticmethod
    def missing_cell_count(df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        return int(df.isna().sum().sum())

    @staticmethod
    def dataset_meta(df: pd.DataFrame, snap: DatasetLineageSnapshot | None = None) -> dict[str, Any]:
        snapshot_meta = None
        if snap:
            snapshot_meta = {
                "stage": snap.stage,
                "version": snap.version,
                "row_count": snap.row_count or len(df),
                "column_count": snap.column_count or len(df.columns),
                "storage_path": snap.storage_path,
                "created_at": snap.created_at.isoformat() if snap.created_at else None,
            }
        return {
            "row_count": len(df),
            "column_count": len(df.columns),
            "columns": [str(c) for c in df.columns],
            "missing_cells": DatasetSnapshotService.missing_cell_count(df),
            "snapshot": snapshot_meta,
        }

    @staticmethod
    def _row_matches_search(row: pd.Series, search: str) -> bool:
        needle = search.strip().lower()
        if not needle:
            return True
        for val in row.values:
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            if needle in str(val).lower():
                return True
        return False

    def paginate_rows(
        self,
        df: pd.DataFrame,
        *,
        offset: int = 0,
        limit: int = 50,
        columns: list[str] | None = None,
        search: str | None = None,
        column_filter: str | None = None,
        row_filter: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        visible_cols = [c for c in (columns or list(df.columns)) if c in df.columns]
        if not visible_cols:
            visible_cols = [str(c) for c in df.columns]

        working = df
        if column_filter and column_filter in df.columns:
            visible_cols = [column_filter]

        if search and search.strip():
            mask = working.apply(lambda r: self._row_matches_search(r, search), axis=1)
            working = working[mask]

        if row_filter and row_filter.strip():
            try:
                target = int(row_filter.strip())
                working = working.iloc[[i for i in range(len(working)) if working.index[i] == target or i == target]]
            except ValueError:
                pattern = re.compile(re.escape(row_filter.strip()), re.IGNORECASE)
                mask = working.apply(
                    lambda r: any(pattern.search(str(v)) for v in r.values if v is not None and not pd.isna(v)),
                    axis=1,
                )
                working = working[mask]

        total = len(working)
        page = working.iloc[offset : offset + limit]
        rows: list[dict[str, Any]] = []
        for pos, (_, series) in enumerate(page.iterrows()):
            row_index = int(page.index[pos]) if hasattr(page.index, "__getitem__") else offset + pos
            payload: dict[str, Any] = {"_row_index": row_index}
            for col in visible_cols:
                val = series[col]
                if pd.isna(val):
                    payload[str(col)] = None
                elif hasattr(val, "item"):
                    payload[str(col)] = val.item()
                else:
                    payload[str(col)] = val
            rows.append(payload)

        return {
            "total_rows": total,
            "offset": offset,
            "limit": limit,
            "columns": [str(c) for c in visible_cols],
            "rows": rows,
        }

    def export_dataframe(self, df: pd.DataFrame, fmt: str) -> tuple[bytes, str, str]:
        fmt = fmt.lower()
        if fmt == "csv":
            return df.to_csv(index=False).encode("utf-8"), "text/csv", "csv"
        if fmt == "xlsx":
            buf = io.BytesIO()
            df.to_excel(buf, index=False, engine="openpyxl")
            return buf.getvalue(), (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ), "xlsx"
        raise ValueError(f"Unsupported export format: {fmt}")

    def ensure_review_snapshot(self, analysis_id: int) -> dict[str, Any] | None:
        """Return metadata for the canonical processed snapshot (final if approved)."""
        stage = resolve_processed_stage(self.db, analysis_id)
        snap = self._latest_snapshot(analysis_id, stage)
        if not snap:
            return None
        phase_label = STAGE_LABELS.get(snap.stage, snap.stage)
        return {
            "analysis_id": analysis_id,
            "phase": phase_label,
            "stage": snap.stage,
            "version": snap.version,
            "row_count": snap.row_count,
            "column_count": snap.column_count,
            "dataset_path": snap.storage_path,
            "created_at": snap.created_at.isoformat() if snap.created_at else datetime.utcnow().isoformat(),
            "meta": snap.meta or {},
        }

    def final_dataset_meta(self, analysis_id: int) -> dict[str, Any] | None:
        snap = self._latest_snapshot(analysis_id, FINAL_STAGE)
        if not snap:
            return None
        meta = snap.meta or {}
        return {
            "stage": FINAL_STAGE,
            "phase": STAGE_LABELS[FINAL_STAGE],
            "version": snap.version,
            "storage_path": snap.storage_path,
            "object_key": snap.object_key,
            "csv_export": meta.get("csv_export"),
            "row_count": snap.row_count,
            "column_count": snap.column_count,
            "approved_at": meta.get("approved_at"),
            "source_stage": meta.get("source_stage"),
        }
