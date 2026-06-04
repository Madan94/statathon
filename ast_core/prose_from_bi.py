"""MoSPI prose from Deep BI coordinate execute results (no filter debug text)."""
from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd

from .deep_bi_execute import _execute_coord_rank, _infer_group_metric, _slice_df_for_query


def _humanize_column(name: str) -> str:
    s = str(name).replace("_", " ").strip()
    mapping = {
        "index al": "General Index (AL)",
        "index rl": "General Index (RL)",
        "inflation al": "year-on-year inflation (AL)",
        "inflation rl": "year-on-year inflation (RL)",
    }
    return mapping.get(s.lower(), s)


def _rank_rows_from_execution(ex) -> tuple[str, str, list[dict[str, Any]]]:
    """Return (group_col, metric_col, ranked row dicts) from execution."""
    for res in reversed(ex.results):
        if res.op != "rank":
            continue
        val = res.value
        if not isinstance(val, list) or not val or not isinstance(val[0], dict):
            continue
        keys = list(val[0].keys())
        group_col = keys[0]
        metric_col = next(
            (k for k in keys if k != group_col and isinstance(val[0].get(k), (int, float))),
            keys[-1],
        )
        return group_col, metric_col, val
    for res in reversed(ex.results):
        if res.op != "aggregate":
            continue
        val = res.value
        if isinstance(val, list) and val and isinstance(val[0], dict):
            keys = list(val[0].keys())
            group_col = keys[0]
            metric_col = next(
                (k for k in keys if k != group_col and isinstance(val[0].get(k), (int, float))),
                keys[-1],
            )
            return group_col, metric_col, val
    return "", "", []


def _period_phrase(query: str) -> str:
    q = query.lower()
    years = re.findall(r"20\d{2}", query)
    months = [m for m in (
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ) if m in q]
    parts = []
    if months:
        parts.append(months[0].capitalize())
    if years:
        parts.append(years[-1])
    return " ".join(parts) if parts else "the reference period"


def _prose_from_rank_rows(
    query: str,
    group_col: str,
    metric_col: str,
    rows: list[dict[str, Any]],
) -> str:
    if not rows or not metric_col:
        return ""
    period = _period_phrase(query)
    metric_h = _humanize_column(metric_col)
    q = query.lower()

    if any(w in q for w in ("highest", "lowest", "top", "bottom", "lead", "rank")):
        lead = rows[0]
        g0 = str(lead.get(group_col, ""))
        v0 = lead.get(metric_col)
        parts = [
            f"During {period}, {g0} recorded the highest {metric_h} "
            f"at {float(v0):.2f} among reporting regions."
        ]
        if len(rows) > 1:
            g1, v1 = str(rows[1].get(group_col, "")), rows[1].get(metric_col)
            parts.append(
                f" This was followed by {g1} ({float(v1):.2f})"
                + (f" and {str(rows[2].get(group_col, ''))} ({float(rows[2].get(metric_col)):.2f})."
                   if len(rows) > 2 else ".")
            )
        return " ".join(parts)

    if any(w in q for w in ("overview", "introduction", "explain", "describe", "framework")):
        return _prose_snapshot(query, rows, group_col, metric_col)

    # Default: top regions + spread
    top, bottom = rows[0], rows[-1] if len(rows) > 1 else rows[0]
    return (
        f"For {period}, regional {metric_h} ranged from "
        f"{float(bottom.get(metric_col)):.2f} in {bottom.get(group_col)} to "
        f"{float(top.get(metric_col)):.2f} in {top.get(group_col)}, "
        f"indicating considerable geographic variation in price movements."
    )


def _prose_snapshot(
    query: str,
    rows: list[dict[str, Any]],
    group_col: str,
    metric_col: str,
) -> str:
    period = _period_phrase(query)
    metric_h = _humanize_column(metric_col)
    vals = [float(r[metric_col]) for r in rows if metric_col in r]
    if not vals:
        return ""
    return (
        f"During {period}, {metric_h} across regions averaged "
        f"{sum(vals)/len(vals):.2f}, with the highest reading of "
        f"{max(vals):.2f} and the lowest of {min(vals):.2f}."
    )


def _prose_all_india_from_df(df: pd.DataFrame, query: str) -> str:
    work = _slice_df_for_query(df, query)
    if work.empty:
        return ""
    period = _period_phrase(query)
    group_col = next((c for c in work.columns if str(c).lower() == "state"), None)
    if group_col:
        ai = work[work[group_col].astype(str).str.lower() == "all india"]
        if not ai.empty:
            row = ai.iloc[0]
            bits = []
            for c in work.columns:
                if not pd.api.types.is_numeric_dtype(work[c]):
                    continue
                if str(c).lower() in ("index_al", "inflation_al", "index_rl", "inflation_rl"):
                    bits.append(f"{_humanize_column(c)} was {float(row[c]):.2f}")
            if bits:
                return f"As of {period}, all-India " + ", ".join(bits[:3]) + "."
    return ""


def prose_for_query(
    query: str,
    df: pd.DataFrame,
    *,
    gemini_narrate: Any | None = None,
) -> str:
    """Build one report paragraph from coordinate Deep BI (no ResponseBuilder filters)."""
    q = query.lower()
    if any(w in q for w in ("all india", "all-india", "national")) and "statewise" not in q:
        snap = _prose_all_india_from_df(df, query)
        if snap:
            return snap

    _, metric = _infer_group_metric(df, query)
    rank_q = f"{query} statewise rank by {metric or 'index_al'}."
    ex = _execute_coord_rank(rank_q, df)
    group_col, metric_col, rows = _rank_rows_from_execution(ex)

    if gemini_narrate and rows:
        payload = {
            "period": _period_phrase(query),
            "metric": _humanize_column(metric_col),
            "group_dimension": group_col,
            "top_regions": rows[:5],
        }
        text = gemini_narrate(query, payload)
        if text and "filtered rows" not in text.lower():
            return text.strip()

    text = _prose_from_rank_rows(query, group_col, metric_col, rows)
    if text and "filtered rows" not in text.lower():
        return text

    return _prose_all_india_from_df(df, query)
