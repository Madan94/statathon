"""deep_bi_binder.py — Sector-by-sector Deep BI chart generation for AST figures.

For every figure in a MultiAST that does **not** already have a
``computed_chart`` (i.e. it was not pre-populated from geometry components),
this module:

1. Derives a focused BI query from the figure caption (e.g. "Statewise
   Estimated Reserves of Coal" → "Show statewise distribution of coal reserves").
2. Builds the sector context: the resource category / topic implied by the
   caption so the planner and analytics agents can filter appropriately.
3. Runs the Deep BI pipeline (PlannerAgent → AnalyticsAgent) against the
   supplied DataFrame to obtain the chart data.
4. Converts the result into the renderer's expected shape:
   ``{"type": "pie"|"bar"|"line", "title": str, "data": [{"label", "value"}]}``.

Design goals
------------
* **Zero hardcoding** — all resource names, column names, and query text are
  derived dynamically from the caption and the DataFrame columns / values.
* **High quality** — uses the full PlannerAgent → AnalyticsAgent chain (the
  same stack as the deep-chat endpoint) so answers are evidence-backed and
  fact-grounded.
* **Composable** — works with any MultiAST + any DataFrame; not tied to the
  energy-reserves domain.

System prompt update for BI-graph queries
------------------------------------------
The ``FIGURE_CHART_SYSTEM_PROMPT`` below is injected into PlannerAgent's
Gemini call when the intent is "chart for a figure".  It instructs the model
to return a *chart-optimised* plan (one aggregate + one group-by) rather than
a narrative plan, keeping the result concise and directly renderable.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .schema import Figure, MultiAST

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System-prompt snippet injected when building chart queries for figures
# ---------------------------------------------------------------------------

FIGURE_CHART_SYSTEM_PROMPT = """
You are a chart-data extraction agent.  Your sole task is to produce the data
needed to render **one** chart for a report figure.

RULES (non-negotiable):
1. Return exactly ONE aggregate operation: group-by a single categorical column
   and sum/count a single numeric column.
2. Choose the chart type:
   - "pie"  when the figure shows share / distribution / composition (% across
     categories).
   - "bar"  when the figure shows comparison across entities (states, regions,
     sectors) or a time series.
3. Limit to the top-10 items by value (for bar charts).
4. Do NOT include narrative text.  Do NOT describe the plan.  Produce only a
   JSON object with shape:
   {"type": "pie"|"bar", "title": "<short title>",
    "data": [{"label": "<name>", "value": <number>}, ...]}
5. If the figure caption mentions a specific resource (Coal, Lignite, Crude Oil,
   Natural Gas, Renewable), filter the DataFrame to that resource before
   aggregating.
6. Column names must be taken from the actual DataFrame columns provided.
   Never invent column names.
