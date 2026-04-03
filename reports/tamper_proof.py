import hashlib
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def write_tamper_proof_pdf(path: str, title: str, lines: list[str], meta: dict) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(p), pagesize=letter)
    y = 750
    c.drawString(72, y, title)
    y -= 24
    for line in lines[:50]:
        c.drawString(72, y, line[:100])
        y -= 14
        if y < 72:
            c.showPage()
            y = 750
    c.save()
    h = sha256_file(str(p))
    sidecar = p.with_suffix(".meta.json")
    sidecar.write_text(__import__("json").dumps({"sha256": h, **meta}, indent=2), encoding="utf-8")
    return h