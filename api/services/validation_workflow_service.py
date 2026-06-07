"""Validation review workflow — acknowledge gate + persist row decisions."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from database.models import ValidationDecision
from services.analysis_query import (
    build_phase3_from_relational,
    get_analysis_meta,
    merge_checkpoint_phase3_overlay,
)
from services.analysis_payload_cache import invalidate_analysis_cache
from services.phase_audit_service import PhaseAuditService


class ValidationWorkflowService:
    def __init__(self, db: Session):
        self.db = db

    def _load(self, analysis_id: int):
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        if an.status != "complete":
            raise ValueError("Analysis not complete")
        return an

    def _get_phase3(self, analysis_id: int) -> dict[str, Any]:
        return build_phase3_from_relational(self.db, analysis_id)

    def acknowledge_validation(
        self,
        analysis_id: int,
        *,
        user_id: int | None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._load(analysis_id)
        overlay: dict[str, Any] = {
            "validation_acknowledged": True,
            "validation_acknowledged_at": datetime.utcnow().isoformat() + "Z",
        }
        if meta:
            overlay["validation_acknowledge_meta"] = meta
        merge_checkpoint_phase3_overlay(self.db, analysis_id, overlay)
        PhaseAuditService(self.db).record(
            analysis_id=analysis_id,
            phase="validation",
            action="proceed_to_anomaly",
            user_id=user_id,
            payload=meta or {},
        )
        invalidate_analysis_cache(analysis_id)
        self.db.commit()
        return {"success": True, "analysis_id": analysis_id, "validation_acknowledged": True}

    def save_decisions(
        self,
        analysis_id: int,
        decisions: list[dict[str, Any]],
        *,
        user_id: int | None,
    ) -> dict[str, Any]:
        self._load(analysis_id)
        self.db.query(ValidationDecision).filter(
            ValidationDecision.analysis_id == analysis_id
        ).delete(synchronize_session=False)

        rows: list[ValidationDecision] = []
        audit = PhaseAuditService(self.db)
        for d in decisions:
            action = str(d.get("decision") or d.get("user_action") or "KEEP").upper()
            row = ValidationDecision(
                analysis_id=analysis_id,
                rule_id=str(d.get("rule_id") or "unknown"),
                column_name=str(d.get("column") or d.get("column_name") or ""),
                row_index=int(d["row_index"]) if d.get("row_index") is not None else None,
                rule_type=str(d.get("rule_type") or d.get("kind") or "single"),
                severity=str(d.get("severity") or "MEDIUM"),
                confidence=float(d.get("confidence") or 0.7),
                decision=action,
                old_value=str(d.get("old_value")) if d.get("old_value") is not None else None,
                new_value=str(d.get("new_value")) if d.get("new_value") is not None else None,
                created_at=datetime.utcnow(),
            )
            rows.append(row)
            audit.record(
                analysis_id=analysis_id,
                phase="validation",
                action=action,
                user_id=user_id,
                entity_type="rule",
                entity_id=str(d.get("rule_id") or "unknown"),
                old_value=d.get("old_value"),
                new_value=d.get("new_value"),
                payload={
                    "column": row.column_name,
                    "row_index": row.row_index,
                    "severity": row.severity,
                    "confidence": row.confidence,
                    "rule_type": row.rule_type,
                },
            )
        if rows:
            self.db.add_all(rows)

        merge_checkpoint_phase3_overlay(
            self.db, analysis_id, {"validation_user_decisions": decisions}
        )
        invalidate_analysis_cache(analysis_id)
        self.db.commit()
        return {"success": True, "analysis_id": analysis_id, "saved": len(rows)}
