"""Validate economics coordinate report: bound AST + PDF checks."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))


def validate(bound_ast_path: Path) -> list[str]:
    errors: list[str] = []
    data = json.loads(bound_ast_path.read_text(encoding="utf-8"))
    paras = data.get("contentAST", {}).get("paragraphs") or []
    energy_pat = re.compile(
        r"\b(coal|lignite|crude oil|natural gas|renewable power|billion tonnes|BCM)\b",
        re.I,
    )
    for p in paras:
        if p.get("type") != "body":
            continue
        text = p.get("content") or ""
        if energy_pat.search(text):
            errors.append(f"{p.get('id')}: still contains energy vocabulary")
        if not text.strip():
            errors.append(f"{p.get('id')}: empty body")

    figures = data.get("figureAST", {}).get("figures") or []
    for fig in figures:
        ch = fig.get("computed_chart") or {}
        pts = ch.get("data") or []
        if len(pts) < 2:
            errors.append(f"{fig.get('figureId')}: chart has <2 points")
        cap = fig.get("caption") or ""
        if "coal" in cap.lower() or "renewable power" in cap.lower():
            errors.append(f"{fig.get('figureId')}: caption not remapped")

    tables = data.get("tableAST", {}).get("tables") or []
    for t in tables:
        if not t.get("rows"):
            errors.append(f"{t.get('tableId')}: no rows")
        title = (t.get("title") or "").lower()
        if "coal" in title or "crude oil" in title:
            errors.append(f"{t.get('tableId')}: table title not remapped")

    return errors


def main() -> int:
    reports = list((_REPO / "storage" / "reports").glob("coord_report_*_bound_ast.json"))
    if not reports:
        print("No bound AST found — run: python scripts/generate_coord_report.py")
        return 1
    latest = max(reports, key=lambda p: p.stat().st_mtime)
    print(f"Validating {latest}")
    errs = validate(latest)
    if errs:
        print("FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("OK: economics remap, tables, figures, and body text checks passed.")
    pdf = latest.with_name(latest.name.replace("_bound_ast.json", ".pdf"))
    if pdf.exists():
        print(f"PDF: {pdf} ({pdf.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
