#!/usr/bin/env python3
"""
Apply missing object-storage columns on `datasets` (Neon Postgres / SQLite).

Safe to run multiple times. Does not print DATABASE_URL or secrets.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_API = _REPO / "api"
for p in (str(_REPO), str(_API)):
    if p not in sys.path:
        sys.path.insert(0, p)


def main() -> int:
    from sqlalchemy import inspect, text

    from database.database import DATABASE_URL, engine

    insp = inspect(engine)
    if not insp.has_table("datasets"):
        print("ERROR: table `datasets` does not exist — run the app once or apply base migrations.")
        return 1

    dialect = engine.dialect.name
    cols = {c["name"] for c in insp.get_columns("datasets")}
    missing_report: list[str] = []

    def exec_sql(sql: str) -> None:
        with engine.begin() as conn:
            conn.execute(text(sql))

    if dialect == "postgresql":
        stmts_by_col = [
            ("object_key", "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS object_key VARCHAR(1024)"),
            ("storage_url", "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS storage_url VARCHAR(2048)"),
            ("file_size", "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS file_size BIGINT"),
            ("checksum", "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS checksum VARCHAR(128)"),
            ("upload_status", "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS upload_status VARCHAR(32)"),
            (
                "storage_provider",
                "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS storage_provider VARCHAR(32) "
                "NOT NULL DEFAULT 'local'",
            ),
        ]
        for name, stmt in stmts_by_col:
            if name not in cols:
                exec_sql(stmt)
                missing_report.append(name)

        try:
            exec_sql("ALTER TABLE datasets ALTER COLUMN storage_path DROP NOT NULL")
            missing_report.append("(storage_path nullable)")
        except Exception:
            pass

        exec_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_datasets_object_key "
            "ON datasets (object_key) WHERE object_key IS NOT NULL"
        )

    elif dialect == "sqlite":
        sqlite_ops = [
            ("object_key", "ALTER TABLE datasets ADD COLUMN object_key VARCHAR(1024)"),
            ("storage_url", "ALTER TABLE datasets ADD COLUMN storage_url VARCHAR(2048)"),
            ("file_size", "ALTER TABLE datasets ADD COLUMN file_size BIGINT"),
            ("checksum", "ALTER TABLE datasets ADD COLUMN checksum VARCHAR(128)"),
            ("upload_status", "ALTER TABLE datasets ADD COLUMN upload_status VARCHAR(32)"),
            ("storage_provider", "ALTER TABLE datasets ADD COLUMN storage_provider VARCHAR(32) DEFAULT 'local'"),
        ]
        for name, stmt in sqlite_ops:
            if name not in cols:
                try:
                    exec_sql(stmt)
                    missing_report.append(name)
                except Exception as ex:
                    print(f"SQLite ALTER warning ({name}): {ex}")

        try:
            exec_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_datasets_object_key ON datasets (object_key)"
            )
        except Exception as ex:
            print(f"SQLite unique index note: {ex}")
    else:
        print(f"Unsupported dialect for auto-migrate: {dialect}")
        print("Apply columns manually using docs/OBJECT_STORAGE.md")
        return 2

    print(f"Dialect={dialect} checked OK.")
    if missing_report:
        print("Applied / touched:", ", ".join(missing_report))
    else:
        print("No missing columns detected (object-storage fields already present).")
    _ = DATABASE_URL  # silence lint — confirms env loaded
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
