"""End-to-end: Enterprise AST + unified_energy_reserves_dataset.csv -> PDF.

Steps:
  1. Load the Enterprise multi-AST template (10 pages, 4 tables, 6 figures, 1 chart).
  2. Load the dataset.
  3. Bind table rows + chart series + figure captions from the dataset
     (purely generic — no hardcoded column names).
  4. Render the bound AST to PDF using the GeometryAST-strict renderer.
  5. Save the bound AST as JSON so it can be inspected.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from ast_core import load_multi_ast, save_multi_ast
from ast_core.template_binder import TemplateBinder
from ast_core.renderer import render_ast_to_pdf

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ast_path = os.path.join(repo, "Enterprise_Document_AST.json")
data_path = os.path.join(repo, "test_data", "unified_energy_reserves_dataset.csv")
pdf_out = os.path.join(repo, "outputs", "energy_report_from_ast.pdf")
ast_out = os.path.join(repo, "outputs", "energy_report_ast_filled.json")

print("=" * 78)
print("Step 1: Load template AST")
ast = load_multi_ast(ast_path)
print(f"  pages={len(ast.layoutAST.pages)}  tables={len(ast.tableAST.tables)}"
      f"  figures={len(ast.figureAST.figures)}  charts={len(ast.chartAST.charts)}")

print("\nStep 2: Load dataset")
df = pd.read_csv(data_path)
print(f"  rows={len(df)}  columns={list(df.columns)}")

print("\nStep 3: Bind dataset to template")
binder = TemplateBinder()
ast, report = binder.bind(ast, df)
print(f"  tables_bound      = {report.tables_bound}")
print(f"  cells_filled      = {report.cells_filled}")
print(f"  figures_captioned = {report.figures_captioned}")
print(f"  charts_filled     = {report.charts_filled}")
print(f"  evidence_entries  = {len(report.evidence)}")
if report.warnings:
    print(f"  warnings ({len(report.warnings)}):")
    for w in report.warnings[:8]:
        print(f"    - {w}")

print("\n  Per-table summary:")
for t in ast.tableAST.tables:
    meta = t.metadata or {}
    print(f"    {t.tableId}: {t.title[:60]!r}")
    print(f"      key_col={meta.get('key_column')}  "
          f"filter={meta.get('filter_applied')}  rows={len(t.rows)}")
    if t.rows:
        first_row = t.rows[0]
        print(f"      first row sample: {first_row[:5]}{'...' if len(first_row) > 5 else ''}")

print("\nStep 4: Render to PDF")
result = render_ast_to_pdf(ast, out_path=pdf_out, allow_overflow=True)
print(f"  pdf_path     = {result.pdf_path}")
print(f"  page_count   = {result.page_count}")
print(f"  size_bytes   = {os.path.getsize(result.pdf_path)}")
print(f"  content_hash = {result.content_hash}")
print(f"  warnings     = {len(result.overflow_warnings)}")

print("\nStep 5: Save bound AST JSON")
save_multi_ast(ast, ast_out)
print(f"  json: {ast_out}")
print(f"\n  PDF: {pdf_out}")
