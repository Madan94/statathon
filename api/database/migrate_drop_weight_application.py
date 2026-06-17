"""Drop survey weight-application tables and phase flag (removed from pipeline)."""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from database.database import engine

logger = logging.getLogger(__name__)


def migrate_drop_weight_application_schema() -> dict:
    dialect = engine.dialect.name
    dropped: list[str] = []

    if dialect == "postgresql":
        with engine.begin() as conn:
            for table in ("weight_audit_logs", "weight_profiles", "weight_applications"):
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                dropped.append(table)
            conn.execute(
                text(
                    "ALTER TABLE analysis_phase_status "
                    "DROP COLUMN IF EXISTS weight_application_completed"
                )
            )
            dropped.append("analysis_phase_status.weight_application_completed")
    else:
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        with engine.begin() as conn:
            for table in ("weight_audit_logs", "weight_profiles", "weight_applications"):
                if table in tables:
                    conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
                    dropped.append(table)
            if "analysis_phase_status" in tables:
                cols = {c["name"] for c in insp.get_columns("analysis_phase_status")}
                if "weight_application_completed" in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE analysis_phase_status "
                            "DROP COLUMN weight_application_completed"
                        )
                    )
                    dropped.append("analysis_phase_status.weight_application_completed")

    logger.info("Weight application schema dropped: %s", dropped)
    return {"migration": "drop_weight_application", "state": "applied", "dropped": dropped}
