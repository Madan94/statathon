"""Create dataset_profiles and profile_generation_logs tables."""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from database.database import Base, engine

logger = logging.getLogger(__name__)


def migrate_dataset_profiles_schema() -> None:
    dialect_name = engine.dialect.name
    insp = inspect(engine)

    import database.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    if dialect_name == "postgresql":
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_dataset_profiles_dataset_id "
                    "ON dataset_profiles (dataset_id)"
                )
            )
    logger.info("Dataset profiles schema migration complete (dialect=%s)", dialect_name)
