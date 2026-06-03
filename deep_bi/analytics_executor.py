"""Execute an AnalyticsPlan against a DataFrame.

Every operation produces:
  * a `value` (scalar or DataFrame)
  * a `row_ids` list — exactly which rows contributed
  * a `computation` dict — fully serialisable describing what was done

These flow into the EvidenceLedger so the narrative can cite them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import numpy as np

from .analytics_planner import AnalyticsPlan, AnalyticsStep

logger = logging.getLogger(__name__)


@dataclass
class AnalyticsResult:
    op: str
    value: Any = None                   # scalar, dict, list of dicts, or DataFrame.to_dict
    row_ids: list[int] = field(default_factory=list)
    computation: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, "value": self.value,
                "row_ids": self.row_ids[:200],  # cap to keep JSON sane
                "row_count": len(self.row_ids),
                "computation": self.computation,
                "explanation": self.explanation,
                "notes": self.notes}


@dataclass
class AnalyticsExecution:
    results: list[AnalyticsResult] = field(default_factory=list)
    final_table: dict[str, Any] | None = None
    final_chart: dict[str, Any] | None = None
    final_metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"results": [r.to_dict() for r in self.results],
                "final_table": self.final_table,
                "final_chart": self.final_chart,
                "final_metrics": self.final_metrics}


class AnalyticsExecutor:

    def execute(self, plan: AnalyticsPlan, df: pd.DataFrame
                 ) -> AnalyticsExecution:
        cur = df.copy() if df is not None else pd.DataFrame()
        execution = AnalyticsExecution()
        # Establish an initial row_id pool (positional)
        cur = cur.reset_index(drop=True)
        active_row_ids = list(range(len(cur)))
        last_grouped: pd.DataFrame | None = None
        last_metric: str | None = None

        for step in plan.steps:
            try:
                if step.op == "filter":
                    cur, ids, comp = self._op_filter(cur, step)
                    active_row_ids = ids
                    execution.results.append(AnalyticsResult(
                        op=step.op, value={"rows_remaining": len(cur)},
                        row_ids=ids, computation=comp,
                        explanation=step.explanation))

                elif step.op == "aggregate":
                    gdf, comp = self._op_aggregate(cur, step)
                    last_grouped = gdf
                    last_metric = step.params.get("metric")
                    execution.results.append(AnalyticsResult(
                        op=step.op, value=gdf.to_dict(orient="records"),
                        row_ids=active_row_ids,
                        computation=comp,
                        explanation=step.explanation))

                elif step.op == "rank":
                    gdf = last_grouped if last_grouped is not None else cur
                    rdf, comp = self._op_rank(gdf, step)
                    last_grouped = rdf
                    execution.results.append(AnalyticsResult(
                        op=step.op, value=rdf.head(20).to_dict(orient="records"),
                        row_ids=active_row_ids,
                        computation=comp,
                        explanation=step.explanation))
                    # Promote to final_table for the UI
                    execution.final_table = {
                        "columns": list(rdf.columns),
                        "rows": rdf.head(15).values.tolist(),
                    }
                    if "metric" in step.params and step.params["metric"] in rdf.columns:
                        execution.final_chart = self._chart_from_ranking(
                            rdf, step.params["metric"]
                        )

                elif step.op == "ratio":
                    rdf, comp = self._op_ratio(last_grouped or cur, step)
                    last_grouped = rdf
                    execution.results.append(AnalyticsResult(
                        op=step.op, value=rdf.head(20).to_dict(orient="records"),
                        row_ids=active_row_ids, computation=comp,
                        explanation=step.explanation))

                elif step.op == "trend":
                    val, comp = self._op_trend(cur, step)
                    execution.results.append(AnalyticsResult(
                        op=step.op, value=val, row_ids=active_row_ids,
                        computation=comp, explanation=step.explanation))
                    if isinstance(val, list):
                        execution.final_chart = {
                            "type": "line",
                            "title": f"Trend of {step.params.get('metric')}",
                            "data": val,
                        }

                elif step.op == "corr":
                    val, comp = self._op_corr(cur, step)
                    execution.results.append(AnalyticsResult(
                        op=step.op, value=val, row_ids=active_row_ids,
                        computation=comp, explanation=step.explanation))

                elif step.op == "compare":
                    val, comp = self._op_compare(cur, step)
                    execution.results.append(AnalyticsResult(
                        op=step.op, value=val, row_ids=active_row_ids,
                        computation=comp, explanation=step.explanation))

                elif step.op == "outlier":
                    val, ids, comp = self._op_outlier(cur, step)
                    execution.results.append(AnalyticsResult(
                        op=step.op, value=val, row_ids=ids,
                        computation=comp, explanation=step.explanation))

                elif step.op == "describe":
                    val, comp = self._op_describe(cur, step)
                    execution.results.append(AnalyticsResult(
                        op=step.op, value=val, row_ids=active_row_ids,
                        computation=comp, explanation=step.explanation))
                    if isinstance(val, dict):
                        execution.final_metrics.update({
                            f"{step.params.get('metric','x')}.{k}": v
                            for k, v in val.items()
                        })

                else:
                    execution.results.append(AnalyticsResult(
                        op=step.op, notes=[f"unsupported op {step.op}"]))
            except Exception as exc:
                logger.warning("analytics step %s failed: %s", step.op, exc)
                execution.results.append(AnalyticsResult(
                    op=step.op, notes=[f"failed: {exc}"],
                    explanation=step.explanation))

        return execution

    # ---------------- Operations ----------------

    @staticmethod
    def _op_filter(df: pd.DataFrame, step: AnalyticsStep
                    ) -> tuple[pd.DataFrame, list[int], dict[str, Any]]:
        dim = step.params.get("dimension")
        val = step.params.get("value")
        # Find any column whose name matches the dimension (case-insensitive)
        col = None
        if dim:
            # Prefer exact (case-insensitive); else substring.
            for c in df.columns:
                if str(c).lower() == str(dim).lower():
                    col = c
                    break
            if col is None:
                for c in df.columns:
                    if str(dim).lower() in str(c).lower():
                        col = c
                        break
        if col is None:
            return df, list(df.index), {"filter": "no matching column",
                                          "requested_dimension": dim}
        if val is None:
            return df, list(df.index), {"filter": "no value"}
        # Try numeric exact -> string exact (case-insensitive) -> substring.
        try:
            num_val = float(val)
            mask = pd.to_numeric(df[col], errors="coerce") == num_val
            match_kind = "numeric_exact"
        except Exception:
            mask = df[col].astype(str).str.lower() == str(val).lower()
            match_kind = "string_exact"
        if not bool(mask.any()):
            # Substring fallback (e.g. value="Renewable" should match "Renewable Energy")
            mask = df[col].astype(str).str.lower().str.contains(
                str(val).lower(), na=False, regex=False,
            )
            match_kind = "string_contains"
        filtered = df[mask].copy()
        return filtered, list(filtered.index), {
            "filter_column": col, "filter_value": val,
            "match_kind": match_kind,
            "rows_before": len(df), "rows_after": len(filtered),
        }

    @staticmethod
    def _op_aggregate(df: pd.DataFrame, step: AnalyticsStep
                       ) -> tuple[pd.DataFrame, dict[str, Any]]:
        by = step.params.get("by") or []
        metric = step.params.get("metric")
        fn = step.params.get("fn", "sum")
        if metric is None or metric not in df.columns:
            return pd.DataFrame(), {"error": "metric not in df"}
        if by:
            if isinstance(by, str):
                by = [by]
            by = [b for b in by if b in df.columns]
        s = pd.to_numeric(df[metric], errors="coerce")
        if by:
            grouped = df.assign(**{metric: s}).groupby(by)[metric].agg(fn).reset_index()
        else:
            grouped = pd.DataFrame({metric: [getattr(s, fn)()]})
        return grouped, {"by": by, "metric": metric, "fn": fn,
                          "rows": len(grouped)}

    @staticmethod
    def _op_rank(df: pd.DataFrame, step: AnalyticsStep
                  ) -> tuple[pd.DataFrame, dict[str, Any]]:
        metric = step.params.get("metric")
        order = step.params.get("order", "desc")
        top_k = int(step.params.get("top_k", 10))
        if metric is None or metric not in df.columns:
            return df.copy(), {"error": "metric not in df"}
        s = pd.to_numeric(df[metric], errors="coerce")
        rdf = df.assign(**{metric: s}).sort_values(
            metric, ascending=(order != "desc")
        ).reset_index(drop=True)
        return rdf.head(top_k), {"metric": metric, "order": order,
                                  "top_k": top_k}

    @staticmethod
    def _op_ratio(df: pd.DataFrame, step: AnalyticsStep
                    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        num = step.params.get("numerator")
        den = step.params.get("denominator")
        if not num or not den or num not in df.columns or den not in df.columns:
            return df.copy(), {"error": "numerator/denominator missing"}
        out = df.copy()
        out["ratio"] = pd.to_numeric(out[num], errors="coerce") / \
                       pd.to_numeric(out[den], errors="coerce").replace(0, pd.NA)
        return out, {"numerator": num, "denominator": den}

    @staticmethod
    def _op_trend(df: pd.DataFrame, step: AnalyticsStep
                    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        metric = step.params.get("metric")
        time_col = step.params.get("time_column")
        if not metric or metric not in df.columns:
            return [], {"error": "metric not in df"}
        if time_col and time_col in df.columns:
            tdf = df.assign(_t=pd.to_datetime(df[time_col], errors="coerce"),
                            _m=pd.to_numeric(df[metric], errors="coerce"))
            tdf = tdf.dropna(subset=["_t", "_m"]).sort_values("_t")
            series = tdf.groupby(tdf["_t"].dt.to_period("Y"))["_m"].mean()
        else:
            # No time col — index becomes implicit
            tdf = df.assign(_m=pd.to_numeric(df[metric], errors="coerce")).dropna(subset=["_m"])
            series = tdf["_m"].rolling(window=max(1, len(tdf) // 20)).mean()
        out = [{"label": str(idx), "value": float(v)}
                for idx, v in series.dropna().items()]
        return out, {"metric": metric, "time_column": time_col,
                      "points": len(out)}

    @staticmethod
    def _op_corr(df: pd.DataFrame, step: AnalyticsStep
                   ) -> tuple[dict[str, Any], dict[str, Any]]:
        metrics = [m for m in (step.params.get("metrics") or []) if m in df.columns]
        if len(metrics) < 2:
            return {}, {"error": "need >= 2 metrics"}
        sub = df[metrics].apply(pd.to_numeric, errors="coerce")
        corr = sub.corr()
        return {"matrix": corr.round(4).fillna(0).to_dict()}, {"metrics": metrics}

    @staticmethod
    def _op_compare(df: pd.DataFrame, step: AnalyticsStep
                     ) -> tuple[dict[str, Any], dict[str, Any]]:
        left = step.params.get("left")
        right = step.params.get("right")
        metrics = step.params.get("metrics") or []

        # Strategy A: value-vs-value (e.g. male vs female in a Gender column)
        anchor_col = None
        if left and right:
            for c in df.columns:
                vals = df[c].astype(str).str.lower().unique()
                if str(left).lower() in vals and str(right).lower() in vals:
                    anchor_col = c
                    break
        if anchor_col is not None:
            out: dict[str, Any] = {}
            for m in metrics:
                if m not in df.columns:
                    continue
                s = pd.to_numeric(df[m], errors="coerce")
                lv = float(s[df[anchor_col].astype(str).str.lower()
                              == str(left).lower()].mean())
                rv = float(s[df[anchor_col].astype(str).str.lower()
                              == str(right).lower()].mean())
                out[m] = {"left": lv, "right": rv,
                          "delta": lv - rv,
                          "rel_change_pct": (lv - rv) / rv * 100 if rv else None}
            return out, {"strategy": "value_vs_value", "anchor_column": anchor_col,
                          "left": left, "right": right}

        # Strategy B: column-vs-column (e.g. Proved_Reserves vs Indicated_Reserves
        # where left/right are PREFIXES of column names).
        def _find_col_for_prefix(prefix: str) -> str | None:
            tok = str(prefix or "").lower()
            if not tok:
                return None
            candidates = [c for c in df.columns if tok in str(c).lower()]
            # Prefer numeric, prefer columns whose first underscore-separated
            # token matches the prefix.
            numeric_candidates = [c for c in candidates
                                    if pd.api.types.is_numeric_dtype(
                                        pd.to_numeric(df[c], errors="coerce"))]
            ranked = numeric_candidates or candidates
            ranked.sort(key=lambda c: (0 if str(c).lower().startswith(tok) else 1,
                                         len(str(c))))
            return ranked[0] if ranked else None

        col_l = _find_col_for_prefix(left)
        col_r = _find_col_for_prefix(right)
        if col_l and col_r and col_l != col_r:
            sl = pd.to_numeric(df[col_l], errors="coerce")
            sr = pd.to_numeric(df[col_r], errors="coerce")
            # If the planner identified a group axis, break the comparison
            # down per group; else give the overall numbers.
            metrics_meta = {"left_column": col_l, "right_column": col_r}
            out: dict[str, Any] = {
                "overall": {
                    "left_sum":  float(sl.sum()),
                    "right_sum": float(sr.sum()),
                    "left_mean":  float(sl.mean()) if sl.notna().any() else 0.0,
                    "right_mean": float(sr.mean()) if sr.notna().any() else 0.0,
                    "delta_sum":  float(sl.sum() - sr.sum()),
                },
            }
            # Per-group if metrics contains a categorical (heuristic)
            group_candidate = next(
                (m for m in metrics
                  if m in df.columns and not pd.api.types.is_numeric_dtype(df[m])),
                None,
            )
            if group_candidate:
                gdf = df.assign(_l=sl, _r=sr).groupby(group_candidate)[["_l", "_r"]]\
                       .sum().reset_index()
                gdf["delta"] = gdf["_l"] - gdf["_r"]
                gdf.columns = [group_candidate, col_l, col_r, "delta"]
                out["per_group"] = gdf.round(2).to_dict(orient="records")
                metrics_meta["group_column"] = group_candidate
            return out, {"strategy": "column_vs_column", **metrics_meta,
                          "left": left, "right": right}

        return {"error": "could not resolve comparison"}, {"left": left, "right": right}

    @staticmethod
    def _op_outlier(df: pd.DataFrame, step: AnalyticsStep
                     ) -> tuple[list[int], list[int], dict[str, Any]]:
        metric = step.params.get("metric")
        if metric is None or metric not in df.columns:
            return [], [], {"error": "metric not in df"}
        s = pd.to_numeric(df[metric], errors="coerce").dropna()
        if s.empty:
            return [], [], {"error": "no numeric values"}
        q1, q3 = s.quantile([0.25, 0.75])
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        mask = (s < lo) | (s > hi)
        ids = s[mask].index.tolist()
        return ids, ids, {"metric": metric, "method": "iqr",
                           "lo": float(lo), "hi": float(hi),
                           "outlier_count": len(ids)}

    @staticmethod
    def _op_describe(df: pd.DataFrame, step: AnalyticsStep
                      ) -> tuple[dict[str, Any], dict[str, Any]]:
        metric = step.params.get("metric")
        if metric and metric in df.columns:
            s = pd.to_numeric(df[metric], errors="coerce").dropna()
            if s.empty:
                return {}, {"error": "no numeric values"}
            return {
                "count": int(s.size),
                "mean":  float(s.mean()),
                "std":   float(s.std(ddof=1)) if s.size > 1 else 0.0,
                "min":   float(s.min()),
                "max":   float(s.max()),
                "median":float(s.median()),
            }, {"metric": metric}
        # No metric — summarise all numerics
        nums = df.select_dtypes(include="number")
        return {"row_count": len(df), "numeric_cols": list(nums.columns),
                 "total_cells": int(df.size)}, {}

    @staticmethod
    def _chart_from_ranking(rdf: pd.DataFrame, metric: str) -> dict[str, Any]:
        if metric not in rdf.columns:
            return {}
        # First non-metric column = label
        label_col = next((c for c in rdf.columns if c != metric), None)
        if label_col is None:
            return {}
        return {
            "type": "bar",
            "title": f"Top {metric}",
            "data": [{"label": str(r[label_col]), "value": float(r[metric])}
                     for _, r in rdf.iterrows()
                     if pd.notna(r[metric])][:15],
        }
