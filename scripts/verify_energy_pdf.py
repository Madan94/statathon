"""Inspect the generated energy PDF — extract text and image bbox per page."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pdfplumber

import glob
out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "outputs")
candidates = sorted(glob.glob(os.path.join(out_dir, "energy_report_*.pdf")),
                     key=os.path.getmtime, reverse=True)
pdf_path = candidates[0] if candidates else os.path.join(out_dir, "energy_report_from_ast.pdf")
print(f"Inspecting: {pdf_path}")

with pdfplumber.open(pdf_path) as pdf:
    print(f"Pages: {len(pdf.pages)}")
    for i, p in enumerate(pdf.pages):
        print(f"\n=== page {i+1} ({p.width}x{p.height}) ===")
        txt = (p.extract_text() or "").encode("ascii", "replace").decode("ascii").strip()
        # Print first 12 lines
        for line in txt.split("\n")[:12]:
            print(f"  {line[:96]}")
        tables = p.extract_tables() or []
        if tables:
            print(f"  TABLES: {len(tables)}")
            for j, t in enumerate(tables):
                print(f"   table[{j}]: rows={len(t)} cols={len(t[0]) if t else 0}")
                if t and t[0]:
                    print(f"    hdr: {[(str(c)[:18] if c else '') for c in t[0][:6]]}")
                for r_idx in (1, 2):
                    if len(t) > r_idx:
                        print(f"    r{r_idx}:  {[(str(c)[:18] if c else '') for c in t[r_idx][:6]]}")
        if p.images:
            print(f"  IMAGES: {len(p.images)}")
            for img in p.images[:3]:
                print(f"    image bbox=({img.get('x0'):.0f},{img.get('top'):.0f})"
                      f"->({img.get('x1'):.0f},{img.get('bottom'):.0f})")
