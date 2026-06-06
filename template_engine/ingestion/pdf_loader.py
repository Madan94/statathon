"""PDF loader — extracts raw page content for AST compilation.

Extraction cascade (most to least capable):
  1. ColPali vision model  (best spatial accuracy, requires GPU sidecar)
  2. pdfplumber layout     (good text + table extraction, pure Python)
  3. PyMuPDF (fitz)        (fast, commercial-friendly)
  4. Stub pages            (always-available fallback; produces headings from filename)

Every extractor returns a unified PageData list.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Unified page-data schema
# ---------------------------------------------------------------------------

@dataclass
class TextBlock:
    text: str
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    font_size: float = 10.0
    bold: bool = False
    all_caps: bool = False


@dataclass
class TableBlock:
    rows: list[list[str]] = field(default_factory=list)
    x0: float = 0.0
    y0: float = 0.0
    col_count: int = 0
    row_count: int = 0


@dataclass
class PageData:
    page_index: int
    width: float
    height: float
    text_blocks: list[TextBlock] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)
    raw_text: str = ""
    has_charts: bool = False

    @property
    def word_count(self) -> int:
        return len(self.raw_text.split())

    @property
    def headings(self) -> list[str]:
        """Heuristic: large, bold, or ALL-CAPS text blocks are headings."""
        heads: list[str] = []
        for tb in self.text_blocks:
            t = tb.text.strip()
            if not t or len(t) > 120:
                continue
            if tb.bold or tb.all_caps or tb.font_size >= 12:
                heads.append(t)
        return heads

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "page_index": self.page_index,
            "width": self.width,
            "height": self.height,
            "word_count": self.word_count,
            "has_tables": bool(self.tables),
            "table_count": len(self.tables),
            "headings": self.headings[:20],
            "raw_text_sample": self.raw_text[:800],
            "has_charts": self.has_charts,
        }


# ---------------------------------------------------------------------------
# Extractor 1: pdfplumber
# ---------------------------------------------------------------------------

def _load_pdfplumber(pdf_path: Path) -> list[PageData] | None:
    try:
        import pdfplumber  # type: ignore
    except Exception:
        return None

    pages: list[PageData] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages):
                raw = page.extract_text() or ""
                words = page.extract_words(
                    extra_attrs=["fontname", "size"], use_text_flow=True
                ) or []
                tables_raw = page.extract_tables() or []

                text_blocks: list[TextBlock] = []
                # Group words by approximate y-coordinate (same line)
                line_map: dict[int, list[dict]] = {}
                for w in words:
                    key = round((w.get("top") or 0) / 3) * 3
                    line_map.setdefault(key, []).append(w)

                for _y, wds in sorted(line_map.items()):
                    line_text = " ".join(str(w.get("text", "")) for w in wds).strip()
                    if not line_text:
                        continue
                    sizes = [w.get("size") or 10.0 for w in wds]
                    avg_size = sum(sizes) / max(len(sizes), 1)
                    is_bold = any("Bold" in str(w.get("fontname", "")) for w in wds)
                    text_blocks.append(TextBlock(
                        text=line_text,
                        x0=float(wds[0].get("x0") or 0),
                        y0=float(wds[0].get("top") or 0),
                        x1=float(wds[-1].get("x1") or 0),
                        y1=float(wds[-1].get("bottom") or 0),
                        font_size=avg_size,
                        bold=is_bold,
                        all_caps=line_text.isupper() and len(line_text) > 3,
                    ))

                table_blocks: list[TableBlock] = []
                for tbl in tables_raw:
                    if not tbl:
                        continue
                    str_rows = [[str(c or "") for c in row] for row in tbl]
                    table_blocks.append(TableBlock(
                        rows=str_rows,
                        col_count=max((len(r) for r in str_rows), default=0),
                        row_count=len(str_rows),
                    ))

                pages.append(PageData(
                    page_index=i,
                    width=float(page.width or 595),
                    height=float(page.height or 842),
                    text_blocks=text_blocks,
                    tables=table_blocks,
                    raw_text=raw,
                ))
    except Exception as exc:
        logger.warning("pdfplumber extraction error: %s", exc)
        return None

    return pages or None


# ---------------------------------------------------------------------------
# Extractor 2: PyMuPDF (fitz)
# ---------------------------------------------------------------------------

def _load_pymupdf(pdf_path: Path) -> list[PageData] | None:
    try:
        import fitz  # type: ignore
    except Exception:
        return None

    pages: list[PageData] = []
    try:
        doc = fitz.open(str(pdf_path))
        for i, page in enumerate(doc):
            raw = page.get_text("text") or ""
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks") or []
            text_blocks: list[TextBlock] = []
            for b in blocks:
                if b.get("type") != 0:
                    continue
                for line in (b.get("lines") or []):
                    for span in (line.get("spans") or []):
                        t = (span.get("text") or "").strip()
                        if not t:
                            continue
                        flags = span.get("flags", 0)
                        text_blocks.append(TextBlock(
                            text=t,
                            x0=span["bbox"][0],
                            y0=span["bbox"][1],
                            x1=span["bbox"][2],
                            y1=span["bbox"][3],
                            font_size=float(span.get("size") or 10),
                            bold=bool(flags & 2**4),
                            all_caps=t.isupper() and len(t) > 3,
                        ))
            rect = page.rect
            pages.append(PageData(
                page_index=i,
                width=float(rect.width),
                height=float(rect.height),
                text_blocks=text_blocks,
                raw_text=raw,
            ))
        doc.close()
    except Exception as exc:
        logger.warning("PyMuPDF extraction error: %s", exc)
        return None

    return pages or None


# ---------------------------------------------------------------------------
# Extractor 3: ColPali HTTP sidecar
# ---------------------------------------------------------------------------

def _load_colpali(pdf_path: Path) -> list[PageData] | None:
    endpoint = os.getenv("COLPALI_ENDPOINT")
    if not endpoint:
        logger.info("[pdf_loader] COLPALI_ENDPOINT not set — skipping ColPali extractor")
        return None

    # COLPALI_ENDPOINT must be the base URL only (no /extract suffix).
    colpali_url = endpoint.rstrip("/") + "/extract"
    # COLPALI_TIMEOUT: increase for large PDFs (default 300s; override in .env).
    timeout = int(os.getenv("COLPALI_TIMEOUT", "300"))
    file_size_kb = pdf_path.stat().st_size / 1024 if pdf_path.exists() else 0
    logger.info(
        "[pdf_loader] ColPali → %s  file=%.1f KB  timeout=%ds",
        colpali_url, file_size_kb, timeout,
    )
    t0 = time.monotonic()
    try:
        import requests  # type: ignore

        with open(pdf_path, "rb") as f:
            r = requests.post(colpali_url, files={"file": f}, timeout=timeout)
        elapsed = time.monotonic() - t0
        r.raise_for_status()
        raw_pages = r.json().get("pages") or []
        logger.info(
            "[pdf_loader] ColPali OK  pages=%d  elapsed=%.1fs",
            len(raw_pages), elapsed,
        )
        pages: list[PageData] = []
        for i, p in enumerate(raw_pages):
            text_blocks = [
                TextBlock(
                    text=b.get("text", ""),
                    x0=b.get("x0", 0),
                    y0=b.get("y0", 0),
                    x1=b.get("x1", 0),
                    y1=b.get("y1", 0),
                    font_size=b.get("font_size", 10),
                    bold=b.get("bold", False),
                    all_caps=(b.get("text", "")).isupper(),
                )
                for b in (p.get("blocks") or [])
                if b.get("text")
            ]
            pages.append(PageData(
                page_index=i,
                width=float(p.get("width") or 595),
                height=float(p.get("height") or 842),
                text_blocks=text_blocks,
                raw_text=p.get("text", ""),
                has_charts=bool(p.get("has_charts")),
            ))
        return pages or None
    except Exception as exc:
        elapsed = time.monotonic() - t0
        err_str = str(exc).lower()
        if "timed out" in err_str or "timeout" in err_str:
            kind = "TIMEOUT"
        elif "refused" in err_str or "failed to establish" in err_str:
            kind = "REFUSED (ColPali not running?)"
        else:
            kind = "ERROR"
        logger.info(
            "[pdf_loader] ColPali %s after %.1fs: %s",
            kind, elapsed, exc,
        )
        return None


# ---------------------------------------------------------------------------
# Stub fallback
# ---------------------------------------------------------------------------

def _stub_pages(pdf_path: Path) -> list[PageData]:
    """Single synthetic page derived from filename — always succeeds."""
    stem = pdf_path.stem.replace("_", " ").replace("-", " ").title()
    return [
        PageData(
            page_index=0,
            width=595.0,
            height=842.0,
            text_blocks=[TextBlock(text=stem, font_size=18, bold=True, all_caps=False)],
            raw_text=stem,
        )
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_pdf(pdf_path: str | Path) -> tuple[list[PageData], str]:
    """Load a PDF using the best available extractor.

    Returns:
      (pages, extraction_method)

    Extraction cascade (logged for full observability):
      1. ColPali  — GPU vision model (best spatial accuracy; requires Docker sidecar)
      2. pdfplumber — text + table layout (pure Python; always available)
      3. PyMuPDF (fitz) — fast fallback
      4. stub — produces filename-derived heading only; never fails
    """
    path = Path(pdf_path)
    if not path.exists():
        logger.warning("[pdf_loader] PDF not found: %s; using stub", path)
        return _stub_pages(path), "stub"

    file_size_kb = path.stat().st_size / 1024
    logger.info("[pdf_loader] load_pdf start: %s  (%.1f KB)", path.name, file_size_kb)

    logger.info("[pdf_loader] cascade 1/4: ColPali")
    pages = _load_colpali(path)
    if pages:
        logger.info("[pdf_loader] ✓ extractor=colpali  pages=%d", len(pages))
        return pages, "colpali"

    logger.info("[pdf_loader] cascade 2/4: pdfplumber")
    pages = _load_pdfplumber(path)
    if pages:
        logger.info("[pdf_loader] ✓ extractor=pdfplumber  pages=%d", len(pages))
        return pages, "pdfplumber"

    logger.info("[pdf_loader] cascade 3/4: PyMuPDF")
    pages = _load_pymupdf(path)
    if pages:
        logger.info("[pdf_loader] ✓ extractor=pymupdf  pages=%d", len(pages))
        return pages, "pymupdf"

    logger.warning("[pdf_loader] cascade 4/4: all extractors failed — using stub (filename only)")
    return _stub_pages(path), "stub"