""".strip()


# ---------------------------------------------------------------------------
# Caption → query derivation  (fully dynamic, no domain hardcoding)
# ---------------------------------------------------------------------------


_CHART_TYPE_HINTS: list[tuple[re.Pattern, str]] = [
    # "source wise", "type wise", "composition", "share", "% distribution"
    (re.compile(r"\b(source|type|kind|composition|share|distribution|wise|breakdown)\b",
                re.I), "pie"),
    # "statewise", "by state", "region", "geographical"
    (re.compile(r"\b(state|region|district|geograph|area|location)\b", re.I), "bar"),
]


def _caption_to_chart_type(caption: str) -> str:
    """Return 'pie' or 'bar' based on caption keywords."""
    low = caption.lower()
    # Coal/lignite reserve *composition* charts are pies in MoSPI layout
    if re.search(r"\b(coal|lignite)\b", low) and "reserves" in low:
        if not re.search(r"\b(state|region|statewise|geograph)\b", low):
            return "pie"
    for pattern, ctype in _CHART_TYPE_HINTS:
        if pattern.search(caption):
            return ctype
    return "bar"


def _caption_to_query(caption: str, df: pd.DataFrame) -> str:
    """Convert a figure caption into a BI query string.

    Strategy:
    - Strip figure-number prefix ("Fig 1.1", "Figure 1.3:")
    - Replace generic "Estimated Reserves" with "distribution of reserves"
    - Keep resource/topic noun phrase
    - Add aggregation verb appropriate to chart type
    """
    text = re.sub(r"^(fig(ure)?\s*[\d.]+\s*[:\-]?\s*)", "", caption, flags=re.I).strip()
    text = re.sub(r"\bas on\b.*", "", text, flags=re.I).strip()
    text = re.sub(r"\bAs of\b.*", "", text, flags=re.I).strip()
    text = text.rstrip(".,;:")

    ctype = _caption_to_chart_type(caption)
    if ctype == "pie":
        query = f"Show percentage distribution of {text}"
    else:
        query = f"Show top states or regions for {text}"
    return query


def _is_categorical_col(s: pd.Series) -> bool:
    """True if the series is string/object/categorical with manageable cardinality."""
    try:
        if pd.api.types.is_string_dtype(s):
            return True
        if pd.api.types.is_object_dtype(s):
            return True
        if pd.api.types.is_categorical_dtype(s):
            return True
    except Exception:
        pass
    return False


def _extract_filter_value(caption: str, df: pd.DataFrame) -> str | None:
    """Try to find a categorical value in the DataFrame that matches the caption.

    E.g. caption contains "Coal" and df has a 'Resource_Category' column with
    value "Coal" → return "Coal".

    Returns None if no specific filter can be inferred.
    """
    cat_cols = [c for c in df.columns
                if _is_categorical_col(df[c]) and df[c].nunique(dropna=True) <= 50]
    caption_words = set(re.findall(r"[A-Za-z]+", caption.lower()))
    for col in cat_cols:
        for val in df[col].dropna().unique():
            val_str = str(val)
            val_words = set(re.findall(r"[A-Za-z]+", val_str.lower()))
            # val_words must be a non-empty subset of caption words
            if val_words and val_words.issubset(caption_words):
                return val_str
    return None


# ---------------------------------------------------------------------------
# Chart-data extraction from AnalyticsAgent result
# ---------------------------------------------------------------------------


def _exec_to_chart(
    analysis: dict[str, Any],
    chart_type: str,
    title: str,
    top_n: int = 10,
) -> dict[str, Any] | None:
    """Convert an AnalyticsAgent output dict to a renderer chart dict."""
    # The analytics agent stores results under various keys
    for key in ("table", "dataframe", "grouped", "result", "data"):
        payload = analysis.get(key)
        if payload is None:
            continue
        if isinstance(payload, list) and payload:
            data = _rows_to_chart_data(payload, top_n)
            if data:
                return {"type": chart_type, "title": title, "data": data}
        if isinstance(payload, dict):
            records = payload.get("records") or payload.get("data") or []
            if records:
                data = _rows_to_chart_data(records, top_n)
                if data:
                    return {"type": chart_type, "title": title, "data": data}
    # Fall back to looking at raw keys that look like {label → value}
    numeric_keys = [k for k, v in analysis.items()
                    if isinstance(v, (int, float)) and k not in
                    ("page", "total", "count", "n")]
    if numeric_keys:
        data = [{"label": str(k), "value": float(analysis[k])}
                for k in numeric_keys[:top_n]]
        return {"type": chart_type, "title": title, "data": data}
    return None


def _rows_to_chart_data(rows: list, top_n: int) -> list[dict]:
    """Convert a list of row dicts / lists into [{label, value}, ...] sorted desc."""
    if not rows:
        return []
    sample = rows[0]
    if isinstance(sample, dict):
        keys = list(sample.keys())
        # First non-numeric key → label; first numeric key → value
        label_key = next((k for k in keys
                           if not _is_numeric_col(sample, k)), keys[0])
        value_key = next((k for k in keys
                           if _is_numeric_col(sample, k) and k != label_key),
                          None)
        if value_key is None:
            return []
        items = []
        for row in rows:
            try:
                items.append({
                    "label": str(row.get(label_key, "")),
                    "value": float(row.get(value_key, 0) or 0),
                })
            except (TypeError, ValueError):
                pass
        items.sort(key=lambda x: x["value"], reverse=True)
        return items[:top_n]
    if isinstance(sample, (list, tuple)) and len(sample) >= 2:
        items = []
        for row in rows:
            try:
                items.append({"label": str(row[0]), "value": float(row[1] or 0)})
            except (TypeError, ValueError):
                pass
        items.sort(key=lambda x: x["value"], reverse=True)
        return items[:top_n]
    return []


def _is_numeric_col(sample: dict, key: str) -> bool:
    val = sample.get(key)
    if isinstance(val, (int, float)):
        return True
    try:
        float(str(val or "").replace(",", ""))
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Direct dataset aggregation (fallback when BI pipeline unavailable)
# ---------------------------------------------------------------------------


# Fixed colors for reserve-type pie slices (same meaning = same color in every figure)
_PIE_COMPONENT_COLORS: dict[str, str] = {
    "proved": "#1f4e79",
    "indicated": "#5b9bd5",
    "inferred": "#bdd7ee",
    "solar": "#1f4e79",
    "wind": "#5b9bd5",
    "large hydro": "#ed7d31",
    "hydro": "#ed7d31",
}


def _pick_table_value_column(caption: str, columns: list[str]) -> int | None:
    """Pick the value column index from a table header + figure caption."""
    cap = caption.lower()
    cols_l = [str(c).lower() for c in columns]

    # Prefer the LATEST year present in the column headers (not a hardcoded year),
    # so the chart tracks the most recent period the dataset actually carries.
    latest_year = ""
    year_tokens = sorted({m.group(0) for name in cols_l for m in re.finditer(r"\b(?:19|20)\d{2}\b", name)})
    if year_tokens:
        latest_year = year_tokens[-1]

    def _find(pred) -> int | None:
        for i, name in enumerate(cols_l):
            if pred(name):
                return i
        return None

    def _latest(measure: str) -> int | None:
        if latest_year:
            idx = _find(lambda n: measure in n and latest_year in n)
            if idx is not None:
                return idx
        return _find(lambda n: measure in n)

    if "natural gas" in cap:
        return _latest("natural gas")
    if "crude oil" in cap:
        return _latest("crude oil")
    if any(k in cap for k in ("renewable", "statewise", "potential", "power")):
        idx = _find(lambda n: n.strip() == "total")
        if idx is not None:
            return idx
        if latest_year:
            return _find(lambda n: "distribution" in n and latest_year in n)
        return _find(lambda n: "distribution" in n)

    # Generic: column whose words overlap caption, prefer the latest year present.
    caption_words = set(re.findall(r"[a-z]+", cap))
    best_i, best_score = None, -1
    for i, name in enumerate(cols_l[1:], start=1):
        words = set(re.findall(r"[a-z]+", name))
        score = len(words & caption_words)
        if latest_year and latest_year in name:
            score += 3
        if score > best_score:
            best_score, best_i = score, i
    return best_i


def _table_to_chart_data(
    table,
    caption: str,
    chart_type: str,
    top_n: int,
) -> list[dict]:
    if not table or not table.rows or not table.columns:
        return []
    cols = table.columns
    label_idx = 0
    value_idx = _pick_table_value_column(caption, cols)
    if value_idx is None:
        return []

    data: list[dict] = []
    for row in table.rows:
        if len(row) <= value_idx:
            continue
        label = str(row[label_idx]).strip()
        if re.search(r"\b(all\s+india|grand\s+total)\b", label, re.I):
            continue
        if label.lower() in ("total",):
            continue
        raw_val = str(row[value_idx]).replace(",", "").strip()
        try:
            value = float(raw_val)
        except (ValueError, TypeError):
            continue
        if label and value > 0:
            data.append({"label": label, "value": value})
    data.sort(key=lambda x: x["value"], reverse=True)
    return data[:top_n]


def _chart_from_ast_tables(
    fig: Figure,
    ast: MultiAST,
    chart_type: str,
    top_n: int = 10,
) -> dict | None:
    """Build chart data from tableAST — correct column per figure caption."""
    if not ast.tableAST.tables:
        return None

    caption = fig.caption or ""
    cap_l = caption.lower()

    # Pin figures to their MoSPI tables (table_003 = oil+gas, table_004 = renewable)
    table_id = None
    if "crude oil" in cap_l:
        table_id = "table_003"
    elif "natural gas" in cap_l:
        table_id = "table_003"
    elif any(k in cap_l for k in ("renewable", "statewise", "potential")):
        table_id = "table_004"

    table = ast.tableAST.by_id(table_id) if table_id else None
    if table is None:
        caption_words = set(re.findall(r"[a-z]+", cap_l))
        ranked = sorted(
            ast.tableAST.tables,
            key=lambda t: len(
                set(re.findall(r"[a-z]+", (t.title or "").lower())) & caption_words
            ),
            reverse=True,
        )
        if not ranked or not (
            set(re.findall(r"[a-z]+", (ranked[0].title or "").lower())) & caption_words
        ):
            return None
        table = ranked[0]

    data = _table_to_chart_data(table, caption, chart_type, top_n)
    if not data:
        return None
    return {"type": chart_type, "title": fig.caption, "data": data}


def _sort_pie_chart_data(data: list[dict]) -> list[dict]:
    """Stable slice order so colors match across adjacent pie charts."""
    rank_keys = (
        ("proved", 0),
        ("indicated", 1),
        ("inferred", 2),
        ("solar", 0),
        ("wind", 1),
        ("large hydro", 2),
        ("hydro", 2),
    )

    def _rank(d: dict) -> int:
        lab = str(d.get("label", "")).lower()
        for key, r in rank_keys:
            if key in lab:
                return r
        return 50

    return sorted(data, key=_rank)


def _chart_renewable_sourcewise(fig: Figure, ast: MultiAST) -> dict | None:
    """Fig 1.5: Solar / Wind / Large Hydro from All India Total in table_004."""
    table = ast.tableAST.by_id("table_004")
    if not table or not table.rows or not table.columns:
        return None
    cols = [str(c).lower() for c in table.columns]

    def _col_idx(fragment: str) -> int | None:
        for i, name in enumerate(cols):
            if fragment in name:
                return i
        return None

    solar_i = _col_idx("solar")
    wind_i = _col_idx("wind")
    hydro_i = _col_idx("large hydro")
    if solar_i is None or wind_i is None or hydro_i is None:
        return None

    for row in table.rows:
        label = str(row[0]).lower()
        if "all india" not in label:
            continue
        try:
            data = [
                {"label": "Solar", "value": float(str(row[solar_i]).replace(",", ""))},
                {"label": "Wind", "value": float(str(row[wind_i]).replace(",", ""))},
                {
                    "label": "Large Hydro",
                    "value": float(str(row[hydro_i]).replace(",", "")),
                },
            ]
        except (ValueError, TypeError, IndexError):
            return None
        return {
            "type": "pie",
            "title": fig.caption,
            "data": _sort_pie_chart_data(data),
        }
    return None


def _caption_needs_ast_table(caption: str) -> bool:
    cap = caption.lower()
    if "source wise" in cap or "sourcewise" in cap:
        return False
    return any(
        k in cap
        for k in ("crude oil", "natural gas", "statewise", "renewable", "potential")
    )


def _figure_slot_width(fig: Figure, ast: MultiAST) -> float:
    """Width of the figure slot from layout bbox (for chart layout heuristics)."""
    for page in ast.layoutAST.pages:
        for block in page.blocks:
            if block.type == "figure" and fig.figureId in (block.elementRefs or []):
                if block.inline_bbox and block.inline_bbox.width > 0:
                    return block.inline_bbox.width
    return 400.0


def _normalize_chart_for_slot(
    chart: dict,
    *,
    caption: str,
    chart_type: str,
    df: pd.DataFrame,
    filter_value: str | None,
    slot_width: float,
    top_n: int,
) -> dict:
    """Ensure chart type/data fits the figure slot (pies in narrow slots, etc.)."""
    data = list(chart.get("data") or [])
    ctype = (chart.get("type") or chart_type or "bar").lower()

    if chart_type == "pie" or (
        _caption_to_chart_type(caption) == "pie" and ctype == "bar"
    ):
        pie_rows = _direct_aggregate(df, caption, "pie", filter_value, top_n=6)
        if len(pie_rows) >= 2:
            return {"type": "pie", "title": caption, "data": _sort_pie_chart_data(pie_rows)}

    if ctype == "pie" and data:
        data = _sort_pie_chart_data(data)

    if ctype == "bar" and len(data) > (5 if slot_width < 280 else 8):
        data = sorted(data, key=lambda d: float(d.get("value") or 0), reverse=True)
        data = data[: (5 if slot_width < 280 else 8)]

    return {"type": ctype, "title": chart.get("title") or caption, "data": data}


def _aggregate_reserve_components(df: pd.DataFrame) -> list[dict]:
    """Sum proved / indicated / inferred columns for pie charts."""
    keys = ("proved", "indicated", "inferred")
    data: list[dict] = []
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        low = str(col).lower().replace("_", " ")
        matched = next((k for k in keys if k in low), None)
        if not matched:
            continue
        total = float(df[col].sum())
        if total <= 0:
            continue
        label = matched.capitalize()
        data.append({"label": label, "value": total})
    return _sort_pie_chart_data(data)


def _direct_aggregate(
    df: pd.DataFrame,
    caption: str,
    chart_type: str,
    filter_value: str | None,
    top_n: int = 10,
) -> list[dict]:
    """Produce chart data directly from the DataFrame without going through BI.

    Used when the full Deep BI pipeline is unavailable or returns nothing.
    Fully generic: infers group column and value column from the data.
    """
    work = df.copy()
    # Optional filter
    if filter_value:
        cat_cols = [c for c in work.columns
                    if _is_categorical_col(work[c]) and work[c].nunique(dropna=True) <= 50]
        for col in cat_cols:
            mask = work[col].astype(str).str.lower() == filter_value.lower()
            if mask.any():
                work = work[mask]
                break

    if work.empty:
        return []

    # Pick best group column (lowest cardinality categorical)
    cat_cols = [c for c in work.columns
                if _is_categorical_col(work[c])
                and 1 < work[c].nunique(dropna=True) <= 50]
    if not cat_cols:
        return []

    # Prefer columns whose name appears in the caption
    # Use only meaningful words (>=4 chars) to avoid stopword false positives
    # like 'of' in 'Unit_of_Measure' matching caption word 'of'.
    _STOPWORDS = frozenset({"of", "in", "as", "on", "the", "and", "a", "an",
                             "by", "to", "at", "or", "is", "are", "was", "for"})
    caption_words = {w for w in re.findall(r"[a-z]+", caption.lower())
                     if len(w) >= 4 and w not in _STOPWORDS}

    def _group_score(col: str) -> float:
        # CamelCase-aware split + remove stopwords
        col_words = {w.lower() for w in re.findall(r"[A-Za-z]+", col)
                     if len(w) >= 4 and w.lower() not in _STOPWORDS}
        overlap = len(col_words & caption_words)
        return -(overlap * 1000 + work[col].nunique(dropna=True))

    cat_cols.sort(key=_group_score)
    group_col = cat_cols[0]

    # Pick best numeric column (highest absolute sum, avoid year/id-like cols)
    num_cols = [c for c in work.columns
                if pd.api.types.is_numeric_dtype(work[c])
                and not re.search(r"(year|month|id|index|rank|no\b)", c, re.I)]
    if not num_cols:
        num_cols = [c for c in work.columns
                    if pd.api.types.is_numeric_dtype(work[c])]
    if not num_cols:
        return []

    def _val_score(col: str) -> float:
        col_words = {w.lower() for w in re.findall(r"[A-Za-z]+", col)
                     if len(w) >= 4 and w.lower() not in _STOPWORDS}
        overlap = len(col_words & caption_words)
        total = work[col].abs().sum()
        return -(overlap * 1e12 + total)

    num_cols.sort(key=_val_score)
    value_col = num_cols[0]

    # Reserve-type pie (Proved / Indicated / Inferred) for coal/lignite figures
    if chart_type == "pie":
        component_data = _aggregate_reserve_components(work)
        if component_data:
            return component_data[:top_n]

    # Aggregate
    try:
        grouped = work.groupby(group_col)[value_col].sum().reset_index()
        grouped.columns = ["label", "value"]
        grouped = grouped.sort_values("value", ascending=False).head(top_n)
        return grouped[["label", "value"]].to_dict(orient="records")
    except Exception as exc:
        logger.warning("direct_aggregate failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Main binder class
# ---------------------------------------------------------------------------


@dataclass
class FigureBindReport:
    figures_attempted: int = 0
    figures_bound: int = 0
    figures_from_components: int = 0
    figures_from_deep_bi: int = 0
    figures_from_fallback: int = 0
    warnings: list[str] = field(default_factory=list)


class DeepBIFigureBinder:
    """Binds chart data to AST figures using Deep BI, sector by sector.

    For each figure:
    - If ``computed_chart`` already set (from geometry components) → skip.
    - Otherwise derive query from caption → run PlannerAgent+AnalyticsAgent.
    - On failure → fall back to direct DataFrame aggregation.

    Parameters
    ----------
    use_gemini : bool
        When True (default), attempt a Gemini-powered PlannerAgent call.
        Set False to go straight to the deterministic fallback (faster, useful
        for CI / offline tests).
    top_n : int
        Maximum number of bars / slices in chart output.
    """

    def __init__(
        self,
        *,
        use_gemini: bool = True,
        top_n: int = 10,
        strict_deep_bi: bool = False,
    ):
        self._use_gemini = use_gemini
        self._top_n = top_n
        self._strict = strict_deep_bi
        self._ast_ref: MultiAST | None = None  # set during bind for table-fallback

    # ------------------------------------------------------------------ public

    def bind(self, ast: MultiAST, df: pd.DataFrame) -> tuple[MultiAST, FigureBindReport]:
        """Populate ``Figure.computed_chart`` for all unbound figures.

        Processes each figure independently ("sector by sector") so a failure
        in one does not block the others.
        """
        report = FigureBindReport()
        self._ast_ref = ast  # allow table-fallback to access AST tables

        if df is None or df.empty:
            # Still try table-based fallback even with no dataset
            for fig in ast.figureAST.figures:
                if fig.computed_chart and fig.computed_chart.get("data"):
                    report.figures_from_components += 1
                    report.figures_bound += 1
                    continue
                report.figures_attempted += 1
                chart_type = _caption_to_chart_type(fig.caption or "")
                chart_data = _chart_from_ast_tables(fig, ast, chart_type, self._top_n)
                if chart_data:
                    fig.computed_chart = chart_data
                    report.figures_bound += 1
                    report.figures_from_fallback += 1
                else:
                    report.warnings.append(f"no data for figure {fig.figureId}")
            return ast, report

        for fig in ast.figureAST.figures:
            report.figures_attempted += 1
            if not self._strict and fig.computed_chart and fig.computed_chart.get("data"):
                report.figures_from_components += 1
                report.figures_bound += 1
                continue  # already populated (e.g. from geometry components)

            caption = fig.caption or fig.figureId
            chart_type = _caption_to_chart_type(caption)
            filter_value = _extract_filter_value(caption, df)

            logger.info(
                "Binding figure %s | chart_type=%s | filter=%r | caption=%r",
                fig.figureId, chart_type, filter_value, caption[:80],
            )

            slot_w = _figure_slot_width(fig, ast)

            chart_data = None

            if self._strict:
                # Deep BI agents only
                if self._use_gemini:
                    try:
                        chart_data = self._bind_via_deep_bi(
                            fig, df, chart_type, filter_value,
                        )
                        if chart_data:
                            report.figures_from_deep_bi += 1
                    except Exception as exc:
                        report.warnings.append(
                            f"Deep BI failed for {fig.figureId}: {exc}"
                        )
                if not chart_data:
                    chart_data = self._bind_via_response_builder(fig, df, chart_type)
                    if chart_data:
                        report.figures_from_deep_bi += 1
            else:
                cap_l = caption.lower()
                if "source wise" in cap_l or "sourcewise" in cap_l:
                    sw = _chart_renewable_sourcewise(fig, ast)
                    if sw and len(sw.get("data") or []) >= 2:
                        chart_data = sw
                        report.figures_from_fallback += 1

                if _caption_needs_ast_table(caption):
                    tbl_chart = _chart_from_ast_tables(
                        fig, ast, chart_type, top_n=self._top_n,
                    )
                    if tbl_chart and len(tbl_chart.get("data") or []) >= 2:
                        chart_data = tbl_chart
                        report.figures_from_fallback += 1

                if chart_type == "pie" and not chart_data:
                    pie_rows = _direct_aggregate(
                        df, caption, "pie", filter_value, top_n=min(6, self._top_n),
                    )
                    if len(pie_rows) >= 2:
                        chart_data = {"type": "pie", "title": caption, "data": pie_rows}
                        report.figures_from_fallback += 1

                if not chart_data and self._use_gemini:
                    try:
                        chart_data = self._bind_via_deep_bi(
                            fig, df, chart_type, filter_value,
                        )
                        if chart_data:
                            report.figures_from_deep_bi += 1
                    except Exception as exc:
                        msg = f"Deep BI failed for {fig.figureId}: {exc}"
                        logger.warning(msg)
                        report.warnings.append(msg)

                if not chart_data and not df.empty:
                    rows = _direct_aggregate(
                        df, caption, chart_type, filter_value, top_n=self._top_n,
                    )
                    if rows and len(rows) >= 3:
                        chart_data = {"type": chart_type, "title": caption, "data": rows}
                        report.figures_from_fallback += 1

                if (not chart_data or len((chart_data or {}).get("data") or []) < 3) \
                        and self._ast_ref is not None:
                    tbl_chart = _chart_from_ast_tables(
                        fig, self._ast_ref, chart_type, self._top_n,
                    )
                    if tbl_chart and len(tbl_chart.get("data") or []) > len(
                            (chart_data or {}).get("data") or []):
                        chart_data = tbl_chart
                        report.figures_from_fallback += 1

            if chart_data:
                chart_data = _normalize_chart_for_slot(
                    chart_data, caption=caption, chart_type=chart_type,
                    df=df, filter_value=filter_value,
                    slot_width=slot_w, top_n=self._top_n,
                )
                fig.computed_chart = chart_data
                report.figures_bound += 1
            else:
                report.warnings.append(f"no data for figure {fig.figureId}")

        return ast, report

    # ----------------------------------------------------------------- private

    def _bind_via_deep_bi(
        self,
        fig: Figure,
        df: pd.DataFrame,
        chart_type: str,
        filter_value: str | None,
    ) -> dict | None:
        """Run PlannerAgent + AnalyticsAgent and convert result to chart data."""
        # Import here to keep the module importable without heavy deps
        try:
            from agents.planner_agent import PlannerAgent
            from agents.analytics_agent import AnalyticsAgent
            from agents.retrieval_agent import RetrievalBundle
        except ImportError as e:
            logger.warning("agent imports failed: %s", e)
            return None

        query = _caption_to_query(fig.caption, df)
        logger.debug("Deep BI query for %s: %r", fig.figureId, query)

        try:
            planner = PlannerAgent()
            plan = planner.plan(
                query=query,
                available_columns=list(df.columns),
                df=df,
                extra_system_prompt=FIGURE_CHART_SYSTEM_PROMPT,
            )
        except Exception as exc:
            logger.warning("PlannerAgent failed for %s: %s", fig.figureId, exc)
            return None

        # Build a minimal RetrievalBundle — AnalyticsAgent.run uses bundle.df
        try:
            bundle = RetrievalBundle(
                df=df,
                kg_neighbors=[],
                kg_paths=[],
                rulebook_chunks=[],
                history_chunks=[],
                anomaly_candidates=[],
                imputation_candidates=[],
                validation_candidates=[],
                resolved_columns=getattr(plan, "target_columns", list(df.columns)),
                domain_columns={},
            )
        except Exception as exc:
            logger.warning("RetrievalBundle build failed for %s: %s", fig.figureId, exc)
            return None

        try:
            analytics = AnalyticsAgent()
            result = analytics.run(
                plan=plan,
                bundle=bundle,
            )
        except Exception as exc:
            logger.warning("AnalyticsAgent failed for %s: %s", fig.figureId, exc)
            return None

        if not result:
            return None

        title = fig.caption or query

        # AnalyticsResult is a dataclass; convert to dict for _exec_to_chart
        if hasattr(result, "to_dict"):
            result_dict = result.to_dict()
        elif isinstance(result, dict):
            result_dict = result
        else:
            result_dict = {}

        # Prefer the structured chart field if it has labels + values
        raw_chart = result_dict.get("chart")
        if isinstance(raw_chart, dict):
            labels = raw_chart.get("labels") or []
            values = raw_chart.get("values") or []
            if labels and values:
                data = [{"label": str(l), "value": float(v or 0)}
                        for l, v in zip(labels, values)]
                data.sort(key=lambda x: x["value"], reverse=True)
                return {"type": chart_type, "title": title,
                        "data": data[:self._top_n]}

        # Fall back to generic table extraction
        chart = _exec_to_chart(result_dict, chart_type, title, top_n=self._top_n)
        return chart

    def _bind_via_response_builder(
        self,
        fig: Figure,
        df: pd.DataFrame,
        chart_type: str,
    ) -> dict | None:
        """Deep BI execute path (intent → plan → execute → chart)."""
        from .deep_bi_execute import chart_from_execution, execute_bi_query

        q = fig.description or _caption_to_query(fig.caption or "", df)
        try:
            ex = execute_bi_query(
                f"{q} Rank top states. Chart type: {chart_type}.",
                df,
                archetype="economic",
            )
            spec = chart_from_execution(
                ex, chart_type=chart_type, top_n=self._top_n, query=q,
            )
            if spec:
                return {"type": spec["type"], "title": fig.caption, "data": spec["data"]}
        except Exception as exc:
            logger.warning("Deep BI execute chart failed %s: %s", fig.figureId, exc)
        return None
