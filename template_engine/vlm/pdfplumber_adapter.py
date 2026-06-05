"""PdfPlumber VLM Adapter — wraps existing pdfplumber extraction as a VLM backend.

This provides backward compatibility with the existing extraction pipeline,
converting pdfplumber's output into the unified VLMPageResult format.
"""
from __future__ import annotations

import logging
from pathlib import Path

from template_engine.vlm.client import VLMClient, VLMExtractionError
from template_engine.vlm.schemas import (
    VLMBBox,
    VLMEntity,
    VLMPageResult,
    VLMRegion,
    VLMTableData,
)

logger = logging.getLogger(__name__)


class PdfPlumberVLMAdapter(VLMClient):
    """Adapter wrapping pdfplumber extraction into VLMPageResult format.

    This is the fallback backend when neither ColPali nor mock fixtures
    are available. Quality is lower than VLM for complex layouts but
    works without GPU.
    """

    @property
    def backend_name(self) -> str:
        return "pdfplumber_fallback"

    def health_check(self) -> bool:
        try:
            import pdfplumber  # noqa: F401
            return True
        except ImportError:
            return False

    def extract_pages(self, pdf_path: Path) -> list[VLMPageResult]:
        pdf_path = Path(pdf_path)  # Ensure Path object
        try:
            import pdfplumber
        except ImportError:
            raise VLMExtractionError(
                "pdfplumber not installed. Install: pip install pdfplumber"
            )

        if not pdf_path.exists():
            raise VLMExtractionError(f"PDF not found: {pdf_path}")

        pages: list[VLMPageResult] = []

        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for i, page in enumerate(pdf.pages):
                    raw_text = page.extract_text() or ""
                    words = page.extract_words(
                        extra_attrs=["fontname", "size"], use_text_flow=True
                    ) or []
                    tables_raw = page.extract_tables() or []

                    # Build regions from word groups
                    regions = self._words_to_regions(words, i, float(page.height or 842))

                    # Build table data
                    tables = []
                    for t_idx, tbl in enumerate(tables_raw):
                        if not tbl:
                            continue
                        str_rows = [[str(c or "") for c in row] for row in tbl]
                        headers = str_rows[0] if str_rows else []
                        data_rows = str_rows[1:] if len(str_rows) > 1 else []
                        region_id = f"r_{i}_tbl_{t_idx}"
                        regions.append(VLMRegion(
                            regionId=region_id,
                            role="table",
                            text=f"Table ({len(data_rows)} rows × {len(headers)} cols)",
                            bbox=VLMBBox(x0=50, y0=0, x1=545, y1=0),
                            confidence=0.7,
                        ))
                        tables.append(VLMTableData(
                            headers=headers,
                            rows=data_rows,
                            regionId=region_id,
                        ))

                    # Extract entities from table headers
                    entities = []
                    for tbl in tables:
                        for h in tbl.headers:
                            if h.strip() and len(h.strip()) > 1:
                                entities.append(VLMEntity(
                                    name=h.strip(),
                                    entityType="dimension",
                                    sourceType="table_header",
                                    sourceRegion=tbl.regionId,
                                    confidence=0.7,
                                ))

                    pages.append(VLMPageResult(
                        pageIndex=i,
                        width=float(page.width or 595),
                        height=float(page.height or 842),
                        regions=regions,
                        entities=entities,
                        tables=tables,
                        charts=[],
                        rawText=raw_text,
                        confidence=0.6,  # lower confidence for programmatic extraction
                    ))

        except Exception as exc:
            if pages:
                raise VLMExtractionError(
                    f"pdfplumber partial failure at page {len(pages)}: {exc}",
                    page_index=len(pages),
                    partial_results=pages,
                )
            raise VLMExtractionError(f"pdfplumber extraction failed: {exc}")

        return pages

    def _words_to_regions(self, words: list[dict], page_idx: int,
                          page_height: float) -> list[VLMRegion]:
        """Group words into line-based regions with role classification."""
        if not words:
            return []

        # Group by approximate y-coordinate
        line_map: dict[int, list[dict]] = {}
        for w in words:
            key = round((w.get("top") or 0) / 4) * 4
            line_map.setdefault(key, []).append(w)

        regions: list[VLMRegion] = []
        for idx, (_y, wds) in enumerate(sorted(line_map.items())):
            text = " ".join(str(w.get("text", "")) for w in wds).strip()
            if not text:
                continue

            sizes = [w.get("size") or 10.0 for w in wds]
            avg_size = sum(sizes) / max(len(sizes), 1)
            is_bold = any("Bold" in str(w.get("fontname", "")) for w in wds)
            y_rel = (wds[0].get("top") or 0) / max(page_height, 1)

            # Classify role
            if y_rel < 0.06:
                role = "header"
            elif y_rel > 0.94:
                role = "footer"
            elif avg_size >= 16:
                role = "title"
            elif avg_size >= 13 or (is_bold and avg_size >= 11 and len(text) < 80):
                role = "heading_h1"
            elif avg_size >= 11 and is_bold and len(text) < 100:
                role = "heading_h2"
            elif text.isupper() and len(text) < 80 and len(text) > 3:
                role = "heading_h2"
            else:
                role = "paragraph"

            x0 = float(wds[0].get("x0") or 0)
            y0 = float(wds[0].get("top") or 0)
            x1 = float(wds[-1].get("x1") or 0)
            y1 = float(wds[-1].get("bottom") or 0)

            regions.append(VLMRegion(
                regionId=f"r_{page_idx}_{idx}",
                role=role,
                text=text,
                bbox=VLMBBox(x0=x0, y0=y0, x1=x1, y1=y1),
                confidence=0.65,
                metadata={"avg_font_size": avg_size, "bold": is_bold},
            ))

        return regions
