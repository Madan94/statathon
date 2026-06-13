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
    # No per-page cap — MoSPI PDFs can have many valid headings per page
    MIN_CONFIDENCE = 0.3  # LayoutLM is generally accurate; 0.5 was too aggressive

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
        thresholds = page_font_thresholds.get(page_idx)

        for region in regions:
            rtype = region.get("type", "")
            text = (region.get("text") or "").strip()
            confidence = region.get("confidence", 0.5)

            # Skip page-running headers/footers — these are not real section titles
            if rtype in ("header", "footer"):
                continue

            if rtype not in ("title", "heading") or not text:
                continue
            if confidence < MIN_CONFIDENCE:
                continue
            if len(text) < 6:
                continue
            # Single-word entries are LayoutLM false positives on dense government PDFs
            if " " not in text and text.upper() not in {"LFPR", "WPR", "UR", "MPCE", "CPI", "GDP", "NSO"}:
                continue
            # PIB nav-bar artifacts — reject entries containing timestamps or "Press Information"
            import re as _re_toc_filter
            if _re_toc_filter.search(
                r"Press\s*(Release|Information)|pib\.gov|\d+:\d+\s*[AP]M|\d+/\d+/\d+|Visitor Counter",
                text, _re_toc_filter.I
            ):
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
                title=text,  # full title — no truncation
                page_index=page_idx,
                level=level,
                region_type=rtype,
            ))

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


def _summarize_chunk(pages: list[dict[str, Any]], max_chars: int = 200) -> str:
    """Extract brief text summary from chunk pages for context injection.

    Now pulls caption, chart, and figure region texts from LayoutLM output
    to give richer semantic context about tables and charts on each page.
    """
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
                texts.append(text[:150])

        # Pull LayoutLM caption/chart/figure region texts for richer context
        for region in (p.get("regions") or []):
            rtype = region.get("type", "")
            rtext = (region.get("text") or "").strip()
            if rtype in ("caption", "chart", "figure") and rtext and len(rtext) > 5:
                texts.append(f"[{rtype}: {rtext[:80]}]")

    combined = " ".join(texts)[:max_chars]
    return combined.strip() if combined.strip() else ""


def extract_caption_entities_from_layout(
    layout_pages: list[dict[str, Any]],
) -> dict[int, list[str]]:
    """Extract table/figure caption texts from LayoutLM regions, keyed by page index.

    These are high-quality entity sources: "Statement 5.1 — LFPR by State" tells us
    the table title, the measure (LFPR), and the dimension (State) in one string.

    Returns:
        Dict mapping page_index → list of caption/chart-title strings
    """
    result: dict[int, list[str]] = {}
    for page in layout_pages:
        page_idx = page.get("page_index", 0)
        captions: list[str] = []
        for region in (page.get("regions") or []):
            rtype = region.get("type", "")
            rtext = (region.get("text") or "").strip()
            if rtype in ("caption", "chart") and rtext and len(rtext) > 5:
                captions.append(rtext)
        if captions:
            result[page_idx] = captions
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: Document Section Graph
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SectionBlock:
    """A structural section of the document derived from LayoutLM + ToC."""
    sectionId: str
    title: str
    pageStart: int
    pageEnd: int
    level: int
    headingRegion: dict[str, Any] | None = None
    textRegions: list[dict[str, Any]] = field(default_factory=list)
    listRegions: list[dict[str, Any]] = field(default_factory=list)
    figureRegions: list[dict[str, Any]] = field(default_factory=list)
    captionRegions: list[dict[str, Any]] = field(default_factory=list)
    isBackMatter: bool = False
    expectedEntities: list[str] = field(default_factory=list)

    def figure_count(self) -> int:
        return len(self.figureRegions)

    def has_figures(self) -> bool:
        return len(self.figureRegions) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "sectionId": self.sectionId,
            "title": self.title,
            "pageStart": self.pageStart,
            "pageEnd": self.pageEnd,
            "level": self.level,
            "isBackMatter": self.isBackMatter,
            "figureCount": self.figure_count(),
            "expectedEntities": self.expectedEntities,
        }


