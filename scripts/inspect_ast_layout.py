"""Map every block in the Enterprise AST layout."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

d = json.load(open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Enterprise_Document_AST.json"), encoding="utf-8"))
pages = d["layoutAST"]["pages"]
print(f"{len(pages)} pages")
for p in pages:
    print(f"\n{p['pageId']}: {p['width']}x{p['height']} - {len(p['blocks'])} blocks")
    for b in p["blocks"]:
        print(f"  {b['blockId']:8s}  type={b['type']:14s}  refs={b['elementRefs']}")
