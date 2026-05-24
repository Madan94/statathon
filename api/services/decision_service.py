"""Persist user analysis decisions (anomaly / column actions)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from database.models import Analysis, Phase3AnomalyDecision
from decision_engine.anomaly_decisions import build_decision_payload


class DecisionService:
    def __init__(self, db: Session):
        self.db = db

    def save_column_decisions(
        self,
        analysis_id: int,
        decisions: dict[str, str],
    ) -> dict:
        an = self.db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not an:
            raise ValueError("Analysis not found")
        if an.status != "complete":
            raise ValueError("Analysis not complete")

        row = (
            self.db.query(Phase3AnomalyDecision)
            .filter(Phase3AnomalyDecision.analysis_id == analysis_id)
            .order_by(Phase3AnomalyDecision.id.desc())
            .first()
        )
        existing_payload = row.payload if row and isinstance(row.payload, dict) else {}
        payload = build_decision_payload(decisions=decisions, existing=existing_payload)

        if row:
            row.payload = payload
            row.status = "submitted"
            row.updated_at = datetime.utcnow()
            row.dataset_id = an.dataset_id
        else:
            self.db.add(
                Phase3AnomalyDecision(
                    dataset_id=an.dataset_id,
                    analysis_id=analysis_id,
                    payload=payload,
                    status="submitted",
                )
            )

        checkpoint = an.checkpoint if isinstance(an.checkpoint, dict) else {}
        phase3 = dict(checkpoint.get("phase3") or {})
        user_decisions = dict(phase3.get("user_decisions") or {})
        user_decisions.update(decisions)
        phase3["user_decisions"] = user_decisions
        checkpoint["phase3"] = phase3
        an.checkpoint = checkpoint

        self.db.commit()
        return {"analysis_id": analysis_id, "decisions": user_decisions, "ledger": payload}
