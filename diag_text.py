import pdfplumber, sys
pdf_path = sys.argv[1] if len(sys.argv) > 1 else input("PDF path: ").strip().strip('"')
with pdfplumber.open(pdf_path) as pdf:
    for i, page in enumerate(pdf.pages[:3]):
        raw = page.extract_text() or ""
        words = page.extract_words(extra_attrs=["fontname","size"], use_text_flow=True)
        tables = page.extract_tables() or []
        print(f"Page {i}: text_len={len(raw)}, words={len(words)}, tables={len(tables)}")
        if words:
            print(f"  Word keys: {list(words[0].keys())}")
            print(f"  First word: {words[0]}")
        if raw:
            print(f"  First 100 chars: {raw[:100]}")
        else:
            print("  ** NO TEXT EXTRACTED **")
