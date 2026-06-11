"""Read lineage snapshots and paginate dataset rows for review (no reprocessing)."""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from core.ingestion import dataframe_for_uploaded_dataset, infer_schema
from database.models import Dataset, DatasetLineageSnapshot
from object_storage.object_store import try_build_default_store
from services.analysis_query import get_analysis_meta, load_analysis_checkpoint

STAGE_LABELS: dict[str, str] = {
    "original": "v1_upload",
    "normalized": "v2_normalization",
    "validated": "v3_rule_validation",
    "anomaly_reviewed": "v4_anomaly",
    "imputed": "v5_missing_value",
    "final": "v6_review",
}

PROCESSED_STAGE_PRIORITY = ("imputed", "anomaly_reviewed", "validated", "normalized", "final")


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
            store = try_build_default_store()
            if store:
                try:
                    body = store.download_object_body(snap.object_key)
                    return pd.read_parquet(io.BytesIO(body))
                except Exception:
                    pass
        return None

    def load_original_dataframe(self, analysis_id: int) -> tuple[pd.DataFrame, DatasetLineageSnapshot | None]:
        """Raw upload — never re-applies pipeline transforms."""
        original_snap = self._latest_snapshot(analysis_id, "original")
        if original_snap:
            df = self._read_snapshot_df(original_snap)
            if df is not None:
                return df, original_snap

        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        ds = self.db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
        if not ds:
            raise ValueError("Dataset not found")

        store = try_build_default_store() if ds.object_key else None
        try:
            df = dataframe_for_uploaded_dataset(ds.storage_path, ds.object_key, ds.filename, store)
        except (FileNotFoundError, OSError):
            if ds.object_key and store:
                df = dataframe_for_uploaded_dataset(None, ds.object_key, ds.filename, store)
            else:
                raise
        return df, original_snap

    def load_processed_dataframe(self, analysis_id: int) -> tuple[pd.DataFrame, DatasetLineageSnapshot | None]:
        """Latest processed artifact — materialized from persisted decisions when needed."""
        from services.apply_service import materialize_processed_dataframe, persist_processed_snapshot

        try:
            df = materialize_processed_dataframe(self.db, analysis_id)
            snap = self._latest_snapshot(analysis_id, "imputed")
            if snap is None or (snap.row_count or 0) != len(df):
                persist_processed_snapshot(self.db, analysis_id)
                self.db.flush()
                snap = self._latest_snapshot(analysis_id, "imputed")
            return df, snap
        except Exception:
            pass

        for stage in PROCESSED_STAGE_PRIORITY:
            snap = self._latest_snapshot(analysis_id, stage)
            if not snap:
                continue
            df = self._read_snapshot_df(snap)
            if df is not None:
                return df, snap

        df, _ = self.load_original_dataframe(analysis_id)
        return df, None

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
        """Alias latest processed snapshot as review-ready metadata (no duplicate write)."""
        snap = self._latest_snapshot(analysis_id, "imputed")
        if not snap:
            return None
        return {
            "analysis_id": analysis_id,
            "phase": "latest_review_version",
            "stage": snap.stage,
            "version": snap.version,
            "row_count": snap.row_count,
            "column_count": snap.column_count,
            "dataset_path": snap.storage_path,
            "created_at": snap.created_at.isoformat() if snap.created_at else datetime.utcnow().isoformat(),
        }
