"""Central phase completion status — backend source of truth for wizard gating."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from database.models import (
    AnalysisPhaseStatus,
    ColumnPhaseReview,
    ImputationRowDecision,
    OutlierDecision,
    ValidationDecision,
)
from services.analysis_query import (
    build_phase3_from_relational,
    count_validation_candidates,
    get_analysis_meta,
    get_normalization_version,
    load_analysis_checkpoint,
    load_checkpoint_phase3_overlay,
)
from services.phase_status_cache import get_cached_phase_status, set_cached_phase_status
from services.analysis_dataframe_service import column_identity_aliases


def _alias_groups(db: Session, analysis_id: int) -> dict[str, set[str]]:
    an = get_analysis_meta(db, analysis_id)
    checkpoint = load_analysis_checkpoint(db, analysis_id) or {}
    config = an.config if an and isinstance(an.config, dict) else {}
    return column_identity_aliases(checkpoint, config)


def _names_match(a: str, b: str, groups: dict[str, set[str]]) -> bool:
    if not a and not b:
        return True
    if not a or not b:
        return False
    return bool(groups.get(a, {a}) & groups.get(b, {b}))


def _all_names(name: str, groups: dict[str, set[str]]) -> set[str]:
    return groups.get(str(name or ""), {str(name or "")})


def _resolve_rule_id(raw: dict[str, Any]) -> str:
    """Stable rule identity — must match between candidates and persisted decisions."""
    rid = raw.get("rule_id")
    if rid and str(rid) not in ("unknown", ""):
        return str(rid)
    rule = raw.get("rule")
    if isinstance(rule, dict) and rule.get("rule_id"):
        return str(rule["rule_id"])
    if isinstance(rule, str) and rule:
        return rule
    return str(raw.get("rule_type") or raw.get("kind") or "rule")


def _position_key(column: str | None, row: int | None) -> tuple[str, int | None]:
    return (str(column or ""), row)


def _candidate_key(c: dict[str, Any]) -> tuple[str, int | None, str]:
    return (
        str(c.get("column") or c.get("column_name") or ""),
        int(c["row"]) if c.get("row") is not None else None,
        _resolve_rule_id(c),
    )


def _decision_key(d: ValidationDecision) -> tuple[str, int | None, str]:
    raw = {
        "rule_id": d.rule_id,
        "rule_type": d.rule_type,
    }
    return (str(d.column_name or ""), d.row_index, _resolve_rule_id(raw))


_schema_ready = False


def ensure_phase_status_schema() -> None:
    """Create phase-status tables if missing (migrations may not have run yet)."""
    global _schema_ready
    if _schema_ready:
        return
    from database.database import engine

    AnalysisPhaseStatus.__table__.create(bind=engine, checkfirst=True)
    ColumnPhaseReview.__table__.create(bind=engine, checkfirst=True)
    try:
        from sqlalchemy import inspect, text

        insp = inspect(engine)
        if "analysis_phase_status" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("analysis_phase_status")}
            if "dataset_review_completed" not in cols:
                dialect = engine.dialect.name
                with engine.begin() as conn:
                    if dialect == "postgresql":
                        conn.execute(
                            text(
                                "ALTER TABLE analysis_phase_status "
                                "ADD COLUMN IF NOT EXISTS dataset_review_completed BOOLEAN NOT NULL DEFAULT FALSE"
                            )
                        )
                    else:
                        conn.execute(
                            text(
                                "ALTER TABLE analysis_phase_status "
                                "ADD COLUMN dataset_review_completed BOOLEAN NOT NULL DEFAULT 0"
                            )
                        )
            if "weight_application_completed" not in cols:
                dialect = engine.dialect.name
                with engine.begin() as conn:
                    if dialect == "postgresql":
                        conn.execute(
                            text(
                                "ALTER TABLE analysis_phase_status "
                                "ADD COLUMN IF NOT EXISTS weight_application_completed BOOLEAN NOT NULL DEFAULT FALSE"
                            )
                        )
                    else:
                        conn.execute(
                            text(
                                "ALTER TABLE analysis_phase_status "
                                "ADD COLUMN weight_application_completed BOOLEAN NOT NULL DEFAULT 0"
                            )
                        )
        WeightProfile = __import__("database.models", fromlist=["WeightProfile"]).WeightProfile
        WeightApplication = __import__("database.models", fromlist=["WeightApplication"]).WeightApplication
        WeightAuditLog = __import__("database.models", fromlist=["WeightAuditLog"]).WeightAuditLog
        WeightProfile.__table__.create(bind=engine, checkfirst=True)
        WeightApplication.__table__.create(bind=engine, checkfirst=True)
        WeightAuditLog.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass
    _schema_ready = True


class PhaseStatusService:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self, analysis_id: int) -> AnalysisPhaseStatus:
        ensure_phase_status_schema()
        row = (
            self.db.query(AnalysisPhaseStatus)
            .filter(AnalysisPhaseStatus.analysis_id == analysis_id)
            .first()
        )
        if row:
            return row
        row = AnalysisPhaseStatus(analysis_id=analysis_id)
        self.db.add(row)
        self.db.flush()
        return row

    def validation_review_progress(
        self,
        analysis_id: int,
        *,
        phase3: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if phase3 is None:
            phase3 = build_phase3_from_relational(self.db, analysis_id)
        db_total = count_validation_candidates(self.db, analysis_id)
        reported_total = int(phase3.get("validation_candidates_reported_total") or 0)
        if not reported_total:
            val_payload = phase3.get("validation_results") or {}
            if isinstance(val_payload, dict):
                reported_total = int(val_payload.get("candidate_count") or 0)

        reviewable = db_total
        total = reported_total if reported_total > reviewable else reviewable
        if total <= 0:
            total = reviewable

        reviewed = self.db.query(ValidationDecision).filter(
            ValidationDecision.analysis_id == analysis_id
        ).count()

        overlay = load_checkpoint_phase3_overlay(self.db, analysis_id)
        acknowledged = bool(overlay.get("validation_acknowledged"))
        status_row = self.get_or_create(analysis_id)
        truncated = reported_total > reviewable > 0
        complete_threshold = reviewable if reviewable else total
        progress_total = reviewable or total
        review_complete = (
            progress_total == 0
            or (reviewed >= complete_threshold and complete_threshold > 0)
        )
        phase_complete = bool(status_row.rule_validation_completed)
        complete = phase_complete or (review_complete and acknowledged)
        return {
            "analysis_id": analysis_id,
            "total": progress_total,
            "reported_total": reported_total if truncated else None,
            "reviewed": reviewed,
            "remaining": max(0, progress_total - reviewed),
            "progress_pct": round((reviewed / progress_total) * 100, 1) if progress_total else 100.0,
            "review_complete": review_complete,
            "phase_complete": phase_complete,
            "acknowledged": acknowledged,
            "complete": complete,
            "stored_total": reviewable,
            "truncated": truncated,
        }

    def mark_rule_validation_complete(self, analysis_id: int) -> AnalysisPhaseStatus:
        row = self.get_or_create(analysis_id)
        row.rule_validation_completed = True
        row.updated_at = datetime.utcnow()
        return row

    def sync_early_phases(self, analysis_id: int) -> AnalysisPhaseStatus:
        """Infer steps 1–5 completion from analysis metadata."""
        row = self.get_or_create(analysis_id)
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            return row
        row.summary_completed = an.status == "complete"
        row.normalization_completed = get_normalization_version(self.db, analysis_id) is not None
        if an.status == "complete":
            row.semantic_completed = True
            row.clustering_completed = True
            row.kg_completed = True
        row.updated_at = datetime.utcnow()
        return row

    def _upsert_column_review(
        self,
        analysis_id: int,
        phase: str,
        column_name: str,
        *,
        status: str,
        item_count: int,
        reviewed_count: int,
    ) -> None:
        ensure_phase_status_schema()
        existing = (
            self.db.query(ColumnPhaseReview)
            .filter(
                ColumnPhaseReview.analysis_id == analysis_id,
                ColumnPhaseReview.phase == phase,
                ColumnPhaseReview.column_name == column_name,
            )
            .first()
        )
        if existing:
            existing.status = status
            existing.item_count = item_count
            existing.reviewed_count = reviewed_count
            existing.updated_at = datetime.utcnow()
        else:
            self.db.add(
                ColumnPhaseReview(
                    analysis_id=analysis_id,
                    phase=phase,
                    column_name=column_name,
                    status=status,
                    item_count=item_count,
                    reviewed_count=reviewed_count,
                )
            )

    def recompute_anomaly_columns(
        self,
        analysis_id: int,
        *,
        phase3: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        if phase3 is None:
            phase3 = build_phase3_from_relational(self.db, analysis_id)
        blocks = phase3.get("anomaly_results") or []
        candidates = [
            c for c in (phase3.get("anomaly_candidates") or []) if isinstance(c, dict)
        ]
        groups = _alias_groups(self.db, analysis_id)
        saved = self.db.query(OutlierDecision).filter(
            OutlierDecision.analysis_id == analysis_id
        ).all()
        saved_by_col: dict[str, set[int]] = {}
        for r in saved:
            for name in _all_names(r.column_name, groups):
                saved_by_col.setdefault(name, set()).add(r.row_index)

        columns_total = 0
        columns_reviewed = 0
        auto_reviewed = 0
        pending_cols: list[str] = []

        for block in blocks:
            if not isinstance(block, dict):
                continue
            col = str(block.get("column") or "")
            if not col or not block.get("detection_run"):
                continue
            columns_total += 1
            col_cands = [
                c for c in candidates
                if _names_match(str(c.get("column") or ""), col, groups)
            ]
            item_count = len(col_cands)
            cand_rows = {int(c["row"]) for c in col_cands if c.get("row") is not None}
            saved_rows: set[int] = set()
            for name in _all_names(col, groups):
                saved_rows |= saved_by_col.get(name, set())
            if item_count == 0:
                status = "auto_reviewed"
                auto_reviewed += 1
                columns_reviewed += 1
            elif cand_rows and cand_rows <= saved_rows:
                status = "reviewed"
                columns_reviewed += 1
            else:
                status = "pending"
                pending_cols.append(col)
            if persist:
                self._upsert_column_review(
                    analysis_id, "anomaly", col,
                    status=status,
                    item_count=item_count,
                    reviewed_count=len(cand_rows & saved_rows) if item_count else 0,
                )

        complete = columns_total == 0 or columns_reviewed >= columns_total
        if persist:
            row = self.get_or_create(analysis_id)
            row.anomaly_completed = complete
            row.updated_at = datetime.utcnow()
        return {
            "columns_total": columns_total,
            "columns_reviewed": columns_reviewed,
            "auto_reviewed": auto_reviewed,
            "pending_columns": pending_cols,
            "complete": complete,
        }

    def recompute_imputation_columns(
        self,
        analysis_id: int,
        *,
        phase3: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        if phase3 is None:
            phase3 = build_phase3_from_relational(self.db, analysis_id)
        overlay = load_checkpoint_phase3_overlay(self.db, analysis_id)
        user_decisions = overlay.get("imputation_user_decisions") or {}
        groups = _alias_groups(self.db, analysis_id)
        saved_keys: set[str] = set()
        for key in user_decisions.keys():
            saved_keys |= _all_names(str(key), groups)
        for r in self.db.query(ImputationRowDecision.column_name).filter(
            ImputationRowDecision.analysis_id == analysis_id
        ).distinct():
            if r[0]:
                saved_keys |= _all_names(str(r[0]), groups)

        needing: dict[str, int] = {}
        for c in phase3.get("imputation_candidates") or []:
            if not isinstance(c, dict):
                continue
            col = str(c.get("column") or "")
            miss = int(c.get("missing_count") or 0)
            if col:
                needing[col] = miss

        all_blocks = phase3.get("imputation_results") or []
        all_cols = {
            str(b.get("column"))
            for b in all_blocks
            if isinstance(b, dict) and b.get("column")
        }
        review_cols = sorted(all_cols | set(needing.keys()))

        columns_total = len(review_cols)
        columns_reviewed = 0
        auto_reviewed = 0
        pending_cols: list[str] = []

        for col in review_cols:
            miss = needing.get(col, 0)
            col_saved = bool(_all_names(col, groups) & saved_keys)
            if miss == 0:
                status = "auto_reviewed"
                auto_reviewed += 1
                columns_reviewed += 1
            elif col_saved:
                status = "reviewed"
                columns_reviewed += 1
            else:
                status = "pending"
                pending_cols.append(col)
            if persist:
                self._upsert_column_review(
                    analysis_id,
                    "imputation",
                    col,
                    status=status,
                    item_count=miss,
                    reviewed_count=1 if col_saved or miss == 0 else 0,
                )

        complete = columns_total == 0 or columns_reviewed >= columns_total
        if persist:
            row = self.get_or_create(analysis_id)
            row.missing_value_completed = complete
            row.updated_at = datetime.utcnow()
        return {
            "columns_total": columns_total,
            "columns_reviewed": columns_reviewed,
            "auto_reviewed": auto_reviewed,
            "pending_columns": pending_cols,
            "complete": complete,
        }

    def _early_phase_flags(self, analysis_id: int) -> dict[str, bool]:
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            return {}
        complete = an.status == "complete"
        return {
            "summary_completed": complete,
            "normalization_completed": get_normalization_version(self.db, analysis_id) is not None,
            "semantic_completed": complete,
            "clustering_completed": complete,
            "kg_completed": complete,
        }

    def get_status_payload(self, analysis_id: int) -> dict[str, Any]:
        cached = get_cached_phase_status(analysis_id)
        if cached:
            return cached

        phase3 = build_phase3_from_relational(self.db, analysis_id)
        val = self.validation_review_progress(analysis_id, phase3=phase3)
        anomaly = self.recompute_anomaly_columns(analysis_id, phase3=phase3, persist=False)
        imputation = self.recompute_imputation_columns(analysis_id, phase3=phase3, persist=False)
        row = self.get_or_create(analysis_id)
        early = self._early_phase_flags(analysis_id)

        column_reviews = (
            self.db.query(ColumnPhaseReview)
            .filter(ColumnPhaseReview.analysis_id == analysis_id)
            .all()
        )
        by_phase: dict[str, list[dict[str, Any]]] = {"anomaly": [], "imputation": []}
        for cr in column_reviews:
            if cr.phase in by_phase:
                by_phase[cr.phase].append(
                    {
                        "column": cr.column_name,
                        "status": cr.status,
                        "item_count": cr.item_count,
                        "reviewed_count": cr.reviewed_count,
                    }
                )

        payload = {
            "analysis_id": analysis_id,
            "summary_completed": early.get("summary_completed", row.summary_completed),
            "normalization_completed": early.get(
                "normalization_completed", row.normalization_completed
            ),
            "semantic_completed": early.get("semantic_completed", row.semantic_completed),
            "clustering_completed": early.get("clustering_completed", row.clustering_completed),
            "kg_completed": early.get("kg_completed", row.kg_completed),
            "rule_validation_completed": row.rule_validation_completed or val["complete"],
            "anomaly_completed": anomaly["complete"] or row.anomaly_completed,
            "missing_value_completed": imputation["complete"] or row.missing_value_completed,
            "weight_application_completed": row.weight_application_completed,
            "dataset_review_completed": row.dataset_review_completed,
            "validation": val,
            "anomaly": anomaly,
            "imputation": imputation,
            "column_reviews": by_phase,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        set_cached_phase_status(analysis_id, payload)
        return payload
