"""Run Deep BI intent → plan → execute (shared by tables, figures, paragraphs)."""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from deep_bi.analytics_executor import AnalyticsExecution, AnalyticsExecutor
from deep_bi.analytics_planner import AnalyticsPlan, AnalyticsPlanner, AnalyticsStep
from deep_bi.column_synonym_kg import ColumnSynonymKG
from deep_bi.intent_parser import IntentParser


def _infer_group_metric(df: pd.DataFrame, query: str) -> tuple[str | None, str | None]:
    """Infer grouping + metric columns from schema + query tokens (no fixed answers)."""
    q = query.lower()
    col_lower = {str(c).lower(): str(c) for c in df.columns}
    group = next(
        (col_lower[k] for k in ("state", "states", "states/uts", "region") if k in col_lower),
        None,
    )
    for pat in (
        r"rank by ([a-z_]+)",
        r"lowest ([a-z_]+)",
        r"highest ([a-z_]+)",
    ):
        for m in re.finditer(pat, q):
            key = m.group(1)
            if key in col_lower:
                return group, col_lower[key]
    metric: str | None = None
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        cl = str(c).lower()
        if "inflation" in q and "inflation" in cl:
            metric = str(c)
            break
        if "index" in q and "index" in cl:
            metric = str(c)
            break
    if metric is None:
        nums = [str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        metric = nums[0] if nums else None
    return group, metric


def _augment_plan_with_rank(plan: AnalyticsPlan, df: pd.DataFrame, query: str) -> AnalyticsPlan:
    """Ensure rank/aggregate steps exist when planner only emitted filters."""
    if any(s.op in ("rank", "aggregate") for s in plan.steps):
        return plan
    group, metric = _infer_group_metric(df, query)
    if not metric:
        return plan
    steps = list(plan.steps)
    if group:
        steps.append(AnalyticsStep(
            op="aggregate",
            params={"by": [group], "metric": metric, "fn": "mean"},
            explanation=f"mean {metric} by {group}",
        ))
    steps.append(AnalyticsStep(
        op="rank",
        params={"metric": metric, "order": "desc", "top_k": 15},
        explanation=f"rank by {metric}",
    ))
    plan.steps = steps
    if metric not in plan.target_columns:
        plan.target_columns = [metric]
    if group and group not in plan.group_columns:
        plan.group_columns = [group]
    return plan


def _slice_df_for_query(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Period slice inferred from query tokens + schema (not fixed answers)."""
    work = df
    q = query.lower()
    if "year" in work.columns:
        years = re.findall(r"20\d{2}", query)
        if years:
            work = work[work["year"].astype(str) == years[-1]]
    if "month" in work.columns:
        months = (
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        )
        for m in months:
            if m in q:
                work = work[work["month"].astype(str).str.lower() == m]
                break
    if "all india" in q and "state" in work.columns:
        # Match the national-aggregate row by any common label the dataset may use
        # (All India / India / National / Total) rather than a single hardcoded one.
        _AGG_LABELS = {"all india", "india", "national", "total", "all-india"}
        sl = work["state"].astype(str).str.strip().str.lower()
        mask = sl.isin(_AGG_LABELS)
        if mask.any():
            work = work[mask]
    elif "state" in work.columns and "statewise" in q:
        _AGG_LABELS = {"all india", "india", "national", "total", "all-india"}
        sl = work["state"].astype(str).str.strip().str.lower()
        work = work[~sl.isin(_AGG_LABELS)]
    return work


def _execute_coord_rank(query: str, df: pd.DataFrame) -> AnalyticsExecution:
    """Coordinate-report path: rank plan from schema + query (no spurious intent filters)."""
    work = _slice_df_for_query(df, query)
    if work.empty:
        work = df
    group, metric = _infer_group_metric(work, query)
    q = query.lower()
    if re.search(r"\bascending\b", q) or (
        re.search(r"\blowest\b", q) and not re.search(r"\bhighest\b", q)
    ):
        order = "asc"
    elif re.search(r"\b(descending|highest|top)\b", q):
        order = "desc"
    else:
        order = "desc"
    if not metric:
        columns = [str(c) for c in df.columns]
        numeric = [c for c in columns if pd.api.types.is_numeric_dtype(df[c])]
        intent = IntentParser().parse(query, columns=columns, dataset_archetype="economic")
        kg = ColumnSynonymKG(columns=columns, column_domains={c: "economic" for c in columns})
        plan = AnalyticsPlanner(kg).plan(intent, columns=columns, numeric_columns=numeric)
        plan = _augment_plan_with_rank(plan, df, query)
        plan.steps = [s for s in plan.steps if s.op != "filter"]
        return AnalyticsExecutor().execute(plan, work)

    steps: list[AnalyticsStep] = []
    if group:
        steps.append(AnalyticsStep(
            op="aggregate",
            params={"by": [group], "metric": metric, "fn": "mean"},
            explanation=f"mean {metric} by {group}",
        ))
    steps.append(AnalyticsStep(
        op="rank",
        params={"metric": metric, "order": order, "top_k": 15},
        explanation=f"rank {metric}",
    ))
    plan = AnalyticsPlan(
        steps=steps,
        target_columns=[metric],
        group_columns=[group] if group else [],
        rationale="coord_rank_plan",
    )
    return AnalyticsExecutor().execute(plan, work)


def _execute_coord_monthly_all_india(df: pd.DataFrame, query: str) -> AnalyticsExecution:
    """Monthly All-India series from schema columns (no intent filters)."""
    work = df.copy()
    state_col = next((c for c in work.columns if str(c).lower() == "state"), None)
    if state_col:
        work = work[work[state_col].astype(str).str.lower() == "all india"]
    if work.empty:
        work = _slice_df_for_query(df, query)
    year_col = next((c for c in work.columns if str(c).lower() == "year"), None)
    if year_col is not None:
        cal = work[work[year_col].astype(str).str.match(r"^\d{4}$", na=False)]
        years = re.findall(r"20\d{2}", query)
        if years:
            y = years[-1]
            subset = cal[cal[year_col].astype(str) == y]
            work = subset if len(subset) >= 3 else cal
        else:
            work = cal
        counts = work.groupby(work[year_col].astype(str)).size()
        y = str(counts.idxmax())
        work = work[work[year_col].astype(str) == y]
    _, metric = _infer_group_metric(work, query)
    if not metric:
        metric = "index_al"
    month_col = next((c for c in work.columns if str(c).lower() == "month"), None)
    year_col = next((c for c in work.columns if str(c).lower() == "year"), None)
    by = [c for c in (month_col, year_col) if c]
    steps: list[AnalyticsStep] = []
    if by:
        steps.append(AnalyticsStep(
            op="aggregate",
            params={"by": by, "metric": metric, "fn": "mean"},
            explanation=f"monthly {metric} for All India",
        ))
        steps.append(AnalyticsStep(
            op="rank",
            params={"metric": metric, "order": "desc", "top_k": 24},
            explanation="order months",
        ))
    plan = AnalyticsPlan(steps=steps, target_columns=[metric], group_columns=by)
    ex = AnalyticsExecutor().execute(plan, work)
    return ex


def execute_bi_query(
    query: str,
    df: pd.DataFrame,
    *,
    archetype: str = "economic",
    coord_mode: bool = True,
) -> AnalyticsExecution:
    if coord_mode:
        return _execute_coord_rank(query, df)

    columns = [str(c) for c in df.columns]
    numeric = [c for c in columns if pd.api.types.is_numeric_dtype(df[c])]
    intent = IntentParser().parse(
        query, columns=columns, dataset_archetype=archetype,
    )
    kg = ColumnSynonymKG(
        columns=columns,
        column_domains={c: archetype for c in columns},
    )
    planner = AnalyticsPlanner(kg)
    plan = planner.plan(intent, columns=columns, numeric_columns=numeric)
    plan = _augment_plan_with_rank(plan, df, query)
    return AnalyticsExecutor().execute(plan, df)


def table_from_execution(ex: AnalyticsExecution) -> dict[str, Any] | None:
    ft = ex.final_table
    if ft and ft.get("rows"):
        return ft
    for res in reversed(ex.results):
        val = res.value
        if isinstance(val, list) and val and isinstance(val[0], dict):
            cols = list(val[0].keys())
            rows = [[row.get(c) for c in cols] for row in val[:20]]
            return {"columns": cols, "rows": rows}
    return None


def chart_from_execution(
    ex: AnalyticsExecution,
    *,
    chart_type: str = "bar",
    top_n: int = 10,
    query: str = "",
) -> dict[str, Any] | None:
    if ex.final_chart:
        ch = ex.final_chart
        labels = ch.get("labels") or []
        values = ch.get("values") or []
        if labels and values:
            data = [
                {"label": str(l), "value": float(v or 0)}
                for l, v in zip(labels, values)
            ]
            return {"type": ch.get("type") or chart_type, "data": data[:top_n]}

    for res in reversed(ex.results):
        val = res.value
        if isinstance(val, list) and val and isinstance(val[0], dict):
            rows = val[:top_n]
            keys = list(rows[0].keys())
            label_k = keys[0]
            num_k = next(
                (k for k in keys if isinstance(rows[0].get(k), (int, float))),
                keys[-1],
            )
            data = [
                {"label": str(r[label_k]), "value": float(r[num_k] or 0)}
                for r in rows
            ]
            if len(data) >= 2:
                if chart_type == "pie" or any(
                    w in query.lower() for w in ("share", "distribution", "pie", "band")
                ):
                    total = sum(d["value"] for d in data) or 1.0
                    data = [
                        {"label": d["label"], "value": round(d["value"] / total * 100, 1)}
                        for d in data
                    ]
                    chart_type = "pie"
                return {"type": chart_type, "data": data}
    return None
