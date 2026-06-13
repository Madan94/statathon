"""Checkpoint backend — persist partial extraction state for resume.

Supports two backends (auto-detected):
  - FileCheckpoint: JSON files in local directory (default for dev)
  - DBCheckpoint: PostgreSQL/SQLite via SQLAlchemy (when DATABASE_URL set)

Usage:
    from template_engine.storage.checkpoint import get_checkpoint_backend
    cp = get_checkpoint_backend()
    cp.save("abc123", "vlm_parsing", {"pages": [...]})
    data = cp.load("abc123", "vlm_parsing")
"""
from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CheckpointBackend(ABC):
    """Abstract checkpoint storage interface."""

    @abstractmethod
    def save(self, source_hash: str, stage: str, data: dict[str, Any]) -> None:
        """Save checkpoint data for a pipeline stage."""
        ...

    @abstractmethod
    def load(self, source_hash: str, stage: str) -> dict[str, Any] | None:
        """Load checkpoint data. Returns None if not found."""
        ...

    @abstractmethod
    def exists(self, source_hash: str, stage: str | None = None) -> bool:
        """Check if checkpoint exists. If stage is None, check any stage."""
        ...

    @abstractmethod
    def load_latest(self, source_hash: str) -> tuple[str, dict[str, Any]] | None:
        """Load the most recent checkpoint for a hash. Returns (stage, data) or None."""
        ...

    @abstractmethod
    def delete(self, source_hash: str) -> None:
        """Delete all checkpoints for a source hash."""
        ...

    @abstractmethod
    def list_hashes(self) -> list[str]:
        """List all source hashes with stored checkpoints."""
        ...


# ---------------------------------------------------------------------------
# Stage ordering (for determining "latest")
# ---------------------------------------------------------------------------

_STAGE_ORDER = [
    "hashing",
    "vlm_parsing",
    "entity_extraction",
    "entity_deduplication",
    "question_inference",
    "ast_assembly",
    "validation",
    "complete",
]


def _stage_index(stage: str) -> int:
    try:
        return _STAGE_ORDER.index(stage)
    except ValueError:
        return -1


# ---------------------------------------------------------------------------
# File-based checkpoint
# ---------------------------------------------------------------------------

