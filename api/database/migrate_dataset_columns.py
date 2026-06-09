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

    # Build list of (column_name, SQL) — only for columns that DON'T already exist
    stmts: list[tuple[str, str]] = []

    needed = {
        "analysis_id": "ALTER TABLE dataset_columns ADD COLUMN IF NOT EXISTS analysis_id INTEGER",
        "normalized_name": "ALTER TABLE dataset_columns ADD COLUMN IF NOT EXISTS normalized_name VARCHAR(512)",
        "is_deleted": "ALTER TABLE dataset_columns ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false",
        "is_excluded": "ALTER TABLE dataset_columns ADD COLUMN IF NOT EXISTS is_excluded BOOLEAN NOT NULL DEFAULT false",
        "is_active": "ALTER TABLE dataset_columns ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true",
        "last_modified": f"ALTER TABLE dataset_columns ADD COLUMN IF NOT EXISTS last_modified {ts}",
    }

    if dialect_name != "postgresql":
        # SQLite doesn't support IF NOT EXISTS for ADD COLUMN
        needed = {
            "analysis_id": "ALTER TABLE dataset_columns ADD COLUMN analysis_id INTEGER",
            "normalized_name": "ALTER TABLE dataset_columns ADD COLUMN normalized_name VARCHAR(512)",
            "is_deleted": "ALTER TABLE dataset_columns ADD COLUMN is_deleted BOOLEAN DEFAULT 0",
            "is_excluded": "ALTER TABLE dataset_columns ADD COLUMN is_excluded BOOLEAN DEFAULT 0",
            "is_active": "ALTER TABLE dataset_columns ADD COLUMN is_active BOOLEAN DEFAULT 1",
            "last_modified": f"ALTER TABLE dataset_columns ADD COLUMN last_modified {ts}",
        }

    for col_name, sql in needed.items():
        if col_name not in cols:
            stmts.append((col_name, sql))

    if not stmts:
        logger.info("Dataset columns migration: all columns already exist — skipping")
    else:
        # Execute each ALTER in its OWN transaction so one timeout doesn't cascade
        for col_name, sql in stmts:
            try:
                with engine.begin() as conn:
                    # Set a short statement timeout for migrations (10s instead of default 2min)
                    if dialect_name == "postgresql":
                        conn.execute(text("SET LOCAL statement_timeout = '10s'"))
                    logger.info("Dataset columns migration: %s", sql)
                    conn.execute(text(sql))
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    logger.debug("Column %s already exists, skipping", col_name)
                else:
                    logger.warning("Dataset columns migration warning (%s): %s", col_name, e)

    # Index creation — also in its own transaction
    if dialect_name == "postgresql":
        try:
            with engine.begin() as conn:
                conn.execute(text("SET LOCAL statement_timeout = '10s'"))
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_dataset_columns_analysis_name "
                        "ON dataset_columns (analysis_id, name) WHERE analysis_id IS NOT NULL"
                    )
                )
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.debug("Index uq_dataset_columns_analysis_name already exists")
            else:
                logger.warning("Could not create uq_dataset_columns_analysis_name: %s", e)

    import database.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Dataset columns normalization schema migration complete (dialect=%s)", dialect_name)
