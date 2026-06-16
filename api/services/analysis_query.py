"""Lightweight Analysis row access — avoid loading huge checkpoint JSON unless required."""
from __future__ import annotations

import os
from typing import Any

from sqlalchemy import case
from sqlalchemy.orm import Session, load_only

from core.json_safe import make_json_safe
from database.models import (
    Analysis,
    Phase3AnomalyIntel,
    Phase3ImputationIntel,
    Phase3ValidationCandidate,
    ValidationResult,
)

VALIDATION_CANDIDATE_READ_LIMIT = int(os.getenv("VALIDATION_CANDIDATE_READ_LIMIT", "250"))
# 0 = persist all validation candidates (no cap)
VALIDATION_CANDIDATE_PERSIST_LIMIT = int(os.getenv("VALIDATION_CANDIDATE_PERSIST_LIMIT", "0"))

_ANALYSIS_META_COLS = (
    Analysis.id,
    Analysis.dataset_id,
    Analysis.status,
    Analysis.config,
    Analysis.error_message,
    Analysis.created_at,
    Analysis.completed_at,
)

_PHASE3_OVERLAY_KEYS = (
    "validation_acknowledged",
    "validation_acknowledged_at",
    "validation_acknowledge_meta",
    "validation_user_decisions",
    "outlier_row_decisions",
    "imputation_method_selections",
    "imputation_user_decisions",
    "method_selections",
)

_CHECKPOINT_OVERLAY_KEYS = (
    "normalization_version",
    "column_normalization",
    "effective_schema",
    "raw_schema",
    "derived_dataset",
    "dataset_lineage",
)


def get_normalization_version(db: Session, analysis_id: int) -> int | None:
    meta = get_analysis_meta(db, analysis_id)
    if meta and isinstance(meta.config, dict):
        ver = meta.config.get("normalization_version")
        if ver is not None:
            try:
                return int(ver)
            except (TypeError, ValueError):
                pass
    overlay = load_checkpoint_top_keys(db, analysis_id)
    ver = overlay.get("normalization_version")
    if ver is not None:
        try:
            return int(ver)
        except (TypeError, ValueError):
            return None
    return None


def set_normalization_meta(
    db: Session,
    analysis_id: int,
    *,
    version: int,
    effective_schema: dict[str, Any],
    raw_schema: list[str],
    user_normalization: list[dict[str, Any]],
) -> None:
    """Persist normalization metadata in the small Analysis.config blob (not checkpoint)."""
    an = (
        db.query(Analysis)
        .options(load_only(Analysis.id, Analysis.config))
        .filter(Analysis.id == analysis_id)
        .first()
    )
    if not an:
        raise ValueError("Analysis not found")
    config = dict(an.config) if isinstance(an.config, dict) else {}
    config["normalization_version"] = version
    config["normalized_schema"] = effective_schema
    config["raw_schema"] = raw_schema
    config["user_normalization"] = user_normalization
    an.config = make_json_safe(config)


def query_analysis_meta(db: Session):
    return db.query(Analysis).options(load_only(*_ANALYSIS_META_COLS))


def get_analysis_meta(db: Session, analysis_id: int) -> Analysis | None:
    return query_analysis_meta(db).filter(Analysis.id == analysis_id).first()


def load_analysis_checkpoint(db: Session, analysis_id: int) -> dict[str, Any] | None:
    cp = db.query(Analysis.checkpoint).filter(Analysis.id == analysis_id).scalar()
    return cp if isinstance(cp, dict) else None


def load_checkpoint_phase3_overlay(db: Session, analysis_id: int) -> dict[str, Any]:
    """Load workflow overlay keys; prefer extracting from phase3 sub-document in one query."""
    try:
        phase3 = (
            db.query(Analysis.checkpoint["phase3"])
            .filter(Analysis.id == analysis_id)
            .scalar()
        )
        if isinstance(phase3, dict):
            return {k: phase3[k] for k in _PHASE3_OVERLAY_KEYS if k in phase3}
    except Exception:
        pass
    overlay: dict[str, Any] = {}
    for key in _PHASE3_OVERLAY_KEYS:
        try:
            val = (
                db.query(Analysis.checkpoint["phase3"][key])
                .filter(Analysis.id == analysis_id)
                .scalar()
            )
        except Exception:
            val = None
        if val is not None:
            overlay[key] = val
    return overlay


def _validation_severity_rank():
    return case(
        (Phase3ValidationCandidate.severity == "CRITICAL", 0),
        (Phase3ValidationCandidate.severity == "HIGH", 1),
        (Phase3ValidationCandidate.severity == "MEDIUM", 2),
        (Phase3ValidationCandidate.severity == "LOW", 3),
        else_=4,
    )


