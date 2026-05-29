#!/usr/bin/env python3
"""Add normalization columns to dataset_columns + audit table (Neon Postgres / SQLite)."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_API = _REPO / "api"
for p in (str(_REPO), str(_API)):
    if p not in sys.path:
        sys.path.insert(0, p)


def main() -> int:
    from database.migrate_dataset_columns import migrate_dataset_columns_schema

    migrate_dataset_columns_schema()
    print("Dataset columns normalization migration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
