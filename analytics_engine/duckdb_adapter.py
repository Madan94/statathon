"""DuckDB over pandas — default analytics path."""
from __future__ import annotations

from typing import Any

import pandas as pd


def run_sql(df: pd.DataFrame, sql: str) -> dict[str, Any]:
    try:
        import duckdb  # type: ignore

        con = duckdb.connect()
        con.register("dataset", df)
        result = con.execute(sql).fetchdf()
        if result.empty:
            return {"columns": list(result.columns), "rows": []}
        rows = result.head(200).to_dict(orient="records")
        return {"columns": list(result.columns), "rows": rows}
    except Exception as exc:
        return {"error": str(exc), "columns": [], "rows": []}
