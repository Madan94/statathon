"""generate_coord_report.py — Coordinate-exact report from fina-ast.json.

End-to-end pipeline:
  1. Load the coordinate-based AST (fina-ast.json) via coord_loader.
     • Inline block bboxes are promoted into GeometryAST nodes.
     • Pre-computed geometry components (e.g. fig_005 pie slices) are bound
       immediately to the matching Figure.
  2. Load the dataset (default: unified_energy_reserves_dataset.csv).
  3. Deep BI figure binder runs sector-by-sector:
     • For each figure without chart data: derives a query from the caption,
       runs PlannerAgent → AnalyticsAgent, converts result to chart data.
     • Falls back to direct DataFrame aggregation on BI failure.
  4. TemplateBinder populates table rows from the dataset (generic, no hardcoding).
  5. render_ast_to_pdf renders every block at its exact declared coordinates.
  6. Output PDF + bound AST JSON saved to storage/reports/.

Usage
-----
    python scripts/generate_coord_report.py
    python scripts/generate_coord_report.py --ast test_data/fina-ast.json \
        --data test_data/unified_energy_reserves_dataset.csv \
        --out storage/reports/coord_report.pdf \
        --no-gemini           # skip Gemini, use direct aggregation only
        --no-table-bind       # skip table binding (render AST tables as-is)

Dynamic / generic
-----------------
Nothing in this script is hardcoded to a specific dataset or AST.
Swap --ast and --data for any compatible pair and the pipeline adapts.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Make repo root importable regardless of cwd
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(_REPO / ".env")
except Exception:
    pass

import pandas as pd

from ast_core.coord_loader import load_coord_ast
from ast_core.deep_bi_binder import DeepBIFigureBinder
from ast_core.renderer import render_ast_to_pdf
from ast_core import save_multi_ast

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("generate_coord_report")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ast",  default=str(_REPO / "test_data" / "fina-ast.json"),
                   help="Path to coordinate-based AST JSON")
    p.add_argument("--data", default=str(_REPO / "test_data" / "unified_energy_reserves_dataset.csv"),
                   help="Path to dataset CSV")
    p.add_argument("--out",  default="",
                   help="Output PDF path (default: storage/reports/coord_report_<stamp>.pdf)")
    p.add_argument("--no-gemini",     dest="use_gemini",    action="store_false",
                   help="Skip Gemini; use direct aggregation for all figures")
    p.add_argument("--no-table-bind", dest="bind_tables",   action="store_false",
                   help="Skip TemplateBinder table rows; render tables from AST as-is")
    p.add_argument("--top-n", type=int, default=10,
                   help="Max bars/slices per chart (default 10)")
    p.set_defaults(use_gemini=True, bind_tables=True)
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run(
    ast_path: str,
    data_path: str,
    out_pdf: str,
    *,
    use_gemini: bool = True,
    bind_tables: bool = True,
    top_n: int = 10,
) -> str:
    stamp = datetime.utcnow().strftime("%H%M%S")

    # ----- Step 1: Load coordinate AST -----
    print("=" * 76)
    print("STEP 1 — Load coordinate AST")
    ast = load_coord_ast(ast_path)
    n_geom = len(ast.geometryAST.nodes)
    n_tables = len(ast.tableAST.tables)
    n_figs = len(ast.figureAST.figures)
    pre_bound = sum(1 for f in ast.figureAST.figures
                    if f.computed_chart and f.computed_chart.get("data"))
    print(f"  AST file     : {ast_path}")
    print(f"  pages        : {len(ast.layoutAST.pages)}")
    print(f"  geometry nodes: {n_geom}  (includes promoted inline bboxes)")
    print(f"  tables       : {n_tables}")
    print(f"  figures      : {n_figs}  ({pre_bound} pre-bound from geometry components)")

    # ----- Step 2: Load dataset -----
    print("\nSTEP 2 — Load dataset")
    if not Path(data_path).exists():
        logger.warning("Dataset not found at %s — figures will use direct aggregation", data_path)
        df = pd.DataFrame()
    else:
        df = pd.read_csv(data_path)
    print(f"  Dataset      : {data_path}")
    print(f"  Shape        : {df.shape}   columns: {list(df.columns)[:8]}{'...' if len(df.columns) > 8 else ''}")

    # ----- Step 3: Deep BI figure binder — sector by sector -----
    print("\nSTEP 3 — Deep BI figure binder (sector by sector)")
    gemini_key = __import__("os").getenv("GEMINI_API_KEY") or __import__("os").getenv("GOOGLE_API_KEY")
    if use_gemini:
        print(f"  Gemini API key : {'set' if gemini_key else 'MISSING — using fallback aggregation'}")
    if not df.empty:
        binder = DeepBIFigureBinder(use_gemini=use_gemini, top_n=top_n)
        ast, fig_report = binder.bind(ast, df)
        print(f"  figures attempted       : {fig_report.figures_attempted}")
        print(f"  bound via components    : {fig_report.figures_from_components}")
        print(f"  bound via Deep BI       : {fig_report.figures_from_deep_bi}")
        print(f"  bound via fallback agg  : {fig_report.figures_from_fallback}")
        print(f"  total bound             : {fig_report.figures_bound}")
        if fig_report.warnings:
            print(f"  warnings ({len(fig_report.warnings)}):")
            for w in fig_report.warnings[:6]:
                print(f"    - {w}")
        # Print summary of each figure's chart
        for fig in ast.figureAST.figures:
            ch = fig.computed_chart or {}
            n_pts = len(ch.get("data") or [])
            print(f"    {fig.figureId:10s}  type={ch.get('type','?'):4s}  points={n_pts:2d}"
                  f"  caption={fig.caption[:55]!r}")
    else:
        print("  (no dataset — skipping figure binding)")

    # ----- Step 4: Table binding -----
    # Coordinate ASTs (fina-ast) ship complete rows incl. distribution %;
    # TemplateBinder overwrite drops columns not in the CSV.
    ast_tables_complete = (
        n_tables > 0
        and all(len(t.rows) >= 2 and len(t.columns) >= 3 for t in ast.tableAST.tables)
    )
    step4_logged = False
    if ast_tables_complete and bind_tables:
        print("\nSTEP 4 — Tables from AST (pre-populated; skipping dataset overwrite)")
        for t in ast.tableAST.tables:
            print(f"    {t.tableId}: '{t.title[:55]}'  rows={len(t.rows)}")
        bind_tables = False
        step4_logged = True

    if bind_tables and not df.empty and n_tables > 0:
        print("\nSTEP 4 — Table binding via TemplateBinder")
        try:
            from ast_core.template_binder import TemplateBinder
            tb = TemplateBinder()
            ast, tb_report = tb.bind(ast, df)
            print(f"  tables_bound  : {tb_report.tables_bound}")
            print(f"  cells_filled  : {tb_report.cells_filled}")
            print(f"  warnings      : {len(tb_report.warnings)}")
            for t in ast.tableAST.tables:
                print(f"    {t.tableId}: '{t.title[:55]}'  rows={len(t.rows)}")
        except Exception as exc:
            logger.warning("TemplateBinder failed: %s — tables rendered from AST", exc)
        step4_logged = True
    elif not step4_logged and n_tables > 0:
        print("\nSTEP 4 — Tables rendered from AST data")
        for t in ast.tableAST.tables:
            print(f"    {t.tableId}: '{t.title[:55]}'  rows={len(t.rows)}")

    # ----- Step 5: Render -----
    print("\nSTEP 5 — Render PDF (coordinate-exact)")
    if not out_pdf:
        reports_dir = _REPO / "storage" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_pdf = str(reports_dir / f"coord_report_{stamp}.pdf")

    result = render_ast_to_pdf(ast, out_path=out_pdf, allow_overflow=True,
                                auto_plan_geometry=False)
    print(f"  PDF path     : {result.pdf_path}")
    print(f"  pages        : {result.page_count}")
    print(f"  size         : {os.path.getsize(result.pdf_path):,} bytes")
    print(f"  SHA-256      : {result.content_hash}")
    if result.overflow_warnings:
        print(f"  overflow warnings ({len(result.overflow_warnings)}):")
        for w in result.overflow_warnings[:8]:
            print(f"    - {w}")

    # ----- Step 6: Save bound AST for inspection -----
    ast_out = out_pdf.replace(".pdf", "_bound_ast.json")
    save_multi_ast(ast, ast_out)
    print(f"\n  Bound AST    : {ast_out}")
    print(f"  PDF          : {result.pdf_path}")
    print("=" * 76)
    return result.pdf_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    args = _parse_args()
    run(
        ast_path=args.ast,
        data_path=args.data,
        out_pdf=args.out,
        use_gemini=args.use_gemini,
        bind_tables=args.bind_tables,
        top_n=args.top_n,
    )
