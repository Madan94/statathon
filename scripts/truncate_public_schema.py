#!/usr/bin/env python3
"""Truncate all tables in the Postgres public schema (app data wipe)."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_API_DIR = _REPO_ROOT / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(1, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")

from sqlalchemy import text

from database.database import engine, DATABASE_URL


def main() -> int:
    if DATABASE_URL.startswith("sqlite"):
        print("Refusing to truncate: DATABASE_URL is SQLite. Point .env at Xata/Postgres.", file=sys.stderr)
        return 1

    with engine.connect() as conn:
        tables = [
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
            ).fetchall()
        ]

    if not tables:
        print("No tables in public schema.")
        return 0

    print(f"Truncating {len(tables)} table(s) in public schema...")
    with engine.begin() as conn:
        for name in tables:
            conn.execute(text(f'TRUNCATE TABLE public."{name}" RESTART IDENTITY CASCADE'))
            print(f"  truncated {name}")

    print("Done. All public tables emptied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
