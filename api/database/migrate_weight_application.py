"""Idempotent migration for weight application tables and phase flag."""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from database.database import engine
from database.models import Base

logger = logging.getLogger(__name__)


def _add_column_if_missing(table: str, column: str, ddl: str) -> bool:
    insp = inspect(engine)
    if not insp.has_table(table):
        return False
    cols = {c["name"] for c in insp.get_columns(table)}
    if column in cols:
        return False
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
    return True


def migrate_weight_application_schema() -> dict:
    Base.metadata.create_all(bind=engine)
    added: list[str] = []
    boolean_default = "FALSE" if engine.dialect.name == "postgresql" else "0"
    if _add_column_if_missing(
        "analysis_phase_status",
        "weight_application_completed",
        f"weight_application_completed BOOLEAN NOT NULL DEFAULT {boolean_default}",
    ):
        added.append("analysis_phase_status.weight_application_completed")
    logger.info("Weight application migration applied; added=%s", added)
    return {"migration": "weight_application", "state": "applied", "added": added}
