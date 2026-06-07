#!/usr/bin/env python3
"""
Run database schema migrations outside the API process.

Usage:
  python scripts/migrate_db.py                  # run all migrations
  python scripts/migrate_db.py --status         # inspect only
  python scripts/migrate_db.py --bootstrap    # create missing tables (SQLAlchemy metadata)
  python scripts/migrate_db.py --only checkpoint_jsonb
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"
sys.path.insert(0, str(API))
sys.path.insert(1, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [migrate_db] %(message)s",
)
logger = logging.getLogger("migrate_db")


def _run_bootstrap() -> dict:
    import database.models  # noqa: F401
    from database.database import Base, engine

    logger.info("Bootstrap: create_all (missing tables only)")
    Base.metadata.create_all(bind=engine)
    return {"migration": "bootstrap", "state": "applied"}


def _migration_registry() -> list[tuple[str, callable]]:
    from database.migrate_auth import migrate_auth_schema
    from database.migrate_report_builder import migrate_report_builder_schema
    from database.migrate_dataset_columns import migrate_dataset_columns_schema
    from database.migrate_checkpoint_jsonb import migrate_checkpoint_jsonb
    from database.migrate_review_decisions import migrate_review_decisions_schema

    return [
        ("auth_schema", migrate_auth_schema),
        ("report_builder_schema", migrate_report_builder_schema),
        ("dataset_columns_schema", migrate_dataset_columns_schema),
        ("review_decisions_schema", migrate_review_decisions_schema),
        ("checkpoint_jsonb", migrate_checkpoint_jsonb),
    ]


def _status_only() -> int:
    from database.migrate_checkpoint_jsonb import checkpoint_migration_status

    logger.info("=== Migration status ===")
    cp = checkpoint_migration_status()
    logger.info("checkpoint_jsonb: state=%s details=%s", cp.get("state"), cp)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Statathon database migrations")
    parser.add_argument("--status", action="store_true", help="Print migration status and exit")
    parser.add_argument("--bootstrap", action="store_true", help="Run SQLAlchemy create_all first")
    parser.add_argument("--only", action="append", default=[], help="Run specific migration(s) only")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Batch size for checkpoint JSONB copy (default 200)",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first migration failure",
    )
    args = parser.parse_args()

    if args.status:
        return _status_only()

    results: list[dict] = []

    if args.bootstrap:
        try:
            results.append(_run_bootstrap())
        except Exception as exc:
            logger.exception("Bootstrap failed: %s", exc)
            return 1

    registry = _migration_registry()
    selected = set(args.only) if args.only else None

    for name, fn in registry:
        if selected and name not in selected:
            logger.info("Skipping migration %s (not selected)", name)
            continue
        logger.info("--- Running migration: %s ---", name)
        try:
            if name == "checkpoint_jsonb":
                result = fn(batch_size=args.batch_size)
            elif name == "review_decisions_schema":
                result = fn()
            else:
                fn()
                result = {"migration": name, "state": "applied"}
        except Exception as exc:
            logger.exception("Migration %s failed: %s", name, exc)
            results.append({"migration": name, "state": "failed", "error": str(exc)})
            if args.fail_fast:
                break
            continue

        if isinstance(result, dict):
            results.append(result)
        else:
            results.append({"migration": name, "state": "applied"})

        logger.info("Migration %s finished: %s", name, results[-1].get("state", "applied"))

    logger.info("=== Migration summary ===")
    for row in results:
        logger.info("%s", row)

    failed = [r for r in results if r.get("state") == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
