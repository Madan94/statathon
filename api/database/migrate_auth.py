"""Apply auth schema changes to existing databases (SQLite + PostgreSQL)."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from database.database import engine

logger = logging.getLogger(__name__)


def _timestamp_type(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "TIMESTAMP"
    return "DATETIME"


def _bool_default(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "BOOLEAN DEFAULT FALSE"
    return "BOOLEAN DEFAULT 0"


def migrate_auth_schema() -> None:
    dialect_name = engine.dialect.name
    insp = inspect(engine)

    if insp.has_table("users"):
        user_cols = {c["name"] for c in insp.get_columns("users")}
        ts = _timestamp_type(dialect_name)
        alters: list[str] = []

        if "full_name" not in user_cols:
            alters.append("ALTER TABLE users ADD COLUMN full_name VARCHAR(256)")
        if "officer_role" not in user_cols:
            alters.append("ALTER TABLE users ADD COLUMN officer_role VARCHAR(256)")
        if "email_verified_at" not in user_cols:
            alters.append(f"ALTER TABLE users ADD COLUMN email_verified_at {ts}")
        if "is_active" not in user_cols:
            alters.append(f"ALTER TABLE users ADD COLUMN is_active {_bool_default(dialect_name)}")
        if "failed_login_count" not in user_cols:
            alters.append("ALTER TABLE users ADD COLUMN failed_login_count INTEGER DEFAULT 0")
        if "locked_until" not in user_cols:
            alters.append(f"ALTER TABLE users ADD COLUMN locked_until {ts}")
        if "created_at" not in user_cols:
            alters.append(f"ALTER TABLE users ADD COLUMN created_at {ts}")

        with engine.begin() as conn:
            for sql in alters:
                logger.info("Auth migration: %s", sql)
                conn.execute(text(sql))
            if alters:
                try:
                    if dialect_name == "postgresql":
                        conn.execute(
                            text(
                                "UPDATE users SET is_active = TRUE "
                                "WHERE is_active IS NULL OR is_active = FALSE"
                            )
                        )
                    else:
                        conn.execute(
                            text(
                                "UPDATE users SET is_active = 1 "
                                "WHERE is_active IS NULL OR is_active = 0"
                            )
                        )
                except Exception as e:
                    logger.warning("Could not backfill users.is_active: %s", e)

    # create_all in main.py creates otp_challenges / refresh_tokens if missing
    missing = [t for t in ("otp_challenges", "refresh_tokens") if not insp.has_table(t)]
    if missing:
        logger.info("Auth tables pending create_all: %s", ", ".join(missing))
