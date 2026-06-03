"""Render the Enterprise template AST to PDF using the new strict renderer."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ast_core import load_multi_ast
from ast_core.renderer import render_ast_to_pdf

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = os.path.join(repo, "Enterprise_Document_AST.json")
out = os.path.join(repo, "outputs", "enterprise_ast_render.pdf")

ast = load_multi_ast(src)
print(f"Loaded AST: {len(ast.layoutAST.pages)} pages, "
      f"{len(ast.contentAST.paragraphs)} paragraphs, "
      f"{len(ast.tableAST.tables)} tables, "
      f"{len(ast.figureAST.figures)} figures")

result = render_ast_to_pdf(ast, out_path=out, allow_overflow=True)

print(f"\nRendered: {result.pdf_path}")
print(f"  pages          : {result.page_count}")
print(f"  size (bytes)   : {os.path.getsize(result.pdf_path)}")
print(f"  content_hash   : {result.content_hash}")
print(f"  warnings count : {len(result.overflow_warnings)}")
for w in result.overflow_warnings[:8]:
    print(f"    - {w}")
if len(result.overflow_warnings) > 8:
    print(f"    ... +{len(result.overflow_warnings) - 8} more")
