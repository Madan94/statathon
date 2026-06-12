"""Validation review workflow — acknowledge gate + persist row decisions."""
from __future__ import annotations

import logging
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
from services.phase_snapshot_service import PhaseSnapshotService
from services.phase_status_service import PhaseStatusService, _candidate_key, _resolve_rule_id

logger = logging.getLogger(__name__)


def _merge_decisions_with_candidates(
    candidates: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ensure every backend candidate has a decision (default KEEP)."""
    by_key: dict[tuple[str, int | None, str], dict[str, Any]] = {}
    for d in decisions:
        by_key[
            (
                str(d.get("column") or d.get("column_name") or ""),
                int(d["row_index"]) if d.get("row_index") is not None else None,
                _resolve_rule_id(d),
            )
        ] = d

    merged: list[dict[str, Any]] = []
    for c in candidates:
        key = _candidate_key(c)
        if key in by_key:
            merged.append(by_key[key])
            continue
        merged.append(
            {
                "column": key[0],
                "row_index": key[1],
                "rule_id": key[2],
                "rule_type": c.get("kind") or "single_column",
                "severity": c.get("severity") or "MEDIUM",
                "confidence": c.get("confidence") or 0.7,
                "decision": "KEEP",
                "old_value": c.get("value"),
            }
        )
    return merged


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

    def review_progress(self, analysis_id: int) -> dict[str, Any]:
        self._load(analysis_id)
        return PhaseStatusService(self.db).validation_review_progress(analysis_id)

    def acknowledge_validation(
        self,
        analysis_id: int,
        *,
        user_id: int | None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._load(analysis_id)
        progress = PhaseStatusService(self.db).validation_review_progress(analysis_id)
        if progress["total"] > 0 and progress["reviewed"] < progress["total"]:
            raise ValueError(
                f"Review all violations before proceeding ({progress['reviewed']}/{progress['total']} saved)"
            )
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
        PhaseStatusService(self.db).mark_rule_validation_complete(analysis_id)
        try:
            PhaseSnapshotService(self.db).refresh_downstream(analysis_id, "validation")
        except Exception as exc:
            logger.warning(
                "validation snapshot skipped for analysis %s: %s",
                analysis_id,
                exc,
            )
        invalidate_analysis_cache(analysis_id)
        self.db.commit()
        return {
            "success": True,
            "analysis_id": analysis_id,
            "validation_acknowledged": True,
            "rule_validation_completed": True,
        }

    def proceed_to_anomaly(
        self,
        analysis_id: int,
        decisions: list[dict[str, Any]],
        *,
        user_id: int | None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomic: save all decisions, acknowledge gate, mark phase complete."""
        self._load(analysis_id)
        phase3 = build_phase3_from_relational(self.db, analysis_id)
        candidates = [
            c for c in (phase3.get("validation_candidates") or []) if isinstance(c, dict)
        ]
        total = len(candidates)
        decisions = _merge_decisions_with_candidates(candidates, decisions)
        saved = self._persist_decisions(analysis_id, decisions, user_id=user_id, commit=False)
        if total > 0 and saved < total:
            self.db.rollback()
            raise ValueError(
                f"Review all violations before proceeding ({saved}/{total} saved)"
            )
        overlay: dict[str, Any] = {
            "validation_acknowledged": True,
            "validation_acknowledged_at": datetime.utcnow().isoformat() + "Z",
            "validation_user_decisions": decisions,
        }
        if meta:
            overlay["validation_acknowledge_meta"] = meta
        merge_checkpoint_phase3_overlay(self.db, analysis_id, overlay)
        PhaseAuditService(self.db).record(
            analysis_id=analysis_id,
            phase="validation",
            action="proceed_to_anomaly",
            user_id=user_id,
            payload={"saved": saved, **(meta or {})},
        )
        PhaseStatusService(self.db).mark_rule_validation_complete(analysis_id)
        try:
            PhaseSnapshotService(self.db).refresh_downstream(analysis_id, "validation")
        except Exception as exc:
            logger.warning(
                "validation snapshot skipped for analysis %s: %s",
                analysis_id,
                exc,
            )
        invalidate_analysis_cache(analysis_id)
        self.db.commit()
        return {
            "success": True,
            "analysis_id": analysis_id,
            "saved": saved,
            "validation_acknowledged": True,
            "rule_validation_completed": True,
        }

    def save_decisions(
        self,
        analysis_id: int,
        decisions: list[dict[str, Any]],
        *,
        user_id: int | None,
    ) -> dict[str, Any]:
        self._load(analysis_id)
        saved = self._persist_decisions(analysis_id, decisions, user_id=user_id, commit=False)
        try:
            PhaseSnapshotService(self.db).refresh_downstream(analysis_id, "validation")
        except Exception as exc:
            logger.warning(
                "validation snapshot skipped for analysis %s: %s",
                analysis_id,
                exc,
            )
        invalidate_analysis_cache(analysis_id)
        self.db.commit()
        return {"success": True, "analysis_id": analysis_id, "saved": saved}

    def _persist_decisions(
        self,
        analysis_id: int,
        decisions: list[dict[str, Any]],
        *,
        user_id: int | None,
        commit: bool,
    ) -> int:
        self.db.query(ValidationDecision).filter(
            ValidationDecision.analysis_id == analysis_id
        ).delete(synchronize_session=False)

        rows: list[ValidationDecision] = []
        audit = PhaseAuditService(self.db)
        for d in decisions:
            action = str(d.get("decision") or d.get("user_action") or "KEEP").upper()
            row = ValidationDecision(
                analysis_id=analysis_id,
                rule_id=str(d.get("rule_id") or d.get("rule_type") or d.get("kind") or "rule"),
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
        self.db.flush()
        merge_checkpoint_phase3_overlay(
            self.db, analysis_id, {"validation_user_decisions": decisions}
        )
        invalidate_analysis_cache(analysis_id)
        if commit:
            self.db.commit()
        return len(rows)
