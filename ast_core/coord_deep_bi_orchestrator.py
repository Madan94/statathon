"""Strict Deep BI orchestration: AST queries → fill paragraphs, tables, figures."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .coord_content_binder import CoordContentBinder, ContentBindReport
from .coord_loader import load_coord_ast
from .coord_table_binder import CoordTableBinder, TableBindReport
from .deep_bi_binder import DeepBIFigureBinder, FigureBindReport
from .domain_remap import apply_heading_remap, clear_prefilled_slots
from .loader import save_multi_ast
from .query_builder import attach_queries
from .renderer import render_ast_to_pdf
from .schema import MultiAST

logger = logging.getLogger(__name__)


@dataclass
class StrictBindReport:
    content: ContentBindReport = field(default_factory=ContentBindReport)
    tables: TableBindReport = field(default_factory=TableBindReport)
    figures: FigureBindReport = field(default_factory=FigureBindReport)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _prepare_ast(ast: MultiAST, df: pd.DataFrame, *, domain: str) -> None:
    """Structure-only prep: remap headings, clear old data, attach BI queries."""
    clear_prefilled_slots(ast)
    if domain == "economics":
        apply_heading_remap(ast)
    attach_queries(ast, df)


def bind_ast_strict(
    ast: MultiAST,
    df: pd.DataFrame,
    *,
    use_gemini: bool = True,
    top_n: int = 10,
) -> tuple[MultiAST, StrictBindReport]:
    """Fill all slots via Deep BI only. Records errors instead of silent fallback."""
    report = StrictBindReport()
    if df.empty:
        report.errors.append("dataset is empty")
        return ast, report

    content_binder = CoordContentBinder(use_gemini=use_gemini, strict=True)
    ast, report.content = content_binder.bind(ast, df)

    table_binder = CoordTableBinder()
    ast, report.tables = table_binder.bind(ast, df)

    fig_binder = DeepBIFigureBinder(
        use_gemini=use_gemini, top_n=top_n, strict_deep_bi=True,
    )
    ast, report.figures = fig_binder.bind(ast, df)

    if report.content.paragraphs_bound < report.content.paragraphs_attempted:
        report.errors.append(
            f"paragraphs: {report.content.paragraphs_bound}/"
            f"{report.content.paragraphs_attempted} bound via Deep BI"
        )
    if report.tables.tables_bound < report.tables.tables_attempted:
        report.errors.append(
            f"tables: {report.tables.tables_bound}/"
            f"{report.tables.tables_attempted} bound via Deep BI"
        )
    if report.figures.figures_bound < report.figures.figures_attempted:
        report.errors.append(
            f"figures: {report.figures.figures_bound}/"
            f"{report.figures.figures_attempted} bound via Deep BI"
        )
    report.errors.extend(report.content.warnings)
    report.errors.extend(report.tables.warnings)
    report.errors.extend(report.figures.warnings)

    return ast, report


@dataclass
class CoordReportResult:
    pdf_path: str
    bound_ast_path: str
    page_count: int
    bind_report: StrictBindReport = field(default_factory=StrictBindReport)
    overflow_warnings: list[str] = field(default_factory=list)


def run_coord_report_strict(
    *,
    ast_path: str | Path,
    data_path: str | Path,
    out_pdf: str | Path,
    domain: str = "economics",
    use_gemini: bool = True,
    top_n: int = 10,
) -> CoordReportResult:
    ast = load_coord_ast(ast_path)
    df = pd.read_csv(data_path) if Path(data_path).exists() else pd.DataFrame()

    _prepare_ast(ast, df, domain=domain)
    ast, bind_report = bind_ast_strict(ast, df, use_gemini=use_gemini, top_n=top_n)

    render = render_ast_to_pdf(
        ast, out_path=str(out_pdf), allow_overflow=True, auto_plan_geometry=False,
    )
    bound_ast_path = str(out_pdf).replace(".pdf", "_bound_ast.json")
    save_multi_ast(ast, bound_ast_path)

    return CoordReportResult(
        pdf_path=render.pdf_path,
        bound_ast_path=bound_ast_path,
        page_count=render.page_count,
        bind_report=bind_report,
        overflow_warnings=list(render.overflow_warnings or []),
    )
