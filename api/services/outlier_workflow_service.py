"""Outlier method selection, detection, and row-level decision persistence."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import pandas as pd
from sqlalchemy.orm import Session

from core.ingestion import dataframe_for_uploaded_dataset
from core.json_safe import make_json_safe
from core.rule_validator import normalize_schema
from database.models import Dataset, OutlierDecision, Phase3AnomalyIntel
from object_storage.object_store import try_build_default_store
from outliers.anomaly_handler import detect_outliers_for_column, merge_column_detection
from services.analysis_query import (
    build_phase3_from_relational,
    get_analysis_meta,
    merge_checkpoint_phase3_overlay,
)
from services.analysis_payload_cache import invalidate_analysis_cache
from services.normalization_service import NormalizationService
from services.phase_audit_service import PhaseAuditService

MethodChoice = Literal["Z_SCORE", "IQR"]
DecisionChoice = Literal["KEEP", "NORMALIZE", "DELETE_VALUE", "DELETE_ROW", "EDIT_VALUE"]


class OutlierWorkflowService:
    def __init__(self, db: Session):
        self.db = db

    def _load_analysis(self, analysis_id: int):
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        if an.status != "complete":
            raise ValueError("Analysis not complete")
        return an

    def _load_df(self, analysis_id: int) -> tuple[pd.DataFrame, dict[str, str]]:
        an = self._load_analysis(analysis_id)
        ds = self.db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
        if not ds:
            raise ValueError("Dataset not found")
        store = try_build_default_store() if ds.object_key else None
        df = dataframe_for_uploaded_dataset(
            dataset_storage_path=ds.storage_path,
            dataset_object_key=ds.object_key,
            filename=ds.filename,
            object_store=store,
        )
        from services.analysis_results_service import resolve_semantic_analysis_payload

        payload = resolve_semantic_analysis_payload(self.db, analysis_id) or {}
        schema = (
            (payload.get("profiling_summary") or {}).get("schema")
            or payload.get("schema")
            or {}
        )
        if not schema:
            schema = {str(c): "numeric" if pd.api.types.is_numeric_dtype(df[c]) else "categorical" for c in df.columns}
        return normalize_schema(df, schema), schema

    def _column_maps(self, analysis_id: int) -> tuple[dict[str, str], dict[str, str]]:
        """Return (ui_to_physical, physical_to_ui) name maps."""
        records = NormalizationService(self.db)._ensure_columns_seeded(analysis_id)
        ui_to_physical: dict[str, str] = {}
        physical_to_ui: dict[str, str] = {}
        for col in records:
            orig = str(col.name)
            norm = str(col.normalized_name or col.name)
            ui_to_physical[norm] = orig
            ui_to_physical[orig] = orig
            physical_to_ui[orig] = norm
        return ui_to_physical, physical_to_ui

    def _resolve_ui_column(self, analysis_id: int, column: str) -> str:
        ui_to_physical, _ = self._column_maps(analysis_id)
        return ui_to_physical.get(column, column)

    def _find_anomaly_block(self, results: list[dict[str, Any]], column: str, analysis_id: int) -> dict[str, Any] | None:
        physical = self._resolve_ui_column(analysis_id, column)
        for block in results:
            if not isinstance(block, dict):
                continue
            bcol = str(block.get("column") or "")
            borig = str(block.get("original_column") or "")
            if bcol == column or bcol == physical or borig == column or borig == physical:
                return block
        return None

    def _match_block_column(self, block: dict[str, Any], column: str, analysis_id: int) -> bool:
        physical = self._resolve_ui_column(analysis_id, column)
        bcol = str(block.get("column") or "")
        borig = str(block.get("original_column") or "")
        return bcol in {column, physical} or borig in {column, physical}

    def _get_phase3(self, analysis_id: int) -> dict[str, Any]:
        return build_phase3_from_relational(self.db, analysis_id)

    def _save_phase3(self, analysis_id: int, dataset_id: int, phase3: dict[str, Any]) -> None:
        intel = (
            self.db.query(Phase3AnomalyIntel)
            .filter(Phase3AnomalyIntel.analysis_id == analysis_id)
            .first()
        )
        payload = make_json_safe(
            {
                "anomaly_results": phase3.get("anomaly_results") or [],
                "anomaly_candidates": phase3.get("anomaly_candidates") or [],
                "goodness_of_fit": phase3.get("goodness_of_fit") or [],
                "method_selections": phase3.get("method_selections") or {},
            }
        )
        if intel:
            intel.payload = payload
        else:
            self.db.add(
                Phase3AnomalyIntel(
                    dataset_id=dataset_id,
                    analysis_id=analysis_id,
                    payload=payload,
                )
            )
        merge_checkpoint_phase3_overlay(
            self.db,
            analysis_id,
            {
                k: phase3[k]
                for k in ("method_selections", "outlier_row_decisions")
                if k in phase3
            },
        )

    def select_method(self, analysis_id: int, column: str, method: MethodChoice) -> dict[str, Any]:
        an = self._load_analysis(analysis_id)
        phase3 = self._get_phase3(analysis_id)
        results = phase3.get("anomaly_results") or []
        block = self._find_anomaly_block(results, column, analysis_id)
        if not block:
            raise ValueError(f"Column {column} not found in anomaly analysis")

        _, physical_to_ui = self._column_maps(analysis_id)
        ui_column = physical_to_ui.get(self._resolve_ui_column(analysis_id, column), column)

        selections = dict(phase3.get("method_selections") or {})
        selections[ui_column] = method
        phase3["method_selections"] = selections

        for r in results:
            if self._match_block_column(r, column, analysis_id):
                r["method_selected"] = method
                r["detection_run"] = False
                r["z_score_hits"] = []
                r["iqr_hits"] = []
                r["column"] = ui_column

        phase3["anomaly_results"] = results
        phase3["anomaly_candidates"] = [
            c for c in (phase3.get("anomaly_candidates") or [])
            if str(c.get("column") or "") not in {column, ui_column}
        ]
        self._save_phase3(analysis_id, an.dataset_id, phase3)
        PhaseAuditService(self.db).record(
            analysis_id=analysis_id,
            phase="anomaly",
            action="select_method",
            entity_type="column",
            entity_id=column,
            new_value=method,
        )
        invalidate_analysis_cache(analysis_id)
        self.db.commit()
        return {"analysis_id": analysis_id, "column": column, "method": method}

    def run_detection(self, analysis_id: int, column: str) -> dict[str, Any]:
        an = self._load_analysis(analysis_id)
        phase3 = self._get_phase3(analysis_id)
        selections = phase3.get("method_selections") or {}
        _, physical_to_ui = self._column_maps(analysis_id)
        physical_col = self._resolve_ui_column(analysis_id, column)
        ui_column = physical_to_ui.get(physical_col, column)
        method = selections.get(column) or selections.get(ui_column)
        if method not in ("Z_SCORE", "IQR"):
            raise ValueError(f"Select Z_SCORE or IQR for column {column} first")

        df, schema = self._load_df(analysis_id)
        if physical_col not in df.columns:
            raise ValueError(f"Column {column} not in dataset")

        results = phase3.get("anomaly_results") or []
        block = self._find_anomaly_block(results, column, analysis_id)
        detection = detect_outliers_for_column(
            df, schema, physical_col, method, column_block=block
        )
        for cand in detection.get("candidates") or []:
            cand["column"] = ui_column
        updated_results, updated_candidates = merge_column_detection(
            results,
            phase3.get("anomaly_candidates") or [],
            ui_column,
            method,
            detection,
        )
        for r in updated_results:
            if self._match_block_column(r, column, analysis_id):
                r["column"] = ui_column
        phase3["anomaly_results"] = updated_results
        phase3["anomaly_candidates"] = updated_candidates
        self._save_phase3(analysis_id, an.dataset_id, phase3)
        PhaseAuditService(self.db).record(
            analysis_id=analysis_id,
            phase="anomaly",
            action="run_detection",
            entity_type="column",
            entity_id=column,
            payload={"method": method, "count": len(detection.get("candidates") or [])},
        )
        invalidate_analysis_cache(analysis_id)
        self.db.commit()
        return {
            "analysis_id": analysis_id,
            "column": column,
            "method": method,
            "candidates": detection.get("candidates") or [],
            "count": len(detection.get("candidates") or []),
        }

    def save_row_decisions(
        self,
        analysis_id: int,
        column: str,
        decisions: list[dict[str, Any]],
        *,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        an = self._load_analysis(analysis_id)
        self.db.query(OutlierDecision).filter(
            OutlierDecision.analysis_id == analysis_id,
            OutlierDecision.column_name == column,
        ).delete(synchronize_session=False)

        rows: list[OutlierDecision] = []
        converted_missing: list[dict[str, Any]] = []
        audit = PhaseAuditService(self.db)
        for d in decisions:
            decision = str(d["decision"]).upper()
            audit_action = decision
            if decision == "DELETE_VALUE":
                audit_action = "CONVERT_TO_MISSING"
                converted_missing.append(
                    {
                        "row_index": int(d["row_index"]),
                        "column_name": column,
                        "original_value": d.get("old_value"),
                        "converted_to_missing": True,
                    }
                )
            elif decision == "EDIT_VALUE":
                audit_action = "IGNORE"
            rows.append(
                OutlierDecision(
                    analysis_id=analysis_id,
                    column_name=column,
                    row_index=int(d["row_index"]),
                    method=str(d.get("method") or d.get("methodology") or ""),
                    severity=str(d.get("severity") or "") or None,
                    decision=decision,
                    old_value=str(d.get("old_value")) if d.get("old_value") is not None else None,
                    new_value=str(d.get("new_value")) if d.get("new_value") is not None else None,
                    confidence=float(d["confidence"]) if d.get("confidence") is not None else None,
                    reviewed_by=user_id,
                    created_at=datetime.utcnow(),
                )
            )
            audit.record(
                analysis_id=analysis_id,
                phase="anomaly",
                action=audit_action,
                user_id=user_id,
                entity_type="row",
                entity_id=f"{column}:{d['row_index']}",
                old_value=d.get("old_value"),
                new_value=d.get("new_value"),
                payload={
                    "column": column,
                    "row_index": d.get("row_index"),
                    "method": d.get("method"),
                    "methodology": d.get("method"),
                    "severity": d.get("severity"),
                    "confidence": d.get("confidence"),
                },
            )
        if rows:
            self.db.add_all(rows)

        phase3 = self._get_phase3(analysis_id)
        col_decisions = dict(phase3.get("outlier_row_decisions") or {})
        col_decisions[column] = decisions
        phase3["outlier_row_decisions"] = col_decisions
        if converted_missing:
            handoff = list(phase3.get("converted_to_missing") or [])
            handoff.extend(converted_missing)
            phase3["converted_to_missing"] = handoff
        self._save_phase3(analysis_id, an.dataset_id, phase3)
        invalidate_analysis_cache(analysis_id)
        self.db.commit()
        return {"success": True, "analysis_id": analysis_id, "column": column, "saved": len(rows)}

    def review_progress(self, analysis_id: int) -> dict[str, Any]:
        phase3 = self._get_phase3(analysis_id)
        candidates = [
            c for c in (phase3.get("anomaly_candidates") or []) if isinstance(c, dict)
        ]
        total = len(candidates)
        candidate_keys = {
            (str(c.get("column") or ""), int(c.get("row")))
            for c in candidates
            if c.get("row") is not None
        }
        saved_rows = self.db.query(OutlierDecision).filter(
            OutlierDecision.analysis_id == analysis_id
        ).all()
        reviewed_keys = {(r.column_name, r.row_index) for r in saved_rows}
        reviewed = len(candidate_keys & reviewed_keys) if candidate_keys else len(reviewed_keys)
        by_severity: dict[str, int] = {}
        for c in candidates:
            sev = str(c.get("severity") or "LOW").upper()
            by_severity[sev] = by_severity.get(sev, 0) + 1
        remaining = max(0, total - reviewed)
        pct = round((reviewed / total) * 100, 1) if total else 100.0
        return {
            "analysis_id": analysis_id,
            "total_anomalies": total,
            "reviewed": reviewed,
            "remaining": remaining,
            "progress_pct": pct,
            "complete": total == 0 or reviewed >= total,
            "by_severity": by_severity,
        }

    def list_decisions(self, analysis_id: int, column: str | None = None) -> list[dict[str, Any]]:
        q = self.db.query(OutlierDecision).filter(OutlierDecision.analysis_id == analysis_id)
        if column:
            q = q.filter(OutlierDecision.column_name == column)
        return [
            {
                "id": r.id,
                "analysis_id": r.analysis_id,
                "column_name": r.column_name,
                "row_index": r.row_index,
                "method": r.method,
                "severity": r.severity,
                "decision": r.decision,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "timestamp": r.created_at.isoformat() if r.created_at else None,
            }
            for r in q.order_by(OutlierDecision.column_name, OutlierDecision.row_index).all()
        ]
