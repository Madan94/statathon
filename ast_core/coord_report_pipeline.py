"""Unified coordinate report pipeline — strict Deep BI by default."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .coord_deep_bi_orchestrator import (
    CoordReportResult,
    StrictBindReport,
    bind_ast_strict,
    run_coord_report_strict,
)
from .coord_loader import load_coord_ast
from .domain_remap import apply_heading_remap, clear_prefilled_slots
from .loader import save_multi_ast
from .query_builder import attach_queries
from .renderer import render_ast_to_pdf

logger = logging.getLogger(__name__)

# Re-export strict runner as default
run_coord_report = run_coord_report_strict


def run_coord_report_legacy(
    *,
    ast_path: str | Path,
    data_path: str | Path,
    out_pdf: str | Path,
    domain: str = "economics",
    use_gemini: bool = True,
    bind_figures: bool = True,
    bind_content: bool = True,
    top_n: int = 10,
    strict_deep_bi: bool = True,
) -> CoordReportResult:
    """CLI-compatible entry; ``strict_deep_bi=True`` is the only supported path."""
    _ = bind_figures, bind_content
    return run_coord_report_strict(
        ast_path=ast_path,
        data_path=data_path,
        out_pdf=out_pdf,
        domain=domain,
        use_gemini=use_gemini,
        top_n=top_n,
    )
