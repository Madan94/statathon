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


def build_toc_from_regions(pages: list[dict[str, Any]]) -> list[ToCEntry]:
    """Extract Table of Contents from LayoutLM-detected heading regions.

    Args:
        pages: LayoutLM output with regions per page.

    Returns:
        Ordered list of ToCEntry objects representing document structure.
    """
    toc: list[ToCEntry] = []
    seen_titles: set[str] = set()
    MAX_PER_PAGE = 8
    MIN_CONFIDENCE = 0.5

    for page in pages:
        page_idx = page.get("page_index", 0)
        regions = page.get("regions") or []
        page_headings = 0

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
            # Skip very short or very long entries (noise)
            if len(text) < 3 or len(text) > 150:
                continue

            # Deduplicate (case-insensitive, strip numbers/punctuation)
            dedup_key = text.lower().strip("0123456789.-: ")
            if dedup_key in seen_titles:
                continue
            seen_titles.add(dedup_key)

            # Estimate heading level from region type + bbox width
            bbox = region.get("bbox", [0, 0, 0, 0])
            page_width = page.get("width", 1000)
            x_start_pct = (bbox[0] / page_width * 100) if page_width > 0 else 0

            if rtype == "title":
                level = 1
            elif x_start_pct > 15:
                level = 3  # indented = subsection
            else:
                level = 2

            toc.append(ToCEntry(
                title=text[:120],
                page_index=page_idx,
                level=level,
                region_type=rtype,
            ))
            page_headings += 1

    logger.info("[chunking] Built ToC with %d entries from %d pages", len(toc), len(pages))
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
        # Try raw_text first (normalized pages), then text (raw ColPali)
        text = p.get("raw_text") or p.get("text") or ""
        if text:
            texts.append(text[:200])

    combined = " ".join(texts)[:max_chars]
    return combined.strip() if combined.strip() else ""
