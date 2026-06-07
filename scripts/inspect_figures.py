"""Inspect figure + chart definitions."""
import sys, os, json
d = json.load(open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Enterprise_Document_AST.json"), encoding="utf-8"))

for f in d["figureAST"]["figures"]:
    desc = f.get("description", "")
    if desc:
        desc = desc.encode("ascii", "replace").decode("ascii")
    print(f"{f['figureId']}: caption={f.get('caption')!r}")
    if desc:
        print(f"    description={desc[:140]!r}")
print()
for c in d["chartAST"]["charts"]:
    print(f"{c['chartId']}: type={c.get('type')} title={c.get('title')!r}")
    print(f"    series={str(c.get('series'))[:200]}")
