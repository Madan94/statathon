"""Compare original upload vs latest working snapshot."""
from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from database.models import ImputationRowDecision, OutlierDecision, ValidationDecision
from core.multiplier_column import is_multiplier_column
from services.analysis_query import (
    build_phase3_from_relational,
    load_analysis_checkpoint,
    load_checkpoint_phase3_overlay,
)
from services.normalization_service import NormalizationService
from services.phase_audit_service import PhaseAuditService

ROW_DELETE_ACTIONS = frozenset({"REMOVE_ROW", "DELETE_ROW", "REJECT"})
SET_MISSING_ACTIONS = frozenset({"TREAT_AS_MISSING", "DELETE_VALUE", "CONVERT_TO_MISSING"})


class DatasetDiffService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _merge_phase3_sources(relational: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        """Prefer non-empty relational data; overlay wins only when it adds content."""
        merged = dict(relational)
        for key, val in overlay.items():
            if val is None:
                continue
            existing = merged.get(key)
            if isinstance(val, dict) and isinstance(existing, dict):
                if not val and existing:
                    continue
                merged[key] = {**existing, **val}
                continue
            if isinstance(val, list) and isinstance(existing, list):
                if not val and existing:
                    continue
                merged[key] = val
                continue
            merged[key] = val
        return merged

    @staticmethod
    def _resolve_row_index(entry: dict[str, Any]) -> int | None:
        for key in ("row_index", "row_id", "row"):
            raw = entry.get(key)
            if raw is None:
                continue
            try:
                return int(raw)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _resolve_decision(entry: dict[str, Any], default: str = "KEEP") -> str:
        return str(
            entry.get("decision")
            or entry.get("user_action")
            or entry.get("action")
            or default
        ).upper()

    @staticmethod
    def _row_signature(series: pd.Series) -> tuple[Any, ...]:
        sig: list[Any] = []
        for val in series.values:
            if pd.isna(val):
                sig.append(None)
            elif hasattr(val, "item"):
                sig.append(val.item())
            else:
                sig.append(val)
        return tuple(sig)

    def _infer_rows_removed(
        self,
        original_df: pd.DataFrame,
        processed_df: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        if original_df.empty or len(original_df) <= len(processed_df):
            return []

        proc_counts: dict[tuple[Any, ...], int] = {}
        for _, row in processed_df.iterrows():
            key = self._row_signature(row)
            proc_counts[key] = proc_counts.get(key, 0) + 1

        inferred: list[dict[str, Any]] = []
        for idx, row in original_df.iterrows():
            key = self._row_signature(row)
            available = proc_counts.get(key, 0)
            if available > 0:
                proc_counts[key] = available - 1
                continue
            inferred.append(
                {
                    "row_index": int(idx),
                    "column": None,
                    "decision": "REMOVED",
                    "phase": "dataset_diff",
                    "kind": "inferred",
                }
            )
        return inferred[:500]

    def _phase3_state(self, analysis_id: int) -> dict[str, Any]:
        overlay = load_checkpoint_phase3_overlay(self.db, analysis_id) or {}
        relational = build_phase3_from_relational(self.db, analysis_id) or {}
        if not isinstance(relational, dict):
            relational = {}
        return self._merge_phase3_sources(relational, overlay)

    @staticmethod
    def _entry_key(entry: dict[str, Any]) -> tuple[Any, ...]:
        return (
            entry.get("phase"),
            entry.get("row_index"),
            str(entry.get("column") or ""),
            str(entry.get("decision") or "").upper(),
            str(entry.get("rule_id") or ""),
        )

    def _append_unique(self, bucket: list[dict[str, Any]], seen: set[tuple[Any, ...]], entry: dict[str, Any]) -> None:
        key = self._entry_key(entry)
        if key in seen:
            return
        seen.add(key)
        bucket.append(entry)

    def _normalization_changes(self, analysis_id: int) -> dict[str, Any]:
        """Collect normalization deltas — one rename per original column, DB wins over checkpoint."""
        renames_by_orig: dict[str, str] = {}
        removed: set[str] = set()
        excluded: set[str] = set()
        seen_checkpoint_orig: set[str] = set()

        def _add_rename(orig: str, norm: str, *, authoritative: bool = False) -> None:
            if not orig or not norm or orig == norm:
                return
            if is_multiplier_column(orig) or is_multiplier_column(norm):
                return
            if authoritative or orig not in renames_by_orig:
                renames_by_orig[orig] = norm

        def _add_removed(name: str) -> None:
            if name and not is_multiplier_column(name):
                removed.add(name)

        def _add_excluded(name: str) -> None:
            if name and not is_multiplier_column(name):
                excluded.add(name)

        try:
            records = NormalizationService(self.db)._ensure_columns_seeded(analysis_id)
            for col in records:
                orig = str(col.name)
                if is_multiplier_column(orig):
                    continue
                norm = str(col.normalized_name or col.name)
                if col.is_deleted:
                    _add_removed(orig)
                elif col.is_excluded:
                    _add_excluded(orig)
                elif norm != orig:
                    _add_rename(orig, norm, authoritative=True)
        except Exception:
            pass

        from services.analysis_query import load_checkpoint_top_keys

        for source in (
            load_checkpoint_top_keys(self.db, analysis_id).get("column_normalization") or [],
            (load_analysis_checkpoint(self.db, analysis_id) or {}).get("column_normalization") or [],
        ):
            for row in source:
                if not isinstance(row, dict):
                    continue
                orig = str(row.get("original_name") or row.get("column") or "")
                if not orig or is_multiplier_column(orig):
                    continue
                if orig in seen_checkpoint_orig:
                    continue
                seen_checkpoint_orig.add(orig)
                norm = str(
                    row.get("normalized_name")
                    or row.get("canonical_name")
                    or row.get("display_name")
                    or orig
                )
                if row.get("is_deleted"):
                    _add_removed(orig)
                elif row.get("is_excluded"):
                    _add_excluded(orig)
                elif norm and norm != orig:
                    _add_rename(orig, norm)
        renamed = [{"from": orig, "to": norm} for orig, norm in sorted(renames_by_orig.items())]
        return {
            "columns_renamed": renamed,
            "columns_removed": sorted(removed),
            "columns_excluded": sorted(excluded),
        }

    def _validation_changes(self, analysis_id: int) -> dict[str, Any]:
        rows_removed: list[dict[str, Any]] = []
        values_changed: list[dict[str, Any]] = []
        rules_applied: list[dict[str, Any]] = []
        seen_rules: set[tuple[Any, ...]] = set()
        seen_removed: set[tuple[Any, ...]] = set()
        seen_changed: set[tuple[Any, ...]] = set()
        fixed = 0

        def ingest(entry: dict[str, Any]) -> None:
            nonlocal fixed
            action = self._resolve_decision(entry)
            entry = {**entry, "decision": action, "row_index": self._resolve_row_index(entry)}
            self._append_unique(rules_applied, seen_rules, entry)
            if action in ROW_DELETE_ACTIONS:
                self._append_unique(rows_removed, seen_removed, entry)
                fixed += 1
            elif action in SET_MISSING_ACTIONS:
                self._append_unique(
                    values_changed,
                    seen_changed,
                    {
                        **entry,
                        "kind": "set_missing",
                        "old_value": entry.get("old_value"),
                        "new_value": None,
                    },
                )
                fixed += 1
            elif action not in ("KEEP", "ACCEPT", "IGNORE_RULE", "EDIT_VALUE", ""):
                self._append_unique(
                    values_changed,
                    seen_changed,
                    {
                        **entry,
                        "kind": "modified",
                        "old_value": entry.get("old_value"),
                        "new_value": entry.get("new_value"),
                    },
                )
                fixed += 1

        for r in self.db.query(ValidationDecision).filter(
            ValidationDecision.analysis_id == analysis_id
        ).all():
            ingest(
                {
                    "row_index": r.row_index,
                    "column": r.column_name,
                    "decision": str(r.decision or "").upper(),
                    "rule_id": r.rule_id,
                    "rule_type": r.rule_type,
                    "phase": "rule_validation",
                    "old_value": r.old_value,
                    "new_value": r.new_value,
                }
            )

        phase3 = self._phase3_state(analysis_id)
        for d in phase3.get("validation_user_decisions") or []:
            if not isinstance(d, dict):
                continue
            ingest(
                {
                    "row_index": self._resolve_row_index(d),
                    "column": d.get("column") or d.get("column_name"),
                    "decision": self._resolve_decision(d),
                    "rule_id": d.get("rule_id"),
                    "rule_type": d.get("rule_type") or d.get("kind"),
                    "phase": "rule_validation",
                    "old_value": d.get("old_value"),
                    "new_value": d.get("new_value"),
                }
            )

        for event in PhaseAuditService(self.db).list_events(analysis_id, phase="validation", limit=2000):
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            ingest(
                {
                    "row_index": self._resolve_row_index(payload) or self._resolve_row_index(
                        {"row_index": event.get("entity_id")}
                    ),
                    "column": payload.get("column"),
                    "decision": self._resolve_decision({"action": event.get("action")}),
                    "rule_id": event.get("entity_id"),
                    "rule_type": payload.get("rule_type"),
                    "phase": "rule_validation",
                    "old_value": event.get("old_value"),
                    "new_value": event.get("new_value"),
                }
            )

        return {
            "rows_removed": rows_removed[:500],
            "values_changed": values_changed[:500],
            "rules_applied": rules_applied[:500],
            "rule_violations_fixed": fixed,
        }

    def _anomaly_changes(self, analysis_id: int) -> dict[str, Any]:
        handled: list[dict[str, Any]] = []
        rows_removed: list[dict[str, Any]] = []
        values_set_missing: list[dict[str, Any]] = []
        seen_handled: set[tuple[Any, ...]] = set()
        seen_removed: set[tuple[Any, ...]] = set()
        seen_missing: set[tuple[Any, ...]] = set()

        def ingest(column: str, row_index: int | None, action: str, **extra: Any) -> None:
            action = str(action or "KEEP").upper()
            if action == "CONVERT_TO_MISSING":
                action = "DELETE_VALUE"
            base = {
                "row_index": row_index,
                "column": column,
                "decision": action,
                "phase": "anomaly",
                **extra,
            }
            if action in ("KEEP", "EDIT_VALUE", "IGNORE"):
                return
            self._append_unique(handled, seen_handled, base)
            if action in ROW_DELETE_ACTIONS:
                self._append_unique(rows_removed, seen_removed, base)
            if action in SET_MISSING_ACTIONS:
                self._append_unique(
                    values_set_missing,
                    seen_missing,
                    {**base, "kind": "set_missing"},
                )

        for r in self.db.query(OutlierDecision).filter(
            OutlierDecision.analysis_id == analysis_id
        ).all():
            ingest(
                str(r.column_name or ""),
                r.row_index,
                str(r.decision or ""),
                old_value=r.old_value,
                new_value=r.new_value,
                method=r.method,
            )

        phase3 = self._phase3_state(analysis_id)
        raw = phase3.get("outlier_row_decisions") or {}
        if isinstance(raw, dict):
            for column, decisions in raw.items():
                if not isinstance(decisions, list):
                    continue
                for d in decisions:
                    if not isinstance(d, dict):
                        continue
                    ingest(
                        str(column),
                        self._resolve_row_index(d),
                        self._resolve_decision(d),
                        old_value=d.get("old_value"),
                        new_value=d.get("new_value"),
                        method=d.get("method") or d.get("methodology"),
                    )

        for event in PhaseAuditService(self.db).list_events(analysis_id, phase="anomaly", limit=2000):
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            column = str(payload.get("column") or "")
            row_index = self._resolve_row_index(payload)
            ingest(
                column,
                row_index,
                self._resolve_decision({"action": event.get("action")}),
                old_value=event.get("old_value"),
                new_value=event.get("new_value"),
            )

        return {
            "anomalies_handled": handled[:500],
            "anomalies_processed": len(handled),
            "rows_removed": rows_removed[:500],
            "values_set_missing": values_set_missing[:500],
        }

    def _imputation_changes(self, analysis_id: int) -> dict[str, Any]:
        imputed: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        count = 0

        def ingest(entry: dict[str, Any]) -> None:
            nonlocal count
            action = str(entry.get("decision") or "ACCEPT").upper()
            if action in ("KEEP_MISSING", "REJECT"):
                return
            self._append_unique(imputed, seen, entry)
            count += 1

        for r in self.db.query(ImputationRowDecision).filter(
            ImputationRowDecision.analysis_id == analysis_id
        ).all():
            ingest(
                {
                    "row_index": r.row_index,
                    "column": r.column_name,
                    "decision": str(r.decision or "ACCEPT").upper(),
                    "original_value": r.original_value,
                    "imputed_value": r.imputed_value,
                    "method": r.method,
                    "phase": "missing_values",
                }
            )

        phase3 = self._phase3_state(analysis_id)
        user_decisions = phase3.get("imputation_user_decisions") or phase3.get("user_decisions") or {}
        if isinstance(user_decisions, dict):
            for column, block in user_decisions.items():
                if isinstance(block, dict):
                    decisions = block.get("decisions") or []
                    method = block.get("method") or ""
                elif isinstance(block, list):
                    decisions = block
                    method = ""
                else:
                    continue
                for d in decisions:
                    if not isinstance(d, dict):
                        continue
                    ingest(
                        {
                            "row_index": self._resolve_row_index(d),
                            "column": d.get("column") or column,
                            "decision": self._resolve_decision(d, default="ACCEPT"),
                            "original_value": d.get("original_value"),
                            "imputed_value": d.get("imputed_value"),
                            "method": d.get("method") or method,
                            "phase": "missing_values",
                        }
                    )

        for event in PhaseAuditService(self.db).list_events(analysis_id, phase="imputation", limit=2000):
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            action = self._resolve_decision({"action": event.get("action")}, default="ACCEPT")
            if action in ("KEEP_MISSING", "REJECT"):
                continue
            entity_id = str(event.get("entity_id") or "")
            column = str(payload.get("column") or (entity_id.split(":")[0] if ":" in entity_id else entity_id))
            row_index = self._resolve_row_index(payload)
            if row_index is None and ":" in entity_id:
                try:
                    row_index = int(entity_id.split(":", 1)[1])
                except ValueError:
                    row_index = None
            ingest(
                {
                    "row_index": row_index,
                    "column": column,
                    "decision": "ACCEPT" if action.startswith("APPLY_") else action,
                    "original_value": event.get("old_value"),
                    "imputed_value": event.get("new_value"),
                    "method": payload.get("method") or action.replace("APPLY_", "").lower(),
                    "phase": "missing_values",
                }
            )

        return {
            "missing_values_imputed": imputed[:500],
            "values_imputed": count,
        }

    def _merged_rows_removed(
        self,
        val: dict[str, Any],
        anomaly: dict[str, Any],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for entry in list(val.get("rows_removed") or []) + list(anomaly.get("rows_removed") or []):
            self._append_unique(merged, seen, entry)
        return merged[:500]

    def _merged_values_set_missing(
        self,
        val: dict[str, Any],
        anomaly: dict[str, Any],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for entry in list(val.get("values_changed") or []):
            if str(entry.get("decision") or "").upper() in SET_MISSING_ACTIONS or entry.get("kind") == "set_missing":
                self._append_unique(merged, seen, entry)
        for entry in list(anomaly.get("values_set_missing") or []):
            self._append_unique(merged, seen, entry)
        return merged[:500]

    def build_diff(
        self,
        analysis_id: int,
        original_df: pd.DataFrame,
        processed_df: pd.DataFrame,
    ) -> dict[str, Any]:
        """Compare persisted original vs working snapshots — metrics from dataframes only."""
        norm = self._normalization_changes(analysis_id)
        val = self._validation_changes(analysis_id)
        anomaly = self._anomaly_changes(analysis_id)
        imputation = self._imputation_changes(analysis_id)

        rows_before = len(original_df)
        rows_after = len(processed_df)
        rows_removed = max(0, rows_before - rows_after)

        columns_removed_list = list(norm["columns_removed"])
        columns_renamed_list = list(norm["columns_renamed"])
        columns_excluded_list = list(norm["columns_excluded"])

        summary = {
            "rows_before": rows_before,
            "rows_after": rows_after,
            "rows_removed": rows_removed,
            "columns_before": len(original_df.columns),
            "columns_after": len(processed_df.columns),
            "columns_removed": len(columns_removed_list),
            "columns_renamed": len(columns_renamed_list),
            "columns_excluded": len(columns_excluded_list),
            "missing_values_before": int(original_df.isna().sum().sum()) if not original_df.empty else 0,
            "missing_values_after": int(processed_df.isna().sum().sum()) if not processed_df.empty else 0,
            "rule_violations_fixed": val["rule_violations_fixed"],
            "anomalies_processed": anomaly["anomalies_processed"],
            "values_imputed": imputation["values_imputed"],
        }

        diff_summary = {
            "rows_removed": [],
            "columns_removed": columns_removed_list,
            "columns_renamed": columns_renamed_list,
            "columns_excluded": columns_excluded_list,
            "values_changed": val["values_changed"],
            "values_set_missing": self._merged_values_set_missing(val, anomaly),
            "missing_values_imputed": imputation["missing_values_imputed"],
            "anomalies_handled": anomaly["anomalies_handled"],
            "rules_applied": val["rules_applied"],
        }
        return {"summary": summary, "diff_summary": diff_summary}

    def column_change_detail(
        self,
        analysis_id: int,
        column: str,
        original_df: pd.DataFrame,
        processed_df: pd.DataFrame,
    ) -> dict[str, Any]:
        norm = self._normalization_changes(analysis_id)
        renamed = next((r for r in norm["columns_renamed"] if r.get("to") == column or r.get("from") == column), None)
        before_label = renamed["from"] if renamed else column
        after_label = renamed["to"] if renamed else column

        reason = "No changes recorded"
        phase = "none"
        rows_changed = 0
        sample: list[dict[str, Any]] = []

        if column in norm["columns_removed"] or before_label in norm["columns_removed"]:
            return {
                "column": column,
                "before_label": before_label,
                "after_label": after_label,
                "rows_changed": 0,
                "reason": "Column deleted during normalisation",
                "phase": "normalization",
                "sample_changes": [],
            }
        if column in norm["columns_excluded"] or before_label in norm["columns_excluded"]:
            return {
                "column": column,
                "before_label": before_label,
                "after_label": after_label,
                "rows_changed": 0,
                "reason": "Column excluded during normalisation",
                "phase": "normalization",
                "sample_changes": [],
            }
        if renamed:
            reason = f"Renamed from {before_label}"
            phase = "normalization"

        proc_col = column if column in processed_df.columns else after_label
        orig_col = before_label if before_label in original_df.columns else column

        for r in self.db.query(OutlierDecision).filter(
            OutlierDecision.analysis_id == analysis_id,
            OutlierDecision.column_name.in_([column, proc_col, orig_col, before_label, after_label]),
        ).all():
            action = str(r.decision or "").upper()
            if action in ("KEEP", "EDIT_VALUE"):
                continue
            rows_changed += 1
            phase = "anomaly"
            reason = "Anomaly handling"
            if len(sample) < 20:
                sample.append(
                    {
                        "row_index": r.row_index,
                        "decision": action,
                        "old_value": r.old_value,
                        "new_value": r.new_value,
                    }
                )

        for r in self.db.query(ImputationRowDecision).filter(
            ImputationRowDecision.analysis_id == analysis_id,
            ImputationRowDecision.column_name.in_([column, proc_col, orig_col, before_label, after_label]),
        ).all():
            action = str(r.decision or "ACCEPT").upper()
            if action in ("KEEP_MISSING", "REJECT"):
                continue
            rows_changed += 1
            phase = "missing_values"
            reason = "Missing value imputation"
            if len(sample) < 20:
                sample.append(
                    {
                        "row_index": r.row_index,
                        "decision": action,
                        "old_value": r.original_value,
                        "new_value": r.imputed_value,
                    }
                )

        for r in self.db.query(ValidationDecision).filter(
            ValidationDecision.analysis_id == analysis_id,
            ValidationDecision.column_name.in_([column, proc_col, orig_col, before_label, after_label]),
        ).all():
            action = str(r.decision or "").upper()
            if action in ("KEEP", "ACCEPT", ""):
                continue
            rows_changed += 1
            phase = "rule_validation"
            reason = "Rule validation action"
            if len(sample) < 20:
                sample.append(
                    {
                        "row_index": r.row_index,
                        "decision": action,
                        "old_value": r.old_value,
                        "new_value": r.new_value,
                    }
                )

        return {
            "column": column,
            "before_label": before_label,
            "after_label": after_label,
            "rows_changed": rows_changed,
            "reason": reason,
            "phase": phase,
            "sample_changes": sample,
        }

    def row_inspection(
        self,
        analysis_id: int,
        row_index: int,
        original_df: pd.DataFrame,
        processed_df: pd.DataFrame,
    ) -> dict[str, Any]:
        original_row: dict[str, Any] | None = None
        processed_row: dict[str, Any] | None = None
        changed_cells: list[dict[str, Any]] = []

        if 0 <= row_index < len(original_df):
            s = original_df.iloc[row_index]
            original_row = {
                str(k): (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v))
                for k, v in s.items()
            }
        if 0 <= row_index < len(processed_df):
            s = processed_df.iloc[row_index]
            processed_row = {
                str(k): (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v))
                for k, v in s.items()
            }

        if original_row and processed_row:
            shared_cols = set(original_row.keys()) & set(processed_row.keys())
            for col in shared_cols:
                ov, pv = original_row[col], processed_row[col]
                if (ov is None and pv is not None) or (ov is not None and pv is None) or ov != pv:
                    changed_cells.append(
                        {
                            "column": col,
                            "before": ov,
                            "after": pv,
                            "kind": "changed",
                        }
                    )

        decisions: list[dict[str, Any]] = []
        for r in self.db.query(ValidationDecision).filter(
            ValidationDecision.analysis_id == analysis_id,
            ValidationDecision.row_index == row_index,
        ).all():
            decisions.append(
                {
                    "phase": "rule_validation",
                    "column": r.column_name,
                    "decision": r.decision,
                    "old_value": r.old_value,
                    "new_value": r.new_value,
                }
            )
        for r in self.db.query(OutlierDecision).filter(
            OutlierDecision.analysis_id == analysis_id,
            OutlierDecision.row_index == row_index,
        ).all():
            decisions.append(
                {
                    "phase": "anomaly",
                    "column": r.column_name,
                    "decision": r.decision,
                    "old_value": r.old_value,
                    "new_value": r.new_value,
                }
            )
        for r in self.db.query(ImputationRowDecision).filter(
            ImputationRowDecision.analysis_id == analysis_id,
            ImputationRowDecision.row_index == row_index,
        ).all():
            decisions.append(
                {
                    "phase": "missing_values",
                    "column": r.column_name,
                    "decision": r.decision,
                    "old_value": r.original_value,
                    "new_value": r.imputed_value,
                }
            )

        return {
            "row_index": row_index,
            "original_row": original_row,
            "processed_row": processed_row,
            "changed_cells": changed_cells,
            "decisions": decisions,
        }
