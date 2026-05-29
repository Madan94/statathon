"""Apply dataset_columns normalization schema to existing databases."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from database.database import Base, engine

logger = logging.getLogger(__name__)


def _timestamp_type(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "TIMESTAMP"
    return "DATETIME"


def migrate_dataset_columns_schema() -> None:
    dialect_name = engine.dialect.name
    insp = inspect(engine)

    if not insp.has_table("dataset_columns"):
        logger.info("dataset_columns table missing — will be created by create_all")
        return

    cols = {c["name"] for c in insp.get_columns("dataset_columns")}
    ts = _timestamp_type(dialect_name)

    if dialect_name == "postgresql":
        pg_stmts = [
            "ALTER TABLE dataset_columns ADD COLUMN IF NOT EXISTS analysis_id INTEGER",
            "ALTER TABLE dataset_columns ADD COLUMN IF NOT EXISTS normalized_name VARCHAR(512)",
            "ALTER TABLE dataset_columns ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE dataset_columns ADD COLUMN IF NOT EXISTS is_excluded BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE dataset_columns ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true",
            f"ALTER TABLE dataset_columns ADD COLUMN IF NOT EXISTS last_modified {ts}",
        ]
    else:
        pg_stmts = []
        sqlite_stmts = [
            ("analysis_id", "ALTER TABLE dataset_columns ADD COLUMN analysis_id INTEGER"),
            ("normalized_name", "ALTER TABLE dataset_columns ADD COLUMN normalized_name VARCHAR(512)"),
            ("is_deleted", "ALTER TABLE dataset_columns ADD COLUMN is_deleted BOOLEAN DEFAULT 0"),
            ("is_excluded", "ALTER TABLE dataset_columns ADD COLUMN is_excluded BOOLEAN DEFAULT 0"),
            ("is_active", "ALTER TABLE dataset_columns ADD COLUMN is_active BOOLEAN DEFAULT 1"),
            ("last_modified", f"ALTER TABLE dataset_columns ADD COLUMN last_modified {ts}"),
        ]
        for name, stmt in sqlite_stmts:
            if name not in cols:
                pg_stmts.append(stmt)

    with engine.begin() as conn:
        for sql in pg_stmts:
            try:
                logger.info("Dataset columns migration: %s", sql)
                conn.execute(text(sql))
            except Exception as e:
                if dialect_name == "sqlite" and "duplicate column" in str(e).lower():
                    logger.debug("Column already exists: %s", e)
                else:
                    logger.warning("Dataset columns migration warning: %s", e)

        if dialect_name == "postgresql":
            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_dataset_columns_analysis_name "
                        "ON dataset_columns (analysis_id, name) WHERE analysis_id IS NOT NULL"
                    )
                )
            except Exception as e:
                logger.warning("Could not create uq_dataset_columns_analysis_name: %s", e)

    import database.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Dataset columns normalization schema migration complete (dialect=%s)", dialect_name)
