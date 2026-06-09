"""Create analysis_phase_status and column_phase_reviews tables."""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def migrate_phase_status_schema(engine) -> dict:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    applied: list[str] = []

    if "analysis_phase_status" not in tables:
        dialect = engine.dialect.name
        if dialect == "postgresql":
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE analysis_phase_status (
                            id SERIAL PRIMARY KEY,
                            analysis_id INTEGER NOT NULL UNIQUE REFERENCES analyses(id) ON DELETE CASCADE,
                            summary_completed BOOLEAN NOT NULL DEFAULT FALSE,
                            normalization_completed BOOLEAN NOT NULL DEFAULT FALSE,
                            semantic_completed BOOLEAN NOT NULL DEFAULT FALSE,
                            clustering_completed BOOLEAN NOT NULL DEFAULT FALSE,
                            kg_completed BOOLEAN NOT NULL DEFAULT FALSE,
                            rule_validation_completed BOOLEAN NOT NULL DEFAULT FALSE,
                            anomaly_completed BOOLEAN NOT NULL DEFAULT FALSE,
                            missing_value_completed BOOLEAN NOT NULL DEFAULT FALSE,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_analysis_phase_status_analysis_id "
                        "ON analysis_phase_status (analysis_id)"
                    )
                )
        else:
            from database.models import AnalysisPhaseStatus  # noqa: F401

            AnalysisPhaseStatus.__table__.create(bind=engine, checkfirst=True)
        applied.append("analysis_phase_status")

    if "column_phase_reviews" not in tables:
        dialect = engine.dialect.name
        if dialect == "postgresql":
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE column_phase_reviews (
                            id SERIAL PRIMARY KEY,
                            analysis_id INTEGER NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                            phase VARCHAR(32) NOT NULL,
                            column_name VARCHAR(512) NOT NULL,
                            status VARCHAR(32) NOT NULL DEFAULT 'pending',
                            item_count INTEGER NOT NULL DEFAULT 0,
                            reviewed_count INTEGER NOT NULL DEFAULT 0,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE (analysis_id, phase, column_name)
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_column_phase_reviews_analysis "
                        "ON column_phase_reviews (analysis_id, phase)"
                    )
                )
        else:
            from database.models import ColumnPhaseReview  # noqa: F401

            ColumnPhaseReview.__table__.create(bind=engine, checkfirst=True)
        applied.append("column_phase_reviews")

    return {"migration": "phase_status_schema", "state": "applied", "tables": applied or ["exists"]}
