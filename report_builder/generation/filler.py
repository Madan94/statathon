"""S5a — Filler: pour analyticsAST values into the template's table/chart/figure slots.

The template ASTs (from ① ``template.ast.json``) carry the *structure* of every
table, chart and figure — columns, axes, footnote templates — but their value
slots are empty (``rows: []``, ``series: []``, ``slot.status: "empty"``). The
analytics stage (S4) produced the *values* with row-level provenance. This stage
joins them:

    template slot  +  analyticsAST (keyed by questionId)  →  filled slot

Every filled artifact gets:
  * its values (numbers stay numeric — formatting is a render-time concern),
  * ``rowIds`` provenance carried straight through from the aggregation rows,
  * a ``provenance`` block linking it to the question / aggregation / evidence,
  * ``slot.status = "filled"`` (or ``"empty"`` when no data could be bound).

It is fully deterministic and offline. Narrative prose (contentAST) is filled by
the separate narrator stage (S5b); this stage only handles value-bearing visuals.
"""
from __future__ import annotations

import copy
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# A small, stable categorical palette (MoSPI-ish). Charts cycle through it; a
# table never needs colours. Kept here so fills are reproducible without a theme.
_DEFAULT_PALETTE = [
    "#1F7A1F", "#0B5394", "#B45F06", "#741B47", "#594F8D",
    "#0C6E6E", "#8B1A1A", "#6A6A00",
]

_COMPONENT_SUFFIX = re.compile(r"_c\d+$")
_TEMPLATE_TOKEN = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _base_question(ref: str | None) -> str:
    """Strip a trailing component suffix so ``q_wpr_01_c2`` → ``q_wpr_01``."""
    return _COMPONENT_SUFFIX.sub("", ref or "")


def _norm(text: Any) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _ctx_lookup(context: dict[str, Any], path: str) -> Any:
    node: Any = context
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _render_template(text: str, context: dict[str, Any]) -> str:
    """Render ``{{a.b}}`` tokens from ``context``; unknown tokens collapse to ''."""
    def sub(m: re.Match[str]) -> str:
        val = _ctx_lookup(context, m.group(1))
        return "" if val is None else str(val)
    return _TEMPLATE_TOKEN.sub(sub, text or "")


class _AnalyticsIndex:
    """questionId → its aggregation / ranking / trend / metric + evidence."""

    def __init__(self, analytics: dict[str, Any], evidence: dict[str, Any]):
        self.aggregations = {a["questionId"]: a for a in analytics.get("aggregations", [])}
        self.rankings = {r["questionId"]: r for r in analytics.get("rankings", [])}
        self.trends = {t["questionId"]: t for t in analytics.get("trends", [])}
        self.metrics: dict[str, list[dict]] = {}
        for m in analytics.get("metrics", []):
            self.metrics.setdefault(m["questionId"], []).append(m)
        self.evidence_by_q: dict[str, str] = {}
        for ev in evidence.get("evidence", []):
            self.evidence_by_q.setdefault(ev["questionId"], ev["evidenceId"])

    def evidence_ref(self, qid: str) -> str:
        return self.evidence_by_q.get(qid, "")


# ─────────────────────────────────────────────────────────────────────────────
# Chart fill
# ─────────────────────────────────────────────────────────────────────────────


def _fill_chart(chart: dict[str, Any], idx: _AnalyticsIndex, palette: list[str]) -> dict[str, Any]:
    chart = copy.deepcopy(chart)
    qid = _base_question(chart.get("biQuery") or (chart.get("slot") or {}).get("fillFrom"))
    agg = idx.aggregations.get(qid)
    points: list[dict[str, Any]] = []
    if agg and agg.get("rows"):
        group_col = agg.get("groupBy")
        # For a 1-D aggregation the x value is that single dimension's member.
        dim = group_col if isinstance(group_col, str) else (group_col[0] if group_col else None)
        for i, row in enumerate(agg["rows"]):
            key = row.get("key") or {}
            x = key.get(dim) if dim else next(iter(key.values()), None)
            points.append({
                "x": x,
                "y": row.get("value"),
                "color": palette[i % len(palette)],
                "rowIds": list(row.get("rowIds") or []),
            })
    chart["series"] = [{"label": chart.get("title") or qid, "points": points}] if points else []
    chart["provenance"] = {
        "questionId": qid,
        "analyticsRef": agg["aggId"] if agg else None,
        "evidenceRef": idx.evidence_ref(qid) or None,
    }
    chart.setdefault("slot", {})["status"] = "filled" if points else "empty"
    return chart


