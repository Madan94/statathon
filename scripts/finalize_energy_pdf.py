"""Render the saved energy report AST to a polished, full-chrome HTML + PDF.

Reads the persisted ``report.output.ast.json`` for the energy template, renders
it with cover + table of contents + provenance appendix + numbered figures/tables
(the formal-deliverable chrome), saves the print HTML, then converts it to PDF
with a local headless Chromium browser (Chrome/Edge). No server PDF engine needed.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from report_builder.generation.renderer import render_html  # noqa: E402

TID = "tpl_energy_enterprise_v2"
SIG = "b7acf2ae375faab7"
GS = Path("report_builder/gold_standard/energy_enterprise_v2")
OUT = Path("outputs")
STEM = f"{TID}__{SIG}"


def find_browser() -> str | None:
    import shutil
    for c in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ):
        if Path(c).exists():
            return c
    for n in ("chrome", "msedge", "chromium"):
        f = shutil.which(n)
        if f:
            return f
    return None


def html_to_pdf(html_file: Path, pdf_file: Path) -> bool:
    browser = find_browser()
    if not browser:
        print("  no local browser found")
        return False
    if pdf_file.exists():
        pdf_file.unlink()
    url = "file:///" + str(html_file.resolve()).replace("\\", "/")
    cmd = [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--no-pdf-header-footer", f"--print-to-pdf={pdf_file.resolve()}", url]
    try:
        subprocess.run(cmd, timeout=120, capture_output=True)
    except Exception as exc:  # noqa: BLE001
        print(f"  browser error: {exc}")
    for _ in range(25):
        if pdf_file.exists() and pdf_file.stat().st_size > 0:
            return True
        time.sleep(0.3)
    return pdf_file.exists() and pdf_file.stat().st_size > 0


def main() -> int:
    import json

    ast_path = OUT / f"{STEM}.report.ast.json"
    if not ast_path.exists():
        print(f"FATAL: {ast_path} not found — run the generation driver first")
        return 1
    report = json.loads(ast_path.read_text(encoding="utf-8"))

    # Document title from the template metadata.
    tmpl = json.loads((GS / f"{TID.replace('tpl_','')}.template.ast.json").read_text(encoding="utf-8-sig"))
    title = (tmpl.get("metadata") or {}).get("name") or "Statistical Report"

    # Full formal chrome: cover + TOC + provenance appendix + numbered elements.
    html = render_html(
        report,
        title=title,
        include_cover=True,
        include_toc=True,
        include_appendix=True,
        number_elements=True,
    )
    print_html = OUT / f"{STEM}.report.print.html"
    print_html.write_text(html, encoding="utf-8")
    print(f"  ✓ print HTML → {print_html}  ({len(html):,} bytes)")
    print(f"    sections={html.count('<section')} tables={html.count('<table')} "
          f"charts={html.count('<svg')} paras={html.count('<p class')}")

    pdf_path = OUT / f"{STEM}.report.pdf"
    if html_to_pdf(print_html, pdf_path):
        print(f"  ✓ PDF        → {pdf_path}  ({pdf_path.stat().st_size:,} bytes)")
        return 0
    print("  ✗ PDF could not be produced")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
