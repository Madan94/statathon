"""Performance indexes for hot query paths."""
from __future__ import annotations

import logging

from sqlalchemy import text

from database.database import engine

logger = logging.getLogger(__name__)

_INDEXES = [
    ("ix_datasets_user_id", "datasets", "user_id"),
    ("ix_analyses_dataset_id", "analyses", "dataset_id"),
    ("ix_analyses_status", "analyses", "status"),
    ("ix_reports_analysis_id", "reports", "analysis_id"),
    ("ix_otp_challenges_email_purpose", "otp_challenges", "email, purpose, consumed_at"),
]


def migrate_perf_indexes() -> dict:
    dialect = engine.dialect.name
    created: list[str] = []
    skipped: list[str] = []

    with engine.begin() as conn:
        for name, table, cols in _INDEXES:
            try:
                if dialect == "postgresql":
                    conn.execute(
                        text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})")
                    )
                else:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))
                created.append(name)
            except Exception as exc:
                logger.debug("Index %s skipped: %s", name, exc)
                skipped.append(name)

        try:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_validation_candidates_analysis_severity "
                    "ON validation_candidates (analysis_id, severity)"
                )
            )
            created.append("ix_validation_candidates_analysis_severity")
        except Exception:
            skipped.append("ix_validation_candidates_analysis_severity")

    return {"migration": "perf_indexes", "created": created, "skipped": skipped}