# ─────────────────────────────────────────────────────────────────────────────
# Table fill
# ─────────────────────────────────────────────────────────────────────────────


def _measure_member(col: dict[str, Any], column_groups: dict[str, dict]) -> str:
    """The pivot member a measure column represents — its group label or header."""
    grp = col.get("group")
    if grp and grp in column_groups:
        return column_groups[grp].get("label") or col.get("header") or ""
    return col.get("header") or ""


def _fill_table(table: dict[str, Any], idx: _AnalyticsIndex, context: dict[str, Any]) -> dict[str, Any]:
    table = copy.deepcopy(table)
    qid = _base_question(table.get("biQuery") or (table.get("slot") or {}).get("fillFrom"))
    columns = table.get("columns") or []
    dim_cols = [c for c in columns if c.get("role") == "dimension"]
    measure_cols = [c for c in columns if c.get("role") == "measure"]
    column_groups = {g["groupId"]: g for g in (table.get("columnGroups") or [])}

    source = idx.aggregations.get(qid) or idx.rankings.get(qid)
    rows: list[dict[str, Any]] = []
    analytics_ref = None

    if source and dim_cols:
        analytics_ref = source.get("aggId") or source.get("rankId")
        records = source.get("rows") or source.get("items") or []
        dim_col = dim_cols[0]
        group_by = source.get("groupBy")
        group_cols = [group_by] if isinstance(group_by, str) else list(group_by or [])

        if len(measure_cols) <= 1:
            # Flat table: one analytics record → one row.
            primary = group_cols[0] if group_cols else None
            for rec in records:
                key = rec.get("key") or {}
                row: dict[str, Any] = {dim_col["columnId"]: key.get(primary) if primary else next(iter(key.values()), None)}
                if measure_cols:
                    row[measure_cols[0]["columnId"]] = rec.get("value")
                row["rowIds"] = list(rec.get("rowIds") or [])
                rows.append(row)
        else:
            # Pivot table: measure columns are members of a secondary dimension.
            rows = _pivot_rows(records, dim_col, measure_cols, group_cols, column_groups)

    # Render footnote templates from the run context.
    for fn in table.get("footnotes") or []:
        if fn.get("textTemplate"):
            fn["text"] = _render_template(fn["textTemplate"], context)

    table["rows"] = rows
    table["provenance"] = {
        "questionId": qid,
        "analyticsRef": analytics_ref,
        "evidenceRef": idx.evidence_ref(qid) or None,
    }
    table.setdefault("slot", {})["status"] = "filled" if rows else "empty"
    return table


def _pivot_rows(
    records: list[dict[str, Any]],
    dim_col: dict[str, Any],
    measure_cols: list[dict[str, Any]],
    group_cols: list[str],
    column_groups: dict[str, dict],
) -> list[dict[str, Any]]:
    """Pivot a 2-key aggregation: primary dim → rows, secondary dim → measure cols."""
    members = {mc["columnId"]: _norm(_measure_member(mc, column_groups)) for mc in measure_cols}
    member_values = set(members.values())

    # Decide which groupBy column is the pivot (secondary) one: the column whose
    # value-set best matches the measure-column member labels.
    secondary = None
    if len(group_cols) >= 2:
        best, best_overlap = None, -1
        for gc in group_cols:
            vals = {_norm(rec.get("key", {}).get(gc)) for rec in records}
            overlap = len(vals & member_values)
            if overlap > best_overlap:
                best, best_overlap = gc, overlap
        secondary = best
    primary = next((gc for gc in group_cols if gc != secondary), group_cols[0] if group_cols else None)

    by_primary: dict[Any, dict[str, Any]] = {}
    order: list[Any] = []
    for rec in records:
        key = rec.get("key") or {}
        pval = key.get(primary) if primary else next(iter(key.values()), None)
        sval = _norm(key.get(secondary)) if secondary else None
        if pval not in by_primary:
            by_primary[pval] = {dim_col["columnId"]: pval, "rowIds": []}
            order.append(pval)
        bucket = by_primary[pval]
        bucket["rowIds"].extend(rec.get("rowIds") or [])
        for col_id, member in members.items():
            if member == sval:
                bucket[col_id] = rec.get("value")
    return [by_primary[p] for p in order]


