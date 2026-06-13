"""End-to-end orchestrator — Phases 0-6 for a single report job.

Phase 0  — Template AST (template_engine)
Phase 1  — KG export (knowledge_graph)
Phase 2  — Memory init (STM/LTM)
Phase 3  — Arrow kernel + facts collection (kernel, report_semantics)
Phase 4/5 — Scribe → Verifier → Consensus (agents / firewall)
Phase 6  — PDF export (exporter)

New in v2:
  • report_semantics.DatasetSummary drives facts collection
  • report_semantics.ReportPlan can override template block order
  • agents.ConsensusEngine replaces single-pass scribe
  • template_engine.compile_template replaces blueprint.compile_template
  • exporter now produces government-grade MoSPI PDF
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from sqlalchemy.orm import Session

from report_builder import knowledge_graph as kg
from report_builder import kernel as kx
from report_builder import firewall as fw
from report_builder.agui import BlockCanvas, RenderedBlock
from report_builder.exporter import export_pdf
from analytics_engine.snapshot import write_parquet_snapshot
from analytics_engine.router import resolve_block_analytics
from report_builder.filter_engine import DataFilterSpec, apply_filters
from report_builder.memory import STM, ReflectionLedger

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Template loading (template_engine preferred; fallback to blueprint)
# ---------------------------------------------------------------------------

def _load_template(template_ast: dict[str, Any] | None):
    """Returns a TemplateAST-compatible object.

    Priority:
      1. Deep blueprint (TemplateBlueprintAST) → convert via shim
      2. template_engine serializer (legacy TemplateAST)
      3. blueprint.template_from_ast_json fallback
      4. DEFAULT_MOSPI_TEMPLATE
    """
    if template_ast:
        # Try deep blueprint format first (has 'topics' key)
        if "topics" in template_ast and "templateId" in template_ast:
            try:
                from ast_core.schema import TemplateBlueprintAST
                from report_builder.blueprint import template_from_deep_blueprint
                deep = TemplateBlueprintAST.from_dict(template_ast)
                return template_from_deep_blueprint(deep)
            except Exception as exc:
                logger.warning("Deep blueprint load failed: %s; trying legacy", exc)

        try:
            from template_engine.ast.template_serializer import deserialize_template
            return deserialize_template(template_ast)
        except Exception as exc:
            logger.warning("template_engine deserialize failed: %s; falling back", exc)

    # blueprint fallback (backward-compat)
    from report_builder import blueprint as bp
    if template_ast:
        return bp.template_from_ast_json(template_ast)
    return bp.DEFAULT_MOSPI_TEMPLATE


# ---------------------------------------------------------------------------
# Facts collection (enhanced via report_semantics)
# ---------------------------------------------------------------------------

def _collect_facts(
    analysis_payload: dict[str, Any],
    df: pd.DataFrame,
) -> dict[str, Any]:
    """Build the canonical facts dict for Scribe + Verifier."""
    try:
        from report_semantics.summarizer.dataset_summarizer import compute_dataset_summary
        from report_semantics.metric_detector.detector import detect_key_metrics

        summary = compute_dataset_summary(analysis_payload, df if not df.empty else None)
        facts = detect_key_metrics(summary, analysis_payload, df if not df.empty else None)
        facts["_summary"] = summary.to_dict()
    except Exception as exc:
        logger.warning("report_semantics facts failed: %s; using legacy", exc)
        facts = _collect_facts_legacy(analysis_payload, df)

    # Post-process: inject energy-specific facts from the actual DataFrame
    _RESERVE_COLS = ["Proved_Reserves", "Indicated_Reserves", "Inferred_Reserves",
                     "Total_Reserves", "Potential_Capacity_MW"]
    if df is not None and not df.empty and any(c in df.columns for c in _RESERVE_COLS):
        facts["dataset_type"] = "energy"
        for col in _RESERVE_COLS:
            if col in df.columns:
                try:
                    facts[f"total_{col}"] = round(float(df[col].sum()), 2)
                    facts[f"mean_{col}"] = round(float(df[col].mean()), 2)
                    facts[f"max_{col}"] = round(float(df[col].max()), 2)
                except Exception:
                    pass
        if "State" in df.columns:
            facts["state_count"] = int(df["State"].nunique())
            try:
                if "Total_Reserves" in df.columns:
                    top_state = df.groupby("State")["Total_Reserves"].sum().idxmax()
                    facts["top_state_by_reserves"] = str(top_state)
                    facts["top_state_total_reserves"] = round(
                        float(df[df["State"] == top_state]["Total_Reserves"].sum()), 2
                    )
            except Exception:
                pass
        if "Resource_Category" in df.columns:
            facts["resource_categories"] = df["Resource_Category"].unique().tolist()
            try:
                if "Total_Reserves" in df.columns:
                    by_resource = df.groupby("Resource_Category")["Total_Reserves"].sum().round(2).to_dict()
                    for k, v in by_resource.items():
                        safe_key = k.lower().replace(" ", "_").replace("-", "_")
                        facts[f"reserves_{safe_key}"] = v
                        # Store unit per resource dynamically from dataset
                        if "Unit_of_Measure" in df.columns:
                            sub_units = df[df["Resource_Category"] == k]["Unit_of_Measure"].dropna().unique()
                            if len(sub_units) == 1:
                                raw = str(sub_units[0])
                                if "billion" in raw.lower():
                                    facts[f"unit_{safe_key}"] = "Billion Tonnes"
                                elif "megawatt" in raw.lower() or "mw" in raw.lower():
                                    facts[f"unit_{safe_key}"] = "MW"
                                elif "million" in raw.lower():
                                    facts[f"unit_{safe_key}"] = "Million Tonnes"
                                else:
                                    facts[f"unit_{safe_key}"] = raw
            except Exception:
                pass

    return facts


def _collect_facts_legacy(
    payload: dict[str, Any], df: pd.DataFrame
) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    health = (
        payload.get("health")
        or (payload.get("profiling_summary") or {}).get("health")
        or {}
    )
    if isinstance(health, dict):
        for k in ("row_count", "column_count", "missing_pct", "duplicate_rows"):
            if k in health:
                facts[k] = health[k]
    if df is not None and not df.empty:
        facts.setdefault("row_count", int(len(df)))
        facts.setdefault("column_count", int(len(df.columns)))
        total = float(df.size) or 1.0
        facts.setdefault("missing_pct", float(df.isna().sum().sum()) / total * 100.0)
    phase3 = payload.get("phase3") or {}
    if isinstance(phase3, dict):
        anomalies = phase3.get("anomaly_candidates") or []
        if isinstance(anomalies, list):
            facts["anomaly_count"] = len(anomalies)
        imputations = phase3.get("imputation_candidates") or []
        if isinstance(imputations, list):
            facts["imputation_count"] = len(imputations)
    ctx = payload.get("dataset_context") or {}
    if isinstance(ctx, dict) and ctx.get("dataset_type"):
        facts["dataset_type"] = ctx["dataset_type"]
    mapping = payload.get("semantic_mapping") or []
    if isinstance(mapping, list):
        facts["mapped_column_count"] = sum(
            1 for r in mapping if isinstance(r, dict) and r.get("domain")
        )
    # Dynamic aggregate facts — works for ANY dataset
    if df is not None and not df.empty:
        # 1. Numeric column aggregates (top 10 by data richness)
        num_cols_sorted = sorted(
            df.select_dtypes(include="number").columns,
            key=lambda c: -float(df[c].abs().sum()),
        )
        for col in num_cols_sorted[:10]:
            try:
                facts[f"total_{col}"] = round(float(df[col].sum()), 2)
                facts[f"mean_{col}"] = round(float(df[col].mean()), 2)
                facts[f"max_{col}"] = round(float(df[col].max()), 2)
            except Exception:
                pass

        # 2. Categorical group stats (group by best cat col, sum best num col)
        cat_cols_sorted = sorted(
            df.select_dtypes(include=["object", "string", "category"]).columns,
            key=lambda c: df[c].nunique(),
        )
        if cat_cols_sorted and num_cols_sorted:
            best_cat = cat_cols_sorted[0]
            best_num = num_cols_sorted[0]
            try:
                by_cat = df.groupby(best_cat)[best_num].sum().sort_values(ascending=False)
                facts["top_group_col"] = best_cat
                facts["top_group_val_col"] = best_num
                facts["group_count"] = int(by_cat.shape[0])
                if len(by_cat):
                    facts["top_group"] = str(by_cat.index[0])
                    facts["top_group_value"] = round(float(by_cat.iloc[0]), 2)
                    facts["top_state"] = facts["top_group"]      # compat alias
                    facts["state_count"] = facts["group_count"]  # compat alias
            except Exception:
                pass

        # 3. Category column → unique values (for legacy "resource_categories" key)
        for col in cat_cols_sorted:
            n = df[col].nunique()
            if 2 <= n <= 20:
                facts[f"{col}_categories"] = df[col].dropna().unique().tolist()
                # legacy alias
                if col.lower() in ("resource_category", "category", "type"):
                    facts["resource_categories"] = facts[f"{col}_categories"]
                # group totals if numeric present
                if num_cols_sorted:
                    try:
                        primary_num = num_cols_sorted[0]
                        by_grp = df.groupby(col)[primary_num].sum().round(2).to_dict()
                        for k, v in by_grp.items():
                            safe_key = str(k).lower().replace(" ", "_").replace("-", "_")
                            facts[f"reserves_{safe_key}"] = v
                        # Units (generic)
                        unit_label = _get_unit_label(df, primary_num)
                        if unit_label:
                            for k in by_grp:
                                safe_key = str(k).lower().replace(" ", "_").replace("-", "_")
                                facts[f"unit_{safe_key}"] = unit_label
                    except Exception:
                        pass

    return facts


# ---------------------------------------------------------------------------
# Block payload renderers — fully generic, works for any dataset
# ---------------------------------------------------------------------------

def _has_numeric_data(df: pd.DataFrame) -> bool:
    """True if df has at least one numeric column with non-zero data."""
    for c in df.select_dtypes(include="number").columns:
        if float(df[c].abs().sum()) > 0:
            return True
    return False


def _get_numeric_cols(df: pd.DataFrame, hints: dict | None = None) -> list[str]:
    """Return numeric columns relevant to the current block, ordered by data richness."""
    num_cols = list(df.select_dtypes(include="number").columns)
    hint_col = (hints or {}).get("value_column")
    if hint_col and hint_col in num_cols:
        num_cols = [hint_col] + [c for c in num_cols if c != hint_col]
    # Order remaining by abs sum (most data first)
    num_cols.sort(key=lambda c: -float(df[c].abs().sum()) if c in df.columns else 0)
    return num_cols


def _get_group_col(df: pd.DataFrame, hints: dict | None = None) -> str | None:
    """Return the best categorical column for group-by, driven by hints first."""
    h = hints or {}
    hint_gc = h.get("group_by")
    if hint_gc and hint_gc in df.columns:
        return hint_gc
    cat_cols = list(df.select_dtypes(include=["object", "string", "category"]).columns)
    if not cat_cols:
        return None
    # Prefer lower-cardinality columns (cleaner groups)
    return min(cat_cols, key=lambda c: df[c].nunique())


def _get_best_value_col(df: pd.DataFrame, hints: dict | None = None) -> str | None:
    """Pick best numeric column — hints override, then most data."""
    num_cols = _get_numeric_cols(df, hints)
    return num_cols[0] if num_cols else None


def _smart_filter(df: pd.DataFrame, hints: dict) -> "tuple[pd.DataFrame, bool]":
    """Apply filter from hints to df.

    Returns (filtered_df, filter_matched).
    If the filter value is not found, returns (empty_df, False).
    Reads hints:
    - resource_category  → find a categorical column containing that value
    - filter_column + filter_value → direct column filter
    """
    filter_val = hints.get("resource_category") or hints.get("filter_value")
    filter_col = hints.get("filter_column")

    if not filter_val:
        return df, True

    # Direct column hint
    if filter_col and filter_col in df.columns:
        try:
            mask = df[filter_col].astype(str).str.lower() == str(filter_val).lower()
            if mask.any():
                return df[mask], True
        except Exception:
            pass

    # Scan all categorical columns for the value
    for col in df.select_dtypes(include=["object", "string", "category"]).columns:
        try:
            mask = df[col].astype(str).str.lower() == str(filter_val).lower()
            if mask.any():
                return df[mask], True
        except Exception:
            pass

    # Value not found in dataset
    return pd.DataFrame(columns=df.columns), False


def _get_unit_label(df: pd.DataFrame, val_col: str | None) -> str:
    """Detect unit from a 'unit' or 'Unit_of_Measure' column dynamically."""
    for unit_col in ("unit", "Unit_of_Measure", "units", "measurement_unit"):
        if unit_col in df.columns:
            vals = df[unit_col].dropna().unique()
            if len(vals) == 1:
                raw = str(vals[0])
                # Normalize common unit strings
                rl = raw.lower()
                if "billion" in rl:
                    return "Billion Tonnes"
                if "megawatt" in rl or " mw" in rl:
                    return "MW"
                if "million" in rl:
                    return "Million Tonnes"
                if "percent" in rl or "%" in raw:
                    return "%"
                if "index" in rl:
                    return "Index"
                return raw
    return ""


def _compute_energy_section_facts(df: pd.DataFrame, resource_category: str | None = None) -> dict:
    """Compute section-level analytical facts for any dataset/filter.

    Works for any dataset — detects numeric/group columns dynamically.
    `resource_category` is treated as a generic filter value.
    """
    facts: dict = {}
    if df.empty:
        return facts

    hints = {"resource_category": resource_category} if resource_category else {}
    sub, matched = _smart_filter(df, hints)
    if not matched or sub.empty:
        facts["resource_not_in_dataset"] = True
        facts["resource_category"] = resource_category
        return facts

    # Best value column
    val_col = _get_best_value_col(sub, hints)
    num_cols = _get_numeric_cols(sub, hints)

    # Per-column totals for all numeric cols
    for col in num_cols[:10]:
        try:
            facts[f"total_{col}"] = round(float(sub[col].sum()), 2)
        except Exception:
            pass

    if val_col and val_col in sub.columns:
        total = float(sub[val_col].sum())
        facts["grand_total_reserves"] = round(total, 2)
        facts["value_column"] = val_col
        facts["value_unit"] = _get_unit_label(sub, val_col) or "units"

        # % breakdown of sibling numeric cols vs the primary val_col
        if total > 0:
            for col in num_cols:
                if col == val_col:
                    continue
                try:
                    col_total = float(sub[col].sum())
                    if col_total > 0:
                        pct = round(col_total / total * 100, 1)
                        safe = col.lower().replace(" ", "_")
                        facts[f"{safe}_pct"] = pct
                        # also named labels for proved/indicated/inferred pattern
                        label = col.replace("_Reserves", "").replace("_reserves", "").lower()
                        if label != col.lower():
                            facts[f"{label}_pct"] = pct
                except Exception:
                    pass

        # Group-by the best categorical column
        group_col = _get_group_col(sub, hints)
        if group_col and group_col in sub.columns and total > 0:
            by_group = (
                sub.groupby(group_col)[val_col].sum()
                .sort_values(ascending=False)
            )
            by_group = by_group[by_group > 0]
            facts["group_col"] = group_col
            facts["group_count"] = int(by_group.shape[0])
            if len(by_group):
                facts["top_group"] = str(by_group.index[0])
                facts["top_group_value"] = round(float(by_group.iloc[0]), 2)
                facts["top_group_pct"] = round(float(by_group.iloc[0]) / total * 100, 1)
                # backward-compat aliases
                facts["top_state"] = facts["top_group"]
                facts["top_state_reserves"] = facts["top_group_value"]
                facts["top_state_pct"] = facts["top_group_pct"]
                facts["state_count"] = facts["group_count"]
                for n in (3, 5):
                    top_n = by_group.head(n)
                    if len(top_n) >= n:
                        facts[f"top{n}_states"] = top_n.index.tolist()
                        facts[f"top{n}_reserves"] = round(float(top_n.sum()), 2)
                        facts[f"top{n}_pct"] = round(float(top_n.sum()) / total * 100, 1)
                        facts[f"top{n}_detail"] = {s: round(float(v), 2) for s, v in top_n.items()}

    if resource_category:
        facts["resource_category"] = resource_category

    return facts


def _render_data_table(df: pd.DataFrame, hints: dict, title: str) -> dict | None:
    """Generic table renderer — works for ANY dataset.

    Uses hints to determine:
    - resource_category / filter_value → which rows to include
    - group_by → how to aggregate
    - value_column → primary value col
    - show_pct → add distribution % column
    - topStates / top_n → limit rows
    """
    try:
        sub, matched = _smart_filter(df, hints)
        if not matched or sub.empty:
            filter_val = hints.get("resource_category") or hints.get("filter_value", "")
            return {"columns": ["Note"],
                    "rows": [{"Note": f"{filter_val} not found in this dataset"}]}

        num_cols = _get_numeric_cols(sub, hints)
        group_col = _get_group_col(sub, hints)

        if not group_col or not num_cols:
            return None

        val_col = num_cols[0]
        display_cols = num_cols[:5]  # up to 5 numeric cols

        agg = sub.groupby(group_col)[display_cols].sum().round(2).reset_index()
        agg = agg.sort_values(val_col, ascending=False)
        agg = agg[agg[val_col] > 0]  # filter zero-value rows

        top_states = hints.get("topStates") or hints.get("top_n")
        if top_states and isinstance(top_states, list):
            filtered = agg[agg[group_col].isin(top_states)]
            if not filtered.empty:
                agg = filtered

        rows = agg.where(pd.notnull(agg), None).to_dict(orient="records")
        grand_total = float(agg[val_col].sum()) if val_col in agg.columns else 0.0

        if hints.get("show_pct", True) and grand_total > 0:
            for row in rows:
                rv = row.get(val_col) or 0
                row["Distribution_Pct"] = round(float(rv) / grand_total * 100, 2)
            result_cols = [group_col] + display_cols + ["Distribution_Pct"]
        else:
            result_cols = [group_col] + display_cols

        return {"columns": result_cols, "rows": rows}
    except Exception:
        return None


# Keep alias for backward compatibility with older energy AST templates
_render_energy_table = _render_data_table


def _render_data_chart(df: pd.DataFrame, hints: dict, title: str) -> dict | None:
    """Generic chart renderer — works for ANY dataset.

    For pie charts: shows % breakdown of sibling numeric columns vs total.
    For bar charts: shows grouped totals by best categorical column.
    """
    try:
        sub, matched = _smart_filter(df, hints)
        if not matched or sub.empty:
            filter_val = hints.get("resource_category") or hints.get("filter_value", "")
            return {"chart_type": "bar", "title": title, "labels": [], "values": [],
                    "subtitle": f"{filter_val} not found in this dataset"}

        chart_type = hints.get("chart_type", "bar")
        chart_group = hints.get("chart_group", "auto")
        show_pct = hints.get("show_pct", True)
        num_cols = _get_numeric_cols(sub, hints)
        val_col = num_cols[0] if num_cols else None
        group_col = _get_group_col(sub, hints)

        if not val_col:
            return None

        # Pie chart — break down multiple numeric columns as slices
        if chart_type == "pie" or chart_group == "reserve_type":
            # Show % of each numeric column vs their combined total
            totals: dict[str, float] = {}
            for col in num_cols[:6]:
                if col == val_col:
                    continue
                col_total = float(sub[col].sum())
                if col_total > 0:
                    totals[col] = col_total
            # If sibling cols exist, show breakdown; else fall back to group-by pie
            if totals:
                grand = sum(totals.values()) or 1.0
                # Use short label (strip common suffixes like _Reserves, _al, _rl)
                def _short_label(c: str) -> str:
                    for sfx in ("_Reserves", "_reserves", "_al", "_rl", "_MW"):
                        c = c.replace(sfx, "")
                    return c.replace("_", " ").title()
                labels = [_short_label(c) for c in totals]
                values = [round(v / grand * 100, 1) for v in totals.values()]
                grand_total = round(sum(totals.values()), 2)
                return {
                    "chart_type": "pie",
                    "title": title,
                    "labels": labels,
                    "values": values,
                    "value_suffix": "%",
                    "subtitle": f"Total = {grand_total:,.0f}",
                    "filter": hints.get("resource_category"),
                }

        # Bar chart — group by categorical column, sum value column
        if not group_col:
            return None
        series = sub.groupby(group_col)[val_col].sum().sort_values(ascending=False)
        series = series[series > 0]
        grand = float(series.sum()) or 1.0

        if show_pct and grand > 0:
            pct_labels = [f"{s} ({round(v/grand*100,1)}%)" for s, v in series.head(25).items()]
        else:
            pct_labels = series.head(25).index.tolist()

        return {
            "chart_type": "bar",
            "title": title,
            "labels": pct_labels,
            "values": [round(float(v), 2) for v in series.head(25).values],
            "x_label": group_col,
            "y_label": val_col,
        }
    except Exception:
        return None


# Keep alias for backward compatibility
_render_energy_chart = _render_data_chart


def _render_block_payload(
    block,
    analysis_payload: dict[str, Any],
    facts: dict[str, Any],
    df: pd.DataFrame,
    kg_result,
    ledger: ReflectionLedger,
) -> dict[str, Any]:
    kind = block.kind
    hints = block.hints or {}
    title = block.title
    dataset_type = str(facts.get("dataset_type") or "unknown")

    if kind == "narrative":
        reflections = ledger.retrieve_similar(block.block_id, title)
        enriched_hints = dict(hints)
        # Enrich narrative hints with dynamic section-level analytics
        if not df.empty and _has_numeric_data(df):
            resource_cat = hints.get("resource_category") or hints.get("filter_value")
            sec_facts = _compute_energy_section_facts(df, resource_cat)
            enriched_hints["_energy_section_facts"] = sec_facts

            val_col = sec_facts.get("value_column") or _get_best_value_col(df)
            unit = sec_facts.get("value_unit") or hints.get("unit") or _get_unit_label(df, val_col) or ""

            parts: list[str] = []
            total = sec_facts.get("grand_total_reserves")
            if total:
                unit_str = f" {unit}" if unit else ""
                parts.append(f"Total: {total:,.0f}{unit_str}")
            # % breakdowns for sibling numeric cols
            for key, val in sec_facts.items():
                if key.endswith("_pct") and val is not None:
                    label = key.replace("_pct", "").replace("_", " ").title()
                    parts.append(f"{label}: {val}% of total")
            if sec_facts.get("top3_states"):
                top3 = sec_facts["top3_states"]
                top3_pct = sec_facts.get("top3_pct", "")
                parts.append(f"Top 3 groups ({', '.join(top3)}) account for {top3_pct}% of total")
            if sec_facts.get("top_state"):
                parts.append(
                    f"Leading group: {sec_facts['top_state']} "
                    f"({sec_facts.get('top_state_pct', '')}% of total)"
                )
            if sec_facts.get("group_count"):
                parts.append(f"Covers {sec_facts['group_count']} groups/regions")

            # All-category summary when no specific filter
            if not resource_cat:
                for cat in (facts.get("resource_categories") or []):
                    safe = cat.lower().replace(" ", "_").replace("-", "_")
                    val = facts.get(f"reserves_{safe}")
                    if val:
                        parts.append(f"{cat}: {val:,.0f}")

            if parts:
                enriched_hints["analytics_context"] = "; ".join(parts)
        text = fw.scribe_narrative(
            block_id=block.block_id,
            block_title=title,
            block_section=block.section,
            hints=enriched_hints,
            facts=facts,
            reflections=reflections,
            dataset_type=dataset_type,
        )
        return {"text": text}

    analytics_payload = resolve_block_analytics(
        engine=hints.get("engine"),
        hints=hints,
        df=df,
        facts=facts,
    )
    if analytics_payload and kind in ("table", "chart", "metric"):
        if kind == "table" and analytics_payload.get("rows") is not None:
            return analytics_payload
        if kind == "chart" and analytics_payload.get("labels"):
            return analytics_payload
        if kind == "metric" and analytics_payload.get("metrics"):
            return analytics_payload

    if kind == "metric":
        metrics_keys = hints.get("metrics") or []
        if hints.get("formats"):
            return {"metrics": {
                "rdf_turtle": kg_result.turtle_path or "(not generated)",
                "rdf_xml": kg_result.rdfxml_path or "(not generated)",
                "triples_count": kg_result.triples_count,
                "neo4j_projected": kg_result.neo4j_pushed,
            }}
        # Generic metric block — works for any dataset that has numeric data
        if not df.empty and _has_numeric_data(df):
            resource_cat = hints.get("resource_category") or hints.get("filter_value")
            sec_facts = _compute_energy_section_facts(df, resource_cat)
            if sec_facts.get("resource_not_in_dataset"):
                return {"metrics": {"Status": f"{resource_cat} not found in this dataset"}}
            metric_map: dict = {}
            total = sec_facts.get("grand_total_reserves")
            unit = sec_facts.get("value_unit") or ""
            val_col = sec_facts.get("value_column", "")
            col_label = val_col.replace("_", " ").title() if val_col else "Total"
            unit_str = f" ({unit})" if unit else ""
            if total is not None:
                metric_map[f"{col_label}{unit_str}"] = f"{total:,.2f}"
            # Add per-sibling-col totals
            for key, v in sec_facts.items():
                if key.startswith("total_") and key != "grand_total_reserves" and isinstance(v, (int, float)) and v > 0:
                    label = key[6:].replace("_", " ").title()
                    pct_key = key[6:].lower() + "_pct"
                    pct = sec_facts.get(pct_key, "")
                    pct_str = f" ({pct}%)" if pct else ""
                    metric_map[label] = f"{v:,.2f}{pct_str}"
            if sec_facts.get("top_group"):
                metric_map["Leading Group"] = (
                    f"{sec_facts['top_group']} ({sec_facts.get('top_group_pct', '')}%)"
                )
            if sec_facts.get("group_count"):
                metric_map["Groups Covered"] = str(sec_facts["group_count"])
            if metric_map:
                return {"metrics": metric_map}
        return {"metrics": {k: facts.get(k, "—") for k in metrics_keys}}

    if kind == "table":
        src = hints.get("source")
        # Dataset-driven table: works for any dataset with numeric data
        if not df.empty and _has_numeric_data(df) and src in (
            "energy_dataset", "dataset", None
        ) and hints.get("resource_category") or hints.get("group_by") or hints.get("value_column"):
            data_table = _render_data_table(df, hints, title)
            if data_table and data_table.get("rows"):
                return data_table
        # Semantic mapping table (fallback for datasets without filter hints)
        if src == "semantic_mapping" and not df.empty and _has_numeric_data(df):
            data_table = _render_data_table(df, hints, title)
            if data_table and data_table.get("rows"):
                return data_table
        if src == "semantic_mapping":
            rows = analysis_payload.get("semantic_mapping") or []
            if isinstance(rows, list):
                pruned = [
                    {
                        "column": r.get("column"),
                        "domain": r.get("domain") or r.get("semantic_domain"),
                        "confidence": r.get("confidence"),
                        "cluster_id": r.get("cluster_id"),
                    }
                    for r in rows if isinstance(r, dict)
                ]
                return {"columns": ["column", "domain", "confidence", "cluster_id"], "rows": pruned}

        if src == "clusters":
            clusters = analysis_payload.get("clusters") or []
            rows = [
                {
                    "cluster_id": c.get("cluster_id"),
                    "domain": c.get("domain"),
                    "support_score": c.get("support_score"),
                    "columns": ", ".join(c.get("columns") or [])[:60] if c.get("columns") else "—",
                }
                for c in (clusters if isinstance(clusters, list) else [])
            ][:40]
            return {"columns": ["cluster_id", "domain", "support_score", "columns"], "rows": rows}

        if src == "phase3.anomaly_candidates":
            phase3 = analysis_payload.get("phase3") or {}
            cands = phase3.get("anomaly_candidates") or []
            rows = [
                {
                    "column": c.get("column"),
                    "row": c.get("row"),
                    "method": c.get("method"),
                    "severity": c.get("severity"),
                    "confidence": c.get("confidence"),
                }
                for c in cands if isinstance(c, dict)
            ][:200]
            return {"columns": ["column", "row", "method", "severity", "confidence"], "rows": rows}

        if src == "phase3.imputation_candidates":
            phase3 = analysis_payload.get("phase3") or {}
            cands = phase3.get("imputation_candidates") or []
            rows = [
                {
                    "column": c.get("column"),
                    "missing_count": c.get("missing_count"),
                    "recommended_method": c.get("recommended_method"),
                    "confidence": c.get("confidence"),
                }
                for c in cands if isinstance(c, dict)
            ]
            return {"columns": ["column", "missing_count", "recommended_method", "confidence"], "rows": rows}

        if src == "health_summary":
            health = (
                analysis_payload.get("health")
                or (analysis_payload.get("profiling_summary") or {}).get("health")
                or {}
            )
            if isinstance(health, dict) and health:
                rows = [{"metric": k, "value": str(v)} for k, v in health.items()]
                return {"columns": ["metric", "value"], "rows": rows}

        return {"columns": [], "rows": []}

    if kind == "chart":
        # Dataset-driven chart: generic for any dataset with numeric data
        if not df.empty and _has_numeric_data(df) and hints.get("source") in (
            "energy_dataset", "dataset", "semantic_mapping", None,
        ):
            data_chart = _render_data_chart(df, hints, title)
            if data_chart and (data_chart.get("labels") or data_chart.get("subtitle")):
                return data_chart

        if hints.get("source") == "missing_per_column" and not df.empty:
            counts = kx.column_missing_counts(df)
            top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:20]
            top = [(k, v) for k, v in top if v > 0]
            if top:
                return {
                    "chart_type": "bar",
                    "title": title,
                    "labels": [k for k, _ in top],
                    "values": [v for _, v in top],
                }

        if hints.get("source") == "column_types" and not df.empty:
            import pandas as _pd
            types: dict[str, int] = {}
            for c in df.columns:
                dtype = df[c].dtype
                if _pd.api.types.is_numeric_dtype(dtype):
                    types["Numeric"] = types.get("Numeric", 0) + 1
                elif _pd.api.types.is_datetime64_any_dtype(dtype):
                    types["DateTime"] = types.get("DateTime", 0) + 1
                else:
                    types["Categorical"] = types.get("Categorical", 0) + 1
            if types:
                return {
                    "chart_type": "bar",
                    "title": "Column Types",
                    "labels": list(types.keys()),
                    "values": list(types.values()),
                }

        if hints.get("chart_type") == "network":
            sg = analysis_payload.get("schema_graph") or {}
            edges = sg.get("edges") if isinstance(sg, dict) else []
            if edges:
                labels, values, seen = [], [], set()
                for e in edges[:20]:
                    if not isinstance(e, dict):
                        continue
                    pair = f"{e.get('source')}→{e.get('target')}"
                    if pair in seen:
                        continue
                    seen.add(pair)
                    labels.append(pair)
                    values.append(float(e.get("weight") or 0.0))
                return {"chart_type": "bar", "title": "Top dependency weights",
                        "labels": labels, "values": values}

        return {"chart_type": hints.get("chart_type", "bar"), "labels": [], "values": []}

    return {}


def _executive_summary_metrics(facts: dict[str, Any], kg_result) -> dict[str, Any]:
    return {
        "Rows": facts.get("row_count", "—"),
        "Columns": facts.get("column_count", "—"),
        "Missing %": (
            f"{facts['missing_pct']:.2f}%"
            if isinstance(facts.get("missing_pct"), (int, float)) else "—"
        ),
        "Anomalies Flagged": facts.get("anomaly_count", 0),
        "Imputation Targets": facts.get("imputation_count", 0),
        "Semantic-Mapped Columns": facts.get("mapped_column_count", 0),
        "KG Triples": kg_result.triples_count,
        "KG Neo4j Pushed": kg_result.neo4j_pushed,
        "Dataset Type": facts.get("dataset_type", "—"),
        "Health Score": facts.get("health_score", "—"),
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _set_job(db: Session, job_id: int, **fields):
    from database.models import ReportJob

    row = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not row:
        return
    for k, v in fields.items():
        if hasattr(row, k):
            setattr(row, k, v)
    db.commit()


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def generate_report(
    *,
    db: Session,
    job_id: int,
    analysis_id: int,
    dataset_id: int,
    analysis_payload: dict[str, Any],
    df_loader: Callable[[], pd.DataFrame],
    template_ast: dict[str, Any] | None,
    dataset_filename: str | None,
    out_root: str | Path | None = None,
    filter_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all phases. Returns status dict; full canvas persisted on the job."""
    out_root = Path(out_root or os.getenv("REPORT_STORAGE_PATH", "./storage/reports"))
    out_root.mkdir(parents=True, exist_ok=True)
    kg_dir = out_root / "kg"
    pdf_path = out_root / f"report_builder_{job_id}.pdf"

    _set_job(db, job_id, status="running", stage="phase0")

    # ----- Phase 0 — Template AST -----
    ast = _load_template(template_ast)
    logger.info("[job %s] Phase 0: template '%s' — %s blocks", job_id, ast.name, len(ast.blocks))

    _set_job(db, job_id, stage="phase1")

    # ----- Phase 1 — KG build + export -----
    kg_result = kg.build_kg_from_state(
        dataset_id=dataset_id,
        analysis_id=analysis_id,
        analysis_payload=analysis_payload,
        out_dir=kg_dir,
    )
    logger.info(
        "[job %s] Phase 1: %s triples (turtle=%s neo4j=%s)",
        job_id, kg_result.triples_count, bool(kg_result.turtle_path), kg_result.neo4j_pushed,
    )

    _set_job(db, job_id, stage="phase2")

    # ----- Phase 2 — Memory -----
    stm = STM()
    ledger = ReflectionLedger(db)
    stm.put(job_id, "session_started", datetime.utcnow().isoformat())

    _set_job(db, job_id, stage="phase3")

    # ----- Phase 3 — Arrow kernel + facts -----
    try:
        df = kx.ensure_loaded(analysis_id, df_loader)
    except Exception as exc:
        logger.warning("[job %s] Arrow kernel load failed: %s", job_id, exc)
        df = pd.DataFrame()

    filter_spec = DataFilterSpec.from_dict(filter_config)
    if filter_spec and not df.empty:
        df = apply_filters(df, filter_spec)
        logger.info("[job %s] Phase 3: filters applied, rows=%s", job_id, len(df))

    snap_path = write_parquet_snapshot(df, analysis_id, out_root / "analytics")
    if snap_path:
        logger.info("[job %s] analytics snapshot: %s", job_id, snap_path)

    facts = _collect_facts(analysis_payload, df)
    logger.info("[job %s] Phase 3: %s facts keys", job_id, len(facts))

    _set_job(db, job_id, stage="phase4_5")

    # ----- Phases 4 & 5 — Scribe + Verifier + AGUI assembly -----
    rendered_blocks: list[RenderedBlock] = []
    verifier_report: dict[str, Any] = {"blocks": []}

    for block in ast.blocks:
        route = kx.classify_intent(block.kind, block.hints or {})
        payload = _render_block_payload(block, analysis_payload, facts, df, kg_result, ledger)

        verifier_dict: dict[str, Any] | None = None
        if block.kind == "narrative" and payload.get("text"):
            verdict = fw.verify_block(
                block_id=block.block_id,
                narrative=payload["text"],
                df=df if not df.empty else None,
                expected_facts=facts,
            )
            verifier_dict = verdict.to_dict()
            verifier_report["blocks"].append(verifier_dict)

        rendered_blocks.append(RenderedBlock(
            block_id=block.block_id,
            kind=block.kind,
            title=block.title,
            section=block.section,
            payload=payload,
            verifier=verifier_dict,
            route={"engine": route.kind, "rationale": route.rationale},
        ))

    summary = _executive_summary_metrics(facts, kg_result)
    canvas = BlockCanvas(
        job_id=job_id,
        analysis_id=analysis_id,
        template_name=ast.name,
        blocks=rendered_blocks,
        summary=summary,
    )
    canvas_dict = canvas.to_dict()

    _set_job(
        db, job_id,
        stage="phase6",
        blocks_json=canvas_dict,
        verifier_report=verifier_report,
        kg_export_path=kg_result.turtle_path,
    )

    # ----- Phase 6 — Export PDF -----
    storage_path, digest = export_pdf(
        canvas_dict=canvas_dict,
        out_path=pdf_path,
        dataset_filename=dataset_filename,
        verifier_report=verifier_report,
    )
    logger.info("[job %s] Phase 6: PDF at %s (%s…)", job_id, storage_path, digest[:12])

    _set_job(
        db, job_id,
        status="exported",
        stage="done",
        final_pdf_path=storage_path,
        content_hash=digest,
    )

    return {
        "status": "exported",
        "job_id": job_id,
        "content_hash": digest,
        "final_pdf_path": storage_path,
        "triples": kg_result.triples_count,
        "blocks": len(rendered_blocks),
    }
