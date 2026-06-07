"""Add review columns to outlier_decisions / imputation_row_decisions (idempotent)."""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from database.database import engine

logger = logging.getLogger(__name__)


def _add_column_if_missing(table: str, column: str, ddl: str) -> bool:
    insp = inspect(engine)
    if not insp.has_table(table):
        return False
    cols = {c["name"] for c in insp.get_columns(table)}
    if column in cols:
        return False
    with engine.begin() as conn:
        conn.execute(text(ddl))
    logger.info("Added column %s.%s", table, column)
    return True


def migrate_review_decisions_schema() -> dict:
    if engine.dialect.name != "postgresql":
        return {"migration": "review_decisions", "state": "skipped", "reason": "non-postgresql"}

    added: list[str] = []
    if _add_column_if_missing(
        "outlier_decisions",
        "confidence",
        "ALTER TABLE outlier_decisions ADD COLUMN confidence DOUBLE PRECISION",
    ):
        added.append("outlier_decisions.confidence")
    if _add_column_if_missing(
        "outlier_decisions",
        "reviewed_by",
        "ALTER TABLE outlier_decisions ADD COLUMN reviewed_by INTEGER REFERENCES users(id)",
    ):
        added.append("outlier_decisions.reviewed_by")
    if _add_column_if_missing(
        "imputation_row_decisions",
        "reviewed_by",
        "ALTER TABLE imputation_row_decisions ADD COLUMN reviewed_by INTEGER REFERENCES users(id)",
    ):
        added.append("imputation_row_decisions.reviewed_by")

    state = "applied" if added else "already_applied"
    return {"migration": "review_decisions", "state": state, "added": added}