# ─────────────────────────────────────────────────────────────────────────────
# Figure fill
# ─────────────────────────────────────────────────────────────────────────────


def _fill_figure(figure: dict[str, Any], filled_charts: dict[str, dict], context: dict[str, Any]) -> dict[str, Any]:
    figure = copy.deepcopy(figure)
    if figure.get("captionTemplate"):
        figure["caption"] = _render_template(figure["captionTemplate"], context)
    elif figure.get("caption"):
        figure["caption"] = _render_template(figure["caption"], context)
    chart = filled_charts.get(figure.get("chartRef"))
    chart_filled = bool(chart and (chart.get("slot") or {}).get("status") == "filled")
    figure.setdefault("slot", {})["status"] = "filled" if chart_filled else "empty"
    return figure


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def fill_visuals(
    template: dict[str, Any],
    analytics: dict[str, Any],
    evidence: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    palette: list[str] | None = None,
) -> dict[str, Any]:
    """Fill all table/chart/figure slots from analyticsAST.

    Args:
        template: the value-free template AST (needs ``tableAST``/``chartAST``/``figureAST``).
        analytics: analyticsAST dict from the executor (S4).
        evidence:  evidenceAST dict from the executor (S4).
        context:   values for footnote/caption templates
                   (e.g. ``{"dataset": {"title": ...}, "period": {"current": ...}}``).
        palette:   chart colour cycle; defaults to a stable MoSPI-ish palette.

    Returns a dict with filled ``tableAST``, ``chartAST``, ``figureAST`` and a
    ``fillTrace`` summarising what was bound.
    """
    context = context or {}
    palette = palette or _DEFAULT_PALETTE
    idx = _AnalyticsIndex(analytics, evidence)

    charts = [_fill_chart(c, idx, palette) for c in (template.get("chartAST") or {}).get("charts", [])]
    tables = [_fill_table(t, idx, context) for t in (template.get("tableAST") or {}).get("tables", [])]
    charts_by_id = {c.get("chartId"): c for c in charts}
    figures = [_fill_figure(f, charts_by_id, context) for f in (template.get("figureAST") or {}).get("figures", [])]

    trace: list[dict[str, Any]] = []
    for c in charts:
        pts = c["series"][0]["points"] if c.get("series") else []
        trace.append({"kind": "chart", "id": c.get("chartId"),
                      "questionId": c["provenance"]["questionId"],
                      "status": c["slot"]["status"], "count": len(pts)})
    for t in tables:
        trace.append({"kind": "table", "id": t.get("tableId"),
                      "questionId": t["provenance"]["questionId"],
                      "status": t["slot"]["status"], "count": len(t.get("rows") or [])})
    for f in figures:
        trace.append({"kind": "figure", "id": f.get("figureId"),
                      "status": f["slot"]["status"]})

    filled = sum(1 for x in trace if x.get("status") == "filled")
    logger.info("[S5a] filled %d/%d visual slots (charts=%d tables=%d figures=%d)",
                filled, len(trace), len(charts), len(tables), len(figures))

    return {
        "tableAST": {"tables": tables},
        "chartAST": {"charts": charts},
        "figureAST": {"figures": figures},
        "fillTrace": trace,
    }
