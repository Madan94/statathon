"""Trace what the binder produces for every figure."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from ast_core import load_multi_ast
from ast_core.template_binder import TemplateBinder

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ast = load_multi_ast(os.path.join(repo, "Enterprise_Document_AST.json"))
df = pd.read_csv(os.path.join(repo, "test_data", "unified_energy_reserves_dataset.csv"))

ast, report = TemplateBinder().bind(ast, df)
for f in ast.figureAST.figures:
    print(f"{f.figureId}: caption={f.caption!r}")
    if f.computed_chart:
        cc = f.computed_chart
        print(f"   chart type={cc.get('type')} title={cc.get('title')!r}")
        print(f"   data ({len(cc.get('data') or [])} points): "
              f"{cc.get('data')[:3]}")
    else:
        print(f"   computed_chart=None (placeholder)")
