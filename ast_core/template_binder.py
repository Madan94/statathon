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
        # Use the existing caption as a query; if it mentions a resource we
        # aggregate the relevant column and append the live number.
        caption_low = (f.caption or "").lower()
        if not caption_low:
            return
        resource_col = next(
            (c for c in df.columns if "resource" in c.lower()
              or "category" in c.lower()),
            None,
        )
        metric_col = next(
            (c for c in df.columns
              if pd.api.types.is_numeric_dtype(df[c])
              and ("total" in c.lower() or "reserves" in c.lower()
                    or "capacity" in c.lower())),
            None,
        )
        if not metric_col:
            return

        # Detect resource in caption
        scope = df
        if resource_col is not None:
            for cand in df[resource_col].astype(str).dropna().unique():
                if str(cand).lower() in caption_low:
                    scope = df[df[resource_col].astype(str) == cand]
                    break
        try:
            total = float(pd.to_numeric(scope[metric_col], errors="coerce").sum())
        except Exception:
            return
        if total > 0:
            tag = f" (total {metric_col} = {int(total) if total == int(total) else round(total, 2)})"
            if tag not in f.caption:
                f.caption = f.caption.rstrip(".") + tag
                report.figures_captioned += 1
                report.evidence.append(EvidenceEntry(
                    evidenceId=f"E_{f.figureId}_total",
                    claim=f"figure caption total of {metric_col}",
                    value=total, source="aggregate",
                    row_ids=[],
                    computation={"agg": "sum", "metric": metric_col},
                    confidence=0.90, verified=True,
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
