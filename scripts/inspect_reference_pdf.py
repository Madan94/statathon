"""Inspect the reference Stat reports.pdf so we know what to match."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pdfplumber

with pdfplumber.open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "test_data", "Stat reports.pdf")) as pdf:
    print(f"pages: {len(pdf.pages)}")
    for i, p in enumerate(pdf.pages):
        print(f"\n=== page {i+1} ({p.width}x{p.height}) ===")
        txt = (p.extract_text() or "").strip()
        ascii_txt = txt.encode("ascii", "replace").decode("ascii")
        print(ascii_txt[:800])
        tables = p.extract_tables()
        if tables:
            print(f"  [{len(tables)} table(s)]")
            for j, t in enumerate(tables):
                print(f"   table[{j}]: rows={len(t)} cols={len(t[0]) if t else 0}")
                if t:
                    hdr = [(str(c)[:20] if c else "") for c in t[0][:8]]
                    print(f"    hdr: {hdr}")
                if len(t) > 1:
                    row = [(str(c)[:20] if c else "") for c in t[1][:8]]
                    print(f"    r1:  {row}")
                if len(t) > 2:
                    row = [(str(c)[:20] if c else "") for c in t[2][:8]]
                    print(f"    r2:  {row}")
        # Pull bbox of any embedded images
        if p.images:
            print(f"  [{len(p.images)} image(s)]")
            for img in p.images[:3]:
                print(f"    image bbox=({img.get('x0')},{img.get('top')})->"
                      f"({img.get('x1')},{img.get('bottom')})")
