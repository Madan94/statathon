"""Jury demo: append invalid rows, re-run validation, optionally restore baseline."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from core.column_roles import build_column_roles, is_identifier_column
from core.feature_flags import validation_demo_noise_enabled
from core.ingestion import infer_schema
from core.rule_validator import normalize_schema
from core.state import AnalysisState
from database.models import Analysis, Dataset, ValidationDecision
from object_storage.object_store import try_build_default_store
from pipelines.phase3_pipeline import rerun_validation_intel
from services.analysis_dataframe_service import load_snapshot_dataframe
from services.analysis_payload_cache import invalidate_analysis_cache
from services.analysis_query import (
    count_all_stored_validation_candidates,
    ensure_validation_display_sample,
    get_analysis_meta,
    load_analysis_checkpoint,
    merge_checkpoint_phase3_overlay,
)
from services.normalization_transform_service import (
    dataframe_checksum,
    load_working_dataframe,
)
from services.phase3_persistence_service import Phase3PersistenceService
from services.phase_status_cache import invalidate_phase_status
from services.phase_status_service import PhaseStatusService
from validation.rule_discovery import DiscoveredRule, discover_all_rules

DEMO_NOISE_COL = "_statathon_demo_noise"
NUMERIC_DEMO_RULE_TYPES = frozenset({"numeric_between", "numeric_min", "numeric_max"})
MAX_DEMO_NOISE_ROWS = 8


def _require_enabled() -> None:
    if not validation_demo_noise_enabled():
        raise PermissionError("Validation demo noise is disabled (set VALIDATION_DEMO_NOISE=1)")


def _load_analysis(db: Session, analysis_id: int) -> Analysis:
    an = get_analysis_meta(db, analysis_id)
    if not an:
        raise ValueError("Analysis not found")
    if an.status != "complete":
        raise ValueError("Analysis not complete")
    return an


def _demo_noise_meta(checkpoint: dict[str, Any]) -> dict[str, Any]:
    meta = checkpoint.get("demo_noise")
    return dict(meta) if isinstance(meta, dict) else {}


def _set_demo_noise_meta(an: Analysis, meta: dict[str, Any]) -> None:
    checkpoint = dict(an.checkpoint or {})
    checkpoint["demo_noise"] = meta
    an.checkpoint = checkpoint


def _columns_meta_from_checkpoint(checkpoint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sp = checkpoint.get("semantic_profile")
    if isinstance(sp, dict):
        cols = sp.get("columns")
        if isinstance(cols, dict) and cols:
            return {str(k): dict(v) if isinstance(v, dict) else {} for k, v in cols.items()}

    out: dict[str, dict[str, Any]] = {}
    for row in checkpoint.get("semantic_mapping") or []:
        if not isinstance(row, dict):
            continue
        col = str(row.get("column") or "")
        if col:
            out[col] = dict(row)
    return out


def _column_profiles_from_checkpoint(checkpoint: dict[str, Any]) -> dict[str, Any]:
    sp = checkpoint.get("semantic_profile")
    if isinstance(sp, dict):
        profiles = sp.get("column_profiles")
        if isinstance(profiles, dict):
            return profiles
    profiling = checkpoint.get("profiling_summary")
    if isinstance(profiling, dict):
        profiles = profiling.get("column_profiles")
        if isinstance(profiles, dict):
            return profiles
    return {}


def _build_analysis_state(
    an: Analysis,
    checkpoint: dict[str, Any],
    columns_meta: dict[str, dict[str, Any]],
) -> AnalysisState:
    sp = checkpoint.get("semantic_profile")
    semantic_profile: dict[str, Any] = {"columns": columns_meta}
    if isinstance(sp, dict):
        for key in ("column_profiles", "unified_domains"):
            if sp.get(key) is not None:
                semantic_profile[key] = sp[key]
        if not semantic_profile.get("column_profiles"):
            profiles = _column_profiles_from_checkpoint(checkpoint)
            if profiles:
                semantic_profile["column_profiles"] = profiles

    return AnalysisState(
        dataset_id=an.dataset_id,
        analysis_id=an.id,
        semantic_profile=semantic_profile,
        schema_graph=checkpoint.get("schema_graph") or {},
        dependency_graph=checkpoint.get("priority_dependencies") or {},
        inferred_dataset_context=checkpoint.get("dataset_context") or {},
        column_normalization=checkpoint.get("column_normalization") or [],
    )


def _load_demo_dataframe(db: Session, analysis_id: int) -> pd.DataFrame:
    snap = load_snapshot_dataframe(db, analysis_id, "normalized")
    if snap is not None and len(snap.columns) > 0:
        schema = infer_schema(snap)
        return normalize_schema(snap, schema)
    df, _, _ = load_working_dataframe(db, analysis_id, apply_user_norm=True)
    return df


def _persist_normalized_snapshot(db: Session, analysis_id: int, df: pd.DataFrame) -> dict[str, Any]:
    from services.apply_service import _persist_snapshot

    an = get_analysis_meta(db, analysis_id)
    if not an:
        raise ValueError("Analysis not found")
    ds = db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
    if not ds:
        raise ValueError("Dataset not found")
    store = try_build_default_store() if ds.object_key else None
    return _persist_snapshot(
        db,
        analysis_id=analysis_id,
        dataset_id=ds.id,
        stage="normalized",
        df=df,
        store=store,
        meta={
            "checksum": dataframe_checksum(df),
            "phase": "demo_noise",
            "demo_noise": True,
        },
    )


def violating_value_for_rule(rule: DiscoveredRule) -> Any | None:
    params = rule.params or {}
    rt = rule.rule_type
    if rt == "numeric_between":
        lo = float(params["min"])
        hi = float(params["max"])
        span = max(abs(hi - lo), 1.0)
        return hi + span * 2
    if rt == "numeric_min":
        return float(params["min"]) - max(abs(float(params["min"])) + 1000, 1000)
    if rt == "numeric_max":
        return float(params["max"]) + max(abs(float(params["max"])) + 1000, 1000)
    return None


def build_demo_noise_rows(
    df: pd.DataFrame,
    rules: list[DiscoveredRule],
    *,
    columns_meta: dict[str, dict[str, Any]] | None = None,
    column_roles: dict[str, str] | None = None,
    max_rows: int = MAX_DEMO_NOISE_ROWS,
) -> list[dict[str, Any]]:
    """Build row dicts that violate discovered single-column numeric rules."""
    if df.empty:
        return []

    roles = column_roles or build_column_roles(columns_meta or {})
    template = df.iloc[0].to_dict()
    rows: list[dict[str, Any]] = []
    used_cols: set[str] = set()

    for rule in rules:
        if len(rows) >= max_rows:
            break
        if rule.kind != "single_column" or rule.rule_type not in NUMERIC_DEMO_RULE_TYPES:
            continue
        if not rule.columns:
            continue
        col = str(rule.columns[0])
        if col not in df.columns or col in used_cols:
            continue
        if is_identifier_column(col, roles, columns_meta):
            continue
        bad = violating_value_for_rule(rule)
        if bad is None:
            continue
        row = dict(template)
        row[col] = bad
        row[DEMO_NOISE_COL] = True
        rows.append(row)
        used_cols.add(col)

    if not rows:
        for col in df.columns:
            if len(rows) >= max(3, min(max_rows, 5)):
                break
            if str(col) == DEMO_NOISE_COL:
                continue
            if is_identifier_column(str(col), roles, columns_meta):
                continue
            series = pd.to_numeric(df[col], errors="coerce")
            if series.notna().sum() < 1:
                continue
            lo = float(series.min())
            hi = float(series.max())
            row = dict(template)
            row[col] = hi + max(abs(hi - lo), 1000) * 3
            row[DEMO_NOISE_COL] = True
            rows.append(row)

    return rows


def _reset_validation_review(db: Session, analysis_id: int) -> None:
    db.query(ValidationDecision).filter(ValidationDecision.analysis_id == analysis_id).delete(
        synchronize_session=False
    )
    status = PhaseStatusService(db).get_or_create(analysis_id)
    status.rule_validation_completed = False
    status.updated_at = datetime.utcnow()
    merge_checkpoint_phase3_overlay(
        db,
        analysis_id,
        {
            "validation_acknowledged": False,
            "validation_user_decisions": {},
        },
    )
    invalidate_phase_status(analysis_id)


def _rerun_validation_for_df(
    db: Session,
    an: Analysis,
    checkpoint: dict[str, Any],
    df: pd.DataFrame,
) -> AnalysisState:
    columns_meta = _columns_meta_from_checkpoint(checkpoint)
    state = _build_analysis_state(an, checkpoint, columns_meta)
    schema = infer_schema(df)
    rerun_validation_intel(df, schema, state)
    Phase3PersistenceService(db).persist_validation_only(state)
    ensure_validation_display_sample(db, an.id)
    _reset_validation_review(db, an.id)
    invalidate_analysis_cache(an.id)
    return state


class ValidationDemoNoiseService:
    def __init__(self, db: Session):
        self.db = db

    def status(self, analysis_id: int) -> dict[str, Any]:
        enabled = validation_demo_noise_enabled()
        out: dict[str, Any] = {
            "enabled": enabled,
            "active": False,
            "rows_added": 0,
            "baseline_row_count": None,
            "current_row_count": None,
            "candidate_count": 0,
            "pending_refresh": False,
        }
        if not enabled:
            return out

        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")

        checkpoint = load_analysis_checkpoint(self.db, analysis_id) or {}
        meta = _demo_noise_meta(checkpoint)
        out["active"] = bool(meta.get("active"))
        out["rows_added"] = int(meta.get("rows_added") or 0)
        out["baseline_row_count"] = meta.get("baseline_row_count")
        out["pending_refresh"] = bool(meta.get("pending_refresh"))
        out["candidate_count"] = count_all_stored_validation_candidates(self.db, analysis_id)

        try:
            df = _load_demo_dataframe(self.db, analysis_id)
            out["current_row_count"] = len(df)
        except Exception:
            pass

        return out

    def inject(self, analysis_id: int) -> dict[str, Any]:
        _require_enabled()
        an = _load_analysis(self.db, analysis_id)
        checkpoint = dict(load_analysis_checkpoint(self.db, analysis_id) or {})
        meta = _demo_noise_meta(checkpoint)
        if meta.get("active"):
            raise ValueError("Demo noise already injected — refresh validation or remove demo noise first")

        df = _load_demo_dataframe(self.db, analysis_id)
        if df.empty:
            raise ValueError("Dataset is empty — cannot inject demo noise")

        columns_meta = _columns_meta_from_checkpoint(checkpoint)
        column_roles = build_column_roles(columns_meta)
        rules = discover_all_rules(
            columns=[str(c) for c in df.columns if str(c) != DEMO_NOISE_COL],
            columns_meta=columns_meta,
            schema_graph=checkpoint.get("schema_graph") or {},
            priority_dependencies=checkpoint.get("priority_dependencies") or {},
            column_profiles=_column_profiles_from_checkpoint(checkpoint),
            unified_domains=(checkpoint.get("semantic_profile") or {}).get("unified_domains")
            if isinstance(checkpoint.get("semantic_profile"), dict)
            else None,
            archetypes=(checkpoint.get("dataset_context") or {}).get("archetypes")
            if isinstance(checkpoint.get("dataset_context"), dict)
            else None,
            column_roles=column_roles,
        )

        noise_rows = build_demo_noise_rows(
            df,
            rules,
            columns_meta=columns_meta,
            column_roles=column_roles,
        )
        if not noise_rows:
            raise ValueError("No applicable rules found to build demo noise rows")

        baseline_row_count = len(df)
        baseline_checksum = dataframe_checksum(df)
        noise_df = pd.DataFrame(noise_rows)
        if DEMO_NOISE_COL not in df.columns:
            df[DEMO_NOISE_COL] = False
        else:
            df[DEMO_NOISE_COL] = df[DEMO_NOISE_COL].fillna(False)
        combined = pd.concat([df, noise_df], ignore_index=True)

        _persist_normalized_snapshot(self.db, analysis_id, combined)
        _set_demo_noise_meta(
            an,
            {
                "active": True,
                "rows_added": len(noise_rows),
                "baseline_row_count": baseline_row_count,
                "baseline_checksum": baseline_checksum,
                "pending_refresh": True,
                "injected_at": datetime.utcnow().isoformat() + "Z",
            },
        )
        self.db.commit()

        return {
            "success": True,
            "analysis_id": analysis_id,
            "rows_added": len(noise_rows),
            "baseline_row_count": baseline_row_count,
            "current_row_count": len(combined),
            "pending_refresh": True,
            "message": "Demo rows appended — click Refresh validation to detect violations",
        }

    def refresh(self, analysis_id: int) -> dict[str, Any]:
        _require_enabled()
        an = _load_analysis(self.db, analysis_id)
        checkpoint = dict(load_analysis_checkpoint(self.db, analysis_id) or {})
        meta = _demo_noise_meta(checkpoint)
        if not meta.get("active"):
            raise ValueError("Inject demo noise before refreshing validation")

        df = _load_demo_dataframe(self.db, analysis_id)
        state = _rerun_validation_for_df(self.db, an, checkpoint, df)

        meta["pending_refresh"] = False
        meta["refreshed_at"] = datetime.utcnow().isoformat() + "Z"
        _set_demo_noise_meta(an, meta)
        self.db.commit()

        summary = (state.validation_results or {}).get("summary") or {}
        gate = summary.get("gate") if isinstance(summary.get("gate"), dict) else summary
        sev = gate.get("severity_breakdown") or {}
        candidate_count = len(state.validation_candidates or [])

        return {
            "success": True,
            "analysis_id": analysis_id,
            "candidate_count": candidate_count,
            "rules_fired": gate.get("rules_fired", candidate_count),
            "severity_breakdown": sev,
            "current_row_count": len(df),
            "rows_added": int(meta.get("rows_added") or 0),
        }

    def remove(self, analysis_id: int) -> dict[str, Any]:
        _require_enabled()
        an = _load_analysis(self.db, analysis_id)
        checkpoint = dict(load_analysis_checkpoint(self.db, analysis_id) or {})
        meta = _demo_noise_meta(checkpoint)
        if not meta.get("active"):
            raise ValueError("No demo noise is active for this analysis")

        df = _load_demo_dataframe(self.db, analysis_id)
        if DEMO_NOISE_COL in df.columns:
            mask = df[DEMO_NOISE_COL].fillna(False).astype(bool)
            cleaned = df.loc[~mask].drop(columns=[DEMO_NOISE_COL], errors="ignore")
        else:
            baseline = int(meta.get("baseline_row_count") or 0)
            cleaned = df.iloc[:baseline].copy() if baseline > 0 else df.copy()
            if DEMO_NOISE_COL in cleaned.columns:
                cleaned = cleaned.drop(columns=[DEMO_NOISE_COL], errors="ignore")

        _persist_normalized_snapshot(self.db, analysis_id, cleaned)
        state = _rerun_validation_for_df(self.db, an, checkpoint, cleaned)

        _set_demo_noise_meta(an, {})
        self.db.commit()

        return {
            "success": True,
            "analysis_id": analysis_id,
            "restored_row_count": len(cleaned),
            "candidate_count": len(state.validation_candidates or []),
            "message": "Demo noise removed and validation restored",
        }
