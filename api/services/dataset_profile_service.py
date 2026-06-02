"""Persist and retrieve dataset upload profiles."""
from __future__ import annotations

import hashlib
import time
from typing import Any

from sqlalchemy.orm import Session

from cache.dataset_profile_cache import DatasetProfileCache
from core.json_safe import make_json_safe
from database.models import Dataset, DatasetProfile, ProfileGenerationLog


def _health_score(completeness: float | None, consistency: float | None) -> float | None:
    if completeness is None and consistency is None:
        return None
    c = completeness if completeness is not None else 0.0
    s = consistency if consistency is not None else 0.0
    return round((c + s) / 2.0, 2)


def profile_dict_from_row(row: DatasetProfile) -> dict[str, Any]:
    pj = row.profile_json if isinstance(row.profile_json, dict) else {}
    return {
        "dataset_id": row.dataset_id,
        "row_count": row.row_count,
        "column_count": row.column_count,
        "file_size_mb": row.file_size_mb,
        "memory_usage_mb": row.memory_usage_mb,
        "numeric_columns": row.numeric_columns,
        "categorical_columns": row.categorical_columns,
        "missing_cells": row.missing_cells,
        "duplicate_rows": row.duplicate_rows,
        "completeness_score": row.completeness_score,
        "consistency_score": row.consistency_score,
        "health_score": row.health_score,
        "profile_version": row.profile_version,
        "column_list": pj.get("column_list"),
        "preview_rows": pj.get("preview_rows"),
        "dtypes": pj.get("dtypes"),
        "missing_per_column": pj.get("missing_per_column"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def profile_dict_from_legacy_dataset(ds: Dataset) -> dict[str, Any] | None:
    if not ds.row_count and not ds.column_count and not ds.health_summary:
        return None
    health = ds.health_summary if isinstance(ds.health_summary, dict) else {}
    completeness = health.get("completeness_pct")
    consistency = health.get("consistency_pct")
    file_mb = round(ds.file_size / (1024 * 1024), 2) if ds.file_size else None
    return {
        "dataset_id": ds.id,
        "row_count": ds.row_count or health.get("rows") or 0,
        "column_count": ds.column_count or health.get("columns") or 0,
        "file_size_mb": file_mb,
        "memory_usage_mb": health.get("memory_usage_mb"),
        "numeric_columns": health.get("numeric_columns", 0),
        "categorical_columns": health.get("categorical_columns", 0),
        "missing_cells": health.get("missing_cells", 0),
        "duplicate_rows": health.get("duplicate_rows", 0),
        "completeness_score": completeness,
        "consistency_score": consistency,
        "health_score": _health_score(completeness, consistency),
        "profile_version": 1,
        "column_list": health.get("column_list"),
        "preview_rows": health.get("preview_rows"),
        "dtypes": health.get("dtypes"),
        "missing_per_column": health.get("missing_per_column"),
    }


class DatasetProfileService:
    def __init__(self, db: Session, cache: DatasetProfileCache | None = None):
        self.db = db
        self.cache = cache or DatasetProfileCache()

    def persist_from_profiler(
        self,
        dataset_id: int,
        profile: dict[str, Any],
        *,
        source_bytes: bytes | None = None,
        generation_time_ms: int | None = None,
    ) -> DatasetProfile:
        t0 = time.perf_counter()
        completeness = profile.get("completeness_pct")
        consistency = profile.get("consistency_pct")
        health = _health_score(completeness, consistency)
        profile_json = make_json_safe(profile.get("health_summary") or profile)

        existing = (
            self.db.query(DatasetProfile).filter(DatasetProfile.dataset_id == dataset_id).first()
        )
        version = (existing.profile_version + 1) if existing else 1

        fields = {
            "row_count": int(profile.get("row_count") or profile.get("rows") or 0),
            "column_count": int(profile.get("column_count") or profile.get("columns") or 0),
            "file_size_mb": profile.get("file_size_mb"),
            "memory_usage_mb": profile.get("memory_usage_mb"),
            "numeric_columns": int(profile.get("numeric_columns") or 0),
            "categorical_columns": int(profile.get("categorical_columns") or 0),
            "missing_cells": int(profile.get("missing_cells") or 0),
            "duplicate_rows": int(profile.get("duplicate_rows") or 0),
            "completeness_score": completeness,
            "consistency_score": consistency,
            "health_score": health,
            "profile_json": profile_json,
            "profile_version": version,
        }

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            row = existing
        else:
            row = DatasetProfile(dataset_id=dataset_id, **fields)
            self.db.add(row)

        elapsed = generation_time_ms
        if elapsed is None:
            elapsed = int((time.perf_counter() - t0) * 1000)

        file_hash = hashlib.sha256(source_bytes).hexdigest() if source_bytes else None
        self.db.add(
            ProfileGenerationLog(
                dataset_id=dataset_id,
                profile_version=version,
                generation_time_ms=elapsed,
                source_file_hash=file_hash,
            )
        )
        self.db.flush()

        payload = profile_dict_from_row(row)
        self.cache.set(dataset_id, payload)
        return row

    def get_profile(self, dataset_id: int, ds: Dataset | None = None) -> dict[str, Any] | None:
        cached = self.cache.get(dataset_id)
        if cached:
            return cached

        row = self.db.query(DatasetProfile).filter(DatasetProfile.dataset_id == dataset_id).first()
        if row:
            payload = profile_dict_from_row(row)
            self.cache.set(dataset_id, payload)
            return payload

        if ds is None:
            ds = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not ds:
            return None

        legacy = profile_dict_from_legacy_dataset(ds)
        if not legacy:
            return None

        # Backfill dataset_profiles from legacy datasets row (one-time)
        self.persist_from_profiler(
            dataset_id,
            {
                **legacy,
                "health_summary": ds.health_summary,
                "completeness_pct": legacy.get("completeness_score"),
                "consistency_pct": legacy.get("consistency_score"),
            },
            generation_time_ms=0,
        )
        self.db.commit()
        row = self.db.query(DatasetProfile).filter(DatasetProfile.dataset_id == dataset_id).first()
        if row:
            payload = profile_dict_from_row(row)
            self.cache.set(dataset_id, payload)
            return payload
        return legacy
