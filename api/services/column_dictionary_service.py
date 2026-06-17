"""Global column dictionary — parse, merge, lookup, persist."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import ColumnDictionaryGlobal, DatasetColumn

SINGLETON_ID = 1
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


class ColumnDictionaryError(ValueError):
    """Invalid dictionary payload."""


def normalize_lookup_key(name: str) -> str:
    return (name or "").strip().lower()


def parse_flat_dictionary(raw: bytes | dict[str, Any]) -> dict[str, str]:
    """Validate flat JSON object mapping source column names to canonical names."""
    if isinstance(raw, bytes):
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ColumnDictionaryError(f"Dictionary file exceeds {MAX_UPLOAD_BYTES} bytes")
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ColumnDictionaryError(f"Invalid JSON: {exc}") from exc
    else:
        data = raw

    if not isinstance(data, dict):
        raise ColumnDictionaryError("Dictionary must be a JSON object")

    out: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise ColumnDictionaryError("All dictionary keys must be strings")
        if isinstance(value, (dict, list)):
            raise ColumnDictionaryError(f"Nested value not allowed for key {key!r}")
        if value is None:
            continue
        if not isinstance(value, str):
            value = str(value)
        source = key.strip()
        target = value.strip()
        if source and target:
            out[source] = target
    return out


def build_lookup_index(mappings: dict[str, str]) -> dict[str, str]:
    """Case-insensitive index: normalized source key -> target name."""
    index: dict[str, str] = {}
    for source, target in mappings.items():
        index[normalize_lookup_key(source)] = target
    return index


def lookup(raw_column_name: str, mappings: dict[str, str]) -> str | None:
    if not mappings:
        return None
    return build_lookup_index(mappings).get(normalize_lookup_key(raw_column_name))


def merge_mappings(
    existing: dict[str, str],
    incoming: dict[str, str],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Keep existing keys; add only new source keys (case-insensitive)."""
    merged = dict(existing)
    existing_keys_lower = {normalize_lookup_key(k) for k in existing}
    added_keys: list[str] = []
    skipped_keys: list[str] = []

    for source, target in incoming.items():
        key_lower = normalize_lookup_key(source)
        if key_lower in existing_keys_lower:
            skipped_keys.append(source)
            continue
        merged[source.strip()] = target.strip()
        existing_keys_lower.add(key_lower)
        added_keys.append(source.strip())

    stats = {
        "added": len(added_keys),
        "skipped": len(skipped_keys),
        "total": len(merged),
        "added_keys": added_keys,
        "skipped_keys": skipped_keys,
    }
    return merged, stats


class ColumnDictionaryService:
    def __init__(self, db: Session):
        self.db = db

    def _get_or_create_singleton(self) -> ColumnDictionaryGlobal:
        row = (
            self.db.query(ColumnDictionaryGlobal)
            .filter(ColumnDictionaryGlobal.id == SINGLETON_ID)
            .first()
        )
        if row:
            return row
        row = ColumnDictionaryGlobal(id=SINGLETON_ID, mappings={}, version=0)
        self.db.add(row)
        self.db.flush()
        return row

    def get_global_summary(self) -> dict[str, Any]:
        row = self._get_or_create_singleton()
        mappings = row.mappings if isinstance(row.mappings, dict) else {}
        return {
            "version": int(row.version or 0),
            "total_keys": len(mappings),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def get_mappings(self) -> dict[str, str]:
        row = self._get_or_create_singleton()
        raw = row.mappings if isinstance(row.mappings, dict) else {}
        return {str(k): str(v) for k, v in raw.items()}

    def upload_and_merge(self, payload: bytes | dict[str, Any], user_id: int) -> dict[str, Any]:
        incoming = parse_flat_dictionary(payload)
        row = self._get_or_create_singleton()
        existing = row.mappings if isinstance(row.mappings, dict) else {}
        merged, merge_stats = merge_mappings(
            {str(k): str(v) for k, v in existing.items()},
            incoming,
        )
        row.mappings = merged
        row.version = int(row.version or 0) + 1
        row.updated_at = datetime.utcnow()
        row.updated_by_user_id = user_id
        self.db.commit()
        self.db.refresh(row)
        return {
            "version": row.version,
            "total_keys": len(merged),
            **merge_stats,
        }

    def apply_to_columns(
        self,
        records: list[DatasetColumn],
        mappings: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Apply dictionary targets to column rows; returns match stats."""
        mapping = mappings if mappings is not None else self.get_mappings()
        if not mapping:
            return {"matched_count": 0, "unmatched_count": len(records), "matched_keys": []}

        index = build_lookup_index(mapping)
        matched_keys: list[str] = []
        matched_count = 0

        for col in records:
            target = index.get(normalize_lookup_key(col.name))
            if not target:
                continue
            col.normalized_name = target
            matched_count += 1
            matched_keys.append(col.name)

        return {
            "matched_count": matched_count,
            "unmatched_count": max(0, len(records) - matched_count),
            "matched_keys": matched_keys,
        }

    @staticmethod
    def column_payload(col: DatasetColumn, mappings: dict[str, str]) -> dict[str, Any]:
        target = lookup(col.name, mappings)
        dictionary_mapped = target is not None and (col.normalized_name or col.name) == target
        return {
            "column_id": col.id,
            "original_name": col.name,
            "normalized_name": col.normalized_name or col.name,
            "is_deleted": col.is_deleted,
            "is_excluded": col.is_excluded,
            "is_active": col.is_active,
            "dictionary_mapped": dictionary_mapped,
            "match_method": "column_dictionary" if dictionary_mapped else None,
        }


def http_error_from_dictionary(exc: Exception) -> HTTPException:
    if isinstance(exc, ColumnDictionaryError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))