@dataclass
class DocumentSectionGraph:
    """Complete section-level representation of a document."""
    docType: str
    title: str
    sections: list[SectionBlock] = field(default_factory=list)
    backMatter: list[SectionBlock] = field(default_factory=list)
    orphanRegions: list[dict[str, Any]] = field(default_factory=list)

    def section_for_page(self, page: int) -> SectionBlock | None:
        """Find the section that owns a given page."""
        for sec in self.sections:
            if sec.pageStart <= page <= sec.pageEnd:
                return sec
        for sec in self.backMatter:
            if sec.pageStart <= page <= sec.pageEnd:
                return sec
        return None

    def figures_for_section(self, section_id: str) -> list[dict[str, Any]]:
        """Get all figure regions belonging to a section."""
        for sec in self.sections + self.backMatter:
            if sec.sectionId == section_id:
                return sec.figureRegions
        return []

    def analytic_sections(self) -> list[SectionBlock]:
        """Non-backMatter sections (the analytic content)."""
        return [s for s in self.sections if not s.isBackMatter]

    def to_dict(self) -> dict[str, Any]:
        return {
            "docType": self.docType,
            "title": self.title,
            "sections": len(self.sections),
            "backMatter": len(self.backMatter),
            "figuresAssociated": sum(s.figure_count() for s in self.sections + self.backMatter),
            "orphanRegions": len(self.orphanRegions),
            "sectionList": [s.to_dict() for s in self.sections + self.backMatter],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

import re as _re_sg


def normalize_section_title(title: str) -> str:
    """Normalize a section title: remove leading numbers, excess whitespace."""
    t = title.strip()
    # Remove leading "1. " or "1 " or "A. " style prefixes
    t = _re_sg.sub(r"^\d{1,2}[\.\s]+", "", t)
    t = _re_sg.sub(r"^[A-Z][\.\s]+", "", t)
    # Collapse whitespace
    t = _re_sg.sub(r"\s+", " ", t).strip()
    return t


def is_back_matter_title(title: str) -> bool:
    """Detect methodology / endnote / appendix sections."""
    t = title.lower().strip()
    # Remove leading letter prefix: "A. Introduction" → "introduction"
    t = _re_sg.sub(r"^[a-z][\.\s]+", "", t)
    back_signals = [
        "introduction", "sample size", "sample design", "methodology",
        "conceptual framework", "compatibility", "definitions",
        "endnote", "appendix", "annexure", "detailed tables",
        "abbreviation", "notes", "reference", "source",
    ]
    return any(s in t for s in back_signals)


def expected_entities_for_section(title: str, doc_type: str = "", domain_pack: Any = None) -> list[str]:
    """Assign expected entity IDs to a section based on title keywords.

    For PLFS/PIB, maps section topics to domain entity names.
    """
    t = title.lower()

    # PLFS/PIB section-to-entity mapping
    _PLFS_SECTION_ENTITIES: dict[str, list[str]] = {
        "lfpr": ["Labour Force Participation Rate", "Gender", "Sector"],
        "labour force participation": ["Labour Force Participation Rate", "Gender", "Sector"],
        "worker population": ["Worker Population Ratio", "Gender", "Sector"],
        "wpr": ["Worker Population Ratio", "Gender", "Sector"],
        "unemployment": ["Unemployment Rate", "Gender", "Sector"],
        "ur ": ["Unemployment Rate", "Gender", "Sector"],
        "regular wage": ["Worker Share", "Employment Status", "Gender"],
        "proportion of workers": ["Worker Share", "Employment Status"],
        "employment status": ["Worker Share", "Employment Status", "Sector"],
        "manufacturing": ["Worker Share", "Industry", "Gender"],
        "service sector": ["Worker Share", "Industry"],
        "industry": ["Worker Share", "Industry", "Sector"],
        "earning": ["Average Monthly Earnings", "Gender", "Employment Status"],
        "female worker": ["Average Monthly Earnings", "Gender"],
        "wage": ["Average Monthly Earnings", "Employment Status"],
        "education": ["Formal Education Years", "Gender", "Sector"],
        "formal education": ["Formal Education Years", "Gender", "Sector"],
        "sample size": ["Survey Period"],
        "methodology": ["Periodic Labour Force Survey"],
        "snapshot": ["Labour Force Participation Rate", "Worker Population Ratio", "Unemployment Rate"],
        "key findings": ["Labour Force Participation Rate", "Worker Population Ratio", "Unemployment Rate"],
    }

    entities: list[str] = []
    for keyword, ent_names in _PLFS_SECTION_ENTITIES.items():
        if keyword in t:
            for name in ent_names:
                if name not in entities:
                    entities.append(name)

    return entities


def _deduplicate_toc_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate ToC entries that differ only in numbering format.

    E.g. "2 Worker Population..." and "2. Worker Population..." on the same page
    should collapse to one entry.
    """
    seen: dict[str, dict[str, Any]] = {}  # normalized_title → entry
    for entry in entries:
        title = entry.get("title", "")
        # Normalize: remove leading number/letter prefixes and period
        norm = normalize_section_title(title).lower()[:50]
        page = entry.get("page", 0)
        key = f"{page}:{norm}"
        if key not in seen:
            seen[key] = entry
        else:
            # Keep the one with higher level (more important)
            existing_level = seen[key].get("level", 9)
            new_level = entry.get("level", 9)
            if new_level < existing_level:
                seen[key] = entry
    return list(seen.values())


# ─────────────────────────────────────────────────────────────────────────────
# Main Builder
# ─────────────────────────────────────────────────────────────────────────────


def build_section_graph(
    toc_entries: list[ToCEntry] | list[dict[str, Any]],
    layout_pages: list[dict[str, Any]],
    page_texts: list[dict[str, Any]] | None = None,
    doc_type: str = "statistical_annual_report",
    domain_pack: Any = None,
    doc_title: str = "Document",
) -> DocumentSectionGraph:
    """Build a DocumentSectionGraph from ToC entries + LayoutLM regions.

    Algorithm:
    1. Normalize and deduplicate ToC entries
    2. Determine page ranges per section
    3. Mark backMatter sections
    4. Attach LayoutLM regions to sections
    5. Assign expected entities from domain pack
    6. Associate figures to nearest heading section

    Args:
        toc_entries: From build_toc_from_regions() or pass1 output
        layout_pages: LayoutLM output per page (with regions)
        page_texts: Optional pdfplumber text per page
        doc_type: Document type for domain-specific logic
        domain_pack: Optional domain pack module for entity mapping
        doc_title: Document title

    Returns:
        DocumentSectionGraph with sections, backMatter, orphan regions
    """
    total_pages = max(len(layout_pages), len(page_texts or []))

    # 1. Normalize ToC entries to dicts
    raw_entries: list[dict[str, Any]] = []
    for entry in toc_entries:
        if isinstance(entry, ToCEntry):
            raw_entries.append({"title": entry.title, "page": entry.page_index, "level": entry.level})
        elif isinstance(entry, dict):
            raw_entries.append({
                "title": entry.get("title", ""),
                "page": entry.get("page", entry.get("page_index", 0)),
                "level": entry.get("level", 2),
            })

    # Sort by page then level
    raw_entries.sort(key=lambda e: (e["page"], e["level"]))

    # 2. Deduplicate (e.g. "2 WPR..." and "2. WPR..." on same page)
    deduped = _deduplicate_toc_entries(raw_entries)
    deduped.sort(key=lambda e: (e["page"], e["level"]))

    # 3. Build sections with page ranges
    sections: list[SectionBlock] = []
    for i, entry in enumerate(deduped):
        title = entry["title"]
        page_start = entry["page"]
        level = entry["level"]

        # Page end: next entry's page - 1, or last page
        if i + 1 < len(deduped):
            # Find next same-or-higher level entry (not sub-sections)
            page_end = page_start  # default: single page
            for j in range(i + 1, len(deduped)):
                next_entry = deduped[j]
                if next_entry["level"] <= level:
                    page_end = max(page_start, next_entry["page"] - 1)
                    break
            else:
                page_end = total_pages - 1
        else:
            page_end = total_pages - 1

        # Ensure page_end >= page_start
        page_end = max(page_end, page_start)

        # 4. Mark backMatter
        is_back = is_back_matter_title(title)

        # 5. Assign expected entities
        expected = expected_entities_for_section(title, doc_type, domain_pack)

        sec = SectionBlock(
            sectionId=f"sg_{i:02d}",
            title=title,
            pageStart=page_start,
            pageEnd=page_end,
            level=level,
            isBackMatter=is_back,
            expectedEntities=expected,
        )
        sections.append(sec)

    # 6. Attach LayoutLM regions to sections
    orphans: list[dict[str, Any]] = []
    for page_idx, page in enumerate(layout_pages):
        for region in (page.get("regions") or []):
            rtype = region.get("type", "")
            rtext = (region.get("text") or "").strip()

            # Skip headers/footers
            if rtype in ("header", "footer"):
                continue

            # Find owning section
            owning_section: SectionBlock | None = None
            for sec in sections:
                if sec.pageStart <= page_idx <= sec.pageEnd:
                    owning_section = sec
                    break

            if not owning_section:
                orphans.append({"page": page_idx, "type": rtype, "text": rtext[:80]})
                continue

            region_data = {"page": page_idx, "type": rtype, "text": rtext, "confidence": region.get("confidence", 0)}

            if rtype in ("title", "heading"):
                if not owning_section.headingRegion:
                    owning_section.headingRegion = region_data
            elif rtype in ("text", "paragraph"):
                owning_section.textRegions.append(region_data)
            elif rtype in ("list", "list-item"):
                owning_section.listRegions.append(region_data)
            elif rtype in ("figure", "picture"):
                owning_section.figureRegions.append(region_data)
            elif rtype == "caption":
                owning_section.captionRegions.append(region_data)
            else:
                owning_section.textRegions.append(region_data)

    # 7. Split into analytic vs backMatter
    analytic = [s for s in sections if not s.isBackMatter]
    back_matter = [s for s in sections if s.isBackMatter]

    graph = DocumentSectionGraph(
        docType=doc_type,
        title=doc_title,
        sections=analytic,
        backMatter=back_matter,
        orphanRegions=orphans,
    )

    logger.info(
        "[section-graph] Built: %d analytic sections, %d backMatter, %d figures associated, %d orphans",
        len(analytic), len(back_matter),
        sum(s.figure_count() for s in sections),
        len(orphans),
    )

    return graph
