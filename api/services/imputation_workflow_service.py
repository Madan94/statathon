"""Imputation method selection + decision persistence."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from database.models import ImputationRowDecision
from services.analysis_query import (
    get_analysis_meta,
    load_checkpoint_phase3_overlay,
    merge_checkpoint_phase3_overlay,
)
from services.analysis_payload_cache import invalidate_analysis_cache
from services.phase_audit_service import PhaseAuditService


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
        invalidate_analysis_cache(analysis_id)
        self.db.commit()
        return {
            "success": True,
            "analysis_id": analysis_id,
            "column": column,
            "method": method.lower(),
            "saved": len(rows),
        }

    def review_progress(self, analysis_id: int) -> dict[str, Any]:
        phase3_overlay = load_checkpoint_phase3_overlay(self.db, analysis_id)
        user_decisions = phase3_overlay.get("imputation_user_decisions") or {}
        from services.analysis_query import build_phase3_from_relational

        phase3 = build_phase3_from_relational(self.db, analysis_id)
        candidates = [
            c for c in (phase3.get("imputation_candidates") or []) if isinstance(c, dict)
        ]
        columns_needing = [c for c in candidates if int(c.get("missing_count") or 0) > 0]
        reviewed_cols = len(user_decisions)
        total_cols = len(columns_needing)
        pct = round((reviewed_cols / total_cols) * 100, 1) if total_cols else 100.0
        return {
            "analysis_id": analysis_id,
            "columns_with_missing": total_cols,
            "reviewed_columns": reviewed_cols,
            "remaining_columns": max(0, total_cols - reviewed_cols),
            "progress_pct": pct,
            "complete": total_cols == 0 or reviewed_cols >= total_cols,
        }
