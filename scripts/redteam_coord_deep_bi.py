"""Red-team accuracy test: strict Deep BI coordinate report (no fallbacks)."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except Exception:
    pass

import pandas as pd

from ast_core.coord_deep_bi_orchestrator import run_coord_report_strict

AST = _REPO / "test_data" / "fina-ast.json"
DATA = _REPO / "test_data" / "Economics - MoSPI.csv"


def _numbers_in_text(text: str) -> list[float]:
    return [float(m) for m in re.findall(r"\b\d+(?:\.\d+)?\b", text)]


def _number_in_df(n: float, df: pd.DataFrame, tol: float = 0.15) -> bool:
    nums = set()
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            for v in df[c].dropna():
                nums.add(round(float(v), 2))
    if round(n, 2) in nums:
        return True
    for v in nums:
        if v and abs(n - v) / max(abs(v), 1e-9) <= tol:
            return True
    return False


def audit_bound_ast(path: Path, df: pd.DataFrame) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    report = {
        "paragraphs_total": 0,
        "paragraphs_deep_bi": 0,
        "paragraphs_with_numbers": 0,
        "numbers_verified": 0,
        "numbers_unverified": 0,
        "tables_deep_bi": 0,
        "tables_total": 0,
        "figures_deep_bi": 0,
        "figures_total": 0,
        "energy_leaks": [],
        "fallback_leaks": [],
        "errors": [],
    }

    energy_re = re.compile(
        r"\b(coal|lignite|crude oil|natural gas|renewable power|billion tonnes)\b", re.I
    )

    for p in data.get("contentAST", {}).get("paragraphs") or []:
        if p.get("type") != "body":
            continue
        report["paragraphs_total"] += 1
        src = p.get("evidenceRefs") or []
        if any(s.startswith("deep_bi") for s in src):
            report["paragraphs_deep_bi"] += 1
        elif p.get("content"):
            report["fallback_leaks"].append(
                f"{p.get('id')}: body without deep_bi evidenceRefs"
            )
        text = p.get("content") or ""
        if energy_re.search(text):
            report["energy_leaks"].append(p.get("id"))
        for n in _numbers_in_text(text):
            report["paragraphs_with_numbers"] += 1
            if _number_in_df(n, df):
                report["numbers_verified"] += 1
            else:
                report["numbers_unverified"] += 1

    for t in data.get("tableAST", {}).get("tables") or []:
        report["tables_total"] += 1
        meta = t.get("metadata") or {}
        src = meta.get("bindSource") or ""
        if src.startswith("deep_bi") and t.get("rows"):
            report["tables_deep_bi"] += 1
        elif t.get("rows"):
            report["fallback_leaks"].append(f"{t.get('tableId')}: rows without deep_bi bindSource")

    for f in data.get("figureAST", {}).get("figures") or []:
        report["figures_total"] += 1
        ch = f.get("computed_chart") or {}
        if ch.get("data"):
            report["figures_deep_bi"] += 1
        else:
            report["errors"].append(f"{f.get('figureId')}: no chart data")

    return report


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    out_pdf = _REPO / "storage" / "reports" / f"redteam_coord_{stamp}.pdf"
    use_gemini = "--no-gemini" not in sys.argv

    print("=" * 72)
    print("RED TEAM: strict Deep BI coordinate report")
    print(f"  Gemini: {use_gemini}")
    print("=" * 72)

    result = run_coord_report_strict(
        ast_path=str(AST),
        data_path=str(DATA),
        out_pdf=str(out_pdf),
        domain="economics",
        use_gemini=use_gemini,
    )

    br = result.bind_report
    print(f"\nBind errors: {len(br.errors)}")
    for e in br.errors[:12]:
        print(f"  - {e}")

    print(
        f"\nContent: {br.content.paragraphs_bound}/{br.content.paragraphs_attempted} "
        f"(gemini={br.content.paragraphs_from_gemini}, "
        f"evidence={br.content.paragraphs_from_deep_bi})"
    )
    print(
        f"Tables:  {br.tables.tables_bound}/{br.tables.tables_attempted} "
        f"(deep_bi={br.tables.tables_from_deep_bi})"
    )
    print(
        f"Figures: {br.figures.figures_bound}/{br.figures.figures_attempted} "
        f"(deep_bi={br.figures.figures_from_deep_bi}, "
        f"fallback={br.figures.figures_from_fallback})"
    )

    df = pd.read_csv(DATA)
    audit = audit_bound_ast(Path(result.bound_ast_path), df)
    print("\nAccuracy audit:")
    for k, v in audit.items():
        if isinstance(v, list) and v:
            print(f"  {k}: {v[:8]}")
        elif not isinstance(v, list):
            print(f"  {k}: {v}")

    passed = (
        br.figures.figures_from_fallback == 0
        and audit["fallback_leaks"] == []
        and not br.errors
        and br.content.paragraphs_bound == br.content.paragraphs_attempted
        and br.tables.tables_bound == br.tables.tables_attempted
        and br.figures.figures_bound == br.figures.figures_attempted
        and audit["figures_deep_bi"] == audit["figures_total"]
    )

    print(f"\nPDF: {result.pdf_path}")
    print(f"AST: {result.bound_ast_path}")
    print("RESULT:", "PASS" if passed else "FAIL")
    print("=" * 72)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
