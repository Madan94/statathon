import requests, sys
pdf_path = sys.argv[1] if len(sys.argv) > 1 else input("PDF path: ").strip().strip('"')
print("Sending to LayoutLM...")
with open(pdf_path, "rb") as f:
    r = requests.post("http://localhost:8001/analyze", files={"file": f}, timeout=600)
if r.status_code != 200:
    print(f"ERROR: {r.status_code} {r.text[:200]}")
else:
    data = r.json()
    print(f"Pages: {len(data['pages'])}")
    for i, p in enumerate(data["pages"][:3]):
        regions = p.get("regions", [])
        texts = [reg.get("text","").strip() for reg in regions if reg.get("text","").strip()]
        types_with_text = [(reg["type"], reg.get("text","")[:40]) for reg in regions if reg.get("text","")]
        print(f"  Page {i}: {len(regions)} regions, {len(texts)} with text")
        for rtype, txt in types_with_text[:5]:
            print(f"    [{rtype}] {txt}")
