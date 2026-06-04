"""Fill TableAST via Deep BI execute pipeline only."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .deep_bi_execute import (
    _execute_coord_monthly_all_india,
    _slice_df_for_query,
    execute_bi_query,
    table_from_execution,
)
from .schema import MultiAST, Table

logger = logging.getLogger(__name__)


@dataclass
class TableBindReport:
    tables_attempted: int = 0
    tables_bound: int = 0
    tables_from_deep_bi: int = 0
    warnings: list[str] = field(default_factory=list)


def _apply_table_result(table: Table, tbl: dict, source: str) -> bool:
    cols = list(tbl.get("columns") or [])
    rows = tbl.get("rows") or []
    if not cols or not rows:
        return False
    table.columns = [str(c) for c in cols]
    table.rows = [
        [row[i] if i < len(row) else "" for i in range(len(cols))]
        for row in rows
    ]
    table.metadata = dict(table.metadata or {})
    table.metadata["bindSource"] = source
    return True


def _metrics_from_title(title: str) -> list[str]:
    t = title.lower()
    metrics: list[str] = []
    if "index" in t:
        metrics.append("index_al")
    if "inflation" in t:
        metrics.append("inflation_al")
    return metrics or ["index_al"]


def _merge_on_group(
    df: pd.DataFrame,
    base_query: str,
    metrics: list[str],
    group_col: str,
) -> dict | None:
    if not metrics:
        return None
    primary = metrics[0]
    ex = execute_bi_query(
        f"{base_query} Statewise rank by {primary}.",
        df,
    )
    tbl = table_from_execution(ex)
    if not tbl:
        return None
    cols = [str(c) for c in (tbl.get("columns") or [])]
    rows = tbl.get("rows") or []
    if group_col not in cols:
        return None
    gi = cols.index(group_col)
    mi = cols.index(primary) if primary in cols else 1
    work = _slice_df_for_query(df, base_query)
    merged: list[dict[str, Any]] = []
    for row in rows:
        key = str(row[gi])
        entry: dict[str, Any] = {group_col: key, primary: row[mi] if mi >= 0 else ""}
        sub = work[work[group_col].astype(str) == key] if group_col in work.columns else work
        for metric in metrics[1:]:
            if metric in sub.columns and not sub.empty:
                entry[metric] = round(float(sub[metric].mean()), 2)
            else:
                entry[metric] = ""
        merged.append(entry)
    out_cols = [group_col] + metrics
    return {
        "columns": out_cols,
        "rows": [[m.get(c, "") for c in out_cols] for m in merged],
    }


class CoordTableBinder:
    def bind(self, ast: MultiAST, df: pd.DataFrame) -> tuple[MultiAST, TableBindReport]:
        report = TableBindReport()
        if df.empty:
            report.warnings.append("empty dataset")
            return ast, report

        group_col = next(
            (str(c) for c in df.columns if str(c).lower() in ("state", "states/uts")),
            "state",
        )

        for table in ast.tableAST.tables:
            report.tables_attempted += 1
            q = (table.metadata or {}).get("biQuery") or table.title
            table.rows = []
            table.columns = []
            title_l = (table.title or "").lower()
            try:
                tbl = None
                if "monthly" in title_l or (
                    "all-india" in title_l and "month" in title_l
                ):
                    metrics = _metrics_from_title(table.title)
                    if len(metrics) == 1:
                        ex = _execute_coord_monthly_all_india(df, q)
                        tbl = table_from_execution(ex)
                    else:
                        parts: list[dict] = []
                        for metric in metrics:
                            ex = _execute_coord_monthly_all_india(
                                df, f"{q} rank by {metric}",
                            )
                            part = table_from_execution(ex)
                            if part:
                                parts.append(part)
                        if parts:
                            by_cols = ["month", "year"]
                            merged_m: dict[tuple, dict] = {}
                            for part in parts:
                                cols = [str(c) for c in part["columns"]]
                                metric_col = next(
                                    (c for c in cols if c not in by_cols + ["state"]),
                                    None,
                                )
                                if not metric_col:
                                    continue
                                mi = cols.index(metric_col)
                                for row in part["rows"]:
                                    key = tuple(row[:2])
                                    merged_m.setdefault(
                                        key, {by_cols[0]: row[0], by_cols[1]: row[1]},
                                    )
                                    merged_m[key][metric_col] = row[mi]
                            out_cols = by_cols + metrics
                            tbl = {
                                "columns": out_cols,
                                "rows": [
                                    [m.get(c, "") for c in out_cols]
                                    for m in merged_m.values()
                                ],
                            }
                        else:
                            tbl = None
                elif "highest" in title_l and "lowest" in title_l:
                    metrics = _metrics_from_title(table.title)
                    metric = (
                        "inflation_al"
                        if "inflation" in title_l
                        else metrics[-1]
                    )
                    ex_hi = execute_bi_query(
                        f"{q} Statewise rank by {metric} descending top 5.", df,
                    )
                    ex_lo = execute_bi_query(
                        f"{q} Statewise rank by {metric} ascending top 5.", df,
                    )
                    hi = table_from_execution(ex_hi)
                    lo = table_from_execution(ex_lo)
                    if hi and lo:
                        cols = list(hi.get("columns") or [])
                        hi_rows = hi.get("rows") or []
                        lo_rows = lo.get("rows") or []
                        seen: set[tuple] = set()
                        rows = []
                        for row in hi_rows[:5] + lo_rows[:5]:
                            key = tuple(row)
                            if key not in seen:
                                seen.add(key)
                                rows.append(row)
                        tbl = {"columns": cols, "rows": rows}
                else:
                    metrics = _metrics_from_title(table.title)
                    if len(metrics) == 1:
                        ex = execute_bi_query(
                            f"{q} Statewise rank by {metrics[0]}.", df,
                        )
                        tbl = table_from_execution(ex)
                    else:
                        tbl = _merge_on_group(df, q, metrics, group_col)

                if tbl and _apply_table_result(table, tbl, "deep_bi_execute"):
                    report.tables_bound += 1
                    report.tables_from_deep_bi += 1
                else:
                    report.warnings.append(
                        f"{table.tableId}: Deep BI execute produced no table"
                    )
            except Exception as exc:
                report.warnings.append(f"{table.tableId}: {exc}")

        return ast, report
