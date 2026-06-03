"""Verify load + round-trip of the Enterprise AST template."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ast_core import load_multi_ast, save_multi_ast

src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "Enterprise_Document_AST.json")
ast = load_multi_ast(src)

print(f"Pages          : {len(ast.layoutAST.pages)}")
print(f"Styles         : {len(ast.styleAST.styles)}")
print(f"Geometry nodes : {len(ast.geometryAST.nodes)}")
print(f"Paragraphs     : {len(ast.contentAST.paragraphs)}")
print(f"Tables         : {len(ast.tableAST.tables)}")
print(f"Figures        : {len(ast.figureAST.figures)}")
print(f"Charts         : {len(ast.chartAST.charts)}")
print(f"Entities       : {len(ast.entityGraph.entities)}")
print(f"Facts          : {len(ast.factAST.facts)}")
print(f"Evidence ents  : {len(ast.evidenceAST.entries)}")

# Print the first 3 paragraphs by id+type
print("\nFirst paragraphs:")
for p in ast.contentAST.paragraphs[:5]:
    print(f"  {p.id} [{p.type:18s}] {p.content[:60]!r}")

# Show first table summary
if ast.tableAST.tables:
    t = ast.tableAST.tables[0]
    print(f"\nTable[0]: {t.title}")
    print(f"  columns={t.columns}")
    print(f"  rows={len(t.rows)}")

# Round-trip
out = os.path.join(os.path.dirname(__file__), "..", "outputs", "ast_roundtrip.json")
path = save_multi_ast(ast, out)
print(f"\nRound-trip saved to: {path}")

# Sanity: re-load and check counts match
reloaded = load_multi_ast(path)
assert len(reloaded.contentAST.paragraphs) == len(ast.contentAST.paragraphs)
assert len(reloaded.tableAST.tables) == len(ast.tableAST.tables)
print("Round-trip OK")
