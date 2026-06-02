"""Route block analytics hints to the configured engine."""
from __future__ import annotations

from typing import Any

import pandas as pd

from analytics_engine import clickhouse_adapter, cube_adapter, duckdb_adapter


def resolve_block_analytics(
    *,
    engine: str | None,
    hints: dict[str, Any],
    df: pd.DataFrame,
    facts: dict[str, Any],
) -> dict[str, Any] | None:
    eng = (engine or hints.get("engine") or hints.get("analytics_engine") or "duckdb").lower()

    if eng == "cube":
        query = hints.get("cube_query")
        if isinstance(query, dict):
            result = cube_adapter.load_query(query)
            if result is not None:
                return result

    if eng == "clickhouse":
        sql = hints.get("clickhouse_sql") or hints.get("sql")
        if isinstance(sql, str) and sql.strip():
            result = clickhouse_adapter.run_query(sql)
            if result is not None:
                return result

    if eng == "duckdb" and isinstance(hints.get("sql"), str) and hints["sql"].strip() and not df.empty:
        return duckdb_adapter.run_sql(df, hints["sql"])

    return None
