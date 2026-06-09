import pdfplumber, sys, os
from dotenv import load_dotenv
load_dotenv()
pdf_path = sys.argv[1] if len(sys.argv) > 1 else input("PDF path: ").strip().strip('"')
with pdfplumber.open(pdf_path) as pdf:
    page = pdf.pages[0]
    words = page.extract_words(extra_attrs=["fontname", "size"], use_text_flow=True)
    print(f"Words on page 0: {len(words)}")
    if words:
        print(f"Word keys: {list(words[0].keys())}")
        sizes = [w.get("size") for w in words[:20]]
        print(f"Font sizes: {sizes}")
        has_size = any(s and s > 0 for s in sizes)
        print(f"Has valid size: {has_size}")
    else:
        print("ERROR: No words extracted!")
    raw = page.extract_text() or ""
    print(f"Raw text length: {len(raw)}")
    print(f"First 200 chars: {raw[:200]}")
