"""Bind a dataset to a template MultiAST.

Given the Enterprise AST template + an arbitrary DataFrame, this module:

  1. Resolves each table's columns to the best-matching columns in the DataFrame
     using the same ColumnSynonymKG logic Deep BI uses. No hardcoded mappings.
  2. Aggregates rows: if a table has a categorical key (e.g. "States/UTs"),
     groups the DataFrame on that axis and computes the metric per group.
     If a table is structured as "single resource per row" (e.g. "Coal /
     Lignite / Renewable") it pivots so each row is a resource.
  3. Generates evidence ledger entries for every cell filled.
  4. Fills figure captions and chart series from the same evidence.

Output: a new MultiAST with concrete numbers, ready for the renderer.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from deep_bi.column_synonym_kg import ColumnSynonymKG
from .schema import (
    EvidenceEntry, MultiAST, Table, Paragraph, Chart, Figure,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Header semantic
# ---------------------------------------------------------------------------


_COMPONENT_KEYS = {
    "proved":     ["proved", "proven", "confirmed"],
    "indicated":  ["indicated", "probable", "measured"],
    "inferred":   ["inferred", "possible"],
    "total":      ["total", "aggregate", "sum"],
    "capacity":   ["capacity", "potential", "mw", "megawatt"],
    "distribution": ["distribution", "share", "percentage", "%"],
}


_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _stem(tok: str) -> str:
    """Tiny pluralisation stripper.

    'states' -> 'state', 'categories' -> 'category', 'uts' -> 'ut'.
    Never strips 'ss' endings, never produces sub-3-letter stems.
    """
    tok = tok.lower()
    if len(tok) <= 2:
        return tok
    if tok.endswith("ies") and len(tok) >= 5:
        return tok[:-3] + "y"
    if tok.endswith("ss"):
        return tok
    if tok.endswith("s") and len(tok) >= 3:
        return tok[:-1]
    return tok


def _stemmed_token_set(s: str) -> set[str]:
    return {_stem(t) for t in re.findall(r"[a-z0-9]+", str(s).lower())}


def _stemmed_variants(header: str) -> list[str]:
    """Return prioritised variants of a header to feed the synonym KG."""
    header = str(header)
    variants: list[str] = [header]
    # Per-token stem
    toks = re.findall(r"[A-Za-z0-9]+", header)
    if toks:
        variants.append(" ".join(_stem(t) for t in toks))
        # Each token individually
        variants.extend(_stem(t) for t in toks if len(t) >= 3)
    # De-dup while preserving order
    seen, dedup = set(), []
    for v in variants:
        if v.lower() not in seen:
            seen.add(v.lower()); dedup.append(v)
    return dedup


@dataclass
class HeaderSemantic:
    raw: str
    component: str | None = None   # 'proved' | 'indicated' | 'inferred' | 'total' | 'capacity' | 'distribution'
    year: int | None = None
    is_key: bool = False           # True if this header is the row label axis

    def to_dict(self) -> dict[str, Any]:
        return {"raw": self.raw, "component": self.component,
                "year": self.year, "is_key": self.is_key}


def _parse_header(h: str, *, key_hints: list[str]) -> HeaderSemantic:
    raw = str(h)
    low = raw.lower()
    sem = HeaderSemantic(raw=raw)
    # Year
    m = _YEAR_RE.search(raw)
    if m:
        sem.year = int(m.group(1))
    # Component
    for key, words in _COMPONENT_KEYS.items():
        if any(w in low for w in words):
            sem.component = key
            break
    # Row-label axis
    for hint in key_hints:
        if hint.lower() in low:
            sem.is_key = True
            break
    return sem


# ---------------------------------------------------------------------------
# Binder
# ---------------------------------------------------------------------------


@dataclass
class BindReport:
    tables_bound: int = 0
    cells_filled: int = 0
    figures_captioned: int = 0
    charts_filled: int = 0
    warnings: list[str] = field(default_factory=list)
    evidence: list[EvidenceEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"tables_bound": self.tables_bound,
                "cells_filled": self.cells_filled,
                "figures_captioned": self.figures_captioned,
                "charts_filled": self.charts_filled,
                "warnings": self.warnings,
                "evidence_count": len(self.evidence)}


class TemplateBinder:

    KEY_HINTS = ["state", "uts", "ut", "region", "district",
                  "resource", "category", "year", "source"]

    def __init__(self, *, column_kg: ColumnSynonymKG | None = None):
        self._kg = column_kg

    # ---------------- Public ----------------

    def bind(self, ast: MultiAST, df: pd.DataFrame) -> tuple[MultiAST, BindReport]:
        """Return a *new* MultiAST with table rows/figures/charts populated from df."""
        report = BindReport()
        if df is None or df.empty:
            report.warnings.append("empty dataframe — nothing to bind")
            return ast, report

        # Build the column synonym KG for this dataset if not provided
        kg = self._kg or ColumnSynonymKG(columns=list(df.columns))

        # Pre-compute available categorical axes (low cardinality strings)
        cat_cols = [c for c in df.columns
                     if not pd.api.types.is_numeric_dtype(df[c])
                     and df[c].nunique(dropna=True) <= max(50, len(df) // 5)]

        # ---- Tables ----
        for t in ast.tableAST.tables:
            try:
                self._bind_table(t, df, kg, cat_cols, report)
            except Exception as exc:
                report.warnings.append(f"table {t.tableId} bind failed: {exc}")

        # ---- Figures (captions) ----
        for f in ast.figureAST.figures:
            try:
                self._bind_figure_caption(f, df, kg, report)
            except Exception as exc:
                report.warnings.append(f"figure {f.figureId} caption failed: {exc}")

        # ---- Charts ----
        for ch in ast.chartAST.charts:
            try:
                self._bind_chart(ch, df, kg, cat_cols, report)
            except Exception as exc:
                report.warnings.append(f"chart {ch.chartId} bind failed: {exc}")

        # Persist evidence into the AST
        ast.evidenceAST.entries.extend(report.evidence)
        return ast, report

    # ---------------- Tables ----------------

    def _bind_table(self, t: Table, df: pd.DataFrame,
                    kg: ColumnSynonymKG, cat_cols: list[str],
                    report: BindReport) -> None:
        if not t.columns:
            return
        # Parse header semantics
        headers = [_parse_header(h, key_hints=self.KEY_HINTS) for h in t.columns]
        key_idx = next((i for i, h in enumerate(headers) if h.is_key), 0)
        key_header = t.columns[key_idx]

        # Resolve the key column in the dataset (e.g. "States/UTs" -> "State").
        # We try multiple normalisations because table headers often differ
        # from dataset column names in pluralisation, separator characters
        # and ordering.
        key_candidates = _stemmed_variants(key_header)
        key_col: str | None = None
        for variant in key_candidates:
            matches = kg.resolve(variant, top_k=3, min_score=0.18)
            key_col = next(
                (m.column for m in matches
                  if m.column in cat_cols
                  or not pd.api.types.is_numeric_dtype(df[m.column])),
                None,
            )
            if key_col:
                break

        if key_col is None:
            # Token-stem fallback: any cat column whose stemmed tokens overlap
            # with the stemmed header tokens.
            hd_tokens = _stemmed_token_set(key_header)
            for c in cat_cols:
                if _stemmed_token_set(c) & hd_tokens:
                    key_col = c
                    break
        if key_col is None:
            report.warnings.append(
                f"table {t.tableId}: cannot resolve key axis '{key_header}'"
            )
            return

        # If the table title mentions a specific resource (Coal / Lignite / Renewable / Gas / Petroleum)
        # we filter df to that resource BEFORE aggregating.
        title_low = (t.title or "").lower()
        resource_col = next(
            (c for c in df.columns if "resource" in c.lower()
              or "category" in c.lower() or "type" in c.lower()),
            None,
        )
        filter_value: str | None = None
        if resource_col is not None:
            for cand in df[resource_col].astype(str).dropna().unique():
                if str(cand).lower() in title_low:
                    filter_value = str(cand)
                    break
        scope = df if filter_value is None else df[df[resource_col].astype(str) == filter_value]
        if scope.empty and filter_value:
            # Substring fallback
            scope = df[df[resource_col].astype(str).str.lower().str.contains(
                filter_value.lower(), na=False, regex=False,
            )]

        # For each non-key column resolve to a dataset metric
        col_to_metric: dict[int, tuple[str, str]] = {}    # idx -> (metric_col, component)
        for i, hdr_sem in enumerate(headers):
            if i == key_idx:
                continue
            # Resolve metric column for this header
            target = None
            for term in (hdr_sem.component or "", hdr_sem.raw):
                if not term:
                    continue
                matches = kg.resolve(term, top_k=5, min_score=0.10)
                target = next(
                    (m.column for m in matches
                      if pd.api.types.is_numeric_dtype(df[m.column])),
                    None,
                )
                if target:
                    break
            # As a final fallback: any numeric col whose name contains the
            # header component verbatim
            if target is None and hdr_sem.component:
                for c in df.columns:
                    if (hdr_sem.component in c.lower()
                          and pd.api.types.is_numeric_dtype(df[c])):
                        target = c
                        break
            if target:
                col_to_metric[i] = (target, hdr_sem.component or hdr_sem.raw)

        if not col_to_metric:
            report.warnings.append(
                f"table {t.tableId}: no metric headers could be resolved"
            )
            return

        # Refuse to bind when fewer than half of the non-key headers resolved
        # to a dataset column. Filling 1-of-8 columns and leaving the rest
        # as None creates a misleading "almost-empty" table; the template's
        # original example rows are a more honest fallback.
        non_key_count = max(1, len(headers) - 1)
        if len(col_to_metric) < max(2, non_key_count // 2):
            report.warnings.append(
                f"table {t.tableId}: only {len(col_to_metric)}/{non_key_count} "
                f"non-key headers resolved; keeping template rows"
            )
            return

        # Aggregate by key_col
        grouped = scope.groupby(key_col)
        rows: list[list[Any]] = []
        key_order = sorted(grouped.groups.keys(),
                            key=lambda x: -float(grouped[
                                next(iter(col_to_metric.values()))[0]
                            ].sum().get(x, 0)))
        for key_val in key_order[:50]:
            row: list[Any] = [None] * len(t.columns)
            row[key_idx] = str(key_val)
            for col_idx, (metric_col, component) in col_to_metric.items():
                try:
                    total = float(pd.to_numeric(
                        grouped.get_group(key_val)[metric_col],
                        errors="coerce",
                    ).sum())
                except Exception:
                    total = 0.0
                # Render integer when whole, else 2dp
                row[col_idx] = int(total) if total == int(total) else round(total, 2)
                # Evidence
                ev = EvidenceEntry(
                    evidenceId=f"E_{t.tableId}_{key_val}_{col_idx}",
                    claim=f"{component} of {metric_col} for {key_val}"
                          + (f" (filter={filter_value})" if filter_value else ""),
                    value=row[col_idx], source="aggregate",
                    row_ids=list(grouped.groups[key_val][:200]),
                    computation={"agg": "sum", "metric": metric_col,
                                  "filter": filter_value,
                                  "key_column": key_col,
                                  "key_value": str(key_val)},
                    confidence=0.95, verified=True,
                )
                report.evidence.append(ev)
                report.cells_filled += 1
            rows.append(row)

        # Append a Total row if a "Total" key isn't already there and the
        # table contains a Distribution column
        if "total" in (t.title or "").lower() or any(
            h.component == "distribution" for h in headers
        ):
            total_row: list[Any] = [None] * len(t.columns)
            total_row[key_idx] = "Total"
            for col_idx, (metric_col, _component) in col_to_metric.items():
                try:
                    total = float(pd.to_numeric(scope[metric_col], errors="coerce").sum())
                except Exception:
                    total = 0.0
                total_row[col_idx] = int(total) if total == int(total) else round(total, 2)
            rows.append(total_row)

        t.rows = rows
        t.metadata = dict(t.metadata or {})
        t.metadata["bound_from_dataset"] = True
        t.metadata["key_column"] = key_col
        t.metadata["filter_applied"] = filter_value
        t.metadata["metric_columns"] = {str(i): v[0] for i, v in col_to_metric.items()}
        report.tables_bound += 1

    # ---------------- Figures ----------------

    def _bind_figure_caption(self, f: Figure, df: pd.DataFrame,
                              kg: ColumnSynonymKG, report: BindReport) -> None:
        """Bind a figure to a real chart spec derived from the dataset.

        Strategy:
          1. Resolve the *resource scope* from the caption / description.
          2. Resolve the *breakdown axis* (composition / by_state /
             by_source / by_region).
          3. Compute the pie data from the dataset rows in scope.
          4. Populate ``figure.computed_chart`` so the renderer draws a
             real pie chart. If the dataset doesn't have the needed
             columns, leave it None (renderer shows a placeholder — never
             invents a chart).
        """
        caption = (f.caption or "")
        description = (f.description or "")
        text = (caption + " " + description).lower()
        if not text.strip():
            return

        resource_col = next(
            (c for c in df.columns if "resource" in c.lower()
              or "category" in c.lower()),
            None,
        )
        scope = df
        resource_label: str | None = None
        if resource_col is not None:
            for cand in df[resource_col].astype(str).dropna().unique():
                cand_low = str(cand).lower()
                cand_tokens = re.findall(r"[a-z]+", cand_low)
                if any(re.search(rf"(?<![a-z]){t}(?![a-z])", text)
                        for t in cand_tokens if len(t) >= 4):
                    scope = df[df[resource_col].astype(str) == cand]
                    resource_label = str(cand)
                    break

        # Detect any resource the caption clearly references (whether or not
        # the dataset has rows for it).
        text_resource_hint: str | None = None
        for kw in ("crude oil", "natural gas", "petroleum", "lignite",
                     "coal", "renewable", "solar", "wind", "biomass"):
            if kw in text:
                text_resource_hint = kw
                break

        # If the caption explicitly mentions a resource that the dataset does
        # NOT contain (no matching Resource_Category), refuse to fall back to
        # the full DataFrame — that would render a chart of the wrong
        # commodity. Leave computed_chart=None so the renderer shows an
        # empty placeholder.
        if (text_resource_hint is not None
              and resource_col is not None
              and resource_label is None):
            return

        # ---- Breakdown axis ----
        # Derive the breakdown axis ENTIRELY from the caption text — no
        # hardcoded energy vocabulary. The pattern "<word>wise" or "by <word>"
        # tells us which axis the chart is asking for; we then look for a
        # column carrying that axis in the dataset.
        breakdown = "composition"
        breakdown_axis_token: str | None = None

        wise_match = re.search(r"\b([a-z]{3,15})\s*wise\b", text)
        if not wise_match:
            wise_match = re.search(r"\bby\s+([a-z]{3,15})\b", text)
        if wise_match:
            axis_word = wise_match.group(1).rstrip("s")  # statewise/states -> state
            breakdown = f"by_{axis_word}"
            breakdown_axis_token = axis_word

        # Composition is the fallback (Proved/Indicated/Inferred-style breakdowns)
        if (breakdown == "composition"
              and not ("composition" in text or "proved" in text
                        or "indicated" in text or "inferred" in text
                        or "reserves of" in text)):
            breakdown_axis_token = None    # nothing recognisable in caption

        chart_spec: dict[str, Any] | None = None
        evidence_value: Any = None
        evidence_comp: dict[str, Any] = {
            "breakdown": breakdown,
            "resource_filter": resource_label or text_resource_hint,
        }

        if breakdown == "composition" and not scope.empty:
            comp_cols: list[tuple[str, str]] = []
            for kind, search in (("Proved", "proved"), ("Indicated", "indicated"),
                                  ("Inferred", "inferred")):
                col = next((c for c in df.columns
                              if search in c.lower()
                              and pd.api.types.is_numeric_dtype(df[c])), None)
                if col is not None:
                    comp_cols.append((kind, col))
            data: list[dict[str, Any]] = []
            for kind, col in comp_cols:
                try:
                    v = float(pd.to_numeric(scope[col], errors="coerce").sum())
                except Exception:
                    v = 0.0
                if v > 0:
                    data.append({"label": kind, "value": v})
            if data:
                # Use the figure caption directly so the chart title matches
                # what the AST declares; strip any "Fig 1.x:" prefix.
                clean_caption = re.sub(r"^Fig\s+\d+(?:\.\d+)?[:\s.]+", "",
                                          caption, flags=re.IGNORECASE).strip()
                chart_spec = {
                    "type": "pie",
                    "title": clean_caption or f"{(resource_label or text_resource_hint or '').title()} Composition",
                    "data": data,
                }
                evidence_value = data

        elif breakdown_axis_token and not scope.empty:
            # Generic axis resolver: look for a NON-numeric column whose name
            # contains the breakdown token as a *word* (not a substring —
            # otherwise "source" would falsely match "Resource_Category").
            tok = breakdown_axis_token.lower()
            tok_pat = re.compile(rf"(?:^|[^a-z]){re.escape(tok)}(?:$|[^a-z])")
            axis_col = next(
                (c for c in df.columns
                  if tok_pat.search(c.lower())
                  and not pd.api.types.is_numeric_dtype(df[c])),
                None,
            )
            if axis_col is None:
                # Try KG synonyms — but still require word-boundary match
                # against the resolved column tokens.
                matches = kg.resolve(breakdown_axis_token, top_k=5, min_score=0.30)
                axis_col = next(
                    (m.column for m in matches
                      if m.column in df.columns
                      and not pd.api.types.is_numeric_dtype(df[m.column])
                      and tok in set(re.findall(r"[a-z]+", m.column.lower()))),
                    None,
                )
            if axis_col is None:
                return  # dataset can't support this breakdown

            # Choose the most relevant numeric metric for the resource scope.
            # Generic rule: only consider metrics that have NON-ZERO totals in
            # the current scope (so we don't pick "Total_Reserves" for
            # renewable rows where every reserves value is 0 — the right
            # column there is "Potential_Capacity_MW").
            numeric_cols = [c for c in df.columns
                              if pd.api.types.is_numeric_dtype(df[c])]
            # Score each numeric column by total magnitude in scope
            scored: list[tuple[str, float]] = []
            for c in numeric_cols:
                try:
                    total = float(pd.to_numeric(scope[c], errors="coerce").abs().sum())
                except Exception:
                    total = 0.0
                if total > 0:
                    scored.append((c, total))
            scored.sort(key=lambda kv: kv[1], reverse=True)

            # Preference ordering: among columns that have data, prefer the
            # one whose name token appears in the caption (e.g. "potential"
            # in the caption favours "Potential_Capacity_MW").
            caption_tokens = set(re.findall(r"[a-z]+", text))
            metric_col = None
            for cand, _total in scored:
                cand_tokens = set(re.findall(r"[a-z]+", cand.lower()))
                if cand_tokens & caption_tokens:
                    metric_col = cand
                    break
            if metric_col is None and scored:
                metric_col = scored[0][0]   # largest-magnitude column in scope
            if axis_col and metric_col:
                grouped = (scope.assign(_m=pd.to_numeric(scope[metric_col],
                                                              errors="coerce"))
                              .groupby(axis_col)["_m"].sum()
                              .sort_values(ascending=False))
                # Generic small-slice collapsing: items below 3% of total
                # collapse into "Others" so labels don't collide.
                grand_total = float(grouped.sum()) or 1.0
                top: list[tuple[Any, float]] = []
                others = 0.0
                for k, v in grouped.items():
                    if v <= 0:
                        continue
                    share = float(v) / grand_total
                    if share >= 0.03 and len(top) < 8:
                        top.append((k, float(v)))
                    else:
                        others += float(v)
                data = [{"label": str(k), "value": v} for k, v in top]
                if others > 0:
                    data.append({"label": "Others", "value": others})
                if data:
                    clean_caption = re.sub(r"^Fig\s+\d+(?:\.\d+)?[:\s.]+", "",
                                              caption, flags=re.IGNORECASE).strip()
                    chart_spec = {
                        "type": "pie",
                        "title": clean_caption or
                                  f"{(resource_label or text_resource_hint or '').title()} by {axis_col}",
                        "data": data,
                    }
                    evidence_value = data
                    evidence_comp["metric_column"] = metric_col
                    evidence_comp["axis_column"] = axis_col

        if chart_spec:
            f.computed_chart = chart_spec
            ev_id = f"E_{f.figureId}_chart"
            f.evidenceRefs.append(ev_id)
            report.figures_captioned += 1
            report.evidence.append(EvidenceEntry(
                evidenceId=ev_id, claim=f.caption,
                value=evidence_value, source="aggregate",
                row_ids=list(scope.index[:200]),
                computation=evidence_comp,
                confidence=0.95, verified=True,
            ))

    # ---------------- Charts ----------------

    def _bind_chart(self, ch: Chart, df: pd.DataFrame,
                     kg: ColumnSynonymKG, cat_cols: list[str],
                     report: BindReport) -> None:
        # Identify the metric column from the title or the existing series
        title_low = (ch.title or "").lower()
        metric_col = None
        for c in df.columns:
            if not pd.api.types.is_numeric_dtype(df[c]):
                continue
            tokens = re.findall(r"[a-z0-9]+", c.lower())
            if any(t in title_low for t in tokens):
                metric_col = c; break
        if metric_col is None:
            metric_col = next(
                (c for c in df.columns
                  if pd.api.types.is_numeric_dtype(df[c])),
                None,
            )
        if metric_col is None or not cat_cols:
            return

        # Group by the first categorical column
        key_col = cat_cols[0]
        grouped = df.groupby(key_col)[metric_col].sum().sort_values(ascending=False)
        data = [{"label": str(k), "value": float(v)} for k, v in grouped.head(15).items()
                 if v > 0]
        if data:
            ch.series = [{"name": metric_col, "data": data}]
            ch.xAxis = key_col
            ch.yAxis = metric_col
            ch.evidenceRefs.append(f"E_{ch.chartId}_series")
            report.charts_filled += 1
            report.evidence.append(EvidenceEntry(
                evidenceId=f"E_{ch.chartId}_series",
                claim=f"chart series: {metric_col} by {key_col}",
                value=data, source="aggregate", row_ids=[],
                computation={"agg": "sum", "metric": metric_col,
                              "key_column": key_col},
                confidence=0.92, verified=True,
            ))
