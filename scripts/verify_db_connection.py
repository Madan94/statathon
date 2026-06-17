#!/usr/bin/env python3
"""Verify DATABASE_URL connectivity and report provider + schema status."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_API_DIR = _REPO_ROOT / "api"
for path in (_API_DIR, _REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")

from sqlalchemy import text

from database.database import DATABASE_URL, engine, pool_stats


def main() -> int:
    print(f"DATABASE_URL host: {pool_stats().get('host_redacted', '(unknown)')}")
    print(f"Backend: {pool_stats().get('backend', 'unknown')}")
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar()
            db_size = conn.execute(
                text("SELECT pg_size_pretty(pg_database_size(current_database()))")
            ).scalar()
            tables = conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            ).scalar()
        print(f"Connected OK")
        print(f"Postgres: {str(version).split(',')[0]}")
        print(f"Database size: {db_size}")
        print(f"Public tables: {tables}")
        if DATABASE_URL.startswith("sqlite"):
            print("Note: using SQLite — switch DATABASE_URL to Xata for production.")
        elif ".sql.xata.sh" not in DATABASE_URL.lower() and ".xata.tech" not in DATABASE_URL.lower():
            print("Note: not a Xata host — update DATABASE_URL if migrating from Supabase.")
        return 0
    except Exception as exc:
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
