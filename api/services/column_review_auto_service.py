"""Auto-apply default anomaly and imputation decisions for Step 7 column review."""
from __future__ import annotations

from typing import Any, Literal

from sqlalchemy.orm import Session

from database.models import ImputationRowDecision, OutlierDecision
from services.analysis_query import build_phase3_from_relational
from services.imputation_workflow_service import ImputationWorkflowService
from services.outlier_workflow_service import OutlierWorkflowService

PhaseName = Literal["anomaly", "imputation"]


class ColumnReviewAutoService:
    def __init__(self, db: Session):
        self.db = db
        self.outlier = OutlierWorkflowService(db)
        self.imputation = ImputationWorkflowService(db)

    def _anomaly_candidates(self, analysis_id: int, column: str) -> list[dict[str, Any]]:
        phase3 = self.outlier._get_phase3(analysis_id)
        aliases = self.outlier._column_aliases(analysis_id, column)
        out: list[dict[str, Any]] = []
        for cand in phase3.get("anomaly_candidates") or []:
            if not isinstance(cand, dict):
                continue
            if str(cand.get("column") or "") in aliases:
                out.append(cand)
        return out

    def _imputation_aliases(self, analysis_id: int, column: str) -> set[str]:
        return self.outlier._column_aliases(analysis_id, column)

    def _find_imputation_candidate(
        self, phase3: dict[str, Any], analysis_id: int, column: str
    ) -> dict[str, Any]:
        aliases = self._imputation_aliases(analysis_id, column)
        for cand in phase3.get("imputation_candidates") or []:
            if not isinstance(cand, dict):
                continue
            if str(cand.get("column") or "") in aliases:
                return cand
        return {}

    def _find_imputation_block(
        self, phase3: dict[str, Any], analysis_id: int, column: str
    ) -> dict[str, Any]:
        aliases = self._imputation_aliases(analysis_id, column)
        for block in phase3.get("imputation_results") or []:
            if not isinstance(block, dict):
                continue
            if str(block.get("column") or "") in aliases:
                return block
        return {}

    def _canonical_imputation_column(self, analysis_id: int, column: str) -> str:
        phase3 = build_phase3_from_relational(self.db, analysis_id)
        candidate = self._find_imputation_candidate(phase3, analysis_id, column)
        if candidate.get("column"):
            return str(candidate["column"])
        block = self._find_imputation_block(phase3, analysis_id, column)
        if block.get("column"):
            return str(block["column"])
        return column

    def _recommended_imputation_method(self, analysis_id: int, column: str) -> str:
        phase3 = build_phase3_from_relational(self.db, analysis_id)
        candidate = self._find_imputation_candidate(phase3, analysis_id, column)
        block = self._find_imputation_block(phase3, analysis_id, column)
        return str(candidate.get("recommended_method") or block.get("recommended") or "median").lower()

    def _imputation_missing_count(self, analysis_id: int, column: str) -> int:
        phase3 = build_phase3_from_relational(self.db, analysis_id)
        candidate = self._find_imputation_candidate(phase3, analysis_id, column)
        return int(candidate.get("missing_count") or 0)

    def auto_apply_anomaly(
        self,
        analysis_id: int,
        column: str,
        *,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        self.outlier._load_analysis(analysis_id)
        phase3 = self.outlier._get_phase3(analysis_id)
        block = self.outlier._find_anomaly_block(
            phase3.get("anomaly_results") or [],
            column,
            analysis_id,
        )
        if not block or not block.get("detection_run"):
            return {"applied": False, "reason": "detection_not_run"}

        candidates = self._anomaly_candidates(analysis_id, column)
        if not candidates:
            return {
                "applied": True,
                "saved": 0,
                "decision": "KEEP",
                "candidate_count": 0,
                "normalized": True,
            }

        cand_rows = {int(c["row"]) for c in candidates if c.get("row") is not None}
        aliases = self.outlier._column_aliases(analysis_id, column)
        saved_rows = {
            r.row_index
            for r in self.db.query(OutlierDecision).filter(
                OutlierDecision.analysis_id == analysis_id,
                OutlierDecision.column_name.in_(aliases),
            )
        }
        if cand_rows and cand_rows <= saved_rows:
            return {
                "applied": True,
                "saved": len(saved_rows),
                "decision": "KEEP",
                "candidate_count": len(candidates),
                "already_applied": True,
                "normalized": True,
            }

        method = str(block.get("method_selected") or "Z_SCORE").upper()
        method_label = "IQR" if method == "IQR" else "Z-Score"
        decisions = [
            {
                "row_index": int(c["row"]),
                "method": c.get("method") or method,
                "methodology": method_label,
                "severity": c.get("severity"),
                "confidence": c.get("confidence"),
                "decision": "KEEP",
                "old_value": c.get("value"),
                "new_value": None,
            }
            for c in candidates
            if c.get("row") is not None
        ]
        res = self.outlier.save_row_decisions(
            analysis_id, column, decisions, user_id=user_id, bulk=True
        )
        return {
            "applied": True,
            "saved": res.get("saved", len(decisions)),
            "decision": "KEEP",
            "candidate_count": len(candidates),
            "method": method,
            "normalized": True,
        }

    def auto_apply_imputation(
        self,
        analysis_id: int,
        column: str,
        *,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        self.imputation._load(analysis_id)
        canonical = self._canonical_imputation_column(analysis_id, column)
        missing = self._imputation_missing_count(analysis_id, column)
        if missing == 0:
            return {
                "applied": True,
                "saved": 0,
                "method": None,
                "missing_count": 0,
                "normalized": True,
            }

        aliases = self._imputation_aliases(analysis_id, column)
        existing = self.db.query(ImputationRowDecision).filter(
            ImputationRowDecision.analysis_id == analysis_id,
            ImputationRowDecision.column_name.in_(aliases),
        ).count()
        method = self._recommended_imputation_method(analysis_id, column)
        if existing > 0:
            return {
                "applied": True,
                "saved": existing,
                "method": method,
                "missing_count": missing,
                "decision": "ACCEPT",
                "already_applied": True,
                "normalized": True,
            }

        confidence, _reason = self.imputation._method_meta(analysis_id, canonical, method)
        decisions = [
            {
                "column": canonical,
                "method": method,
                "decision": "ACCEPT",
                "confidence": confidence,
            }
        ]

        res = self.imputation.save_decisions(
            analysis_id,
            canonical,
            method=method,
            decisions=decisions,
            user_id=user_id,
            bulk=True,
        )
        return {
            "applied": True,
            "saved": missing,
            "method": method,
            "missing_count": missing,
            "decision": "ACCEPT",
            "normalized": True,
        }

    def auto_normalize_column(
        self,
        analysis_id: int,
        column: str,
        *,
        phases: list[PhaseName] | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        use_phases = phases or ["anomaly", "imputation"]
        result: dict[str, Any] = {
            "success": True,
            "analysis_id": analysis_id,
            "column": column,
            "normalized": True,
        }
        if "anomaly" in use_phases:
            result["anomaly"] = self.auto_apply_anomaly(
                analysis_id, column, user_id=user_id
            )
        if "imputation" in use_phases:
            result["imputation"] = self.auto_apply_imputation(
                analysis_id, column, user_id=user_id
            )
        return result
