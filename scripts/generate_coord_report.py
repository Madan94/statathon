"""generate_coord_report.py — Coordinate-exact report from fina-ast.json.

Unified pipeline (``ast_core.coord_report_pipeline``):
  1. Load coordinate AST (inline bboxes → geometry nodes)
  2. Domain remap (economics: retarget energy template → CPI dataset)
  3. Deep BI fills body paragraphs (ResponseBuilder + Gemini)
  4. Deep BI / domain logic fills figures and tables
  5. Render PDF at exact layout coordinates

Usage
-----
    python scripts/generate_coord_report.py
    python scripts/generate_coord_report.py --domain economics \\
        --data "test_data/Economics - MoSPI.csv" \\
        --ast test_data/fina-ast.json
    python scripts/generate_coord_report.py --domain energy --no-gemini
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(_REPO / ".env")
except Exception:
    pass

from ast_core.coord_deep_bi_orchestrator import run_coord_report_strict as run_coord_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("generate_coord_report")

_DEFAULT_AST = _REPO / "test_data" / "fina-ast.json"
_DEFAULT_ECON_DATA = _REPO / "test_data" / "Economics - MoSPI.csv"
_DEFAULT_ENERGY_DATA = _REPO / "test_data" / "unified_energy_reserves_dataset.csv"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ast", default=str(_DEFAULT_AST), help="Coordinate AST JSON")
    p.add_argument("--data", default="", help="Dataset CSV (default by --domain)")
    p.add_argument("--domain", choices=("economics", "energy"), default="economics",
                   help="Template domain remap (default: economics)")
    p.add_argument("--out", default="", help="Output PDF path")
    p.add_argument("--no-gemini", dest="use_gemini", action="store_false",
                   help="Skip Gemini narratives (Deep BI deterministic only)")
    p.add_argument("--no-content", dest="bind_content", action="store_false",
                   help="Skip paragraph Deep BI bind")
    p.add_argument("--no-figures", dest="bind_figures", action="store_false",
                   help="Skip figure binding")
    p.add_argument("--top-n", type=int, default=10)
    p.set_defaults(use_gemini=True, bind_content=True, bind_figures=True)
    return p.parse_args()


def main() -> str:
    args = _parse_args()
    data_path = args.data or (
        str(_DEFAULT_ECON_DATA) if args.domain == "economics" else str(_DEFAULT_ENERGY_DATA)
    )
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    out_pdf = args.out or str(_REPO / "storage" / "reports" / f"coord_report_{stamp}.pdf")

    print("=" * 76)
    print("Coordinate report pipeline")
    print(f"  AST     : {args.ast}")
    print(f"  Data    : {data_path}")
    print(f"  Domain  : {args.domain}")
    print(f"  Gemini  : {args.use_gemini}")
    print("=" * 76)

    if not args.bind_content and not args.bind_figures:
        print("Nothing to bind (content and figures disabled).")
        return ""

    result = run_coord_report(
        ast_path=args.ast,
        data_path=data_path,
        out_pdf=out_pdf,
        domain=args.domain,
        use_gemini=args.use_gemini,
        top_n=args.top_n,
    )

    br = result.bind_report
    cr, tr, fr = br.content, br.tables, br.figures
    print(f"\nStrict Deep BI bind:")
    print(f"  Paragraphs: {cr.paragraphs_bound}/{cr.paragraphs_attempted} "
          f"(gemini={cr.paragraphs_from_gemini}, evidence={cr.paragraphs_from_deep_bi})")
    print(f"  Tables:     {tr.tables_bound}/{tr.tables_attempted} (deep_bi={tr.tables_from_deep_bi})")
    print(f"  Figures:    {fr.figures_bound}/{fr.figures_attempted} "
          f"(deep_bi={fr.figures_from_deep_bi}, fallback={fr.figures_from_fallback})")
    if br.errors:
        for e in br.errors[:8]:
            print(f"  ERROR: {e}")

    print(f"\nPDF       : {result.pdf_path}")
    print(f"Bound AST : {result.bound_ast_path}")
    print(f"Pages     : {result.page_count}")
    print(f"Size      : {os.path.getsize(result.pdf_path):,} bytes")
    if result.overflow_warnings:
        print(f"Overflow warnings: {len(result.overflow_warnings)}")
    print("=" * 76)
    return result.pdf_path


if __name__ == "__main__":
    main()
