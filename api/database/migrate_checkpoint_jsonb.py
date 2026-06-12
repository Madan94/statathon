"""Safe batched migration: analyses.checkpoint JSON → JSONB (run via scripts/migrate_db.py)."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text

from database.database import engine

logger = logging.getLogger(__name__)

MIGRATION_NAME = "checkpoint_jsonb"
DEFAULT_BATCH_SIZE = 200


def _column_udt(conn, column: str) -> str | None:
    row = conn.execute(
        text(
            """
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'analyses'
              AND column_name = :col
            """
        ),
        {"col": column},
    ).fetchone()
    return row[0] if row else None


def _table_exists() -> bool:
    return inspect(engine).has_table("analyses")


def checkpoint_migration_status() -> dict[str, Any]:
    """Inspect current checkpoint column state without mutating schema."""
    status: dict[str, Any] = {
        "migration": MIGRATION_NAME,
        "state": "unknown",
        "dialect": engine.dialect.name,
    }
    if engine.dialect.name != "postgresql":
        status["state"] = "skipped"
        status["reason"] = "non-postgresql"
        return status
    if not _table_exists():
        status["state"] = "skipped"
        status["reason"] = "analyses_table_missing"
        return status

    with engine.connect() as conn:
        checkpoint_udt = _column_udt(conn, "checkpoint")
        staging_udt = _column_udt(conn, "checkpoint_jsonb")
        status["checkpoint_udt"] = checkpoint_udt
        status["checkpoint_jsonb_udt"] = staging_udt

        if checkpoint_udt == "jsonb":
            status["state"] = "already_applied"
            return status

        if checkpoint_udt is None:
            status["state"] = "skipped"
            status["reason"] = "checkpoint_column_missing"
            return status

        pending = 0
        if staging_udt == "jsonb":
            pending = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM analyses
                    WHERE checkpoint IS NOT NULL
                      AND checkpoint_jsonb IS NULL
                    """
                )
            ).scalar()
            pending = int(pending or 0)
        status["pending_copy_rows"] = pending

        if staging_udt == "jsonb" and pending > 0:
            status["state"] = "in_progress"
            status["reason"] = "staging_column_partial_copy"
        elif staging_udt == "jsonb" and pending == 0:
            status["state"] = "ready_to_swap"
            status["reason"] = "copy_complete_rename_pending"
        else:
            status["state"] = "pending"
            status["reason"] = f"checkpoint_is_{checkpoint_udt}"
    return status


def migrate_checkpoint_jsonb(*, batch_size: int = DEFAULT_BATCH_SIZE) -> dict[str, Any]:
    """
    Idempotent JSON → JSONB migration using a staging column and batched copies.

    Never uses ``ALTER COLUMN ... TYPE jsonb`` on large tables (Neon timeout safe).
    """
    status = checkpoint_migration_status()
    if status["state"] in ("already_applied", "skipped"):
        logger.info(
            "Migration %s: %s (%s)",
            MIGRATION_NAME,
            status["state"],
            status.get("reason", ""),
        )
        return status

    if engine.dialect.name != "postgresql" or not _table_exists():
        return status

    copied_total = 0

    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE analyses ADD COLUMN IF NOT EXISTS checkpoint_jsonb JSONB")
        )
    logger.info("Migration %s: staging column checkpoint_jsonb ensured", MIGRATION_NAME)

    while True:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE analyses AS a
                    SET checkpoint_jsonb = a.checkpoint::jsonb
                    FROM (
                        SELECT id
                        FROM analyses
                        WHERE checkpoint IS NOT NULL
                          AND checkpoint_jsonb IS NULL
                        ORDER BY id
                        LIMIT :batch_size
                    ) AS batch
                    WHERE a.id = batch.id
                    """
                ),
                {"batch_size": batch_size},
            )
            batch_count = int(result.rowcount or 0)

        if batch_count == 0:
            break
        copied_total += batch_count
        logger.info(
            "Migration %s: copied batch=%s total=%s",
            MIGRATION_NAME,
            batch_count,
            copied_total,
        )

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE analyses
                SET checkpoint_jsonb = NULL
                WHERE checkpoint IS NULL AND checkpoint_jsonb IS NULL
                """
            )
        )

        remaining = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM analyses
                WHERE checkpoint IS NOT NULL AND checkpoint_jsonb IS NULL
                """
            )
        ).scalar()
        if int(remaining or 0) > 0:
            status["state"] = "failed"
            status["reason"] = "copy_incomplete"
            status["remaining_rows"] = int(remaining)
            logger.error(
                "Migration %s failed: %s rows still not copied",
                MIGRATION_NAME,
                remaining,
            )
            return status

        mismatch = conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM analyses
                    WHERE checkpoint IS NOT NULL
                      AND checkpoint_jsonb IS NOT NULL
                      AND checkpoint::text IS DISTINCT FROM checkpoint_jsonb::text
                    LIMIT 1
                )
                """
            )
        ).scalar()
        if bool(mismatch):
            status["state"] = "failed"
            status["reason"] = "verification_mismatch"
            logger.error("Migration %s failed: checkpoint/jsonb text mismatch in sample", MIGRATION_NAME)
            return status

        conn.execute(text("ALTER TABLE analyses RENAME COLUMN checkpoint TO checkpoint_legacy"))
        conn.execute(text("ALTER TABLE analyses RENAME COLUMN checkpoint_jsonb TO checkpoint"))
        conn.execute(text("ALTER TABLE analyses DROP COLUMN checkpoint_legacy"))

    status["state"] = "applied"
    status["rows_copied"] = copied_total
    status.pop("reason", None)
    logger.info(
        "Migration %s: applied successfully (rows_copied=%s)",
        MIGRATION_NAME,
        copied_total,
    )
    return status
