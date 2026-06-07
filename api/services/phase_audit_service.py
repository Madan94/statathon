"""Unified phase audit logging — PostgreSQL + JSONL fallback."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from database.models import PhaseAuditEvent
from validation.audit_log import AuditEntry, AuditLog

logger = logging.getLogger(__name__)


class PhaseAuditService:
    def __init__(self, db: Session):
        self.db = db
        self._jsonl = AuditLog()

    def record(
        self,
        *,
        analysis_id: int,
        phase: str,
        action: str,
        user_id: int | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        old_value: Any = None,
        new_value: Any = None,
        payload: dict[str, Any] | None = None,
    ) -> PhaseAuditEvent:
        def _str(v: Any) -> str | None:
            if v is None:
                return None
            if isinstance(v, (str, int, float, bool)):
                return str(v)
            return json.dumps(v, default=str)

        row = PhaseAuditEvent(
            analysis_id=analysis_id,
            user_id=user_id,
            phase=phase.upper(),
            action=action.upper(),
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=_str(old_value),
            new_value=_str(new_value),
            payload=payload or {},
            created_at=datetime.utcnow(),
        )
        self.db.add(row)

        self._jsonl.append(
            AuditEntry(
                rule_id=entity_id or action,
                rule_type=phase,
                column=str(payload.get("column") if payload else entity_type or ""),
                row_id=int(payload["row_index"]) if payload and payload.get("row_index") is not None else None,
                old_value=old_value,
                new_value=new_value,
                user_action=action,
                confidence=float(payload.get("confidence") or 1.0) if payload else 1.0,
                severity=str(payload.get("severity") or "INFO") if payload else "INFO",
                user_id=user_id,
                analysis_id=analysis_id,
                diagnostics=payload or {},
            )
        )
        return row

    def list_events(
        self,
        analysis_id: int,
        *,
        phase: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        q = self.db.query(PhaseAuditEvent).filter(PhaseAuditEvent.analysis_id == analysis_id)
        if phase:
            q = q.filter(PhaseAuditEvent.phase == phase.upper())
        rows = q.order_by(PhaseAuditEvent.created_at.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "analysis_id": r.analysis_id,
                "user_id": r.user_id,
                "phase": r.phase,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "payload": r.payload,
                "timestamp": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
