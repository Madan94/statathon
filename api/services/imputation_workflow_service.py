"""Imputation method selection, missing-row context, and decision persistence."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from database.models import ImputationRowDecision
from imputation.executors import impute
from missing_values.row_context_builder import build_missing_rows_payload
from services.analysis_dataframe_service import (
    column_identity_aliases,
    load_analysis_dataframe,
    resolve_column_alias,
)
from services.analysis_query import (
    build_phase3_from_relational,
    get_analysis_meta,
    load_analysis_checkpoint,
    load_checkpoint_phase3_overlay,
    merge_checkpoint_phase3_overlay,
)
from services.analysis_payload_cache import invalidate_analysis_cache
from services.phase_audit_service import PhaseAuditService
from services.phase_snapshot_service import PhaseSnapshotService
from services.phase_status_service import PhaseStatusService

logger = logging.getLogger(__name__)


class ImputationWorkflowService:
    def __init__(self, db: Session):
        self.db = db

    def _load(self, analysis_id: int):
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        if an.status != "complete":
            raise ValueError("Analysis not complete")
        return an

    def _method_meta(self, analysis_id: int, column: str, method: str) -> tuple[float, str]:
        phase3 = build_phase3_from_relational(self.db, analysis_id)
        candidate = next(
            (c for c in (phase3.get("imputation_candidates") or []) if c.get("column") == column),
            {},
        )
        block = next(
            (b for b in (phase3.get("imputation_results") or []) if b.get("column") == column),
            {},
        )
        ranked = (block.get("ranked_methods") or []) if isinstance(block, dict) else []
        reason = ""
        confidence = float(candidate.get("confidence") or block.get("confidence") or 0.7)
        for row in ranked:
            if str(row.get("method", "")).lower() == method.lower():
                confidence = float(row.get("score") or confidence)
                reason = str(row.get("reason") or "")
                break
        if not reason:
            reason = f"{method.upper()} imputation selected for this column"
        return confidence, reason

    def select_method(self, analysis_id: int, column: str, method: str) -> dict[str, Any]:
        self._load(analysis_id)
        imputation_method_selections = dict(
            load_checkpoint_phase3_overlay(self.db, analysis_id).get("imputation_method_selections") or {}
        )
        imputation_method_selections[column] = method.lower()
        merge_checkpoint_phase3_overlay(
            self.db,
            analysis_id,
            {"imputation_method_selections": imputation_method_selections},
        )
        PhaseAuditService(self.db).record(
            analysis_id=analysis_id,
            phase="imputation",
            action="select_method",
            entity_type="column",
            entity_id=column,
            new_value=method.lower(),
        )
        invalidate_analysis_cache(analysis_id)
        self.db.commit()
        return {"analysis_id": analysis_id, "column": column, "method": method.lower()}

    def _resolve_df_column(self, analysis_id: int, column: str, df) -> str | None:
        an = get_analysis_meta(self.db, analysis_id)
        checkpoint = load_analysis_checkpoint(self.db, analysis_id) or {}
        config = an.config if an and isinstance(an.config, dict) else {}
        groups = column_identity_aliases(checkpoint, config)
        resolved = resolve_column_alias(column, groups, set(df.columns))
        if resolved:
            return resolved
        if column in df.columns:
            return column
        for name in groups.get(column, {column}):
            if name in df.columns:
                return name
        return None

    def list_missing_rows(
        self,
        analysis_id: int,
        column: str,
        *,
        method: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._load(analysis_id)
        overlay = load_checkpoint_phase3_overlay(self.db, analysis_id)
        selections = overlay.get("imputation_method_selections") or {}
        use_method = (method or selections.get(column) or "median").lower()
        confidence, reason = self._method_meta(analysis_id, column, use_method)

        df, _schema = load_analysis_dataframe(self.db, analysis_id)
        df_col = self._resolve_df_column(analysis_id, column, df)
        if not df_col:
            return {"total_missing": 0, "rows": [], "column": column, "method": use_method}

        series = df[df_col]
        imputed_series = impute(series.copy(), df, use_method)
        context_cols = [c for c in df.columns if c != df_col][:8]

        payload = build_missing_rows_payload(
            df,
            df_col,
            method=use_method,
            imputed_series=imputed_series,
            confidence=confidence,
            reason=reason,
            offset=offset,
            limit=limit,
            context_columns=context_cols,
        )
        payload["column"] = column
        payload["display_column"] = df_col
        payload["method"] = use_method
        return payload

    def save_decisions(
        self,
        analysis_id: int,
        column: str,
        *,
        method: str,
        decisions: list[dict[str, Any]] | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        self._load(analysis_id)
        self.db.query(ImputationRowDecision).filter(
            ImputationRowDecision.analysis_id == analysis_id,
            ImputationRowDecision.column_name == column,
        ).delete(synchronize_session=False)

        rows: list[ImputationRowDecision] = []
        audit = PhaseAuditService(self.db)
        payload_decisions = decisions or [
            {
                "column": column,
                "method": method.lower(),
                "decision": "ACCEPT",
            }
        ]
        for d in payload_decisions:
            decision = str(d.get("decision") or "ACCEPT").upper()
            audit_action = decision
            if decision == "ACCEPT":
                audit_action = f"APPLY_{str(d.get('method') or method).upper()}"
            rows.append(
                ImputationRowDecision(
                    analysis_id=analysis_id,
                    column_name=str(d.get("column") or column),
                    row_index=int(d["row_index"]) if d.get("row_index") is not None else None,
                    method=str(d.get("method") or method).lower(),
                    decision=decision,
                    original_value=str(d.get("original_value")) if d.get("original_value") is not None else None,
                    imputed_value=str(d.get("imputed_value")) if d.get("imputed_value") is not None else None,
                    confidence=float(d.get("confidence") or 0.0) if d.get("confidence") is not None else None,
                    reviewed_by=user_id,
                    created_at=datetime.utcnow(),
                )
            )
            audit.record(
                analysis_id=analysis_id,
                phase="imputation",
                action=audit_action,
                user_id=user_id,
                entity_type="row" if d.get("row_index") is not None else "column",
                entity_id=f"{column}:{d.get('row_index')}" if d.get("row_index") is not None else column,
                old_value=d.get("original_value"),
                new_value=d.get("imputed_value"),
                payload={"method": d.get("method") or method, "decision": decision},
            )
        if rows:
            self.db.add_all(rows)

        overlay = load_checkpoint_phase3_overlay(self.db, analysis_id)
        method_selections = dict(overlay.get("imputation_method_selections") or {})
        method_selections[column] = method.lower()
        user_decisions = dict(overlay.get("imputation_user_decisions") or {})
        user_decisions[column] = {"method": method.lower(), "decisions": payload_decisions}
        merge_checkpoint_phase3_overlay(
            self.db,
            analysis_id,
            {
                "imputation_method_selections": method_selections,
                "imputation_user_decisions": user_decisions,
            },
        )
        try:
            PhaseSnapshotService(self.db).snapshot_imputation(analysis_id)
        except Exception as exc:
            logger.warning("imputation snapshot skipped for analysis %s: %s", analysis_id, exc)
            try:
                from services.apply_service import persist_processed_snapshot

                persist_processed_snapshot(self.db, analysis_id)
            except Exception as retry_exc:
                logger.warning(
                    "processed snapshot materialize failed for analysis %s: %s",
                    analysis_id,
                    retry_exc,
                )
        progress = PhaseStatusService(self.db).recompute_imputation_columns(analysis_id)
        invalidate_analysis_cache(analysis_id)
        self.db.commit()
        return {
            "success": True,
            "analysis_id": analysis_id,
            "column": column,
            "method": method.lower(),
            "saved": len(rows),
            "complete": progress["complete"],
        }

    def review_progress(self, analysis_id: int) -> dict[str, Any]:
        self._load(analysis_id)
        progress = PhaseStatusService(self.db).recompute_imputation_columns(analysis_id)
        self.db.commit()
        return {
            "analysis_id": analysis_id,
            "columns_total": progress["columns_total"],
            "columns_reviewed": progress["columns_reviewed"],
            "auto_reviewed": progress["auto_reviewed"],
            "pending_columns": progress["pending_columns"],
            "columns_with_missing": progress["columns_total"],
            "reviewed_columns": progress["columns_reviewed"],
            "remaining_columns": max(0, progress["columns_total"] - progress["columns_reviewed"]),
            "progress_pct": round(
                (progress["columns_reviewed"] / progress["columns_total"]) * 100, 1
            )
            if progress["columns_total"]
            else 100.0,
            "complete": progress["complete"],
        }
