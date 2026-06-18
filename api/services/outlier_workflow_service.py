"""Outlier method selection, detection, and row-level decision persistence."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import pandas as pd
from sqlalchemy.orm import Session

from core.ingestion import infer_schema
from core.json_safe import make_json_safe
from database.models import OutlierDecision, Phase3AnomalyIntel
from services.analysis_dataframe_service import (
    column_identity_aliases,
    load_phase_dataframe,
    resolve_column_alias,
)
from services.analysis_query import get_analysis_meta, load_analysis_checkpoint
from outliers.anomaly_handler import detect_outliers_for_column, merge_column_detection
from services.analysis_query import load_checkpoint_phase3_overlay, merge_checkpoint_phase3_overlay
from services.analysis_payload_cache import invalidate_analysis_cache
from services.phase_status_cache import invalidate_phase_status
from services.normalization_service import NormalizationService
from services.phase_audit_service import PhaseAuditService
from services.phase_snapshot_service import refresh_downstream_with_status
from services.phase_status_service import PhaseStatusService

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

    def _alias_groups(self, analysis_id: int) -> dict[str, set[str]]:
        an = get_analysis_meta(self.db, analysis_id)
        checkpoint = load_analysis_checkpoint(self.db, analysis_id) or {}
        config = an.config if an and isinstance(an.config, dict) else {}
        groups = column_identity_aliases(checkpoint, config)

        ui_to_physical, physical_to_ui = self._column_maps(analysis_id)
        for ui, physical in ui_to_physical.items():
            groups.setdefault(ui, set()).update({ui, physical})
            groups.setdefault(physical, set()).update({ui, physical})
        for physical, ui in physical_to_ui.items():
            groups.setdefault(physical, set()).update({ui, physical})
            groups.setdefault(ui, set()).update({ui, physical})

        merged: dict[str, set[str]] = {}
        for names in groups.values():
            bucket: set[str] = set()
            for name in names:
                bucket |= groups.get(name, {name})
            for name in bucket:
                merged[name] = bucket
        return merged

    def _load_df(self, analysis_id: int) -> tuple[pd.DataFrame, dict[str, Any]]:
        return load_phase_dataframe(self.db, analysis_id, "anomaly")

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

    def _physical_column(self, analysis_id: int, column: str) -> str:
        ui_to_physical, _ = self._column_maps(analysis_id)
        return ui_to_physical.get(column, column)

    def _ui_column(self, analysis_id: int, column: str) -> str:
        _, physical_to_ui = self._column_maps(analysis_id)
        physical = self._physical_column(analysis_id, column)
        return physical_to_ui.get(physical, column)

    def _column_aliases(self, analysis_id: int, column: str) -> set[str]:
        groups = self._alias_groups(analysis_id)
        aliases = set(groups.get(column, {column}))
        aliases.add(column)
        aliases.add(self._physical_column(analysis_id, column))
        aliases.add(self._ui_column(analysis_id, column))
        return {a for a in aliases if a}

    def _resolve_df_column(
        self,
        df: pd.DataFrame,
        analysis_id: int,
        column: str,
        block: dict[str, Any] | None = None,
    ) -> str | None:
        groups = self._alias_groups(analysis_id)
        candidates: set[str] = set(groups.get(column, {column}))
        if block:
            for key in ("column", "original_column"):
                val = block.get(key)
                if val:
                    candidates |= groups.get(str(val), {str(val)})
        hit = resolve_column_alias(column, groups, set(df.columns))
        if hit:
            return hit
        for name in candidates:
            if name in df.columns:
                return name
        return None

    def _resolve_method(
        self,
        selections: dict[str, Any],
        analysis_id: int,
        column: str,
        block: dict[str, Any] | None = None,
    ) -> str | None:
        aliases = self._column_aliases(analysis_id, column)
        if block:
            for key in ("column", "original_column"):
                val = block.get(key)
                if val:
                    aliases |= self._column_aliases(analysis_id, str(val))
            selected = str(block.get("method_selected") or "").upper()
            if selected in ("Z_SCORE", "IQR"):
                return selected
        for name in aliases:
            method = str(selections.get(name) or "").upper()
            if method in ("Z_SCORE", "IQR"):
                return method
        return None

    def _find_anomaly_block(self, results: list[dict[str, Any]], column: str, analysis_id: int) -> dict[str, Any] | None:
        aliases = self._column_aliases(analysis_id, column)
        for block in results:
            if not isinstance(block, dict):
                continue
            bcol = str(block.get("column") or "")
            borig = str(block.get("original_column") or "")
            if bcol in aliases or borig in aliases:
                return block
        return None

    def _match_block_column(self, block: dict[str, Any], column: str, analysis_id: int) -> bool:
        aliases = self._column_aliases(analysis_id, column)
        bcol = str(block.get("column") or "")
        borig = str(block.get("original_column") or "")
        return bcol in aliases or borig in aliases

    def _load_anomaly_payload(self, analysis_id: int) -> dict[str, Any]:
        """Load anomaly intel without rebuilding validation/imputation phase3."""
        intel = (
            self.db.query(Phase3AnomalyIntel)
            .filter(Phase3AnomalyIntel.analysis_id == analysis_id)
            .first()
        )
        payload = dict(intel.payload) if intel and isinstance(intel.payload, dict) else {}
        overlay = load_checkpoint_phase3_overlay(self.db, analysis_id)
        if overlay.get("method_selections"):
            payload["method_selections"] = overlay["method_selections"]
        if overlay.get("outlier_row_decisions"):
            payload["outlier_row_decisions"] = overlay["outlier_row_decisions"]
        return {
            "anomaly_results": payload.get("anomaly_results") or [],
            "anomaly_candidates": payload.get("anomaly_candidates") or [],
            "goodness_of_fit": payload.get("goodness_of_fit") or [],
            "method_selections": payload.get("method_selections") or {},
            "outlier_row_decisions": payload.get("outlier_row_decisions") or {},
        }

    def _get_phase3(self, analysis_id: int) -> dict[str, Any]:
        return self._load_anomaly_payload(analysis_id)

    def _load_detection_series(
        self,
        analysis_id: int,
        column: str,
        block: dict[str, Any] | None,
    ) -> tuple[pd.Series, dict[str, Any], str]:
        """Load only the target column for outlier detection."""
        from database.models import DatasetLineageSnapshot
        from services.analysis_dataframe_service import (
            WORKING_STAGE_BY_PHASE,
            _STAGE_FALLBACKS,
            load_snapshot_dataframe,
        )

        stage = WORKING_STAGE_BY_PHASE.get("anomaly", "validated")
        stages = [stage, *_STAGE_FALLBACKS.get(stage, ())]
        df: pd.DataFrame | None = None
        df_col: str | None = None

        for st in stages:
            snap = (
                self.db.query(DatasetLineageSnapshot)
                .filter(
                    DatasetLineageSnapshot.analysis_id == analysis_id,
                    DatasetLineageSnapshot.stage == st,
                )
                .order_by(DatasetLineageSnapshot.version.desc())
                .first()
            )
            if not snap or not snap.storage_path:
                continue
            try:
                import pyarrow.parquet as pq

                available = set(pq.read_schema(snap.storage_path).names)
                df_col = self._resolve_df_column(
                    type("_Cols", (), {"columns": list(available)})(),
                    analysis_id,
                    column,
                    block,
                )
                if not df_col or df_col not in available:
                    continue
                df = pd.read_parquet(snap.storage_path, columns=[df_col])
                break
            except Exception:
                snap_df = load_snapshot_dataframe(self.db, analysis_id, st)
                if snap_df is None:
                    continue
                df_col = self._resolve_df_column(snap_df, analysis_id, column, block)
                if not df_col:
                    continue
                df = snap_df[[df_col]]
                break

        if df is None or not df_col:
            full_df, schema = self._load_df(analysis_id)
            df_col = self._resolve_df_column(full_df, analysis_id, column, block)
            if not df_col:
                raise ValueError(f"Column {column} not in dataset")
            schema = infer_schema(full_df[[df_col]])
            return full_df[df_col], schema, df_col

        schema = infer_schema(df)
        return df[df_col], schema, df_col

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

    def _apply_method_selection(
        self,
        phase3: dict[str, Any],
        analysis_id: int,
        column: str,
        method: MethodChoice,
    ) -> str:
        results = phase3.get("anomaly_results") or []
        block = self._find_anomaly_block(results, column, analysis_id)
        if not block:
            raise ValueError(f"Column {column} not found in anomaly analysis")

        ui_column = self._ui_column(analysis_id, column)
        aliases = self._column_aliases(analysis_id, column)
        if block.get("column"):
            aliases.add(str(block["column"]))
        if block.get("original_column"):
            aliases.add(str(block["original_column"]))

        selections = dict(phase3.get("method_selections") or {})
        for name in aliases:
            selections[name] = method
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
        return ui_column

    def select_method(self, analysis_id: int, column: str, method: MethodChoice) -> dict[str, Any]:
        an = self._load_analysis(analysis_id)
        phase3 = self._load_anomaly_payload(analysis_id)
        self._apply_method_selection(phase3, analysis_id, column, method)
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

    def run_detection(
        self,
        analysis_id: int,
        column: str,
        method: MethodChoice | None = None,
    ) -> dict[str, Any]:
        an = self._load_analysis(analysis_id)
        phase3 = self._load_anomaly_payload(analysis_id)
        results = phase3.get("anomaly_results") or []
        block = self._find_anomaly_block(results, column, analysis_id)

        if method:
            ui_column = self._apply_method_selection(phase3, analysis_id, column, method)
        else:
            ui_column = self._ui_column(analysis_id, column)
            selections = phase3.get("method_selections") or {}
            method = self._resolve_method(selections, analysis_id, column, block)
            if not method:
                raise ValueError(f"Select Z_SCORE or IQR for column {column} first")

        series, schema, df_col = self._load_detection_series(analysis_id, column, block)
        detection = detect_outliers_for_column(
            pd.DataFrame({df_col: series}),
            schema,
            df_col,
            method,
            column_block=block,
        )
        for cand in detection.get("candidates") or []:
            cand["column"] = ui_column
        match_aliases = self._column_aliases(analysis_id, column)
        if block:
            for key in ("column", "original_column"):
                val = block.get(key)
                if val:
                    match_aliases |= self._column_aliases(analysis_id, str(val))
        updated_results, updated_candidates = merge_column_detection(
            results,
            phase3.get("anomaly_candidates") or [],
            ui_column,
            method,
            detection,
            column_aliases=match_aliases,
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
        PhaseStatusService(self.db).recompute_anomaly_columns(analysis_id, phase3=phase3)
        invalidate_analysis_cache(analysis_id)
        invalidate_phase_status(analysis_id)
        self.db.commit()
        updated_block = next(
            (r for r in updated_results if self._match_block_column(r, column, analysis_id)),
            None,
        )
        return {
            "analysis_id": analysis_id,
            "column": column,
            "method": method,
            "candidates": detection.get("candidates") or [],
            "count": len(detection.get("candidates") or []),
            "anomaly_block": updated_block,
        }

    def save_row_decisions(
        self,
        analysis_id: int,
        column: str,
        decisions: list[dict[str, Any]],
        *,
        user_id: int | None = None,
        bulk: bool = False,
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
            if not bulk:
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
        if bulk and rows:
            audit.record(
                analysis_id=analysis_id,
                phase="anomaly",
                action="KEEP_BULK",
                user_id=user_id,
                entity_type="column",
                entity_id=column,
                payload={"column": column, "rows": len(rows), "decision": "KEEP"},
            )
        if rows:
            self.db.add_all(rows)

        phase3 = self._get_phase3(analysis_id)
        col_decisions = dict(phase3.get("outlier_row_decisions") or {})
        if bulk or len(decisions) > 200:
            col_decisions[column] = {
                "bulk": True,
                "decision": "KEEP",
                "row_count": len(decisions),
            }
        else:
            col_decisions[column] = make_json_safe(decisions)
        phase3["outlier_row_decisions"] = col_decisions
        if converted_missing:
            handoff = list(phase3.get("converted_to_missing") or [])
            handoff.extend(converted_missing)
            phase3["converted_to_missing"] = handoff
        self._save_phase3(analysis_id, an.dataset_id, phase3)
        PhaseStatusService(self.db).recompute_anomaly_columns(analysis_id)
        snapshot, snapshot_error = refresh_downstream_with_status(
            self.db, analysis_id, "anomaly"
        )
        if snapshot_error:
            import logging
            logging.getLogger(__name__).warning(
                "anomaly snapshot failed for analysis %s: %s", analysis_id, snapshot_error
            )
        invalidate_analysis_cache(analysis_id)
        self.db.commit()
        return {
            "success": True,
            "analysis_id": analysis_id,
            "column": column,
            "saved": len(rows),
            "snapshot": snapshot,
            "snapshot_error": snapshot_error,
        }

    def review_progress(self, analysis_id: int) -> dict[str, Any]:
        self._load_analysis(analysis_id)
        col_progress = PhaseStatusService(self.db).recompute_anomaly_columns(analysis_id)
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
        self.db.commit()
        return {
            "analysis_id": analysis_id,
            "total_anomalies": total,
            "reviewed": reviewed,
            "remaining": remaining,
            "progress_pct": pct,
            "complete": col_progress["complete"],
            "columns_total": col_progress["columns_total"],
            "columns_reviewed": col_progress["columns_reviewed"],
            "auto_reviewed": col_progress["auto_reviewed"],
            "pending_columns": col_progress["pending_columns"],
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
