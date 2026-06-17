"""Persist and apply user-approved column normalization across pipeline phases."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from analysis_state.schema_state import (
    apply_effective_schema_to_payload,
    build_effective_schema,
)
from core.json_safe import make_json_safe
from repositories.column_audit_repository import ColumnAuditRepository
from repositories.dataset_column_repository import DatasetColumnRepository
from database.models import SemanticProfile
from services.analysis_query import (
    get_analysis_meta,
    get_normalization_version,
    load_analysis_checkpoint,
    load_checkpoint_top_keys,
    set_normalization_meta,
)
from services.column_dictionary_service import ColumnDictionaryService, lookup


class NormalizationService:
    def __init__(self, db: Session):
        self.db = db
        self.columns = DatasetColumnRepository(db)
        self.audit = ColumnAuditRepository(db)

    def seed_from_analysis_payload(
        self,
        *,
        dataset_id: int,
        analysis_id: int,
        raw_columns: list[str],
        payload: dict[str, Any],
    ) -> None:
        inferred: dict[str, str] = {}
        schema = (payload.get("profiling_summary") or {}).get("schema")
        if isinstance(schema, dict):
            inferred = {str(k): str(v) for k, v in schema.items()}

        suggested: dict[str, str] = {}
        for row in payload.get("column_normalization") or []:
            if not isinstance(row, dict):
                continue
            # Key by the canonical identity (matches the renamed df columns that
            # are seeded as raw_columns); fall back to the raw original name.
            key = (
                row.get("canonical_name")
                or row.get("normalized_name")
                or row.get("original_name")
                or row.get("column")
            )
            if not key:
                continue
            suggested[str(key)] = str(
                row.get("display_name") or row.get("normalized_name") or key
            )

        self.columns.seed_from_raw_columns(
            dataset_id=dataset_id,
            analysis_id=analysis_id,
            raw_columns=raw_columns,
            inferred_types=inferred,
            suggested_names=suggested,
        )
        self.db.commit()

    def _ensure_columns_seeded(self, analysis_id: int) -> list:
        records = self.columns.list_for_analysis(analysis_id)
        if records:
            return records
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            return []
        config = an.config if isinstance(an.config, dict) else {}
        raw = config.get("raw_schema")
        if raw:
            self.columns.seed_from_raw_columns(
                dataset_id=an.dataset_id,
                analysis_id=analysis_id,
                raw_columns=[str(c) for c in raw],
                inferred_types={},
                suggested_names={},
            )
            self.db.commit()
            return self.columns.list_for_analysis(analysis_id)

        overlay = load_checkpoint_top_keys(self.db, analysis_id)
        raw = overlay.get("raw_schema")
        if raw:
            self.columns.seed_from_raw_columns(
                dataset_id=an.dataset_id,
                analysis_id=analysis_id,
                raw_columns=[str(c) for c in raw],
                inferred_types={},
                suggested_names={},
            )
            self.db.commit()
            return self.columns.list_for_analysis(analysis_id)

        profile_cols = [
            r[0]
            for r in self.db.query(SemanticProfile.column_name)
            .filter(SemanticProfile.analysis_id == analysis_id)
            .order_by(SemanticProfile.column_name)
            .all()
        ]
        if profile_cols:
            self.columns.seed_from_raw_columns(
                dataset_id=an.dataset_id,
                analysis_id=analysis_id,
                raw_columns=[str(c) for c in profile_cols],
                inferred_types={},
                suggested_names={},
            )
            self.db.commit()
            return self.columns.list_for_analysis(analysis_id)

        return []

    def apply_dictionary_to_analysis(self, analysis_id: int) -> dict[str, Any]:
        """Apply global dictionary overrides to raw column names for this analysis."""
        records = self._ensure_columns_seeded(analysis_id)
        dict_svc = ColumnDictionaryService(self.db)
        mappings = dict_svc.get_mappings()
        if not mappings:
            return {
                "matched": 0,
                "unmatched": len(records),
                "columns": self._column_rows_with_dictionary(records, mappings),
                "dictionary": dict_svc.get_global_summary(),
            }

        apply_stats = dict_svc.apply_to_columns(records, mappings)
        self.db.commit()
        refreshed = self.columns.list_for_analysis(analysis_id)
        return {
            "matched": apply_stats["matched_count"],
            "unmatched": apply_stats["unmatched_count"],
            "columns": self._column_rows_with_dictionary(refreshed, mappings),
            "dictionary": {
                **dict_svc.get_global_summary(),
                "matched_count": apply_stats["matched_count"],
            },
        }

    def _column_rows_with_dictionary(
        self,
        records: list,
        mappings: dict[str, str],
    ) -> list[dict[str, Any]]:
        dict_svc = ColumnDictionaryService(self.db)
        return [
            dict_svc.column_payload(col, mappings)
            for col in records
        ]

    def _dictionary_matched_count(self, records: list, mappings: dict[str, str]) -> int:
        count = 0
        for col in records:
            target = lookup(col.name, mappings)
            if target and (col.normalized_name or col.name) == target:
                count += 1
        return count

    def get_step2_normalization(self, analysis_id: int) -> dict[str, Any]:
        """Step 2 GET payload with dictionary auto-apply when not yet saved."""
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")

        version = get_normalization_version(self.db, analysis_id)
        records = self._ensure_columns_seeded(analysis_id)
        dict_svc = ColumnDictionaryService(self.db)
        mappings = dict_svc.get_mappings()
        summary = dict_svc.get_global_summary()

        if not version and mappings:
            dict_svc.apply_to_columns(records, mappings)
            self.db.commit()
            records = self.columns.list_for_analysis(analysis_id)

        matched_count = self._dictionary_matched_count(records, mappings)
        return {
            "normalization_version": version,
            "dictionary": {
                "version": summary["version"],
                "total_keys": summary["total_keys"],
                "matched_count": matched_count,
            },
            "columns": self._column_rows_with_dictionary(records, mappings),
        }

    def get_effective_schema_response(self, analysis_id: int) -> dict[str, Any]:
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        records = self._ensure_columns_seeded(analysis_id)
        version = get_normalization_version(self.db, analysis_id)
        return {
            "dataset_id": an.dataset_id,
            "analysis_id": analysis_id,
            "normalization_version": version,
            "columns": build_effective_schema(records),
            "column_map": [
                {
                    "column_id": c.id,
                    "original_name": c.name,
                    "normalized_name": c.normalized_name or c.name,
                    "is_deleted": c.is_deleted,
                    "is_excluded": c.is_excluded,
                    "is_active": c.is_active,
                    "last_modified": c.last_modified.isoformat() if c.last_modified else None,
                }
                for c in records
            ],
        }

    def get_saved_decisions(self, analysis_id: int) -> dict[str, Any] | None:
        version = get_normalization_version(self.db, analysis_id)
        if not version:
            return None
        records = self._ensure_columns_seeded(analysis_id)
        return {
            "normalization_version": version,
            "columns": [
                {
                    "column_id": c.id,
                    "original_name": c.name,
                    "normalized_name": c.normalized_name or c.name,
                    "is_deleted": c.is_deleted,
                    "is_excluded": c.is_excluded,
                    "is_active": c.is_active,
                }
                for c in records
            ],
        }

    def save_normalization(
        self,
        analysis_id: int,
        user_id: int,
        column_updates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")

        records = self._ensure_columns_seeded(analysis_id)
        checkpoint = load_analysis_checkpoint(self.db, analysis_id) or {}
        by_name = {c.name: c for c in records}
        for c in records:
            if c.normalized_name:
                by_name[str(c.normalized_name)] = c
        for row in checkpoint.get("column_normalization") or []:
            if not isinstance(row, dict):
                continue
            target = None
            for key in (
                row.get("canonical_name"),
                row.get("normalized_name"),
                row.get("original_name"),
            ):
                if key and str(key) in by_name:
                    target = by_name[str(key)]
                    break
            if not target:
                continue
            for alias in (
                row.get("original_name"),
                row.get("canonical_name"),
                row.get("normalized_name"),
                row.get("display_name"),
            ):
                if alias:
                    by_name[str(alias)] = target
        if not by_name:
            raise ValueError("Column registry not initialized for this analysis")

        version = int(get_normalization_version(self.db, analysis_id) or 0) + 1
        now = datetime.utcnow()

        for upd in column_updates:
            orig = str(upd.get("original_name") or upd.get("name") or "")
            if not orig or orig not in by_name:
                continue
            col = by_name[orig]
            old_norm = col.normalized_name or col.name
            new_norm = str(upd.get("normalized_name") or upd.get("display_name") or old_norm).strip()
            if not new_norm:
                new_norm = orig
            is_deleted = bool(upd.get("is_deleted", False))
            is_excluded = bool(upd.get("is_excluded", False))
            is_active = not is_deleted and not is_excluded

            actions: list[str] = []
            if new_norm != old_norm:
                actions.append("rename")
                self.audit.log(
                    dataset_id=an.dataset_id,
                    analysis_id=analysis_id,
                    column_id=col.id,
                    user_id=user_id,
                    old_name=old_norm,
                    new_name=new_norm,
                    action="rename",
                    payload={"original_name": orig},
                )
            if is_deleted and not col.is_deleted:
                actions.append("delete")
                self.audit.log(
                    dataset_id=an.dataset_id,
                    analysis_id=analysis_id,
                    column_id=col.id,
                    user_id=user_id,
                    old_name=orig,
                    new_name=None,
                    action="delete",
                )
            if is_excluded and not col.is_excluded:
                actions.append("exclude")
                self.audit.log(
                    dataset_id=an.dataset_id,
                    analysis_id=analysis_id,
                    column_id=col.id,
                    user_id=user_id,
                    old_name=orig,
                    new_name=new_norm,
                    action="exclude",
                )
            if is_active and not col.is_active and not is_deleted and not is_excluded:
                actions.append("include")
                self.audit.log(
                    dataset_id=an.dataset_id,
                    analysis_id=analysis_id,
                    column_id=col.id,
                    user_id=user_id,
                    old_name=orig,
                    new_name=new_norm,
                    action="include",
                )

            col.normalized_name = new_norm
            col.is_deleted = is_deleted
            col.is_excluded = is_excluded
            col.is_active = is_active
            col.last_modified = now
            if not actions and upd:
                self.audit.log(
                    dataset_id=an.dataset_id,
                    analysis_id=analysis_id,
                    column_id=col.id,
                    user_id=user_id,
                    old_name=old_norm,
                    new_name=new_norm,
                    action="update",
                    payload=upd,
                )

        self.db.flush()
        refreshed = self.columns.list_for_analysis(analysis_id)
        effective = build_effective_schema(refreshed)
        raw_schema = [c.name for c in refreshed]
        user_norm = make_json_safe(
            [
                {
                    "column_id": c.id,
                    "original_name": c.name,
                    "normalized_name": c.normalized_name,
                    "is_deleted": c.is_deleted,
                    "is_excluded": c.is_excluded,
                }
                for c in refreshed
            ]
        )
        set_normalization_meta(
            self.db,
            analysis_id,
            version=version,
            effective_schema=effective,
            raw_schema=raw_schema,
            user_normalization=user_norm,
        )
        from services.analysis_payload_cache import invalidate_analysis_cache
        from services.normalization_transform_service import persist_normalized_snapshot
        from services.phase_status_service import PhaseStatusService

        invalidate_analysis_cache(analysis_id)
        try:
            persist_normalized_snapshot(self.db, analysis_id)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "normalized snapshot skipped for analysis %s: %s", analysis_id, exc
            )
        row = PhaseStatusService(self.db).get_or_create(analysis_id)
        row.normalization_completed = True
        row.updated_at = datetime.utcnow()
        self.db.commit()

        return {
            "analysis_id": analysis_id,
            "dataset_id": an.dataset_id,
            "normalization_version": version,
            "effective_schema": effective,
            "column_count": len(effective),
        }

    def apply_to_payload(self, analysis_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        version = get_normalization_version(self.db, analysis_id)
        if not version:
            return payload
        records = self._ensure_columns_seeded(analysis_id)
        if not records:
            return payload
        return apply_effective_schema_to_payload(
            payload, records, normalization_version=int(version)
        )
