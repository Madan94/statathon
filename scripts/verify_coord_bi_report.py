"""Verify coordinate report pipeline: layout + Deep BI + chart render."""
from __future__ import annotations

import io
import sys
from pathlib import Path

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
from ast_core.renderer import _render_chart_png


def main() -> None:
    ast_path = _REPO / "test_data" / "fina-ast.json"
    data_path = _REPO / "test_data" / "unified_energy_reserves_dataset.csv"

    print("=" * 72)
    print("1. Load coordinate AST + compaction")
    ast = load_coord_ast(ast_path)
    df = pd.read_csv(data_path)

    import os
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    use_gemini = bool(key)
    print(f"2. Deep BI figure binder (gemini={'on' if use_gemini else 'off'})")
    binder = DeepBIFigureBinder(use_gemini=use_gemini, top_n=8)
    ast, report = binder.bind(ast, df)
    print(f"   bound={report.figures_bound}/{report.figures_attempted}")
    print(f"   deep_bi={report.figures_from_deep_bi} fallback={report.figures_from_fallback}")

    ok = 0
    for fig in ast.figureAST.figures:
        ch = fig.computed_chart or {}
        data = ch.get("data") or []
        ctype = ch.get("type", "?")
        png = _render_chart_png(ch, width_pt=230, height_pt=180) if data else None
        status = "OK" if png and len(png) > 2000 else "FAIL"
        if status == "OK":
            ok += 1
        print(f"   {fig.figureId}: {ctype:4s} n={len(data):2d} png={len(png) if png else 0:6d}B  [{status}]")

    print(f"\n3. Chart PNG render: {ok}/{len(ast.figureAST.figures)} passed")
    print("4. Run: python scripts/generate_coord_report.py")
    print("=" * 72)


if __name__ == "__main__":
    main()
