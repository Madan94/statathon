"""Context-Aware Late Chunking Engine.

Splits documents at section boundaries and prepends semantic context
from prior sections to each chunk. This allows Qwen-VL to process
80+ page documents within a 2048-token context window while maintaining
document-level awareness.

Strategy:
    1. Build document ToC from LayoutLM headings
    2. Split at section boundaries (natural break points)
    3. For each chunk, prepend condensed context prefix:
       "[Document: {title}, Page {n}/{total}. Sections so far: {ToC summary}]"
    4. Process chunk with full prefix → extract content + entities
    5. Merge all chunk outputs, resolve cross-references
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToCEntry:
    """A single heading in the document Table of Contents."""
    title: str
    page_index: int
    level: int  # 1=chapter, 2=section, 3=subsection
    region_type: str = "heading"  # from LayoutLM


@dataclass
class DocumentChunk:
    """A chunk of the document with context prefix."""
    chunk_id: int
    pages: list[int]  # page indices in this chunk
    section_title: str
    context_prefix: str  # prepended to LLM prompt
    content: list[dict[str, Any]]  # page data for this chunk
    toc_position: str  # e.g., "Section 3 of 7"


def build_toc_from_regions(
    pages: list[dict[str, Any]],
    page_texts: list[dict[str, Any]] | None = None,
) -> list[ToCEntry]:
    """Extract Table of Contents from LayoutLM-detected heading regions.

    Uses pdfplumber word font sizes (when available) to infer heading level:
        level 1 (chapter):    font size in top 15% of page  OR LayoutLM 'title'
        level 2 (section):    font size in top 15-40%       OR non-indented 'heading'
        level 3 (subsection): font size below top 40%       OR indented 'heading'

    This replaces the naive rtype=='title'→level=1 heuristic which causes
    LayoutLM to produce 80+ level-1 entries on dense government PDFs.

    Args:
        pages:      LayoutLM output with regions per page.
        page_texts: Optional pdfplumber word data per page (list of
                    {words: [{text, size, fontname, ...}]} dicts).

    Returns:
        Ordered list of ToCEntry objects representing document structure.
    """
    toc: list[ToCEntry] = []
    seen_titles: set[str] = set()
    MAX_PER_PAGE = 8
    MIN_CONFIDENCE = 0.5

    # ── Pre-compute per-page font-size thresholds from pdfplumber words ──
    # Build a map: page_idx → (p85_size, p70_size, median_size)
    # Headings with font_size >= p85 → level 1, >= p70 → level 2, else → level 3
    page_font_thresholds: dict[int, tuple[float, float, float]] = {}
    if page_texts:
        for i, pt in enumerate(page_texts):
            sizes = [
                w.get("size", 0)
                for w in (pt.get("words") or [])
                if w.get("size", 0) > 0
            ]
            if sizes:
                sizes_sorted = sorted(sizes)
                n = len(sizes_sorted)
                p85 = sizes_sorted[int(n * 0.85)]
                p70 = sizes_sorted[int(n * 0.70)]
                median = sizes_sorted[n // 2]
                page_font_thresholds[i] = (p85, p70, median)

    def _get_word_font_size(page_idx: int, heading_text: str) -> float:
        """Look up the font size of a heading by matching text in pdfplumber words."""
        if not page_texts or page_idx >= len(page_texts):
            return 0.0
        needle = heading_text.lower().strip()[:30]
        for w in (page_texts[page_idx].get("words") or []):
            if needle in str(w.get("text", "")).lower():
                return float(w.get("size", 0))
        return 0.0

    for page in pages:
        page_idx = page.get("page_index", 0)
        regions = page.get("regions") or []
        page_headings = 0
        thresholds = page_font_thresholds.get(page_idx)

        for region in regions:
            if page_headings >= MAX_PER_PAGE:
                break

            rtype = region.get("type", "")
            text = (region.get("text") or "").strip()
            confidence = region.get("confidence", 0.5)

            if rtype not in ("title", "heading") or not text:
                continue
            if confidence < MIN_CONFIDENCE:
                continue
            if len(text) < 3 or len(text) > 150:
                continue

            # Deduplicate (case-insensitive, strip numbers/punctuation)
            dedup_key = text.lower().strip("0123456789.-: ")
            if dedup_key in seen_titles:
                continue
            seen_titles.add(dedup_key)

            # ── Level inference (font-size preferred over LayoutLM type) ──
            if thresholds:
                p85, p70, _ = thresholds
                font_size = _get_word_font_size(page_idx, text)
                if font_size >= p85 and p85 > 0:
                    level = 1
                elif font_size >= p70 and p70 > 0:
                    level = 2
                else:
                    # Fall back to LayoutLM type + bbox for level 3 vs 2
                    bbox = region.get("bbox", [0, 0, 0, 0])
                    page_width = page.get("width", 1000)
                    x_start_pct = (bbox[0] / page_width * 100) if page_width > 0 else 0
                    level = 3 if x_start_pct > 15 else 2
            else:
                # No font data — use original bbox heuristic
                bbox = region.get("bbox", [0, 0, 0, 0])
                page_width = page.get("width", 1000)
                x_start_pct = (bbox[0] / page_width * 100) if page_width > 0 else 0
                if rtype == "title":
                    level = 1
                elif x_start_pct > 15:
                    level = 3
                else:
                    level = 2

            toc.append(ToCEntry(
                title=text[:120],
                page_index=page_idx,
                level=level,
                region_type=rtype,
            ))
            page_headings += 1

    level_counts = {1: sum(1 for e in toc if e.level == 1),
                    2: sum(1 for e in toc if e.level == 2),
                    3: sum(1 for e in toc if e.level == 3)}
    logger.info("[chunking] Built ToC with %d entries from %d pages (L1=%d, L2=%d, L3=%d)",
                len(toc), len(pages), level_counts[1], level_counts[2], level_counts[3])
    return toc


def split_into_chunks(
    pages: list[dict[str, Any]],
    toc: list[ToCEntry],
    doc_title: str = "Untitled",
    max_pages_per_chunk: int = 5,
) -> list[DocumentChunk]:
    """Split document into chunks at section boundaries with context prefixes.

    Args:
        pages: Full page data (from LayoutLM or raw extraction).
        toc: Document table of contents.
        doc_title: Document title for context prefix.
        max_pages_per_chunk: Maximum pages per chunk (safety limit).

    Returns:
        List of DocumentChunk objects ready for LLM processing.
    """
    if not pages:
        return []

    total_pages = len(pages)

    # Find section boundaries (pages where new sections start)
    section_breaks: list[int] = [0]  # always start at page 0
    for entry in toc:
        if entry.level <= 2 and entry.page_index not in section_breaks:
            section_breaks.append(entry.page_index)
    section_breaks.sort()

    # Create page ranges for each chunk
    chunk_ranges: list[tuple[int, int]] = []
    for i, start in enumerate(section_breaks):
        end = section_breaks[i + 1] if i + 1 < len(section_breaks) else total_pages
        # Split large sections into sub-chunks
        while start < end:
            chunk_end = min(start + max_pages_per_chunk, end)
            chunk_ranges.append((start, chunk_end))
            start = chunk_end

    # Build chunks with context prefixes
    chunks: list[DocumentChunk] = []
    prior_sections_summary: list[str] = []

    for chunk_idx, (start, end) in enumerate(chunk_ranges):
        page_indices = list(range(start, end))
        chunk_pages = [p for p in pages if p.get("page_index") in page_indices]

        # Find section title for this chunk
        section_title = "Content"
        for entry in reversed(toc):
            if entry.page_index <= start:
                section_title = entry.title
                break

        # Build context prefix
        toc_summary = _format_toc_summary(toc, current_page=start)
        prior_summary = "; ".join(prior_sections_summary[-5:]) if prior_sections_summary else "None"

        context_prefix = (
            f"[Document: \"{doc_title}\" ({total_pages} pages). "
            f"Outline: {toc_summary}. "
            f"Prior sections summary: {prior_summary}. "
            f"NOW READING: \"{section_title}\" (pages {start + 1}-{end})]"
        )

        chunks.append(DocumentChunk(
            chunk_id=chunk_idx,
            pages=page_indices,
            section_title=section_title,
            context_prefix=context_prefix,
            content=chunk_pages,
            toc_position=f"Section {chunk_idx + 1} of {len(chunk_ranges)}",
        ))

        # Update prior sections summary for next chunk's context
        # Extract key info from this chunk for future reference
        chunk_text_preview = _summarize_chunk(chunk_pages)
        if chunk_text_preview:
            prior_sections_summary.append(f"{section_title}: {chunk_text_preview}")

    logger.info(
        "[chunking] Split %d pages into %d chunks (max %d pages/chunk)",
        total_pages, len(chunks), max_pages_per_chunk,
    )
    return chunks


def _format_toc_summary(toc: list[ToCEntry], current_page: int, max_entries: int = 10) -> str:
    """Format ToC as compact string, marking current position."""
    if not toc:
        return "No headings detected"

    parts: list[str] = []
    for entry in toc[:max_entries]:
        marker = "→" if entry.page_index <= current_page else " "
        indent = "  " * (entry.level - 1)
        parts.append(f"{marker}{indent}{entry.title}")

    if len(toc) > max_entries:
        parts.append(f"  ...({len(toc) - max_entries} more)")

    return " | ".join(parts)


def _summarize_chunk(pages: list[dict[str, Any]], max_chars: int = 150) -> str:
    """Extract brief text summary from chunk pages for context injection."""
    texts: list[str] = []
    for p in pages:
        # Use blocks if available (from pass 2.5 merge)
        blocks = p.get("blocks") or []
        if blocks:
            for block in blocks[:5]:
                if block.get("type") in ("heading", "paragraph"):
                    content = block.get("content", "")
                    if content:
                        texts.append(content[:100])
                elif block.get("type") == "table":
                    cols = block.get("columns", [])
                    texts.append(f"Table({','.join(cols[:3])})")
        else:
            # Fallback to raw_text
            text = p.get("raw_text") or p.get("text") or ""
            if text:
                texts.append(text[:200])

    combined = " ".join(texts)[:max_chars]
    return combined.strip() if combined.strip() else ""