class FileCheckpoint(CheckpointBackend):
    """JSON file-based checkpoint storage.

    Structure:
        {checkpoint_dir}/{source_hash[:16]}/{stage}.json
    """

    def __init__(self, base_dir: str | Path = "./checkpoints"):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _hash_dir(self, source_hash: str) -> Path:
        return self._base / source_hash[:16]

    def _stage_file(self, source_hash: str, stage: str) -> Path:
        return self._hash_dir(source_hash) / f"{stage}.json"

    def save(self, source_hash: str, stage: str, data: dict[str, Any]) -> None:
        d = self._hash_dir(source_hash)
        d.mkdir(parents=True, exist_ok=True)
        payload = {
            "source_hash": source_hash,
            "stage": stage,
            "timestamp": time.time(),
            "data": data,
        }
        self._stage_file(source_hash, stage).write_text(
            json.dumps(payload, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug("Checkpoint saved: %s/%s", source_hash[:8], stage)

    def load(self, source_hash: str, stage: str) -> dict[str, Any] | None:
        f = self._stage_file(source_hash, stage)
        if not f.exists():
            return None
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
            return payload.get("data")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load checkpoint %s/%s: %s", source_hash[:8], stage, exc)
            return None

    def exists(self, source_hash: str, stage: str | None = None) -> bool:
        if stage:
            return self._stage_file(source_hash, stage).exists()
        return self._hash_dir(source_hash).exists() and any(
            self._hash_dir(source_hash).iterdir()
        )

    def load_latest(self, source_hash: str) -> tuple[str, dict[str, Any]] | None:
        d = self._hash_dir(source_hash)
        if not d.exists():
            return None

        best_stage: str | None = None
        best_idx = -1
        for f in d.glob("*.json"):
            stage = f.stem
            idx = _stage_index(stage)
            if idx > best_idx:
                best_idx = idx
                best_stage = stage

        if best_stage is None:
            return None

        data = self.load(source_hash, best_stage)
        if data is None:
            return None
        return (best_stage, data)

    def delete(self, source_hash: str) -> None:
        d = self._hash_dir(source_hash)
        if d.exists():
            import shutil
            shutil.rmtree(d)
            logger.debug("Checkpoint deleted: %s", source_hash[:8])

    def list_hashes(self) -> list[str]:
        if not self._base.exists():
            return []
        return [d.name for d in self._base.iterdir() if d.is_dir()]


# ---------------------------------------------------------------------------
# DB-based checkpoint (SQLAlchemy)
# ---------------------------------------------------------------------------

class DBCheckpoint(CheckpointBackend):
    """Database-backed checkpoint using SQLAlchemy.

    Table: extraction_checkpoints (source_hash, stage, data_json, created_at)
    Auto-creates table if not exists.
    """

    def __init__(self, database_url: str):
        from sqlalchemy import (
            Column, DateTime, MetaData, String, Table, Text,
            create_engine, func, select, delete as sa_delete,
        )
        self._engine = create_engine(database_url, pool_pre_ping=True)
        self._metadata = MetaData()
        self._table = Table(
            "extraction_checkpoints",
            self._metadata,
            Column("source_hash", String(64), primary_key=True),
            Column("stage", String(32), primary_key=True),
            Column("data_json", Text, nullable=False),
            Column("created_at", DateTime, server_default=func.now()),
        )
        self._metadata.create_all(self._engine)
        # Keep references for query building
        self._select = select
        self._sa_delete = sa_delete

    def save(self, source_hash: str, stage: str, data: dict[str, Any]) -> None:
        from sqlalchemy import text as sa_text
        data_json = json.dumps(data, default=str, ensure_ascii=False)
        with self._engine.begin() as conn:
            # Upsert via delete + insert (portable across SQLite/Postgres)
            conn.execute(
                self._sa_delete(self._table).where(
                    (self._table.c.source_hash == source_hash) &
                    (self._table.c.stage == stage)
                )
            )
            conn.execute(
                self._table.insert().values(
                    source_hash=source_hash,
                    stage=stage,
                    data_json=data_json,
                )
            )
        logger.debug("DB checkpoint saved: %s/%s", source_hash[:8], stage)

    def load(self, source_hash: str, stage: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                self._select(self._table.c.data_json).where(
                    (self._table.c.source_hash == source_hash) &
                    (self._table.c.stage == stage)
                )
            ).first()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    def exists(self, source_hash: str, stage: str | None = None) -> bool:
        from sqlalchemy import func as sa_func
        with self._engine.connect() as conn:
            q = self._select(sa_func.count()).select_from(self._table).where(
                self._table.c.source_hash == source_hash
            )
            if stage:
                q = q.where(self._table.c.stage == stage)
            result = conn.execute(q).scalar()
        return (result or 0) > 0

    def load_latest(self, source_hash: str) -> tuple[str, dict[str, Any]] | None:
        with self._engine.connect() as conn:
            rows = conn.execute(
                self._select(self._table.c.stage, self._table.c.data_json).where(
                    self._table.c.source_hash == source_hash
                )
            ).fetchall()

        if not rows:
            return None

        best_stage: str | None = None
        best_idx = -1
        best_data: str = ""
        for stage, data_json in rows:
            idx = _stage_index(stage)
            if idx > best_idx:
                best_idx = idx
                best_stage = stage
                best_data = data_json

        if best_stage is None:
            return None
        try:
            return (best_stage, json.loads(best_data))
        except json.JSONDecodeError:
            return None

    def delete(self, source_hash: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                self._sa_delete(self._table).where(
                    self._table.c.source_hash == source_hash
                )
            )

    def list_hashes(self) -> list[str]:
        from sqlalchemy import distinct
        with self._engine.connect() as conn:
            rows = conn.execute(
                self._select(distinct(self._table.c.source_hash))
            ).fetchall()
        return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_checkpoint_backend(
    backend: str = "auto",
    file_dir: str = "./checkpoints",
) -> CheckpointBackend:
    """Create the appropriate checkpoint backend.

    Args:
        backend: "auto" | "file" | "db"
            - auto: use DB if DATABASE_URL is set, else file
            - file: always use file-based
            - db: always use database

    Returns:
        CheckpointBackend instance.
    """
    if backend == "db" or (backend == "auto" and os.getenv("DATABASE_URL")):
        db_url = os.getenv("DATABASE_URL", "")
        if db_url:
            logger.info("Using DB checkpoint backend")
            return DBCheckpoint(db_url)
        # Fall through to file if DATABASE_URL is empty
        logger.warning("DATABASE_URL empty, falling back to file checkpoint")

    logger.info("Using file checkpoint backend: %s", file_dir)
    return FileCheckpoint(file_dir)
