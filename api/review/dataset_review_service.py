"""Dataset review & approval orchestration."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from review.dataset_diff_service import DatasetDiffService
from review.dataset_snapshot_service import DatasetSnapshotService
from services.phase_audit_service import PhaseAuditService
from services.phase_status_service import PhaseStatusService


class DatasetReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.snapshots = DatasetSnapshotService(db)
        self.diff = DatasetDiffService(db)

    def _phase_flags(self, analysis_id: int) -> dict[str, bool]:
        ps = PhaseStatusService(self.db)
        row = ps.get_or_create(analysis_id)
        imputation = ps.recompute_imputation_columns(analysis_id)
        if imputation["complete"]:
            row.missing_value_completed = True
        return {
            "missing_value_completed": bool(row.missing_value_completed),
            "dataset_review_completed": bool(row.dataset_review_completed),
        }

    def get_review_payload(self, analysis_id: int) -> dict[str, Any]:
        flags = self._phase_flags(analysis_id)
        if not flags["missing_value_completed"]:
            raise ValueError("Complete Missing Value Intelligence before dataset review")

        original_df, orig_snap = self.snapshots.load_original_dataframe(analysis_id)
        processed_df, proc_snap = self.snapshots.load_processed_dataframe(analysis_id)
        self.db.commit()
        diff_payload = self.diff.build_diff(analysis_id, original_df, processed_df)

        review_snap = self.snapshots.ensure_review_snapshot(analysis_id)
        snapshot_list = self.snapshots.list_snapshots(analysis_id)
        if review_snap and not any(s.get("phase") == "latest_review_version" for s in snapshot_list):
            snapshot_list.append(review_snap)

        can_approve = flags["missing_value_completed"] and not flags["dataset_review_completed"]
        can_report = flags["dataset_review_completed"]

        return {
            "analysis_id": analysis_id,
            "original_dataset": self.snapshots.dataset_meta(original_df, orig_snap),
            "processed_dataset": self.snapshots.dataset_meta(processed_df, proc_snap),
            "summary": diff_payload["summary"],
            "diff_summary": diff_payload["diff_summary"],
            "snapshots": [
                {
                    "stage": s.get("stage") or s.get("phase"),
                    "version": s.get("version"),
                    "row_count": s.get("row_count", 0),
                    "column_count": s.get("column_count", 0),
                    "storage_path": s.get("dataset_path") or s.get("storage_path"),
                    "created_at": s.get("created_at"),
                }
                for s in snapshot_list
            ],
            "dataset_review_completed": flags["dataset_review_completed"],
            "missing_value_completed": flags["missing_value_completed"],
            "can_approve": can_approve,
            "can_proceed_to_report": can_report,
        }

    def get_rows(
        self,
        analysis_id: int,
        side: str,
        *,
        offset: int = 0,
        limit: int = 50,
        columns: list[str] | None = None,
        search: str | None = None,
        column_filter: str | None = None,
        row_filter: str | None = None,
    ) -> dict[str, Any]:
        flags = self._phase_flags(analysis_id)
        if not flags["missing_value_completed"]:
            raise ValueError("Complete Missing Value Intelligence before dataset review")

        if side == "original":
            df, _ = self.snapshots.load_original_dataframe(analysis_id)
        elif side == "processed":
            df, _ = self.snapshots.load_processed_dataframe(analysis_id)
        else:
            raise ValueError("side must be 'original' or 'processed'")

        page = self.snapshots.paginate_rows(
            df,
            offset=offset,
            limit=limit,
            columns=columns,
            search=search,
            column_filter=column_filter,
            row_filter=row_filter,
        )
        page["side"] = side
        return page

    def get_column_changes(self, analysis_id: int, column: str) -> dict[str, Any]:
        original_df, _ = self.snapshots.load_original_dataframe(analysis_id)
        processed_df, _ = self.snapshots.load_processed_dataframe(analysis_id)
        return self.diff.column_change_detail(analysis_id, column, original_df, processed_df)

    def get_row_inspection(self, analysis_id: int, row_index: int) -> dict[str, Any]:
        original_df, _ = self.snapshots.load_original_dataframe(analysis_id)
        processed_df, _ = self.snapshots.load_processed_dataframe(analysis_id)
        return self.diff.row_inspection(analysis_id, row_index, original_df, processed_df)

    def approve_dataset(self, analysis_id: int, user_id: int | None = None) -> dict[str, Any]:
        flags = self._phase_flags(analysis_id)
        if not flags["missing_value_completed"]:
            raise ValueError("Complete Missing Value Intelligence before approving the dataset")
        if flags["dataset_review_completed"]:
            return {
                "success": True,
                "analysis_id": analysis_id,
                "dataset_review_completed": True,
                "can_proceed_to_report": True,
            }

        row = PhaseStatusService(self.db).get_or_create(analysis_id)
        row.dataset_review_completed = True
        row.updated_at = datetime.utcnow()
        PhaseAuditService(self.db).record(
            analysis_id=analysis_id,
            phase="dataset_review",
            action="approve",
            user_id=user_id,
            entity_type="dataset",
            entity_id=str(analysis_id),
            payload={"approved_at": datetime.utcnow().isoformat()},
        )
        self.db.commit()
        return {
            "success": True,
            "analysis_id": analysis_id,
            "dataset_review_completed": True,
            "can_proceed_to_report": True,
        }

    def build_download(
        self,
        analysis_id: int,
        kind: str,
    ) -> tuple[bytes, str, str]:
        flags = self._phase_flags(analysis_id)
        if not flags["missing_value_completed"]:
            raise ValueError("Complete Missing Value Intelligence before downloading review artifacts")

        if kind == "original_csv":
            df, _ = self.snapshots.load_original_dataframe(analysis_id)
            data, mime, ext = self.snapshots.export_dataframe(df, "csv")
            return data, mime, f"analysis_{analysis_id}_original.{ext}"
        if kind == "original_xlsx":
            df, _ = self.snapshots.load_original_dataframe(analysis_id)
            data, mime, ext = self.snapshots.export_dataframe(df, "xlsx")
            return data, mime, f"analysis_{analysis_id}_original.{ext}"
        if kind == "processed_csv":
            df, _ = self.snapshots.load_processed_dataframe(analysis_id)
            data, mime, ext = self.snapshots.export_dataframe(df, "csv")
            return data, mime, f"analysis_{analysis_id}_processed.{ext}"
        if kind == "processed_xlsx":
            df, _ = self.snapshots.load_processed_dataframe(analysis_id)
            data, mime, ext = self.snapshots.export_dataframe(df, "xlsx")
            return data, mime, f"analysis_{analysis_id}_processed.{ext}"
        if kind == "audit_summary":
            events = PhaseAuditService(self.db).list_events(analysis_id)
            body = json.dumps({"analysis_id": analysis_id, "events": events}, indent=2, default=str)
            return body.encode("utf-8"), "application/json", f"analysis_{analysis_id}_audit_summary.json"
        if kind == "transformation_summary":
            payload = self.get_review_payload(analysis_id)
            slim = {
                "analysis_id": analysis_id,
                "summary": payload["summary"],
                "diff_summary": payload["diff_summary"],
                "snapshots": payload["snapshots"],
            }
            body = json.dumps(slim, indent=2, default=str)
            return body.encode("utf-8"), "application/json", f"analysis_{analysis_id}_transformation_summary.json"
        raise ValueError(f"Unknown download kind: {kind}")