def _validation_candidates_query(
    db: Session,
    analysis_id: int,
    *,
    severity: str | None = None,
    column: str | None = None,
    rule_id: str | None = None,
):
    q = db.query(Phase3ValidationCandidate).filter(
        Phase3ValidationCandidate.analysis_id == analysis_id
    )
    if severity:
        q = q.filter(Phase3ValidationCandidate.severity == severity.upper())
    if column:
        q = q.filter(Phase3ValidationCandidate.column_name.ilike(f"%{column}%"))
    return q


def count_validation_candidates(
    db: Session,
    analysis_id: int,
    *,
    severity: str | None = None,
    column: str | None = None,
    rule_id: str | None = None,
) -> int:
    return (
        _validation_candidates_query(
            db,
            analysis_id,
            severity=severity,
            column=column,
            rule_id=rule_id,
        ).count()
    )


def list_validation_candidates_paginated(
    db: Session,
    analysis_id: int,
    *,
    page: int = 1,
    page_size: int = 50,
    severity: str | None = None,
    column: str | None = None,
    rule_id: str | None = None,
) -> dict[str, Any]:
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 200))
    q = _validation_candidates_query(
        db,
        analysis_id,
        severity=severity,
        column=column,
        rule_id=rule_id,
    )
    total = q.count()
    rows = (
        q.options(
            load_only(
                Phase3ValidationCandidate.id,
                Phase3ValidationCandidate.kind,
                Phase3ValidationCandidate.column_name,
                Phase3ValidationCandidate.row_index,
                Phase3ValidationCandidate.severity,
                Phase3ValidationCandidate.candidate_action,
                Phase3ValidationCandidate.detail,
            )
        )
        .order_by(_validation_severity_rank(), Phase3ValidationCandidate.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [_candidate_to_dict(row) for row in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


def load_all_validation_candidate_dicts(db: Session, analysis_id: int) -> list[dict[str, Any]]:
    rows = (
        _validation_candidates_query(db, analysis_id)
        .options(
            load_only(
                Phase3ValidationCandidate.id,
                Phase3ValidationCandidate.kind,
                Phase3ValidationCandidate.column_name,
                Phase3ValidationCandidate.row_index,
                Phase3ValidationCandidate.severity,
                Phase3ValidationCandidate.candidate_action,
                Phase3ValidationCandidate.detail,
            )
        )
        .order_by(_validation_severity_rank(), Phase3ValidationCandidate.id)
        .all()
    )
    return [_candidate_to_dict(row) for row in rows]


def _validation_candidate_rows(db: Session, analysis_id: int, *, limit: int) -> tuple[list[Phase3ValidationCandidate], int | None]:
    sev_rank = _validation_severity_rank()
    rows = (
        db.query(Phase3ValidationCandidate)
        .options(
            load_only(
                Phase3ValidationCandidate.id,
                Phase3ValidationCandidate.kind,
                Phase3ValidationCandidate.column_name,
                Phase3ValidationCandidate.row_index,
                Phase3ValidationCandidate.severity,
                Phase3ValidationCandidate.candidate_action,
                Phase3ValidationCandidate.detail,
            )
        )
        .filter(Phase3ValidationCandidate.analysis_id == analysis_id)
        .order_by(sev_rank, Phase3ValidationCandidate.id)
        .limit(limit + 1)
        .all()
    )
    if not rows:
        return [], 0
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]
    total: int | None = None if truncated else len(rows)
    return rows, total


def _candidate_to_dict(row: Phase3ValidationCandidate) -> dict[str, Any]:
    from validation.candidate_display import enrich_validation_candidate

    if isinstance(row.detail, dict):
        return enrich_validation_candidate(row.detail)
    return enrich_validation_candidate(
        {
            "kind": row.kind,
            "column": row.column_name,
            "row": row.row_index,
            "severity": row.severity,
            "candidate_action": row.candidate_action,
        }
    )


def load_checkpoint_json_key(db: Session, analysis_id: int, key: str) -> Any | None:
    """Read a single top-level checkpoint key without loading the full blob."""
    try:
        val = db.query(Analysis.checkpoint[key]).filter(Analysis.id == analysis_id).scalar()
        return val
    except Exception:
        return None


def load_checkpoint_top_keys(db: Session, analysis_id: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    meta = get_analysis_meta(db, analysis_id)
    if meta and isinstance(meta.config, dict):
        cfg = meta.config
        if cfg.get("normalization_version") is not None:
            out["normalization_version"] = cfg["normalization_version"]
        if cfg.get("normalized_schema") is not None:
            out["effective_schema"] = cfg["normalized_schema"]
        if cfg.get("raw_schema") is not None:
            out["raw_schema"] = cfg["raw_schema"]
        if cfg.get("user_normalization") is not None:
            out["column_normalization"] = cfg["user_normalization"]

    for key in _CHECKPOINT_OVERLAY_KEYS:
        if key in out:
            continue
        val = load_checkpoint_json_key(db, analysis_id, key)
        if val is not None:
            out[key] = val
    return out


def build_phase3_from_relational(db: Session, analysis_id: int) -> dict[str, Any]:
    phase3: dict[str, Any] = {}

    anomaly = (
        db.query(Phase3AnomalyIntel)
        .filter(Phase3AnomalyIntel.analysis_id == analysis_id)
        .first()
    )
    if anomaly and isinstance(anomaly.payload, dict):
        phase3.update(anomaly.payload)

    imputation = (
        db.query(Phase3ImputationIntel)
        .filter(Phase3ImputationIntel.analysis_id == analysis_id)
        .first()
    )
    if imputation and isinstance(imputation.payload, dict):
        for key in ("imputation_results", "imputation_candidates", "user_decisions"):
            if imputation.payload.get(key) is not None:
                phase3[key] = imputation.payload[key]

    candidates, candidate_total = _validation_candidate_rows(
        db, analysis_id, limit=VALIDATION_CANDIDATE_READ_LIMIT
    )
    total_count = count_validation_candidates(db, analysis_id)
    if total_count:
        phase3["validation_candidates_total"] = total_count
    if candidates:
        phase3["validation_candidates"] = [_candidate_to_dict(c) for c in candidates]
        if total_count > len(candidates):
            phase3["validation_candidates_truncated"] = True
        elif candidate_total is None:
            phase3["validation_candidates_truncated"] = True
        elif candidate_total > len(candidates):
            phase3["validation_candidates_truncated"] = True

    val_row = (
        db.query(ValidationResult)
        .options(load_only(ValidationResult.payload))
        .filter(ValidationResult.analysis_id == analysis_id)
        .order_by(ValidationResult.id.desc())
        .first()
    )
    if val_row and isinstance(val_row.payload, dict):
        phase3["validation_results"] = val_row.payload
        if val_row.payload.get("candidates_truncated"):
            phase3["validation_candidates_truncated"] = True
            reported = val_row.payload.get("candidate_count")
            if reported is not None:
                phase3["validation_candidates_reported_total"] = int(reported)
    elif not phase3.get("validation_results"):
        try:
            summary = (
                db.query(Analysis.checkpoint["phase3"]["validation_results"])
                .filter(Analysis.id == analysis_id)
                .scalar()
            )
            if isinstance(summary, dict):
                phase3["validation_results"] = summary
        except Exception:
            pass

    phase3.update(load_checkpoint_phase3_overlay(db, analysis_id))
    return phase3


def merge_checkpoint_phase3_overlay(db: Session, analysis_id: int, updates: dict[str, Any]) -> None:
    """Patch only small phase3 workflow keys without loading the full checkpoint blob."""
    import json

    from sqlalchemy import text

    existing = load_checkpoint_phase3_overlay(db, analysis_id)
    merged = dict(existing)
    for key, val in updates.items():
        if key not in _PHASE3_OVERLAY_KEYS:
            continue
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **val}
        else:
            merged[key] = val

    patch = json.dumps(make_json_safe(merged))
    dialect = db.bind.dialect.name if db.bind else "postgresql"
    if dialect == "postgresql":
        db.execute(
            text(
                """
                UPDATE analyses
                SET checkpoint = jsonb_set(
                    COALESCE(checkpoint::jsonb, '{}'::jsonb),
                    '{phase3}',
                    CAST(:phase3 AS jsonb),
                    true
                )
                WHERE id = :analysis_id
                """
            ),
            {"phase3": patch, "analysis_id": analysis_id},
        )
        return

    an = db.query(Analysis).options(load_only(Analysis.id, Analysis.checkpoint)).filter(
        Analysis.id == analysis_id
    ).first()
    if not an:
        raise ValueError("Analysis not found")
    cp = dict(an.checkpoint) if isinstance(an.checkpoint, dict) else {}
    cp["phase3"] = merged
    an.checkpoint = make_json_safe(cp)


def slim_checkpoint_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop bulky phase3 blobs already stored in relational phase-3 tables."""
    slim = dict(payload)
    phase3 = slim.get("phase3")
    if isinstance(phase3, dict):
        slim["phase3"] = {
            k: phase3[k]
            for k in _PHASE3_OVERLAY_KEYS
            if phase3.get(k) is not None
        }
    return slim
