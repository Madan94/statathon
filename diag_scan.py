import pdfplumber, sys
pdf_path = sys.argv[1] if len(sys.argv) > 1 else input("PDF path: ").strip().strip('"')
with pdfplumber.open(pdf_path) as pdf:
    for i, page in enumerate(pdf.pages[:3]):
        raw = page.extract_text() or ""
        chars = page.chars or []
        images = page.images or []
        print(f"Page {i}: chars={len(chars)}, images={len(images)}, text_len={len(raw)}")
        print(f"  Page size: {page.width}x{page.height}")
        if images:
            for img in images[:2]:
                w = img.get('x1',0) - img.get('x0',0)
                h = img.get('bottom',0) - img.get('top',0)
                coverage = (w*h)/(page.width*page.height)*100
                print(f"  Image: {w:.0f}x{h:.0f} ({coverage:.0f}% of page)")
        if len(chars) == 0 and len(images) > 0:
            print("  ** SCANNED PDF: Image-only, no text layer **")
        elif len(chars) == 0 and len(images) == 0:
            print("  ** PROTECTED or CORRUPT: no chars and no images **")
