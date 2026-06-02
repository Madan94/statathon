"""AnalyticsAgent — deep quantitative reasoning over the dataset.

Supports:
  aggregation    — GROUP BY + statistics (mean, median, std, count, sum)
  correlation    — Pearson + Spearman matrices with significance
  trend          — Linear regression over a time axis
  forecast       — ARIMA (statsmodels) / Prophet fallback
  distribution   — Percentiles, skewness, kurtosis, histogram bins
  comparative    — Segment comparison, rank tables
  cross_section  — Multi-dimensional cross-tabulation
  anomaly        — Outlier impact + phase3 integration
  statistical_test — Chi-square, t-test, ANOVA, Mann-Whitney (auto-select)
  general        — Mixed summary across resolved columns

All methods return AnalyticsResult which is consumed by the Scribe agent
and assembled into RenderedBlocks.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class AnalyticsResult:
    mode: str
    facts: dict[str, Any] = field(default_factory=dict)
    table: dict[str, Any] | None = None      # {columns: [], rows: []}
    chart: dict[str, Any] | None = None      # {chart_type, labels, values, ...}
    metrics: dict[str, Any] | None = None    # {metric: value, ...}
    narrative_hints: str = ""                # pre-computed hints for Scribe
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "facts": self.facts,
            "table": self.table,
            "chart": self.chart,
            "metrics": self.metrics,
            "narrative_hints": self.narrative_hints,
            "error": self.error,
        }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return None


def _numeric_cols(df: pd.DataFrame, candidates: list[str] | None = None) -> list[str]:
    cols = candidates or list(df.columns)
    return [c for c in cols if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]


def _cat_cols(df: pd.DataFrame, candidates: list[str] | None = None) -> list[str]:
    cols = candidates or list(df.columns)
    return [c for c in cols if c in df.columns and not pd.api.types.is_numeric_dtype(df[c])]


def _df_to_table(df: pd.DataFrame, max_rows: int = 200) -> dict[str, Any]:
    df2 = df.head(max_rows).where(pd.notnull(df), None)
    return {
        "columns": [str(c) for c in df2.columns],
        "rows": df2.to_dict(orient="records"),
    }


# ─── Analytics modes ──────────────────────────────────────────────────────────

class AnalyticsAgent:

    # ── Aggregation ──────────────────────────────────────────────────────

    def aggregation(
        self,
        df: pd.DataFrame,
        resolved_columns: list[str],
        query: str,
    ) -> AnalyticsResult:
        if df.empty:
            return AnalyticsResult("aggregation", error="No data")

        q = query.lower()
        num_cols = _numeric_cols(df, resolved_columns)
        cat_cols = _cat_cols(df, resolved_columns)

        # Detect groupby column from query or pick first categorical
        group_col: str | None = None
        for c in cat_cols:
            if c.lower() in q:
                group_col = c
                break
        if group_col is None and cat_cols:
            group_col = cat_cols[0]

        if group_col and num_cols:
            try:
                agg_df = (
                    df.groupby(group_col)[num_cols[:5]]
                    .agg(["mean", "median", "std", "count"])
                    .round(3)
                )
                agg_df.columns = ["_".join(c) for c in agg_df.columns]
                agg_df = agg_df.reset_index()
                table = _df_to_table(agg_df, 50)
                top_col = num_cols[0]
                sorted_df = df.groupby(group_col)[top_col].mean().sort_values(ascending=False)
                chart = {
                    "chart_type": "bar",
                    "title": f"Mean {top_col} by {group_col}",
                    "labels": sorted_df.index.tolist()[:20],
                    "values": [_safe_float(v) for v in sorted_df.values[:20]],
                }
                facts = {
                    "group_by": group_col,
                    "groups_count": int(df[group_col].nunique()),
                    f"mean_{top_col}": _safe_float(df[top_col].mean()),
                }
                hints = (
                    f"Aggregated {', '.join(num_cols[:3])} by {group_col}. "
                    f"{int(df[group_col].nunique())} unique groups. "
                    f"Mean {top_col}: {_safe_float(df[top_col].mean()):.3f}."
                )
                return AnalyticsResult("aggregation", facts=facts, table=table,
                                       chart=chart, narrative_hints=hints)
            except Exception as exc:
                logger.warning("aggregation failed: %s", exc)

        # Fallback: simple summary stats
        stats = df[num_cols[:8]].describe().round(3).to_dict() if num_cols else {}
        return AnalyticsResult(
            "aggregation",
            facts={k: v.get("mean") for k, v in stats.items()},
            table={"columns": ["stat"] + num_cols[:8],
                   "rows": [{"stat": s, **{c: stats.get(c, {}).get(s) for c in num_cols[:8]}}
                             for s in ["mean", "std", "min", "max"]]},
            narrative_hints=f"Summary statistics over {len(num_cols)} numeric columns.",
        )

    # ── Correlation ───────────────────────────────────────────────────────

    def correlation(
        self,
        df: pd.DataFrame,
        resolved_columns: list[str],
        query: str,
    ) -> AnalyticsResult:
        num_cols = _numeric_cols(df, resolved_columns)
        if len(num_cols) < 2:
            return AnalyticsResult("correlation", error="Need ≥2 numeric columns")
        try:
            from scipy.stats import pearsonr, spearmanr  # type: ignore
            sub = df[num_cols[:10]].dropna()
            pearson_mat = sub.corr(method="pearson").round(3)
            spearman_mat = sub.corr(method="spearman").round(3)

            # Top pairs
            pairs: list[dict] = []
            for i, a in enumerate(num_cols[:10]):
                for b in num_cols[i+1:10]:
                    if a in sub.columns and b in sub.columns:
                        r_p, p_p = pearsonr(sub[a], sub[b])
                        r_s, p_s = spearmanr(sub[a], sub[b])
                        pairs.append({
                            "col_a": a, "col_b": b,
                            "pearson_r": round(r_p, 3),
                            "pearson_p": round(p_p, 4),
                            "spearman_r": round(r_s, 3),
                            "spearman_p": round(p_s, 4),
                            "significant": p_p < 0.05,
                        })
            pairs.sort(key=lambda x: abs(x["pearson_r"]), reverse=True)
            top = pairs[:20]

            chart = {
                "chart_type": "bar",
                "title": "Top correlated column pairs (Pearson r)",
                "labels": [f"{p['col_a']} x {p['col_b']}" for p in top[:10]],
                "values": [p["pearson_r"] for p in top[:10]],
            }
            facts = {
                "top_pair": f"{top[0]['col_a']} x {top[0]['col_b']}" if top else "—",
                "top_pearson_r": top[0]["pearson_r"] if top else None,
                "significant_pairs": sum(1 for p in pairs if p["significant"]),
            }
            hints = (
                f"Computed Pearson+Spearman correlations for {len(num_cols)} numeric columns. "
                f"Strongest pair: {facts.get('top_pair', '---')} (r={facts.get('top_pearson_r')}). "
                f"{facts.get('significant_pairs')} statistically significant pairs (p<0.05)."
            )
            return AnalyticsResult(
                "correlation", facts=facts,
                table={"columns": ["col_a","col_b","pearson_r","pearson_p","spearman_r","significant"],
                       "rows": top},
                chart=chart, narrative_hints=hints,
            )
        except ImportError:
            corr = df[num_cols[:8]].corr().round(3)
            table = _df_to_table(corr.reset_index().rename(columns={"index": "column"}))
            return AnalyticsResult("correlation", table=table,
                                   narrative_hints="Pearson correlation matrix.")
        except Exception as exc:
            return AnalyticsResult("correlation", error=str(exc))

    # ── Trend ─────────────────────────────────────────────────────────────

    def trend(
        self,
        df: pd.DataFrame,
        resolved_columns: list[str],
        query: str,
    ) -> AnalyticsResult:
        num_cols = _numeric_cols(df, resolved_columns)
        if not num_cols:
            return AnalyticsResult("trend", error="No numeric columns for trend")

        # Look for a time-like column
        time_col: str | None = None
        for c in df.columns:
            if any(kw in c.lower() for kw in ["year", "month", "date", "time", "period"]):
                time_col = c
                break

        if time_col is None:
            time_col = df.columns[0]

        target_col = num_cols[0]
        try:
            from scipy.stats import linregress  # type: ignore
            sub = df[[time_col, target_col]].dropna().sort_values(time_col)
            x = np.arange(len(sub))
            y = sub[target_col].values.astype(float)
            slope, intercept, r_value, p_value, std_err = linregress(x, y)

            facts = {
                "trend_slope": round(float(slope), 4),
                "trend_r_squared": round(float(r_value ** 2), 4),
                "trend_p_value": round(float(p_value), 4),
                "trend_direction": "increasing" if slope > 0 else "decreasing",
                "trend_column": target_col,
                "time_column": time_col,
            }
            # Group by time column for a cleaner chart (mean per period)
            try:
                grouped = (
                    df.groupby(time_col)[target_col]
                    .mean()
                    .reset_index()
                    .sort_values(time_col)
                )
                chart_labels = grouped[time_col].astype(str).tolist()
                chart_values = [_safe_float(v) for v in grouped[target_col].tolist()]
            except Exception:
                chart_labels = sub[time_col].astype(str).tolist()[-50:]
                chart_values = [_safe_float(v) for v in y[-50:]]
            chart = {
                "chart_type": "line",
                "title": f"{target_col} trend over {time_col}",
                "labels": chart_labels,
                "values": chart_values,
            }
            direction = facts["trend_direction"]
            sig = "statistically significant" if p_value < 0.05 else "not statistically significant"
            hints = (
                f"{target_col} shows a {direction} trend (slope={slope:.4f}, "
                f"R²={r_value**2:.3f}, {sig} at p={p_value:.4f})."
            )
            return AnalyticsResult("trend", facts=facts, chart=chart,
                                   narrative_hints=hints)
        except Exception as exc:
            return AnalyticsResult("trend", error=str(exc))

    # ── Distribution ──────────────────────────────────────────────────────

    def distribution(
        self,
        df: pd.DataFrame,
        resolved_columns: list[str],
        query: str,
    ) -> AnalyticsResult:
        num_cols = _numeric_cols(df, resolved_columns)
        if not num_cols:
            return AnalyticsResult("distribution", error="No numeric columns")
        target = num_cols[0]
        try:
            from scipy.stats import skew, kurtosis  # type: ignore
            col = df[target].dropna()
            percentiles = [5, 10, 25, 50, 75, 90, 95]
            pct_vals = [_safe_float(np.percentile(col, p)) for p in percentiles]
            sk = _safe_float(float(skew(col)))
            ku = _safe_float(float(kurtosis(col)))
            hist_counts, hist_edges = np.histogram(col, bins=20)
            chart = {
                "chart_type": "bar",
                "title": f"Distribution of {target}",
                "labels": [f"{e:.1f}" for e in hist_edges[:-1]],
                "values": hist_counts.tolist(),
            }
            facts = {
                f"mean_{target}": _safe_float(float(col.mean())),
                f"std_{target}": _safe_float(float(col.std())),
                f"skewness_{target}": sk,
                f"kurtosis_{target}": ku,
                f"p50_{target}": _safe_float(float(col.median())),
            }
            table = {
                "columns": ["percentile", "value"],
                "rows": [{"percentile": f"P{p}", "value": v}
                         for p, v in zip(percentiles, pct_vals)],
            }
            hints = (
                f"{target}: mean={facts[f'mean_{target}']:.2f}, "
                f"std={facts[f'std_{target}']:.2f}, "
                f"skew={sk:.2f} ({'right-skewed' if sk and sk>0 else 'left-skewed' if sk else 'symmetric'})."
            )
            return AnalyticsResult("distribution", facts=facts,
                                   table=table, chart=chart, narrative_hints=hints)
        except Exception as exc:
            return AnalyticsResult("distribution", error=str(exc))

    # ── Forecast ──────────────────────────────────────────────────────────

    def forecast(
        self,
        df: pd.DataFrame,
        resolved_columns: list[str],
        query: str,
    ) -> AnalyticsResult:
        num_cols = _numeric_cols(df, resolved_columns)
        if not num_cols:
            return AnalyticsResult("forecast", error="No numeric columns for forecast")
        target = num_cols[0]
        col_data = df[target].dropna().reset_index(drop=True)
        if len(col_data) < 6:
            return AnalyticsResult("forecast", error="Insufficient data for forecast (need ≥6)")

        # Try Prophet first
        try:
            from prophet import Prophet  # type: ignore
            import warnings
            ds_col = None
            for c in df.columns:
                if any(kw in c.lower() for kw in ["year","month","date","time","period"]):
                    ds_col = c
                    break
            if ds_col:
                prophet_df = df[[ds_col, target]].rename(columns={ds_col: "ds", target: "y"}).dropna()
                prophet_df["ds"] = pd.to_datetime(prophet_df["ds"], errors="coerce")
                prophet_df = prophet_df.dropna()
                if len(prophet_df) >= 10:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        m = Prophet(yearly_seasonality=True, weekly_seasonality=False,
                                    daily_seasonality=False)
                        m.fit(prophet_df)
                        future = m.make_future_dataframe(periods=6, freq="Y")
                        forecast_df = m.predict(future)
                    last6 = forecast_df.tail(6)
                    chart = {
                        "chart_type": "line",
                        "title": f"Prophet forecast: {target}",
                        "labels": last6["ds"].dt.strftime("%Y").tolist(),
                        "values": [_safe_float(v) for v in last6["yhat"].tolist()],
                        "lower": [_safe_float(v) for v in last6["yhat_lower"].tolist()],
                        "upper": [_safe_float(v) for v in last6["yhat_upper"].tolist()],
                    }
                    facts = {
                        "forecast_method": "Prophet",
                        "forecast_column": target,
                        f"forecast_6step_mean": _safe_float(float(last6["yhat"].mean())),
                    }
                    return AnalyticsResult("forecast", facts=facts, chart=chart,
                                           narrative_hints=f"Prophet 6-step forecast for {target}.")
        except Exception as exc:
            logger.debug("Prophet forecast: %s", exc)

        # ARIMA fallback via statsmodels
        try:
            from statsmodels.tsa.arima.model import ARIMA  # type: ignore
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = ARIMA(col_data, order=(1, 1, 1))
                result = model.fit()
            forecast_vals = result.forecast(steps=6)
            chart = {
                "chart_type": "line",
                "title": f"ARIMA(1,1,1) forecast: {target}",
                "labels": [f"t+{i+1}" for i in range(6)],
                "values": [_safe_float(v) for v in forecast_vals.tolist()],
            }
            facts = {
                "forecast_method": "ARIMA(1,1,1)",
                "forecast_column": target,
                f"forecast_next": _safe_float(float(forecast_vals.iloc[0])),
            }
            return AnalyticsResult("forecast", facts=facts, chart=chart,
                                   narrative_hints=f"ARIMA forecast for {target}.")
        except Exception as exc:
            logger.debug("ARIMA forecast: %s", exc)

        # Linear extrapolation fallback
        x = np.arange(len(col_data))
        y = col_data.values.astype(float)
        slope = float(np.polyfit(x, y, 1)[0])
        last_val = float(y[-1])
        future_vals = [last_val + slope * (i + 1) for i in range(6)]
        chart = {
            "chart_type": "line",
            "title": f"Linear extrapolation: {target}",
            "labels": [f"t+{i+1}" for i in range(6)],
            "values": [_safe_float(v) for v in future_vals],
        }
        return AnalyticsResult(
            "forecast",
            facts={"forecast_method": "linear_extrapolation", "forecast_column": target},
            chart=chart,
            narrative_hints=f"Linear extrapolation for {target} (slope={slope:.4f}/period).",
        )

    # ── Statistical tests ─────────────────────────────────────────────────

    def statistical_test(
        self,
        df: pd.DataFrame,
        resolved_columns: list[str],
        query: str,
    ) -> AnalyticsResult:
        num_cols = _numeric_cols(df, resolved_columns)
        cat_cols = _cat_cols(df, resolved_columns)
        if not num_cols:
            return AnalyticsResult("statistical_test", error="No numeric columns")

        target = num_cols[0]
        results_rows: list[dict] = []
        facts: dict[str, Any] = {}

        try:
            from scipy import stats  # type: ignore

            # Chi-square for categorical pairs
            if cat_cols:
                for cat in cat_cols[:2]:
                    try:
                        contingency = pd.crosstab(df[cat], df[target].round(0))
                        chi2, p_val, dof, _ = stats.chi2_contingency(contingency)
                        results_rows.append({
                            "test": "Chi-Square",
                            "columns": f"{cat} × {target}",
                            "statistic": round(float(chi2), 4),
                            "p_value": round(float(p_val), 4),
                            "dof": int(dof),
                            "significant": p_val < 0.05,
                        })
                        facts[f"chi2_{cat}"] = round(float(chi2), 4)
                        facts[f"chi2_{cat}_p"] = round(float(p_val), 4)
                    except Exception:
                        pass

            # T-test / ANOVA on first categorical grouping
            if cat_cols:
                cat = cat_cols[0]
                groups = [g.dropna().values for _, g in df.groupby(cat)[target]]
                groups = [g for g in groups if len(g) >= 3]
                if len(groups) == 2:
                    t_stat, p_val = stats.ttest_ind(*groups)
                    results_rows.append({
                        "test": "Independent T-Test",
                        "columns": f"{target} by {cat}",
                        "statistic": round(float(t_stat), 4),
                        "p_value": round(float(p_val), 4),
                        "significant": p_val < 0.05,
                    })
                    facts["t_stat"] = round(float(t_stat), 4)
                    facts["t_p_value"] = round(float(p_val), 4)
                elif len(groups) > 2:
                    f_stat, p_val = stats.f_oneway(*groups)
                    results_rows.append({
                        "test": "One-Way ANOVA",
                        "columns": f"{target} by {cat}",
                        "statistic": round(float(f_stat), 4),
                        "p_value": round(float(p_val), 4),
                        "significant": p_val < 0.05,
                    })
                    facts["f_stat"] = round(float(f_stat), 4)
                    facts["anova_p_value"] = round(float(p_val), 4)

            # Mann-Whitney if 2 groups
            if len(groups := [g.dropna().values
                               for _, g in df.groupby(cat_cols[0] if cat_cols else df.columns[0])[target]
                               if len(g) >= 3]) == 2:
                try:
                    u_stat, p_val = stats.mannwhitneyu(*groups, alternative="two-sided")
                    results_rows.append({
                        "test": "Mann-Whitney U",
                        "columns": target,
                        "statistic": round(float(u_stat), 4),
                        "p_value": round(float(p_val), 4),
                        "significant": p_val < 0.05,
                    })
                except Exception:
                    pass

        except ImportError:
            return AnalyticsResult("statistical_test",
                                   error="scipy not installed; install scipy for stat tests")
        except Exception as exc:
            return AnalyticsResult("statistical_test", error=str(exc))

        sig_count = sum(1 for r in results_rows if r.get("significant"))
        hints = (
            f"Ran {len(results_rows)} statistical tests on {target}. "
            f"{sig_count} significant at p<0.05."
        )
        return AnalyticsResult(
            "statistical_test",
            facts=facts,
            table={"columns": ["test","columns","statistic","p_value","significant"],
                   "rows": results_rows},
            metrics={k: v for k, v in facts.items()},
            narrative_hints=hints,
        )

    # ── Anomaly impact ────────────────────────────────────────────────────

    def anomaly(
        self,
        df: pd.DataFrame,
        resolved_columns: list[str],
        anomaly_candidates: list[dict],
        query: str,
    ) -> AnalyticsResult:
        if anomaly_candidates:
            from_payload = pd.DataFrame(anomaly_candidates[:200])
            facts = {
                "total_anomalies": len(anomaly_candidates),
                "high_severity": sum(1 for a in anomaly_candidates if a.get("severity") == "high"),
                "affected_columns": len({a.get("column") for a in anomaly_candidates if a.get("column")}),
            }
            table = _df_to_table(from_payload[
                [c for c in ["column", "row", "method", "severity", "confidence"]
                 if c in from_payload.columns]
            ], 100)
            chart = None
            col_counts = from_payload.get("column", pd.Series()).value_counts().head(10) \
                if "column" in from_payload.columns else pd.Series()
            if not col_counts.empty:
                chart = {
                    "chart_type": "bar",
                    "title": "Anomalies per column",
                    "labels": col_counts.index.tolist(),
                    "values": col_counts.values.tolist(),
                }
            hints = (
                f"{facts['total_anomalies']} anomalies detected. "
                f"{facts['high_severity']} high-severity. "
                f"Affects {facts['affected_columns']} columns."
            )
            return AnalyticsResult("anomaly", facts=facts, table=table,
                                   chart=chart, narrative_hints=hints)

        # Compute IQR-based anomalies from dataset
        if df.empty:
            return AnalyticsResult("anomaly", error="No data or anomaly candidates")
        num_cols = _numeric_cols(df, resolved_columns)
        rows: list[dict] = []
        for col in num_cols[:6]:
            Q1, Q3 = df[col].quantile(0.25), df[col].quantile(0.75)
            IQR = Q3 - Q1
            lo, hi = Q1 - 1.5 * IQR, Q3 + 1.5 * IQR
            out = df[(df[col] < lo) | (df[col] > hi)][col]
            if len(out):
                rows.append({"column": col, "outlier_count": len(out),
                             "iqr_low": round(float(lo), 3), "iqr_high": round(float(hi), 3)})
        facts = {"computed_anomaly_columns": len(rows)}
        return AnalyticsResult(
            "anomaly",
            facts=facts,
            table={"columns": ["column","outlier_count","iqr_low","iqr_high"], "rows": rows},
            narrative_hints=f"IQR-based anomaly check over {len(num_cols)} numeric columns.",
        )

    # ── General fallback ──────────────────────────────────────────────────

    def general(
        self,
        df: pd.DataFrame,
        resolved_columns: list[str],
    ) -> AnalyticsResult:
        if df.empty:
            return AnalyticsResult("general", error="No data")
        num_cols = _numeric_cols(df, resolved_columns)
        cat_cols = _cat_cols(df, resolved_columns)
        facts: dict[str, Any] = {
            "row_count": len(df),
            "column_count": len(df.columns),
            "numeric_columns": len(num_cols),
            "categorical_columns": len(cat_cols),
            "missing_cells": int(df.isna().sum().sum()),
        }
        rows = []
        for col in num_cols[:10]:
            rows.append({
                "column": col,
                "mean": _safe_float(float(df[col].mean())),
                "std": _safe_float(float(df[col].std())),
                "missing": int(df[col].isna().sum()),
            })
        table = {"columns": ["column","mean","std","missing"], "rows": rows}
        hints = (
            f"Dataset: {facts['row_count']} rows, {facts['column_count']} columns. "
            f"{facts['numeric_columns']} numeric, {facts['categorical_columns']} categorical. "
            f"{facts['missing_cells']} missing cells."
        )
        return AnalyticsResult("general", facts=facts, table=table, narrative_hints=hints)

    # ── Dispatch ──────────────────────────────────────────────────────────

    def _apply_filters(
        self,
        df: pd.DataFrame,
        filter_conditions: dict,
    ) -> pd.DataFrame:
        """Apply filter conditions from the planner.

        filter_conditions is now {actual_column_name: value}, so we can
        apply directly without any hardcoded column-name mapping.
        """
        if df.empty or not filter_conditions:
            return df
        fdf = df.copy()

        for col, val in filter_conditions.items():
            if not val:
                continue
            # Direct column match (new style: col is the actual column name)
            if col in fdf.columns:
                try:
                    mask = fdf[col].astype(str).str.lower() == str(val).lower()
                    if mask.any():
                        fdf = fdf[mask]
                        continue
                except Exception:
                    pass
            # Legacy fallback: col is a semantic key like "state" or "resource_category"
            # Try to find a matching column heuristically
            cat_cols = _cat_cols(fdf)
            best = next(
                (c for c in cat_cols
                 if col.replace("_", "").lower() in c.lower().replace("_", "")),
                None,
            )
            if best:
                try:
                    mask = fdf[best].astype(str).str.lower() == str(val).lower()
                    if mask.any():
                        fdf = fdf[mask]
                except Exception:
                    pass

        return fdf if not fdf.empty else df

    def _pick_groupby(self, df: pd.DataFrame, resolved_columns: list[str], query: str) -> str | None:
        """Choose the best groupby column dynamically from query and available columns."""
        q = query.lower()
        cat_cols = _cat_cols(df, resolved_columns)

        # Prefer column whose name or values match query keywords
        for c in cat_cols:
            if c.lower() in q:
                return c

        # Check if unique values of categorical columns appear in query
        for c in cat_cols:
            try:
                unique_vals = df[c].dropna().unique()
                for v in unique_vals:
                    if str(v).lower() in q:
                        return c
            except Exception:
                pass

        # For comparison queries, prefer lower-cardinality categoricals (more meaningful segments)
        if any(kw in q for kw in ("compare", "versus", "vs", "contrast", "differ")):
            # Pick the categorical column with fewest unique values (best for comparison)
            if cat_cols:
                sorted_by_card = sorted(
                    cat_cols,
                    key=lambda c: df[c].nunique() if c in df.columns else 999,
                )
                return sorted_by_card[0]

        # Prefer columns whose names overlap with query words (most explicit signal)
        # CamelCase-aware matching
        def _col_words_a(col: str) -> set:
            camel = re.sub(r"([a-z])([A-Z])", r"\1 \2",
                           re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", col))
            return set(re.split(r"[\s_\-]+", camel.lower()))

        q_words = set(re.split(r"[\s_\-]+", q))
        for c in cat_cols:
            if _col_words_a(c) & q_words:
                return c

        # Prefer lower-cardinality columns (better groupby candidates)
        if cat_cols:
            return min(
                cat_cols,
                key=lambda c: (df[c].nunique() if c in df.columns else 999),
            )

        return None

    def run(
        self,
        *,
        plan,                                     # ExecutionPlan
        bundle,                                   # RetrievalBundle
    ) -> AnalyticsResult:
        mode = plan.intent
        # Apply any filter conditions (state / resource_category) detected by planner
        filter_conds = getattr(plan, "filter_conditions", {}) or {}
        df = self._apply_filters(bundle.df, filter_conds)
        cols = bundle.resolved_columns
        query = plan.query
        anomalies = bundle.anomaly_candidates

        if mode == "correlation":
            return self.correlation(df, cols, query)
        if mode in ("trend", "temporal"):
            return self.trend(df, cols, query)
        if mode == "distribution":
            # For distribution, use aggregation_smart if it's a categorical query
            # (e.g. "distribution by state" is really an aggregation)
            grp = self._pick_groupby(df, cols, query)
            if grp:
                return self._aggregation_smart(df, cols, query)
            return self.distribution(df, cols, query)
        if mode == "forecast":
            return self.forecast(df, cols, query)
        if mode == "statistical_test":
            return self.statistical_test(df, cols, query)
        if mode == "anomaly":
            return self.anomaly(df, cols, anomalies, query)
        if mode in ("aggregation", "cross_section"):
            return self._aggregation_smart(df, cols, query)
        if mode == "comparative":
            # For comparative queries, use unfiltered df so all groups are visible.
            return self._aggregation_smart(bundle.df, cols, query)
        if mode == "narrative":
            # If df has numeric + categorical columns, produce a cross-section instead of
            # falling back to general stats — narrative queries like "Show X by Y" deserve real data
            num = _numeric_cols(df, cols)
            cat = _cat_cols(df)
            if num and cat:
                return self._aggregation_smart(df, cols, query)
        return self.general(df, cols)

    def _aggregation_smart(
        self,
        df: pd.DataFrame,
        resolved_columns: list[str],
        query: str,
    ) -> AnalyticsResult:
        """Aggregation with smarter groupby selection for energy/resource data."""
        if df.empty:
            return AnalyticsResult("aggregation", error="No data")

        num_cols = _numeric_cols(df, resolved_columns)
        if num_cols:
            # Prioritize columns that:
            # 1. Have non-zero sum (actually contain data)
            # 2. Are mentioned in the query (by column name words)
            q_lower = query.lower()
            q_words = set(re.split(r"[\s_\-]+", q_lower))

            # Temporal/ID columns shouldn't be primary value columns for aggregation
            _temporal_kws = {"year", "month", "date", "quarter", "time",
                              "id", "site", "code", "no", "number", "index"}

            def _col_priority(c: str) -> tuple:
                c_words = set(re.split(r"[\s_\-]+", c.lower()))
                query_match = bool(c_words & q_words)
                is_temporal = bool(c_words & _temporal_kws)
                col_sum = float(df[c].abs().sum()) if c in df.columns else 0.0
                # Temporal/ID cols sorted last; within same tier, sort by data richness
                return (2 if is_temporal else (0 if query_match else 1), -col_sum)

            num_cols = sorted(num_cols, key=_col_priority)
        group_col = self._pick_groupby(df, resolved_columns, query)

        if group_col and group_col in df.columns and num_cols:
            try:
                # Pick the primary value column: highest sum (handles renewable MW vs reserves=0)
                top_col = num_cols[0]
                # For energy data: sum is more meaningful than mean
                agg_df = (
                    df.groupby(group_col)[num_cols[:5]]
                    .agg(["sum", "mean", "count"])
                    .round(2)
                )
                agg_df.columns = ["_".join(c) for c in agg_df.columns]
                agg_df = agg_df.reset_index().sort_values(
                    f"{top_col}_sum", ascending=False
                )
                table = _df_to_table(agg_df, 60)

                sorted_series = df.groupby(group_col)[top_col].sum().sort_values(ascending=False)
                sorted_series = sorted_series[sorted_series > 0]  # filter zero groups
                if sorted_series.empty:
                    # All zero — something wrong with filter; fall back to all data
                    sorted_series = df.groupby(group_col)[top_col].sum().sort_values(ascending=False)
                chart = {
                    "chart_type": "bar",
                    "title": f"Total {top_col} by {group_col}",
                    "labels": sorted_series.index.tolist()[:20],
                    "values": [_safe_float(v) for v in sorted_series.values[:20]],
                    "x_label": group_col,
                    "y_label": top_col,
                }

                top_group = sorted_series.index[0] if len(sorted_series) else "—"
                facts: dict[str, Any] = {
                    "group_by": group_col,
                    "groups_count": int(df[group_col].nunique()),
                    "top_group": str(top_group),
                    f"total_{top_col}": _safe_float(df[top_col].sum()),
                    f"top_{top_col}": _safe_float(sorted_series.iloc[0]) if len(sorted_series) else None,
                }
                # Add per-group totals as facts
                for grp, val in sorted_series.items():
                    safe_key = re.sub(r"[^a-z0-9_]", "_", str(grp).lower())
                    facts[f"{safe_key}_{top_col}"] = _safe_float(val)

                hints = (
                    f"Total {top_col} by {group_col}: {int(df[group_col].nunique())} groups. "
                    f"Highest: {top_group} ({_safe_float(sorted_series.iloc[0]):.1f}). "
                    f"Overall total: {_safe_float(df[top_col].sum()):.1f}."
                )
                return AnalyticsResult("aggregation", facts=facts, table=table,
                                       chart=chart, narrative_hints=hints)
            except Exception as exc:
                logger.warning("smart aggregation failed: %s", exc)

        return self.aggregation(df, resolved_columns, query)
