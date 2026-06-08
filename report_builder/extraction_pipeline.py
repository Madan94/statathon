"""Multi-Pass Extraction Pipeline — LayoutLM + Qwen-VL.

Orchestrates the 7-pass extraction flow for Enterprise Document AST + Blueprint:
    Pass 0: PDF rasterization (pdf2image 150dpi + pdfplumber raw text/tables/words)
    Pass 1: Layout detection via LayoutLMv3 (CPU, port 8001) → regions per page
    Pass 2: Entity + Structure extraction via Qwen2.5-VL (GPU, port 8002)
            → per-page entities, structure_type, description, chart_types (50-150 tokens)
    Pass 2.5: Document Knowledge Graph (PROGRAMMATIC, no LLM)
            → entity merge, table structure analysis, chapter hierarchy,
              per-page context scripts, MoSPI section pattern detection
    Pass 3: Two-loop AST building via Qwen-VL (GPU)
            Loop 1: question extraction per section chunk
            Loop 2: entity binding + AnswerStructure per question
    Pass 4: Programmatic assembly → Enterprise AST + embedded blueprint subtree
            (TopicNode → QuestionNode → AnswerStructure → AnswerComponent)
    Pass 5: Optional Gemini enhancement
            → entity classification, alias gen, blueprint validation, gap fill

Architecture:
    - LayoutLM detects WHERE things are (bboxes, types: table/heading/text/figure)
    - Qwen-VL extracts ENTITIES + STRUCTURE + SEMANTIC CONTEXT (NOT text/values)
    - pdfplumber table headers = gold standard entity source
    - Per-page UNIQUE context scripts (position-aware, entity-carrying)
    - Pipeline works fully offline without Gemini

Environment variables:
    LAYOUTLM_ENDPOINT       = http://localhost:8001
    SGLANG_ENDPOINT         = http://localhost:8002
    SGLANG_MODEL            = Qwen/Qwen2.5-VL-3B-Instruct-AWQ
    PIPELINE_GPU_MODE       = sequential | concurrent | gemini_only
    GEMINI_MODEL            = gemini-2.5-flash
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

from report_builder.chunking import (
    ToCEntry,
    build_toc_from_regions,
    extract_caption_entities_from_layout,
)

logger = logging.getLogger(__name__)

_LAYOUTLM_ENDPOINT = os.getenv("LAYOUTLM_ENDPOINT", "http://localhost:8001")
_SGLANG_ENDPOINT = os.getenv("SGLANG_ENDPOINT", "http://localhost:8002")


# ─────────────────────────────────────────────────────────────────────────────
# Robust JSON Extraction (handles truncated / wrapped VLM output)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json_from_response(raw: str) -> dict | None:
    """Extract a JSON dict from potentially messy LLM output.

    Handles:
        - Markdown code blocks (```json ... ```, ``` ... ```)
        - Text before/after JSON
        - Truncated JSON (attempts bracket repair)
        - Partial arrays
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # Strip markdown code fences (multiple formats)
    if "```" in text:
        # Find content between first ``` and last ```
        parts = text.split("```")
        if len(parts) >= 3:
            # Take the content of the first fenced block
            inner = parts[1]
            # Remove language tag (e.g., "json\n")
            if inner and inner.split("\n", 1)[0].strip().isalpha():
                inner = inner.split("\n", 1)[-1]
            text = inner.strip()
        elif len(parts) == 2:
            # Opening ``` without closing — take everything after it
            inner = parts[1]
            if inner and inner.split("\n", 1)[0].strip().isalpha():
                inner = inner.split("\n", 1)[-1]
            text = inner.strip()

    # Try direct parse first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Find the first { and try to parse from there
    brace_start = text.find("{")
    if brace_start == -1:
        return None

    candidate = text[brace_start:]

    # Try direct parse of substring
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Try trimming trailing text after last }
    brace_end = candidate.rfind("}")
    if brace_end >= 0:
        trimmed = candidate[: brace_end + 1]
        try:
            obj = json.loads(trimmed)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # Attempt repair of truncated JSON: close unclosed brackets
    repaired = _repair_truncated_json(candidate)
    if repaired:
        try:
            obj = json.loads(repaired)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    return None


def _repair_truncated_json(text: str) -> str | None:
    """Attempt to close unclosed brackets/braces in truncated JSON."""
    # Count open/close brackets
    open_braces = 0
    open_brackets = 0
    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            open_braces += 1
        elif ch == "}":
            open_braces -= 1
        elif ch == "[":
            open_brackets += 1
        elif ch == "]":
            open_brackets -= 1

    if open_braces <= 0 and open_brackets <= 0:
        return None  # Not truncated, just invalid

    # Close unclosed structures
    # First strip any trailing incomplete key/value
    # Find last complete value (ends with ", or }, or ], or number, or true/false/null)
    import re
    # Remove trailing partial string or key
    cleaned = re.sub(r',\s*"[^"]*$', '', text)  # trailing "incomplete_key
    cleaned = re.sub(r',\s*"[^"]*":\s*"[^"]*$', '', cleaned)  # trailing "key": "incomplete_val
    cleaned = re.sub(r',\s*"[^"]*":\s*\[[^\]]*$', lambda m: m.group(0) + "]", cleaned)  # close trailing array
    cleaned = re.sub(r',\s*$', '', cleaned)  # trailing comma

    # Recount after cleanup
    open_braces = 0
    open_brackets = 0
    in_string = False
    escape_next = False
    for ch in cleaned:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            open_braces += 1
        elif ch == "}":
            open_braces -= 1
        elif ch == "[":
            open_brackets += 1
        elif ch == "]":
            open_brackets -= 1

    # Append closers
    suffix = "]" * max(open_brackets, 0) + "}" * max(open_braces, 0)
    return cleaned + suffix if suffix else None


# ─────────────────────────────────────────────────────────────────────────────
# Entity Name Validation — shared by all passes
# ─────────────────────────────────────────────────────────────────────────────

_ENGLISH_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "up", "into", "then", "than",
    "this", "that", "these", "those", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "not",
    "no", "nor", "so", "yet", "both", "either", "each", "all", "any",
    "few", "more", "most", "other", "some", "such", "own", "same",
    "too", "very", "just", "as", "while", "also", "its", "it", "he",
    "she", "they", "we", "you", "i", "me", "him", "her", "us", "them",
    "our", "your", "their", "my", "note", "fig", "tab", "sl", "sr",
    "viz", "viz.", "etc", "etc.", "per", "as", "re", "vs", "vs.",
})

# Known header qualifiers for MoSPI/NSSO tables — used in multi-row header merge
_HEADER_QUALIFIERS: frozenset[str] = frozenset({
    "rural", "urban", "total", "male", "female", "persons", "both",
    "code", "name", "number", "percent", "%", "rate", "ratio", "index",
    "0-14", "15-29", "30-44", "45-59", "60+", "15+", "15-59",
    "cws", "ups", "usps", "uss", "cwss",
    "q1", "q2", "q3", "q4", "jul-sep", "oct-dec", "jan-mar", "apr-jun",
    "2018-19", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24",
    "annual", "quarterly", "monthly",
})

import re as _re_entity

_FIGREF_RE = _re_entity.compile(
    r"^(table|figure|fig|chart|diagram|annex|appendix|statement|box|exhibit)\s+[\d.]+",
    _re_entity.I,
)
_NUMERIC_ONLY_RE = _re_entity.compile(r"^[\d,.\-+%\s/()]+$")
_URL_RE = _re_entity.compile(r"https?://|www\.", _re_entity.I)
_TIMESTAMP_RE = _re_entity.compile(r"^\d+/\d+/\d+|^\d+:\d+\s*[AP]M", _re_entity.I)
_PAREN_ABBREV_RE = _re_entity.compile(r"^\([A-Z+]{2,10}\):?$")

# Phrases that Qwen echoes verbatim from the prompt template
_PROMPT_ECHO_PHRASES: frozenset[str] = frozenset({
    "exactcolumnheader", "metricname", "sectiontitle", "entity1", "entity2",
    "specific analytical question", "one-line summary", "visible chart title",
    "exact column header", "exact section title", "metric name",
})


_COMMON_NOISE_WORDS: frozenset[str] = frozenset({
    "press", "page", "bureau", "release", "information", "ministry", "government",
    "india", "click", "here", "home", "back", "next", "previous", "download",
    "total", "number", "value", "data", "report", "result", "table", "figure",
    "note", "source", "item", "area", "time", "period", "year", "date",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "samrat", "cycle", "areas", "workers", "while", "engaged", "sustained",
    "market", "presented", "long", "mainly", "mainly",
})

import re as _re_entity_extra


def _is_valid_entity_name(name: str) -> bool:
    """Return True if name is a valid entity (not a stopword / noise / reference)."""
    cleaned = name.strip()
    # Minimum 4 chars
    if len(cleaned) < 4:
        return False
    if not any(c.isalpha() for c in cleaned):
        return False
    # Max 80 chars — no full sentences or section headings
    if len(cleaned) > 80:
        return False
    # Reject pure single-word lowercase (likely body-text noise)
    if " " not in cleaned and cleaned == cleaned.lower() and len(cleaned) < 8:
        return False
    if cleaned.lower() in _ENGLISH_STOPWORDS:
        return False
    if cleaned.lower() in _PROMPT_ECHO_PHRASES:
        return False
    if _FIGREF_RE.match(cleaned):
        return False
    if _NUMERIC_ONLY_RE.match(cleaned):
        return False
    if _URL_RE.search(cleaned):
        return False
    if _TIMESTAMP_RE.match(cleaned):
        return False
    # Section headings like "2. Worker Population Ratio..." — not entities
    if _re_entity_extra.match(r'^\d{1,2}\.\s+[A-Z]', cleaned):
        return False
    # Data value fragments containing mid-string percentages (e.g., "WPR for male 78.4%,")
    if _re_entity_extra.search(r'\d+\.?\d*%', cleaned) and len(cleaned) > 25:
        return False
    # Reject fragment artifacts ending with comma/semicolon
    if cleaned[-1] in ".,;:—–" and len(cleaned.split()) <= 4:
        return False
    # Reject pure parenthetical abbreviations like "(PLFS)" "(WPR):"
    if _PAREN_ABBREV_RE.match(cleaned):
        return False
    if cleaned.lower() in _COMMON_NOISE_WORDS:
        return False
    return True


def _merge_multirow_headers(table: list[list]) -> tuple[list[str], int]:
    """Merge multi-row spanning headers common in MoSPI/NSSO PDFs.

    Example (PLFS table):
        Row 0: "State/UT", None,    "LFPR",    None,    None,    "WPR",    None,    None
        Row 1: "Code",     "Rural", "Urban",   "Total", "Rural", "Urban",  "Total"
        → merged: ["State/UT Code", "LFPR Rural", "LFPR Urban", "LFPR Total",
                   "WPR Rural", "WPR Urban", "WPR Total"]

    Returns:
        (merged_header_list, data_start_row_index)
    """
    if not table:
        return [], 0

    row0 = [str(c or "").strip() for c in table[0]]
    if len(table) < 2:
        return row0, 1

    row1 = [str(c or "").strip() for c in table[1]]
    total_cols = max(len(row0), len(row1))
    if total_cols == 0:
        return row0, 1

    # Count truly empty cells in row 0
    empty_in_row0 = sum(1 for c in row0 if not c)

    # Single-row header: fewer than 25% empty cells
    if empty_in_row0 < max(1, total_cols * 0.25):
        return row0, 1

    # Decide if row 1 looks like qualifiers (not data rows)
    non_empty_r1 = [c for c in row1 if c]
    if not non_empty_r1:
        return row0, 1

    qualifier_hits = sum(
        1 for c in non_empty_r1
        if c.lower() in _HEADER_QUALIFIERS or len(c) <= 12
    )
    row1_is_qualifier = qualifier_hits >= len(non_empty_r1) * 0.5

    if not row1_is_qualifier:
        return row0, 1

    # Forward-fill row 0: propagate non-empty values rightward across merged cells
    filled_row0: list[str] = []
    last_val = ""
    for cell in row0:
        if cell:
            last_val = cell
            filled_row0.append(cell)
        else:
            filled_row0.append(last_val)

    # Combine: for positions where row0 was empty, prefix(filled) + qualifier(row1)
    merged: list[str] = []
    for j in range(total_cols):
        orig0 = row0[j] if j < len(row0) else ""
        fill0 = filled_row0[j] if j < len(filled_row0) else ""
        r1 = row1[j] if j < len(row1) else ""

        if orig0 and r1 and r1.lower() != orig0.lower():
            # Both have distinct content → "State/UT Code"
            merged.append(f"{orig0} {r1}".strip())
        elif orig0:
            merged.append(orig0)
        elif fill0 and r1:
            # Span fill + qualifier → "LFPR Rural"
            merged.append(f"{fill0} {r1}".strip())
        elif r1:
            merged.append(r1)
        elif fill0:
            merged.append(fill0)
        else:
            merged.append(f"col_{j}")

    return merged, 2  # actual data starts at row index 2


# ─────────────────────────────────────────────────────────────────────────────
# MoSPI Domain Keywords — used in entity classification and question generation
# ─────────────────────────────────────────────────────────────────────────────

_MOSPI_MEASURE_KEYWORDS: frozenset[str] = frozenset({
    "lfpr", "wpr", "ur", "rate", "ratio", "index", "score", "percent", "%",
    "count", "total", "sum", "average", "mean", "median", "growth", "change",
    "mpce", "cpi", "gdp", "nsdp", "gsdp", "nva", "gva", "value", "amount",
    "expenditure", "income", "wage", "salary", "earning", "cost", "price",
    "production", "output", "yield", "area", "quantity", "volume",
    "population", "workforce", "worker", "employment", "unemployment",
    "participation", "enrolment", "literacy", "mortality", "fertility",
    "prevalence", "incidence", "coverage", "penetration",
})

_MOSPI_DIMENSION_KEYWORDS: frozenset[str] = frozenset({
    "state", "district", "region", "zone", "division", "block", "village",
    "urban", "rural", "sector", "gender", "male", "female", "sex",
    "age", "group", "cohort", "category", "class", "type", "kind",
    "occupation", "industry", "activity", "enterprise", "household",
    "social", "religion", "caste", "education", "qualification",
    "year", "quarter", "month", "period", "round", "survey",
    "annual", "quarterly", "monthly", "weekly", "daily",
})

_MOSPI_METADATA_KEYWORDS: frozenset[str] = frozenset({
    "source", "note", "notes", "methodology", "definition", "concept",
    "nsso", "census", "ministry", "mospi", "plfs", "nss", "cso",
    "government", "india", "reference", "base", "revision",
    "remark", "footnote", "abbreviation",
})

# MoSPI heading patterns for hybrid ToC extraction
_MOSPI_HEADING_PATTERNS = [
    # Chapter / Part patterns
    (r"^(CHAPTER|Chapter)\s+([IVXLC0-9]+)[:\.\s]+(.*)", 1),
    (r"^(PART|Part)\s+([IVXLCA-Z0-9]+)[:\.\s]+(.*)", 1),
    (r"^(SECTION|Section)\s+([IVXA-Z0-9]+)[:\.\s]+(.*)", 1),
    # Statement / Table / Annexure
    (r"^(Statement)\s+(\d+\.\d+)[:\s—\-]+(.*)", 2),
    (r"^(Table)\s+(\d+\.\d+)[:\.\s]+(.*)", 2),
    (r"^(ANNEXURE|Annexure|APPENDIX|Appendix)\s+([A-Z0-9\-]+)[:\.\s]*(.*)", 2),
    # Numbered sections (e.g. "1.2 Labour Force" or "1. Stable Labour Force")
    (r"^\d+\.\d+\s+[A-Z][A-Za-z\s]{5,}", 2),
    # Single-digit numbered sections: "1. Stable LFPR" "2. Worker Population" etc.
    (r"^(\d+)\.\s+([A-Z][A-Za-z\s,/\(\)]{8,})", 1),
    # ALL CAPS lines (≥ 8 chars, not just a label)
    (r"^([A-Z][A-Z\s\-/]{7,80})$", 1),
    # Letter-dot sections: "A. Introduction" "B. Sample Size"
    (r"^([A-Z])\.\s+([A-Z][A-Za-z\s]{5,})", 2),
]

# ─────────────────────────────────────────────────────────────────────────────
# Website Artifact Detection
# ─────────────────────────────────────────────────────────────────────────────

_WEBSITE_NAV_PATTERNS = [
    r"^\d+/\d+/\d+,?\s+\d+:\d+\s*[AP]M",   # "6/6/26, 9:49 AM"
    r"^:\d+\s*[AP]M",                         # ":49 AM"
    r"Press\s+(Release|Information)\s*(Page|Bureau)",
    r"www\.\w+\.gov\.in",
    r"https?://",
    r"^\d+/\d+$",                             # "1/11" page numbers
    r"\.aspx\?",                               # ASP.NET URLs
]
_WEBSITE_NAV_RE = [_re_entity.compile(p, _re_entity.I) for p in _WEBSITE_NAV_PATTERNS]


def _is_website_artifact_table(table: list[list]) -> bool:
    """Return True if this table is a website nav-bar artifact, not real data.

    PIB press release PDFs contain HTML nav-bar tables that pdfplumber falsely
    detects as data tables. They contain fragments like "Press Re", ":49 AM",
    "| Press Information Bu", split across cells. Scan ALL rows.
    """
    if not table:
        return False
    # Scan first 4 rows (nav bars are always at top/bottom of page)
    for row in table[:4]:
        if not row:
            continue
        row_text = " ".join(str(c or "") for c in row)
        combined = "".join(str(c or "") for c in row)
        for rx in _WEBSITE_NAV_RE:
            if rx.search(row_text):
                return True
        if _re_entity.search(r"Press\s*Releas|Information\s*Bur|AM\s*Press|\d+/\d+/\d+.*[AP]M", combined, _re_entity.I):
            return True
    # Additional check: small tables (<=8 non-empty cells) with nav phrases anywhere
    all_cells = [str(c or "").strip() for row in table for c in row if str(c or "").strip()]
    if 0 < len(all_cells) <= 8:
        all_text = " ".join(all_cells)
        if _re_entity.search(r"Press|Bureau|pib\.gov|mospi\.gov|:\d+\s*[AP]M|Release\s*Page", all_text, _re_entity.I):
            return True
    return False


def _fix_unicode_artifacts(text: str) -> str:
    """Remove control chars and fix common PDF encoding garbling.
    Patterns are expressed as raw byte/hex sequences for pure-ASCII source.
    """
    import re as _re_uni
    # Remove control characters
    text = _re_uni.sub(r"[\x00-\x08\x0e-\x1b]", "", text)
    # Fix garbled en/em dashes and Rupee sign using hex-encoded search patterns
    # UTF-8 E2 80 93 (en dash) mis-decoded as Win-1252: bytes E2=xE2 80=x80 93=x93
    _EN = chr(0x2013)  # en dash
    _EM = chr(0x2014)  # em dash
    _RS = chr(0x20b9)  # Rupee sign
    _LQ = chr(0x201c)  # left curly quote
    _AP = chr(0x2019)  # apostrophe
    _A  = chr(0x00e2)  # a with circumflex (mis-decoded byte E2)
    _EU = chr(0x20ac)  # euro sign (mis-decoded byte 80 in Win-1252)
    _LC = chr(0x201c)  # left curly quote (mis-decoded byte 93 in Win-1252)
    _RC = chr(0x201d)  # right curly quote (mis-decoded byte 94 in Win-1252)
    _OE = chr(0x0153)  # oe ligature (mis-decoded byte 9C in Win-1252)
    _TM = chr(0x2122)  # trade mark (mis-decoded byte 99 in Win-1252)
    _S1 = chr(0x00b9)  # superscript 1 (mis-decoded byte B9)
    text = text.replace(_A + _EU + _LC, _EN)  # a+euro+ldquote -> en dash
    text = text.replace(_A + _EU + _RC, _EM)  # a+euro+rdquote -> em dash
    text = text.replace(_A + _EU + _OE, _LQ)  # a+euro+oe -> left quote
    text = text.replace(_A + _EU + _TM, _AP)  # a+euro+TM -> apostrophe
    text = text.replace(_A + _S1, _RS)         # a+sup1 -> Rupee
    text = text.replace(_A + _EU, _EM)         # a+euro alone -> em dash
    text = text.replace(_A, _EN)               # lone a -> en dash
    return text

def _extract_toc_hybrid(
    page_texts: list[dict[str, Any]],
    layout_pages: list[dict[str, Any]],
    toc_layoutlm: list[ToCEntry],
) -> list[ToCEntry]:
    """3-level hybrid ToC cascade: L1 regex patterns -> L2 font-size -> L3 Gemini (last resort).

    L1 (regex): Numbered/all-caps patterns common in MoSPI/NSSO publications.
    L2 (font-size): pdfplumber word-level font sizes when L1 is sparse.
    L3 (Gemini): Last resort if L1+L2 together find fewer than 3 chapters.
    Always merges with LayoutLM output; caller gets the best combined result.
    """
    import re as _re_toc
    from difflib import SequenceMatcher as _SM

    # Regex patterns for MoSPI headings (returns (title, level))
    _PATTERNS: list[tuple[str, int]] = [
        (r"^(?:CHAPTER|Chapter)\s+([IVXLC0-9]+)[:\.\s]*(.*)", 1),
        (r"^(?:SECTION|Section)\s+([IVXA-Z0-9]+)[:\.\s]*(.*)", 1),
        (r"^(?:Statement)\s+(\d+[\.\-]\d+)[:\s\-]*(.*)", 2),
        (r"^(?:ANNEXURE|Annexure|APPENDIX|Appendix)\s+([A-Z0-9]+)[:\.\s]*(.*)", 2),
        # Numbered sections like "1. Stable LFPR..." — level 1 (primary chapter in PLFS/NSSO)
        (r"^(\d{1,2})\.\s+(.{8,})", 1),
        # Letter sections like "A. Introduction" — level 2 (endnotes/appendix sub-sections)
        (r"^([A-Z])\.\s+([A-Z].{5,})", 2),
        (r"^([A-Z][A-Z\s\-]{10,70})$", 1),              # ALL CAPS line >= 10 chars
    ]

    l1_entries_raw: list[ToCEntry] = []
    for page_idx, pt in enumerate(page_texts):
        raw = (pt.get("raw_text") or "").strip()
        for line in raw.splitlines():
            line = line.strip()
            if len(line) < 5 or len(line) > 250:
                continue
            for pat, level in _PATTERNS:
                m = _re_toc.match(pat, line)
                if m:
                    groups = [g for g in m.groups() if g and g.strip()]
                    title = " ".join(groups).strip()
                    if len(title) >= 4:
                        l1_entries_raw.append(ToCEntry(title=title, page_index=page_idx, level=level, region_type="regex"))
                    break  # first matching pattern wins

    # Deduplicate numbered sections by section number, keeping the LAST page occurrence.
    # PLFS press releases have a numbered summary on page 0 ("1. LFPR and WPR...")
    # AND real section headings on later pages ("1. Stable LFPR...").
    # We keep the last occurrence so the actual section heading wins over the snapshot item.
    _num_sec_re = _re_toc.compile(r"^(\d{1,2})\s+")
    _num_best: dict[str, ToCEntry] = {}  # section_number → best entry
    l1_other: list[ToCEntry] = []       # non-numbered entries (CAPS, Chapter, etc.)

    for entry in l1_entries_raw:
        m = _num_sec_re.match(entry.title)
        if m:
            num = m.group(1)
            # Always prefer later page (actual heading over snapshot body text)
            existing = _num_best.get(num)
            if existing is None or entry.page_index > existing.page_index:
                _num_best[num] = entry
        else:
            l1_other.append(entry)

    # Recombine: numbered sections (deduped) + non-numbered, sorted by page
    l1_entries = sorted(list(_num_best.values()) + l1_other, key=lambda e: (e.page_index, e.title))

    logger.info("[toc_hybrid] L1 regex: %d entries (raw=%d, deduped numbered=%d, other=%d)",
                len(l1_entries), len(l1_entries_raw), len(_num_best), len(l1_other))

    # L2: font-size hierarchy from pdfplumber words
    # Only fires when L1 is sparse. Requires a real heading-vs-body gap of >= 1.5pt.
    l2_entries: list[ToCEntry] = []
    if len(l1_entries) < 3:
        import statistics as _stats
        all_sizes: list[float] = []
        for pt in page_texts:
            for w in (pt.get("words") or []):
                sz = w.get("size") or w.get("fontsize") or 0
                if isinstance(sz, (int, float)) and 6 <= sz <= 72:
                    all_sizes.append(float(sz))

        if all_sizes:
            # Compute body text size as the mode/median (most common), NOT just "3rd largest"
            try:
                body_size = _stats.median(all_sizes)
            except Exception:
                body_size = sorted(all_sizes)[len(all_sizes) // 2]

            # Only treat a line as a heading if it's meaningfully larger than body text
            heading_threshold = body_size + 1.5   # must be at least 1.5pt above body
            h1_threshold = body_size + 3.0         # 3pt+ above body → H1

            # Collect unique sizes that qualify as headings
            heading_sizes = sorted(
                {s for s in all_sizes if s >= heading_threshold},
                reverse=True,
            )
            if not heading_sizes:
                logger.info("[toc_hybrid] L2 font-size: 0 entries (no size larger than body %.1fpt)", body_size)
            else:
                h1_sz = heading_sizes[0]
                h2_sz = heading_sizes[1] if len(heading_sizes) > 1 else h1_sz

                for page_idx, pt in enumerate(page_texts):
                    words = pt.get("words") or []
                    lines_by_y: dict[int, list[dict]] = {}
                    for w in words:
                        sz = w.get("size") or w.get("fontsize") or 0
                        if not isinstance(sz, (int, float)):
                            continue
                        sz = float(sz)
                        if sz >= heading_threshold:
                            y_key = int((w.get("top") or 0) // 4) * 4
                            lines_by_y.setdefault(y_key, []).append({"text": w.get("text", ""), "size": sz})

                    page_l2_count = 0
                    for y_key in sorted(lines_by_y):
                        if page_l2_count >= 3:  # max 3 L2 headings per page
                            break
                        grp = lines_by_y[y_key]
                        line_text = " ".join(g["text"] for g in grp).strip()
                        # Must have >= 2 words, >= 8 chars, not a page number
                        if len(line_text) < 8 or line_text.isdigit() or len(line_text.split()) < 2:
                            continue
                        max_sz = max(g["size"] for g in grp)
                        lvl = 1 if max_sz >= h1_sz - 0.5 else 2
                        l2_entries.append(ToCEntry(title=line_text, page_index=page_idx, level=lvl, region_type="font_size"))
                        page_l2_count += 1

        logger.info("[toc_hybrid] L2 font-size: %d entries (body=%.1fpt threshold)",
                    len(l2_entries), body_size if all_sizes else 0.0)

    # L3: Gemini last resort
    l3_entries: list[ToCEntry] = []
    combined_so_far = len(l1_entries) + len(l2_entries) + len(toc_layoutlm)
    if combined_so_far < 3:
        try:
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if api_key:
                sample_text = "\n\n".join(
                    (pt.get("raw_text") or "")[:800]
                    for pt in page_texts[:12]
                )
                prompt = (
                    "Extract the table of contents from this government statistical document.\n"
                    "Output JSON array: [{\"title\": \"Chapter title\", \"page\": 1, \"level\": 1}, ...]\n"
                    "level 1=chapter, 2=section, 3=subsection. JSON only.\n\n"
                    + sample_text[:6000]
                )
                gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
                try:
                    from google import genai as _genai
                    client = _genai.Client(api_key=api_key)
                    resp = client.models.generate_content(model=gemini_model, contents=prompt)
                    raw = (resp.text or "").strip()
                except ImportError:
                    import google.generativeai as _legacy
                    _legacy.configure(api_key=api_key)
                    resp = _legacy.GenerativeModel(gemini_model).generate_content(prompt)
                    raw = (resp.text or "").strip()

                parsed = _extract_json_array_from_response(raw)
                if parsed:
                    for item in parsed:
                        if not isinstance(item, dict):
                            continue
                        title = (item.get("title") or "").strip()
                        page = int(item.get("page") or 1) - 1
                        level = int(item.get("level") or 1)
                        if title and 0 <= page < len(page_texts):
                            l3_entries.append(ToCEntry(title=title, page_index=max(0, page), level=level, region_type="gemini"))
                    logger.info("[toc_hybrid] L3 Gemini: %d entries", len(l3_entries))
        except Exception as exc:
            logger.warning("[toc_hybrid] L3 Gemini failed (non-fatal): %s", exc)

    # Merge all sources: start from LayoutLM, add L1, L2, L3 (dedup by page+title)
    all_new = l1_entries + l2_entries + l3_entries
    merged = _merge_toc_sources(toc_layoutlm, all_new)
    logger.info("[toc_hybrid] merged: %d total entries (L1=%d L2=%d L3=%d layoutlm=%d)",
                len(merged), len(l1_entries), len(l2_entries), len(l3_entries), len(toc_layoutlm))
    return merged


def _merge_toc_sources(layoutlm: list[ToCEntry], new_entries: list[ToCEntry]) -> list[ToCEntry]:
    """Merge LayoutLM ToC with pattern/font/Gemini entries, deduplicated and sorted."""
    combined = list(layoutlm)
    seen = {(e.page_index, e.title.lower().strip()[:40]) for e in layoutlm}
    for e in new_entries:
        key = (e.page_index, e.title.lower().strip()[:40])
        if key not in seen:
            seen.add(key)
            combined.append(e)
    combined.sort(key=lambda e: (e.page_index, e.level))
    return combined


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2.6: Entity Type Classification (Improvement 3)
# ─────────────────────────────────────────────────────────────────────────────

def pass2_6_entity_classification(document_map: dict[str, Any]) -> dict[str, Any]:
    """Classify entities as dimension / measure / filter / metadata.

    Step 1 (always): Programmatic classification from table structure + keyword lists.
    Step 2 (optional): Gemini batch classification for ambiguous entities.

    Writes `entityType_hint` onto each entity in document_map["all_entities"].
    Returns the updated document_map.
    """
    all_entities = document_map.get("all_entities") or []
    table_structures = document_map.get("table_structures") or []

    if not all_entities:
        return document_map

    logger.info("[pass2.6] ▶ Entity type classification (%d entities)", len(all_entities))

    # Build lookup sets from table structures
    table_measures: set[str] = set()
    table_dimensions: set[str] = set()
    table_filter_values: set[str] = set()

    for ts in table_structures:
        for m in (ts.get("measures") or []):
            table_measures.add(m.lower())
        for d in (ts.get("dimensions") or []):
            table_dimensions.add(d.lower())
        for bd in (ts.get("breakdowns") or []):
            for v in (bd.get("values") or []):
                table_filter_values.add(v.lower())

    # ── Step 1: Programmatic classification ──
    ambiguous: list[dict[str, Any]] = []

    for ent in all_entities:
        name = ent.get("name") or ""
        name_lower = name.lower()

        # Table structure membership (highest confidence)
        if name_lower in table_measures:
            ent["entityType_hint"] = "measure"
            continue
        if name_lower in table_dimensions:
            ent["entityType_hint"] = "dimension"
            continue
        if name_lower in table_filter_values:
            ent["entityType_hint"] = "filter"
            continue

        # Metadata patterns
        if any(k in name_lower for k in _MOSPI_METADATA_KEYWORDS):
            ent["entityType_hint"] = "metadata"
            continue

        # Known measure keywords (whole word match)
        if any(k in name_lower.split() or name_lower == k for k in _MOSPI_MEASURE_KEYWORDS):
            ent["entityType_hint"] = "measure"
            continue

        # Known dimension keywords
        if any(k in name_lower.split() or name_lower == k for k in _MOSPI_DIMENSION_KEYWORDS):
            ent["entityType_hint"] = "dimension"
            continue

        # Source-type heuristics
        source = ent.get("source") or ""
        if source == "table_header":
            # Table headers: first column is dimension, others are likely measures
            # Use position in table to guess
            is_first_col = False
            for ts in table_structures:
                cols_lower = [c.lower() for c in (ts.get("columns") or [])]
                if cols_lower and cols_lower[0] == name_lower:
                    is_first_col = True
                    break
            ent["entityType_hint"] = "dimension" if is_first_col else "measure"
        elif source == "heading":
            ent["entityType_hint"] = "dimension"
        elif source == "vlm":
            ambiguous.append(ent)
            ent["entityType_hint"] = "dimension"  # default until Gemini updates
        else:
            ent["entityType_hint"] = "dimension"

    logger.info("[pass2.6]   Step 1 programmatic: %d measures, %d dimensions, %d metadata, %d ambiguous",
                sum(1 for e in all_entities if e.get("entityType_hint") == "measure"),
                sum(1 for e in all_entities if e.get("entityType_hint") == "dimension"),
                sum(1 for e in all_entities if e.get("entityType_hint") == "metadata"),
                len(ambiguous))

    # ── Step 2: Gemini batch classification for ambiguous entities ──
    ambiguous_to_classify = [e for e in ambiguous if e.get("entityType_hint") == "dimension"][:40]
    if ambiguous_to_classify:
        try:
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if api_key:
                doc_title = document_map.get("title", "document")
                entity_lines = "\n".join(
                    f'  "{e["name"]}"' for e in ambiguous_to_classify
                )
                table_ctx = ""
                for ts in table_structures[:5]:
                    table_ctx += f"Table cols: {', '.join(ts['columns'][:6])}\n"

                prompt = (
                    f'Document: "{doc_title}" (Indian government statistical report)\n'
                    f"Table structures:\n{table_ctx}\n"
                    "Classify each entity as one of: dimension, measure, filter, metadata\n"
                    "  dimension = categorical grouping variable (State, Gender, Sector, Year)\n"
                    "  measure = numeric metric to aggregate (LFPR, WPR, rate, count, total)\n"
                    "  filter = threshold or conditional value (Rural, Urban, Male, Female)\n"
                    "  metadata = source, methodology, notes (NSSO, Source, Note)\n\n"
                    f"Entities to classify:\n{entity_lines}\n\n"
                    'Output JSON array: [{"name": "LFPR", "type": "measure"}, ...]\n'
                    "JSON only."
                )
                gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
                try:
                    from google import genai as _genai
                    client = _genai.Client(api_key=api_key)
                    resp = client.models.generate_content(model=gemini_model, contents=prompt)
                    raw = (resp.text or "").strip()
                except ImportError:
                    import google.generativeai as _legacy
                    _legacy.configure(api_key=api_key)
                    resp = _legacy.GenerativeModel(gemini_model).generate_content(prompt)
                    raw = (resp.text or "").strip()

                classifications = _extract_json_array_from_response(raw)
                if classifications:
                    name_to_type: dict[str, str] = {
                        item.get("name", "").lower(): item.get("type", "dimension")
                        for item in classifications
                        if isinstance(item, dict)
                    }
                    updated = 0
                    for ent in ambiguous_to_classify:
                        classified = name_to_type.get(ent["name"].lower())
                        if classified in ("dimension", "measure", "filter", "metadata"):
                            ent["entityType_hint"] = classified
                            updated += 1
                    logger.info("[pass2.6]   Step 2 Gemini: classified %d ambiguous entities", updated)
        except Exception as exc:
            logger.warning("[pass2.6]   Step 2 Gemini failed (non-fatal): %s", exc)

    logger.info("[pass2.6] ✓ Classification complete: %d entities typed",
                sum(1 for e in all_entities if e.get("entityType_hint")))
    return document_map


# ─────────────────────────────────────────────────────────────────────────────
# Entity Reference Resolver — fuzzy name → entityId (Improvement 5)
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_entity_ref(ref_name: str, all_entities: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Resolve an entity reference string to an entity dict via exact → alias → fuzzy match.

    Used in Pass 3 Loop 2 and Pass 4 to convert Qwen-returned entity names
    (which may differ from how they are stored in the KG) to real entity dicts.
    """
    if not ref_name or not all_entities:
        return None

    ref_lower = ref_name.lower().strip()

    # 1. Exact match (case-insensitive)
    for e in all_entities:
        if e.get("name", "").lower() == ref_lower:
            return e

    # 2. Alias match
    for e in all_entities:
        for alias in (e.get("aliases") or []):
            if str(alias).lower() == ref_lower:
                return e

    # 3. Substring match (ref contains entity name or vice versa)
    for e in all_entities:
        ename = e.get("name", "").lower()
        if ename and (ref_lower in ename or ename in ref_lower) and len(ename) >= 3:
            return e

    # 4. Fuzzy match (SequenceMatcher)
    from difflib import SequenceMatcher
    best: dict[str, Any] | None = None
    best_score = 0.0
    for e in all_entities:
        score = SequenceMatcher(None, ref_lower, e.get("name", "").lower()).ratio()
        if score > best_score and score >= 0.70:
            best, best_score = e, score
    return best


# ─────────────────────────────────────────────────────────────────────────────
# Pass 0: PDF Rasterization
# ─────────────────────────────────────────────────────────────────────────────

def pass0_rasterize(pdf_path: Path) -> tuple[list[bytes], list[dict[str, Any]]]:
    """Rasterize PDF pages to PNG images + extract raw text with pdfplumber.

    Returns:
        (page_images_png, page_texts)
        page_images_png: list of PNG bytes per page
        page_texts: list of {raw_text, words, tables, width, height} per page
    """
    import pdfplumber

    logger.info("[pass0] Rasterizing PDF: %s", pdf_path.name)
    t0 = time.monotonic()

    # Rasterize pages to PNG
    try:
        import pdf2image
        poppler_path = os.getenv("POPPLER_PATH") or None
        images = pdf2image.convert_from_path(str(pdf_path), dpi=150, fmt="png", poppler_path=poppler_path)
    except Exception as exc:
        logger.error("[pass0] pdf2image failed: %s — trying Pillow fallback", exc)
        images = []

    # Resize images to fit within max dimension to reduce VLM token count
    _max_dim = int(os.getenv("VLM_MAX_IMAGE_DIM", "800"))
    page_images: list[bytes] = []
    for img in images:
        w, h = img.size
        if max(w, h) > _max_dim:
            scale = _max_dim / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), resample=1)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page_images.append(buf.getvalue())

    # Extract text with pdfplumber (backup + enrichment)
    page_texts: list[dict[str, Any]] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                raw_text = _fix_unicode_artifacts(page.extract_text() or "")
                words = page.extract_words(extra_attrs=["fontname", "size"], use_text_flow=True) or []

                # ── Table extraction: default first, then borderless fallback ──
                tables = page.extract_tables() or []
                # Filter out website navigation bar artifacts immediately
                tables = [t for t in tables if not _is_website_artifact_table(t)]
                if not tables:
                    # Borderless tables (common in govt PDFs) need text-alignment strategy
                    try:
                        borderless = page.extract_tables(table_settings={
                            "vertical_strategy": "text",
                            "horizontal_strategy": "text",
                            "snap_tolerance": 5,
                            "join_tolerance": 3,
                            "edge_min_length": 3,
                            "min_words_vertical": 3,
                            "min_words_horizontal": 1,
                        }) or []
                        # Filter nav-bar artifacts from borderless too
                        tables = [t for t in borderless if not _is_website_artifact_table(t)]
                    except Exception:
                        tables = []

                # Detect headings from font analysis
                headings: list[str] = []
                for w in words:
                    if w.get("size", 0) >= 12 or "Bold" in str(w.get("fontname", "")):
                        text = str(w.get("text", "")).strip()
                        if text and len(text) > 3:
                            headings.append(text)

                # ── Embedded image / chart detection ──
                # PDF embedded images that are large relative to the page
                # are almost certainly charts or figures.
                page_w = float(page.width or 595)
                page_h = float(page.height or 842)
                page_area = page_w * page_h
                embedded_figures: list[dict[str, Any]] = []
                try:
                    for img_obj in (page.images or []):
                        x0 = float(img_obj.get("x0") or 0)
                        y0 = float(img_obj.get("top") or img_obj.get("y0") or 0)
                        x1 = float(img_obj.get("x1") or page_w)
                        y1 = float(img_obj.get("bottom") or img_obj.get("y1") or page_h)
                        img_area = max(0.0, (x1 - x0) * (y1 - y0))
                        # Heuristic: embedded image covering >8% of page = likely figure/chart
                        if page_area > 0 and img_area / page_area >= 0.08:
                            embedded_figures.append({
                                "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                                "area_fraction": round(img_area / page_area, 3),
                                "source": "pdf_embedded",
                            })
                except Exception:
                    pass

                page_texts.append({
                    "raw_text": raw_text,
                    "words": words,
                    "tables": tables,
                    "headings": headings,
                    "embedded_figures": embedded_figures,
                    "width": page_w,
                    "height": page_h,
                    "word_count": len(raw_text.split()),
                })
    except Exception as exc:
        logger.warning("[pass0] pdfplumber failed: %s", exc)

    elapsed = time.monotonic() - t0
    logger.info("[pass0] ✓ Rasterized %d images + %d text pages (%.1fs)", len(page_images), len(page_texts), elapsed)
    return page_images, page_texts


# ─────────────────────────────────────────────────────────────────────────────
# Pass 1: Layout Detection via LayoutLMv3
# ─────────────────────────────────────────────────────────────────────────────

def pass1_layout_detection(pdf_path: Path) -> list[dict[str, Any]] | None:
    """Send PDF to LayoutLM service → get regions per page.

    Returns:
        List of page dicts with regions, or None on failure.
    """
    endpoint = _LAYOUTLM_ENDPOINT.rstrip("/") + "/analyze"
    timeout = int(os.getenv("LAYOUTLM_TIMEOUT", "300"))

    logger.info("[pass1] ▶ LayoutLM POST → %s (timeout=%ds)", endpoint, timeout)
    t0 = time.monotonic()

    try:
        with open(pdf_path, "rb") as f:
            r = requests.post(endpoint, files={"file": f}, timeout=timeout)
        r.raise_for_status()
        body = r.json()
        pages = body.get("pages") or []
        elapsed = time.monotonic() - t0
        logger.info("[pass1] ✓ LayoutLM detected regions on %d pages (%.1fs)", len(pages), elapsed)
        return pages
    except Exception as exc:
        elapsed = time.monotonic() - t0
        logger.error("[pass1] ✗ LayoutLM failed: %s (%.1fs)", exc, elapsed)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2: Entity + Structure Extraction via Qwen-VL (SIMPLIFIED)
# ─────────────────────────────────────────────────────────────────────────────

def pass2_entity_structure_extraction(
    page_images: list[bytes],
    layout_pages: list[dict[str, Any]],
    page_texts: list[dict[str, Any]],
    doc_title: str = "Document",
) -> list[dict[str, Any]]:
    """Extract ENTITIES + STRUCTURE TYPE + DESCRIPTION per page using Qwen-VL.

    This pass does NOT extract paragraph text or table values.
    Qwen-VL's job is to identify:
        - What entities/concepts appear on this page
        - What is the structural purpose of this page (data table, chart, narrative, etc.)
        - A one-line description of the page's content
        - What chart types are visible (if any)

    Output per page: ~50-150 tokens (never truncates at 2048 context).

    Falls back to pdfplumber headings + table headers as entity source if VLM fails.

    Returns:
        List of per-page dicts with {page_index, entities[], structure_type, description, chart_types[]}.
    """
    endpoint = _SGLANG_ENDPOINT.rstrip("/") + "/v1/chat/completions"
    model = os.getenv("SGLANG_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct-AWQ")
    timeout = int(os.getenv("SGLANG_TIMEOUT", "120"))
    total_pages = len(page_images)

    # Pre-flight: check if vLLM is alive
    vlm_alive = False
    if total_pages > 0:
        try:
            health_url = _SGLANG_ENDPOINT.rstrip("/") + "/v1/models"
            hr = requests.get(health_url, timeout=5)
            vlm_alive = hr.status_code == 200
        except Exception:
            pass
        if not vlm_alive:
            logger.warning("[pass2] vLLM not reachable — falling back to pdfplumber-only entities")

    # If vLLM is down, extract entities from pdfplumber only
    if not vlm_alive or total_pages == 0:
        results: list[dict[str, Any]] = []
        for i, page_text in enumerate(page_texts):
            entities = _entities_from_pdfplumber(page_text, i)
            has_tables = bool(page_text.get("tables"))
            results.append({
                "page_index": i,
                "entities": entities,
                "structure_type": "data_table" if has_tables else "narrative",
                "description": "",
                "chart_types": [],
                "vlm_used": False,
            })
        logger.info("[pass2] ✓ Built %d entity pages from pdfplumber (no VLM)", len(results))
        return results

    logger.info("[pass2] ▶ Entity+structure extraction: %d pages via Qwen-VL", total_pages)
    t0 = time.monotonic()

    results: list[dict[str, Any]] = []
    hard_failures = 0
    _max_hard_fail = int(os.getenv("VLM_MAX_CONSECUTIVE_FAIL", "3"))
    vlm_skipped = False

    for i, img_bytes in enumerate(page_images):
        page_text = page_texts[i] if i < len(page_texts) else {}
        page_layout = layout_pages[i] if i < len(layout_pages) else {}
        regions = page_layout.get("regions") or []

        vlm_result = None

        if vlm_skipped:
            pass
        elif hard_failures >= _max_hard_fail:
            logger.warning("[pass2] %d hard VLM failures — skipping VLM for remaining pages", hard_failures)
            vlm_skipped = True
        else:
            try:
                img_b64 = base64.b64encode(img_bytes).decode("utf-8")

                # Concise region hint from LayoutLM
                region_types = ", ".join(set(r.get("type", "?") for r in regions[:10])) or "none"
                # Hint if pdfplumber detected embedded images (likely charts)
                n_embedded = len(page_text.get("embedded_figures") or [])
                image_hint = f" (PDF has {n_embedded} embedded image(s) — likely charts/figures)" if n_embedded else ""

                prompt = (
                    f"Page {i + 1}/{total_pages} of \"{doc_title}\".\n"
                    f"Detected layout regions: {region_types}{image_hint}\n\n"
                    "Examine this page carefully. Your tasks:\n"
                    "1. List ONLY entities that appear VERBATIM as column headers, section titles, "
                    "or metric names visible on the page. Do NOT invent anything not explicitly "
                    "printed. Examples: 'LFPR', 'State/UT', 'Rural', 'Urban', "
                    "'Labour Force Participation Rate', 'Unemployment Rate', 'MPCE'. "
                    "Exclude articles ('the','a'), prepositions ('of','in'), "
                    "figure references ('Table 1','Figure 2.3'), pure numbers.\n"
                    "2. If a table is present, extract its exact visible title or statement number "
                    "(e.g. 'Statement 5.1', 'Table 3.2 — LFPR by State'). Use empty string if none.\n"
                    "3. If a section/chapter heading is visible, extract it exactly "
                    "(e.g. 'Chapter 3: Key Labour Market Indicators'). Use empty string if none.\n"
                    "4. Identify charts/graphs if visible: bar, line, pie, scatter, area, map.\n"
                    "5. Provide visible chart titles if any.\n"
                    "6. Classify the dominant page structure.\n"
                    "Output ONLY this JSON (no prose, no markdown):\n"
                    '{"entities":["ExactColumnHeader","MetricName"],'
                    '"structure_type":"data_table|chart_page|narrative|title_page|appendix|mixed",'
                    '"description":"one-line summary",'
                    '"table_title":"Statement X.Y or table title if present else empty",'
                    '"section_heading":"Chapter or section heading if present else empty",'
                    '"chart_types":["bar_chart","line_chart","pie_chart","scatter_plot","area_chart","map"],'
                    '"chart_titles":["visible chart title if any"]}\n'
                    "chart_types MUST be [] if no charts visible. JSON only."
                )

                payload = {
                    "model": model,
                    "messages": [
                        {"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                            {"type": "text", "text": prompt},
                        ]},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 256,
                }

                r = requests.post(endpoint, json=payload, timeout=timeout)
                if r.status_code == 200:
                    raw = r.json()["choices"][0]["message"]["content"].strip()
                    vlm_result = _extract_json_from_response(raw)
                    if vlm_result:
                        hard_failures = 0
                        logger.debug("[pass2] Page %d VLM OK — %d entities", i,
                                     len(vlm_result.get("entities") or []))
                    else:
                        logger.info("[pass2] Page %d VLM returned text but no valid JSON", i)
                elif r.status_code >= 500:
                    logger.warning("[pass2] Page %d VLM returned %d (hard failure)", i, r.status_code)
                    hard_failures += 1
                else:
                    logger.debug("[pass2] Page %d VLM returned %d", i, r.status_code)
                    hard_failures += 1
            except (requests.ConnectionError, requests.Timeout) as exc:
                logger.warning("[pass2] Page %d connection failed: %s", i, type(exc).__name__)
                hard_failures += 1
            except Exception as exc:
                logger.warning("[pass2] Page %d error: %s", i, exc)
                hard_failures += 1

        # Build result — merge VLM entities with pdfplumber entities
        pdfplumber_entities = _entities_from_pdfplumber(page_text, i)

        if vlm_result:
            vlm_entities = vlm_result.get("entities") or []
            # Normalize and validate: VLM returns list of strings; filter noise/stopwords
            vlm_entity_names = [
                str(e).strip() for e in vlm_entities
                if isinstance(e, str) and _is_valid_entity_name(str(e).strip())
            ]
            # Merge: VLM + pdfplumber, dedup by lowered name
            seen_lower: set[str] = set()
            merged_entities: list[dict[str, Any]] = []
            for name in vlm_entity_names:
                key = name.lower().strip()
                if key not in seen_lower:
                    seen_lower.add(key)
                    merged_entities.append({"name": name, "source": "vlm", "page": i})
            for ent in pdfplumber_entities:
                key = ent["name"].lower().strip()
                if key not in seen_lower:
                    seen_lower.add(key)
                    merged_entities.append(ent)

            # Extract table_title and section_heading — feed to ToC hybrid cascade
            table_title = str(vlm_result.get("table_title") or "").strip()
            section_heading = str(vlm_result.get("section_heading") or "").strip()

            results.append({
                "page_index": i,
                "entities": merged_entities,
                "structure_type": vlm_result.get("structure_type", "mixed"),
                "description": str(vlm_result.get("description", ""))[:200],
                "table_title": table_title,
                "section_heading": section_heading,
                "chart_types": vlm_result.get("chart_types") or [],
                "chart_titles": [str(t).strip() for t in (vlm_result.get("chart_titles") or []) if str(t).strip()],
                "vlm_used": True,
            })
        else:
            # Fallback: pdfplumber only
            has_tables = bool(page_text.get("tables"))
            # LayoutLM chart regions OR pdfplumber embedded images → chart_page
            has_charts_layoutlm = any(r.get("type") in ("chart", "figure") for r in regions)
            has_embedded = bool(page_text.get("embedded_figures"))
            if has_tables and (has_charts_layoutlm or has_embedded):
                stype = "mixed"
            elif has_tables:
                stype = "data_table"
            elif has_charts_layoutlm or has_embedded:
                stype = "chart_page"
            else:
                stype = "narrative"

            # Build chart_types from embedded figures if no VLM
            fallback_chart_types = []
            if has_charts_layoutlm:
                fallback_chart_types.append("chart")
            elif has_embedded:
                fallback_chart_types.append("figure")

            results.append({
                "page_index": i,
                "entities": pdfplumber_entities,
                "structure_type": stype,
                "description": "",
                "chart_types": fallback_chart_types,
                "chart_titles": [],
                "vlm_used": False,
            })

        if (i + 1) % 5 == 0 or i == total_pages - 1:
            logger.info("[pass2]   processed %d/%d pages (vlm_ok=%d)", i + 1, total_pages,
                        sum(1 for r in results if r.get("vlm_used")))

    elapsed = time.monotonic() - t0
    total_entities = sum(len(r.get("entities") or []) for r in results)
    logger.info("[pass2] ✓ Extracted %d entities from %d pages (%.1fs)", total_entities, len(results), elapsed)
    return results


def _entities_from_pdfplumber(page_text: dict[str, Any], page_index: int) -> list[dict[str, Any]]:
    """Extract entity candidates from pdfplumber data (table headers + headings).

    Priority: merged table headers > headings.
    Bold/large-font individual words are intentionally excluded — they produce
    stopwords and word fragments as entities.
    """
    entities: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(name: str, source: str):
        key = name.lower().strip()
        if key and key not in seen and _is_valid_entity_name(name) and len(name) < 100:
            seen.add(key)
            entities.append({"name": name.strip(), "source": source, "page": page_index})

    # Priority 1: Table headers — use multi-row merge to handle MoSPI spanning headers
    for table in (page_text.get("tables") or []):
        if table and len(table) >= 1:
            headers, _ = _merge_multirow_headers(table)
            for h in headers:
                if h:
                    _add(h, "table_header")

    # Priority 2: Headings (section/chapter titles from font analysis)
    for h in (page_text.get("headings") or []):
        if isinstance(h, str) and h.strip():
            _add(h.strip(), "heading")

    return entities


# ─────────────────────────────────────────────────────────────────────────────
# Numbered Section Extraction (used by Pass 2.5 Step 7)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_numbered_sections(page_texts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract numbered/lettered sections from raw page text without LLM.

    Matches patterns like:
      "1. Stable LFPR for Persons aged 15 Years..."
      "A. Introduction"
      "2.1 Labour Force Participation Rate"
    Returns list of dicts: {title, number, page_index, level, raw_line}
    """
    import re as _re_ns
    _SECTION_PATS = [
        (r"^(\d+\.\d+)\s+(.{8,})", 2),                 # 2.1 Sub-section
        (r"^(\d{1,2})\.\s+(.{8,})", 1),                 # 1. Section (PLFS numbered chapters)
        (r"^([A-Z])\.\s+([A-Z].{5,})", 2),              # A. Letter section (endnotes)
        (r"^(Statement\s+\d+[\.\-]\d+)[:\s\-]+(.{5,})", 2),  # Statement 5.1
    ]

    sections: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page_idx, pt in enumerate(page_texts):
        raw = (pt.get("raw_text") or "").strip()
        for line in raw.splitlines():
            line = line.strip()
            if len(line) < 6 or len(line) > 120:
                continue
            for pat, level in _SECTION_PATS:
                m = _re_ns.match(pat, line)
                if m:
                    number = m.group(1).strip()
                    title = m.group(2).strip()
                    key = title.lower()[:50]
                    if key not in seen and len(title) >= 5:
                        seen.add(key)
                        sections.append({
                            "number": number,
                            "title": title,
                            "page_index": page_idx,
                            "level": level,
                            "raw_line": line,
                        })
                    break

    return sections


def _generate_questions_from_sections(
    numbered_sections: list[dict[str, Any]],
    all_entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate pre-computed analytical questions from section headings (no LLM).

    For each section, produces 1-2 questions based on entity type hints found
    in the section title. These serve as fallback questions if Pass 3 VLM fails.
    Returns list of question dicts compatible with Pass 3 output schema.
    """
    _MEASURE_KEYWORDS_QG = {
        "lfpr", "labour force", "worker population", "wpr", "unemployment",
        "unemployment rate", "ur", "mpce", "consumption", "expenditure",
        "cpi", "inflation", "earnings", "wage", "salary", "income",
        "rate", "ratio", "index", "score", "percent", "percentage",
    }
    _DIMENSION_KEYWORDS_QG = {
        "state", "district", "gender", "rural", "urban", "sector",
        "age", "group", "category", "type", "industry", "occupation",
    }
    _TREND_WORDS = {"trend", "change", "growth", "decline", "increase", "decrease", "comparison"}

    questions: list[dict[str, Any]] = []
    q_id_counter = 0

    # Build entity name set for binding
    entity_name_lower = {(e.get("name") or "").lower(): e for e in all_entities}

    for sec in numbered_sections:
        title = sec.get("title", "")
        title_lower = title.lower()
        page_idx = sec.get("page_index", 0)

        # Detect measures and dimensions mentioned in the section title
        found_measures = [k for k in _MEASURE_KEYWORDS_QG if k in title_lower]
        found_dims = [k for k in _DIMENSION_KEYWORDS_QG if k in title_lower]
        is_trend = any(w in title_lower for w in _TREND_WORDS)

        if not found_measures and not found_dims:
            # Generic question for the section
            q_id_counter += 1
            questions.append({
                "questionId": f"pq_{q_id_counter}",
                "intent": f"What are the key findings in the section on {title}?",
                "questionType": "describe",
                "sourceHeading": title,
                "sourcePageIndex": page_idx,
                "requiredEntities": [],
                "_source": "programmatic_section",
            })
            continue

        # Comparison question
        measure_label = found_measures[0].upper() if found_measures else title
        dim_label = found_dims[0].title() if found_dims else "category"

        if is_trend:
            q_id_counter += 1
            questions.append({
                "questionId": f"pq_{q_id_counter}",
                "intent": f"What is the trend in {measure_label} across survey years?",
                "questionType": "trend",
                "sourceHeading": title,
                "sourcePageIndex": page_idx,
                "requiredEntities": [],
                "_source": "programmatic_section",
            })
        else:
            q_id_counter += 1
            questions.append({
                "questionId": f"pq_{q_id_counter}",
                "intent": (
                    f"How does {measure_label} vary across {dim_label}?"
                    if found_dims else
                    f"What is the {measure_label} and how does it compare across groups?"
                ),
                "questionType": "comparison",
                "sourceHeading": title,
                "sourcePageIndex": page_idx,
                "requiredEntities": [],
                "_source": "programmatic_section",
            })

    return questions


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2.5: Document Knowledge Graph (PROGRAMMATIC — no LLM)
# ─────────────────────────────────────────────────────────────────────────────

def pass2_5_document_knowledge_graph(
    entity_pages: list[dict[str, Any]],
    layout_pages: list[dict[str, Any]],
    page_texts: list[dict[str, Any]],
    toc: list[ToCEntry],
    doc_title: str = "Document",
) -> dict[str, Any]:
    """Build a complete Document Knowledge Graph programmatically (no LLM).

    Steps:
        1. Entity collection + dedup from 4 sources (pdfplumber headers priority)
        2. Table structure analysis (columns → dimensions/measures/breakdowns)
        3. Chapter/section hierarchy from ToC
        4. Entity relationship detection (co-occurrence, prefix patterns)
        5. Per-page unique context script generation
        6. MoSPI section pattern detection

    Returns:
        document_map: {
            title, page_count,
            chapters: [{chapterId, title, pageRange, sections[]}],
            all_entities: [{entityId, name, source, pages[], entityType_hint}],
            table_structures: [{tableId, page, columns, dimensions[], measures[], breakdowns[], layout}],
            entity_relationships: [{from, to, relation}],
            section_patterns: [{sectionId, pattern, components[]}],
            per_page_context_scripts: [str per page],
        }
    """
    logger.info("[pass2.5] ▶ Building Document Knowledge Graph")
    t0 = time.monotonic()
    total_pages = max(len(entity_pages), len(page_texts))

    # ── Step 1: Entity Collection + Dedup ──
    entity_index: dict[str, dict[str, Any]] = {}  # key=lowered name → entity dict

    def _register_entity(name: str, source: str, page: int, priority: int):
        key = name.lower().strip()
        # Reject stopwords, noise, figure references, pure numbers
        if not key or not _is_valid_entity_name(name) or len(name) >= 100:
            return
        if key in entity_index:
            ent = entity_index[key]
            if page not in ent["pages"]:
                ent["pages"].append(page)
            # Upgrade source if higher priority
            if priority < ent["_priority"]:
                ent["source"] = source
                ent["_priority"] = priority
        else:
            entity_index[key] = {
                "entityId": f"ent_{len(entity_index) + 1:03d}",
                "name": name.strip(),
                "source": source,
                "pages": [page],
                "_priority": priority,
            }

    # Source 1 (priority 0): pdfplumber table headers — most reliable
    # Use multi-row merge to reconstruct MoSPI/NSSO spanning headers
    for i, pt in enumerate(page_texts):
        for table in (pt.get("tables") or []):
            if table and len(table) >= 1:
                merged_headers, _ = _merge_multirow_headers(table)
                for h in merged_headers:
                    if h:
                        _register_entity(h, "table_header", i, 0)

    # Source 2 (priority 1): LayoutLM heading region text
    for i, page in enumerate(layout_pages or []):
        for region in (page.get("regions") or []):
            if region.get("type") in ("heading", "title"):
                text = (region.get("text") or "").strip()
                if text and 2 < len(text) < 120:
                    _register_entity(text, "heading", i, 1)

    # Source 2b (priority 0): LayoutLM caption region texts — table/figure titles
    # These are gold-standard: "Statement 5.1 — LFPR by State" → LFPR, State, Statement 5.1
    caption_map = extract_caption_entities_from_layout(layout_pages or [])
    for page_idx, captions in caption_map.items():
        for cap_text in captions:
            # Register the full caption as an entity (high priority, same as table_header)
            _register_entity(cap_text, "caption", page_idx, 0)
            # Also split on " — ", " : ", " by " to extract sub-entities
            import re as _re_cap
            parts = _re_cap.split(r"\s+[—\-–:]\s+|\s+by\s+", cap_text, flags=_re_cap.I)
            for part in parts:
                part = part.strip()
                if _is_valid_entity_name(part) and len(part) < 80:
                    _register_entity(part, "caption_part", page_idx, 0)

    # Source 3 (priority 2): VLM-extracted entities (already filtered by Pass 2)
    for ep in entity_pages:
        page_idx = ep.get("page_index", 0)
        for ent in (ep.get("entities") or []):
            name = ent.get("name", "") if isinstance(ent, dict) else str(ent)
            if name.strip():
                _register_entity(name, "vlm", page_idx, 2)

        # Source 3b (priority 1): VLM table_title and section_heading from Pass 2
        table_title = ep.get("table_title") or ""
        section_heading = ep.get("section_heading") or ""
        if table_title:
            _register_entity(table_title, "table_title", page_idx, 1)
        if section_heading:
            _register_entity(section_heading, "section_heading", page_idx, 1)

    # Source 4 (bold_word) intentionally removed — individual bold words are too
    # noisy and register stopwords ("and", "the"), single letters, and word fragments.

    # Finalize entities
    all_entities = []
    for ent in entity_index.values():
        del ent["_priority"]
        all_entities.append(ent)

    all_entities = _deduplicate_entities(all_entities)
    all_entities = _enrich_entity_aliases(all_entities)

    # Cap entities: protect known MoSPI core names first, then sort by source priority
    _MOSPI_CORE_KEYWORDS = frozenset({
        "lfpr", "wpr", "ur", "labour force participation", "worker population",
        "unemployment rate", "unemployment", "gender", "rural", "urban", "plfs",
        "usual status", "age group", "earnings", "employment", "education",
        "casual labour", "self-employed", "regular wage", "manufacturing",
        "agriculture", "sector", "survey year", "mospi", "nsso",
    })
    for _ent in all_entities:
        _n = (_ent.get("name") or "").lower()
        _ent["_priority_protect"] = any(k in _n for k in _MOSPI_CORE_KEYWORDS)

    if len(all_entities) > 60:
        _protected = [e for e in all_entities if e.get("_priority_protect")]
        _remainder = [e for e in all_entities if not e.get("_priority_protect")]
        _ENT_PRIORITY = {"table_header": 0, "heading": 1, "vlm": 2, "bold_word": 3}
        _remainder.sort(key=lambda e: (_ENT_PRIORITY.get(e.get("source", "vlm"), 2), -len(e.get("pages") or [0])))
        _cap = max(0, 60 - len(_protected))
        all_entities = _protected + _remainder[:_cap]
        logger.info("[pass2.5]   Entity count capped to 60 (protected=%d, others=%d)", len(_protected), _cap)

    logger.info("[pass2.5]   Step 1: %d unique entities from %d pages", len(all_entities), total_pages)

    # ── Step 2: Table Structure Analysis ──
    table_structures: list[dict[str, Any]] = []
    for i, pt in enumerate(page_texts):
        for t_idx, table in enumerate(pt.get("tables") or []):
            if not table or len(table) < 2:
                continue

            # Merge multi-row spanning headers (critical for MoSPI/NSSO PDFs)
            headers, data_start = _merge_multirow_headers(table)
            if not headers or len(headers) < 2:
                continue

            # Classify columns: dimension vs measure vs breakdown
            dimensions: list[str] = []
            measures: list[str] = []
            breakdowns: list[dict[str, str]] = []

            # Analyze data rows — start after merged header rows
            data_rows = table[data_start:min(data_start + 5, len(table))]
            for col_idx, header in enumerate(headers):
                if not header:
                    continue
                # Check if column values are mostly numeric
                numeric_count = 0
                text_count = 0
                for row in data_rows:
                    if col_idx < len(row):
                        val = str(row[col_idx] or "").strip().replace(",", "").replace("%", "")
                        try:
                            float(val)
                            numeric_count += 1
                        except (ValueError, TypeError):
                            if val:
                                text_count += 1

                if numeric_count > text_count:
                    measures.append(header)
                else:
                    dimensions.append(header)

            # Detect breakdowns: repeated prefix + known qualifier
            # (e.g., "LFPR Rural", "LFPR Urban", "LFPR Total" → prefix="LFPR", quals=["Rural","Urban","Total"])
            prefix_groups: dict[str, list[str]] = {}
            for h in headers:
                parts = h.rsplit(" ", 1)
                if len(parts) == 2 and len(parts[0]) > 2:
                    qualifier = parts[1].strip()
                    prefix = parts[0].strip()
                    # Only group if qualifier looks like a known categorical split
                    if qualifier.lower() in _HEADER_QUALIFIERS or len(qualifier) <= 10:
                        prefix_groups.setdefault(prefix, []).append(qualifier)

            for prefix, qualifiers in prefix_groups.items():
                if len(qualifiers) >= 2:
                    breakdowns.append({
                        "measure": prefix,
                        "breakdown_by": "qualifier",
                        "values": qualifiers,
                    })

            # Detect layout type
            if breakdowns:
                layout_type = "cross_tabulation"
            elif len(dimensions) >= 2:
                layout_type = "multi_dimension"
            else:
                layout_type = "simple"

            table_structures.append({
                "tableId": f"tbl_{i + 1}_{t_idx + 1}",
                "page": i,
                "columns": headers,
                "dimensions": dimensions,
                "measures": measures,
                "breakdowns": breakdowns,
                "layout": layout_type,
                "row_count": len(table) - 1,
                "description": f"Table with {len(headers)} columns, {len(table) - 1} rows",
            })

    # Also try borderless table detection via text heuristics on pages with no pdfplumber tables
    import re as _re_nav
    _NAV_PAGE_RE = _re_nav.compile(
        r"Press\s*Releas|Information\s*Bur|pib\.gov|mospi\.gov|:\d+\s*[AP]M|\d+/\d+/\d+.*[AP]M",
        _re_nav.I,
    )
    for i, pt in enumerate(page_texts):
        if any(ts["page"] == i for ts in table_structures):
            continue  # already have a pdfplumber table for this page

        # Skip if the page raw text looks like a PIB nav-bar page
        page_raw = pt.get("raw_text") or ""
        if _NAV_PAGE_RE.search(page_raw[:500]):
            continue  # nav-bar page — no real table

        # Check if LayoutLM detected a table region
        has_layout_table = False
        if i < len(layout_pages):
            has_layout_table = any(r.get("type") == "table" for r in (layout_pages[i].get("regions") or []))

        wants_table = has_layout_table or (
            entity_pages[i].get("structure_type") == "data_table" if i < len(entity_pages) else False
        )
        if wants_table:
            parsed = _extract_table_from_text(page_raw)
            if parsed and parsed["row_count"] >= 3:
                # One final artifact check on the parsed column names
                fake_row = [parsed["columns"]]
                if not _is_website_artifact_table(fake_row):
                    table_structures.append({
                        "tableId": f"tbl_{i + 1}_h1",
                        "page": i,
                        "columns": parsed["columns"],
                        "dimensions": [],
                        "measures": [],
                        "breakdowns": [],
                        "layout": "simple",
                        "row_count": parsed["row_count"],
                        "description": "Table detected from text heuristics",
                    })

    logger.info("[pass2.5]   Step 2: %d table structures analyzed", len(table_structures))

    # ── Step 3: Chapter/Section Hierarchy ──
    chapters: list[dict[str, Any]] = []
    current_chapter: dict[str, Any] | None = None

    for entry in toc:
        if entry.level == 1:
            # New chapter
            if current_chapter:
                chapters.append(current_chapter)
            current_chapter = {
                "chapterId": f"ch_{len(chapters) + 1:02d}",
                "title": entry.title,
                "pageRange": [entry.page_index, entry.page_index],
                "level": 1,
                "sections": [],
            }
        elif entry.level >= 2 and current_chapter:
            current_chapter["sections"].append({
                "sectionId": f"sec_{len(chapters) + 1:02d}_{len(current_chapter['sections']) + 1:02d}",
                "title": entry.title,
                "page": entry.page_index,
                "level": entry.level,
            })
            # Extend chapter page range
            current_chapter["pageRange"][1] = max(current_chapter["pageRange"][1], entry.page_index)
        elif entry.level >= 2 and not current_chapter:
            # Level-2 section appears before any level-1 chapter — promote to chapter
            current_chapter = {
                "chapterId": f"ch_{len(chapters) + 1:02d}",
                "title": entry.title,
                "pageRange": [entry.page_index, entry.page_index],
                "level": entry.level,
                "sections": [],
            }

    if current_chapter:
        # Extend last chapter to end of document
        current_chapter["pageRange"][1] = max(current_chapter["pageRange"][1], total_pages - 1)
        chapters.append(current_chapter)

    # Cap chapters: at most 2 per page (prevents L2 noise from creating 80+ chapters)
    max_chapters = max(5, total_pages * 2)
    if len(chapters) > max_chapters:
        logger.warning("[pass2.5] Capping chapters %d → %d (noise suppression)", len(chapters), max_chapters)
        chapters = chapters[:max_chapters]
        # Extend last retained chapter to end of document
        if chapters:
            chapters[-1]["pageRange"][1] = total_pages - 1

    # If no ToC found, create a single chapter for the whole document
    if not chapters:
        chapters.append({
            "chapterId": "ch_01",
            "title": doc_title,
            "pageRange": [0, total_pages - 1],
            "sections": [],
        })

    # ── Filter junk chapters ──
    # Remove single-word stopword chapters, PIB nav-bar chapters, and very short titles
    import re as _re_ch_filter
    _NAV_TITLE_RE_CH = _re_ch_filter.compile(
        r"Press\s*(Release|Information)|pib\.gov|mospi\.gov|\d+/\d+/\d+.*[AP]M|:\d+\s*[AP]M|"
        r"Visitor Counter|Release ID|Read this release",
        _re_ch_filter.I,
    )
    chapters_before_filter = len(chapters)
    chapters = [
        ch for ch in chapters
        if (
            len(ch["title"].split()) >= 2          # at least 2 words
            and len(ch["title"]) >= 8              # at least 8 chars
            and ch["title"].lower().strip() not in _ENGLISH_STOPWORDS
            and ch["title"].lower().strip() not in _COMMON_NOISE_WORDS
            and not _NAV_TITLE_RE_CH.search(ch["title"])
        )
    ]
    if chapters_before_filter != len(chapters):
        logger.info("[pass2.5]   Chapter filter: %d → %d (removed %d junk chapters)",
                    chapters_before_filter, len(chapters), chapters_before_filter - len(chapters))

    # Re-assign chapterIds after filtering (keep ordering, fix numbering)
    for _i, _ch in enumerate(chapters):
        _ch["chapterId"] = f"ch_{_i + 1:02d}"

    logger.info("[pass2.5]   Step 3: %d chapters from ToC", len(chapters))
    for _ch in chapters[:12]:
        logger.info("[pass2.5]   Chapter: [p%d-p%d] '%s'",
                    _ch["pageRange"][0], _ch["pageRange"][1], _ch["title"][:60])

    # ── Step 4: Entity Relationship Detection ──
    entity_relationships: list[dict[str, str]] = []

    # Co-occurrence: entities appearing on same page in tables
    for ts in table_structures:
        page = ts["page"]
        page_ents = [e for e in all_entities if page in e["pages"]]
        for dim in ts["dimensions"]:
            dim_ent = next((e for e in page_ents if e["name"].lower() == dim.lower()), None)
            for meas in ts["measures"]:
                meas_ent = next((e for e in page_ents if e["name"].lower() == meas.lower()), None)
                if dim_ent and meas_ent:
                    entity_relationships.append({
                        "from": dim_ent["entityId"],
                        "to": meas_ent["entityId"],
                        "relation": "dimension_of",
                    })

    # Prefix-based: same prefix columns → measure × breakdown
    for ts in table_structures:
        for bd in ts.get("breakdowns") or []:
            entity_relationships.append({
                "from": bd["measure"],
                "to": ", ".join(bd["values"]),
                "relation": "breakdown_by",
            })

    logger.info("[pass2.5]   Step 4: %d entity relationships", len(entity_relationships))

    # ── Step 5: Per-Page Context Script Generation ──
    per_page_context_scripts: list[str] = []

    for i in range(total_pages):
        # Find chapter for this page
        chapter_title = doc_title
        chapter_range = [0, total_pages - 1]
        for ch in chapters:
            if ch["pageRange"][0] <= i <= ch["pageRange"][1]:
                chapter_title = ch["title"]
                chapter_range = ch["pageRange"]
                break

        # Get structure type from pass 2
        stype = "unknown"
        page_desc = ""
        if i < len(entity_pages):
            stype = entity_pages[i].get("structure_type", "unknown")
            page_desc = entity_pages[i].get("description", "")

        # Entities in scope (this page + prior pages in same chapter)
        chapter_entities = [
            e["name"] for e in all_entities
            if any(p >= chapter_range[0] and p <= i for p in e["pages"])
        ][:15]  # cap to avoid overflow

        # Table structures on this page
        page_tables = [ts for ts in table_structures if ts["page"] == i]
        table_desc = ""
        if page_tables:
            t = page_tables[0]
            dims_str = ", ".join(t["dimensions"][:3]) or "?"
            meas_str = ", ".join(t["measures"][:3]) or "?"
            bds_str = " | ".join(
                f"{b['measure']}×({','.join(b['values'][:3])})"
                for b in (t.get("breakdowns") or [])[:2]
            )
            table_desc = f"Table: dims=[{dims_str}] measures=[{meas_str}]"
            if bds_str:
                table_desc += f" breakdowns=[{bds_str}]"

        # Caption/table_title from VLM Pass 2 — adds statement number context
        page_ep = entity_pages[i] if i < len(entity_pages) else {}
        vl_table_title = page_ep.get("table_title") or ""
        vl_section_heading = page_ep.get("section_heading") or ""

        # LayoutLM caption texts for this page
        page_captions = caption_map.get(i) or []

        # Build condensed prior summary
        prior_summary = ""
        if i > chapter_range[0]:
            prior_pages = [ep for ep in entity_pages if chapter_range[0] <= ep.get("page_index", -1) < i]
            prior_types = [ep.get("structure_type", "?") for ep in prior_pages[:5]]
            if prior_types:
                prior_summary = f"Prior: {', '.join(prior_types)}"

        # Coming next
        next_section = ""
        for entry in toc:
            if entry.page_index > i:
                next_section = f"Next: \"{entry.title}\""
                break

        # Assemble context script — richer with VLM table_title, section_heading, captions
        parts = [
            f'[Doc: "{doc_title}" ({total_pages}p)',
            f'Ch: "{chapter_title}" (p{chapter_range[0] + 1}-{chapter_range[1] + 1})',
        ]
        if vl_section_heading:
            parts.append(f'Heading: "{vl_section_heading}"')
        if prior_summary:
            parts.append(prior_summary)
        parts.append(f"This page: {stype}")
        if page_desc:
            parts.append(page_desc)
        if vl_table_title:
            parts.append(f'Table: "{vl_table_title}"')
        elif table_desc:
            parts.append(table_desc)
        if page_captions:
            parts.append(f'Captions: {"; ".join(page_captions[:2])}')
        # Include typed entities (dimension vs measure) for Pass 3 guidance
        typed_ents = []
        for ename in chapter_entities[:10]:
            ent_obj = next((e for e in all_entities if e["name"] == ename), None)
            if ent_obj:
                etype = ent_obj.get("entityType_hint", "?")
                typed_ents.append(f"{ename}({etype[0]})")  # e.g. "LFPR(m)" "State(d)"
            else:
                typed_ents.append(ename)
        if typed_ents:
            parts.append(f"Entities: {', '.join(typed_ents)}")
        if next_section:
            parts.append(next_section)
        parts.append("]")

        script = ". ".join(parts)
        per_page_context_scripts.append(script[:600])  # slightly wider cap

    logger.info("[pass2.5]   Step 5: %d context scripts generated", len(per_page_context_scripts))

    # ── Step 6: MoSPI Section Pattern Detection ──
    section_patterns: list[dict[str, Any]] = []
    _patterns_per_chapter: dict[str, int] = {}

    for ch in chapters:
        _ch_id = ch["chapterId"]
        for sec in ch.get("sections") or [{"sectionId": ch["chapterId"], "title": ch["title"], "page": ch["pageRange"][0]}]:
            # Cap section patterns per chapter to avoid hundreds of patterns
            if _patterns_per_chapter.get(_ch_id, 0) >= 5:
                break
            _patterns_per_chapter[_ch_id] = _patterns_per_chapter.get(_ch_id, 0) + 1
            sec_page = sec.get("page", ch["pageRange"][0])
            # Gather structure types for pages in this section
            sec_end = total_pages - 1
            # Find next section's page
            for s2 in ch.get("sections") or []:
                if s2.get("page", 0) > sec_page:
                    sec_end = s2["page"] - 1
                    break

            sec_types = []
            for ep in entity_pages:
                if sec_page <= ep.get("page_index", -1) <= sec_end:
                    sec_types.append(ep.get("structure_type", "unknown"))

            has_tables = any(ts["page"] >= sec_page and ts["page"] <= sec_end for ts in table_structures)
            has_charts = "chart_page" in sec_types or "mixed" in sec_types
            mostly_text = all(t in ("narrative", "title_page") for t in sec_types) if sec_types else True

            # Pattern matching
            if mostly_text and not has_tables:
                pattern = "executive_summary"
                components = ["narrative_paragraph", "metric_card"]
            elif has_charts and has_tables:
                pattern = "trend_analysis"
                components = ["narrative_paragraph", "line_chart", "data_table"]
            elif has_tables and len([ts for ts in table_structures if sec_page <= ts["page"] <= sec_end]) >= 2:
                pattern = "state_comparison"
                components = ["narrative_paragraph", "data_table", "grouped_bar_chart"]
            elif has_tables:
                pattern = "demographic_breakdown"
                components = ["narrative_paragraph", "data_table", "pie_chart"]
            else:
                pattern = "descriptive"
                components = ["narrative_paragraph"]

            # level: use section's own level if it's a subsection, else chapter level
            # This ensures Loop 1 can distinguish chapter-level vs sub-section patterns
            sec_level = sec.get("level", ch.get("level", 1))
            section_patterns.append({
                "sectionId": sec.get("sectionId", ch["chapterId"]),
                "title": sec.get("title", ch["title"]),
                "pageRange": [sec_page, sec_end],
                "pattern": pattern,
                "level": sec_level,
                "chapterId": ch["chapterId"],
                "suggested_components": components,
            })

    logger.info("[pass2.5]   Step 6: %d section patterns detected", len(section_patterns))

    # ── Step 7: Numbered section extraction + programmatic question pre-generation ──
    # Done here so questions are available even if Qwen Pass 3 fails completely.
    numbered_sections = _extract_numbered_sections(page_texts)
    fact_questions = []
    if numbered_sections:
        fact_questions = _generate_questions_from_sections(numbered_sections, all_entities)
    logger.info("[pass2.5]   Step 7: %d numbered sections → %d pre-generated questions",
                len(numbered_sections), len(fact_questions))

    # ── Assemble Document Knowledge Graph ──
    document_map = {
        "title": doc_title,
        "page_count": total_pages,
        "chapters": chapters,
        "all_entities": all_entities,
        "table_structures": table_structures,
        "entity_relationships": entity_relationships,
        "section_patterns": section_patterns,
        "per_page_context_scripts": per_page_context_scripts,
        "_numbered_sections": numbered_sections,
        "_fact_questions": fact_questions,
    }

    elapsed = time.monotonic() - t0
    logger.info(
        "[pass2.5] ✓ Document KG built: %d entities, %d tables, %d chapters, "
        "%d patterns, %d context scripts (%.1fs)",
        len(all_entities), len(table_structures), len(chapters),
        len(section_patterns), len(per_page_context_scripts), elapsed,
    )
    return document_map


def _split_text_into_paragraphs(text: str) -> list[str]:
    """Split raw text into paragraphs at double newlines or large gaps."""
    import re
    # Split on double newlines, or single newline followed by indent
    paragraphs = re.split(r'\n\s*\n', text)
    # Filter empty
    return [p.strip() for p in paragraphs if p.strip() and len(p.strip()) > 20]


def _format_regions_for_prompt(regions: list[dict]) -> str:
    """Format LayoutLM regions into concise prompt text."""
    if not regions:
        return "(No regions detected — analyze the full page)"

    lines = []
    for i, r in enumerate(regions[:15]):  # cap at 15 regions
        rtype = r.get("type", "unknown")
        bbox = r.get("bbox", [0, 0, 0, 0])
        text_hint = (r.get("text") or "")[:80]
        lines.append(f"  [{i}] {rtype} at [{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}]"
                     + (f" hint=\"{text_hint}\"" if text_hint else ""))
    return "\n".join(lines)


def _extract_table_from_text(raw_text: str) -> dict | None:
    """Detect and extract tabular data from raw text using heuristics.

    Looks for:
        - Lines with consistent multi-space or tab separators
        - Numeric columns aligned vertically
        - Header row followed by data rows

    Returns:
        {"columns": [...], "rows": [{col: val, ...}], "row_count": N} or None
    """
    import re

    if not raw_text or len(raw_text) < 20:
        return None

    lines = raw_text.strip().split("\n")
    if len(lines) < 3:
        return None

    # Strategy 1: Tab-separated lines
    tab_lines = [l for l in lines if "\t" in l]
    if len(tab_lines) >= 3:
        cells_per_line = [l.split("\t") for l in tab_lines]
        # Check consistency (all rows have similar column count)
        col_counts = [len(c) for c in cells_per_line]
        mode_cols = max(set(col_counts), key=col_counts.count)
        if mode_cols >= 2:
            consistent = [c for c in cells_per_line if len(c) == mode_cols]
            if len(consistent) >= 2:
                headers = [h.strip() for h in consistent[0]]
                rows = []
                for row_cells in consistent[1:]:
                    rows.append({
                        headers[k] if k < len(headers) and headers[k] else f"col_{k}": v.strip()
                        for k, v in enumerate(row_cells)
                    })
                return {"columns": headers, "rows": rows, "row_count": len(rows)}

    # Strategy 2: Multi-space separated (2+ spaces as delimiter)
    multi_space_lines = []
    for line in lines:
        # Skip very short lines or lines that look like headings
        if len(line.strip()) < 10:
            continue
        # Check if line has 2+ segments separated by 2+ spaces
        parts = re.split(r" {2,}", line.strip())
        if len(parts) >= 3:
            multi_space_lines.append(parts)

    if len(multi_space_lines) >= 3:
        # Check column count consistency
        col_counts = [len(p) for p in multi_space_lines]
        mode_cols = max(set(col_counts), key=col_counts.count)
        if mode_cols >= 3:
            consistent = [p for p in multi_space_lines if len(p) == mode_cols]
            if len(consistent) >= 3:
                # First consistent row is likely the header
                headers = [h.strip() for h in consistent[0]]
                rows = []
                for row_parts in consistent[1:]:
                    rows.append({
                        headers[k] if k < len(headers) and headers[k] else f"col_{k}": v.strip()
                        for k, v in enumerate(row_parts)
                    })
                return {"columns": headers, "rows": rows, "row_count": len(rows)}

    # Strategy 3: Lines with numbers that look like data rows
    # (common in government statistical reports)
    numeric_lines = []
    for line in lines:
        # Count number-like tokens in the line
        tokens = line.split()
        if len(tokens) >= 3:
            num_count = sum(1 for t in tokens if re.match(r'^[\d,.\-+%]+$', t.strip()))
            if num_count >= 2 and num_count / len(tokens) >= 0.4:
                numeric_lines.append(tokens)

    if len(numeric_lines) >= 3:
        # Find the most common token count
        token_counts = [len(t) for t in numeric_lines]
        mode_tokens = max(set(token_counts), key=token_counts.count)
        consistent = [t for t in numeric_lines if len(t) == mode_tokens]
        if len(consistent) >= 3:
            # Try to find a header line just before the first numeric line
            first_num_idx = None
            for idx, line in enumerate(lines):
                tokens = line.split()
                if len(tokens) >= 3:
                    num_count = sum(1 for t in tokens if re.match(r'^[\d,.\-+%]+$', t.strip()))
                    if num_count >= 2 and num_count / len(tokens) >= 0.4:
                        first_num_idx = idx
                        break

            headers = []
            if first_num_idx and first_num_idx > 0:
                header_line = lines[first_num_idx - 1]
                header_tokens = re.split(r"  {2,}|\t", header_line.strip())
                if len(header_tokens) >= 2:
                    headers = [h.strip() for h in header_tokens]

            if not headers:
                headers = [f"col_{k}" for k in range(mode_tokens)]

            rows = []
            for row_tokens in consistent[:10]:  # Cap at 10 rows
                row_dict = {}
                for k, v in enumerate(row_tokens):
                    col_name = headers[k] if k < len(headers) else f"col_{k}"
                    row_dict[col_name] = v.strip()
                rows.append(row_dict)
            return {"columns": headers, "rows": rows, "row_count": len(rows)}

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Pass 3: Two-Loop AST Building via Qwen-VL
# ─────────────────────────────────────────────────────────────────────────────

def pass3_two_loop_ast_building(
    document_map: dict[str, Any],
    page_texts: list[dict[str, Any]],
    doc_title: str = "Document",
    page_images: list[bytes] | None = None,
) -> dict[str, Any]:
    """Build questions + entity bindings via two Qwen-VL loops.

    Loop 1: Question extraction per section chunk
        Input: per-page context script + section content summary
        Output: [{questionId, intent, questionType, page, sourceHeading}]

    Loop 2: Entity binding + AnswerStructure per question
        Input: question + full entity list + table structures + section pattern
        Output: [{requiredEntities, answerStructure, inferenceConfidence}]

    Returns:
        {
            "questions": [{questionId, intent, questionType, requiredEntities, answerStructure, ...}],
            "topics": [{topicId, title, questionIds, pageRange}],
        }
    """
    endpoint = _SGLANG_ENDPOINT.rstrip("/") + "/v1/chat/completions"
    model = os.getenv("SGLANG_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct-AWQ")
    timeout = int(os.getenv("SGLANG_TIMEOUT", "120"))

    logger.info("[pass3] ▶ Two-loop AST building via Qwen-VL")
    t0 = time.monotonic()

    chapters = document_map.get("chapters") or []
    all_entities = document_map.get("all_entities") or []
    table_structures = document_map.get("table_structures") or []
    section_patterns = document_map.get("section_patterns") or []
    context_scripts = document_map.get("per_page_context_scripts") or []

    # Pre-flight: check if vLLM is alive
    vlm_alive = False
    try:
        hr = requests.get(_SGLANG_ENDPOINT.rstrip("/") + "/v1/models", timeout=5)
        vlm_alive = hr.status_code == 200
    except Exception:
        pass

    if not vlm_alive:
        logger.warning("[pass3] vLLM not reachable — generating stub questions programmatically")
        return _programmatic_question_fallback(document_map, page_texts)

    # ── Build entity summary for Loop 2 (shared across all questions) ──
    entity_summary = ", ".join(e["name"] for e in all_entities[:30])
    if len(entity_summary) > 300:
        entity_summary = entity_summary[:300] + "..."

    # ═══════════════════════════════════════════════════════════════════
    # LOOP 1: Question Extraction per Chapter (one call per real chapter)
    # ═══════════════════════════════════════════════════════════════════
    logger.info("[pass3] ── Loop 1: Question extraction ──")
    raw_questions: list[dict[str, Any]] = []
    consecutive_failures = 0

    # Use document_map chapters directly — each chapter gets ONE Qwen call.
    # This guarantees each chapter's questions get the chapter's real page range,
    # producing distinct page values → distinct topic assignments in pass3.
    # Fall back to section_patterns level-1 slice if chapters unavailable.
    chapters_loop1 = document_map.get("chapters") or []
    if chapters_loop1:
        top_level_sections = [
            {
                "sectionId": ch["chapterId"],
                "title": ch["title"],
                "pageRange": ch["pageRange"],
                "pattern": "descriptive",
                "level": 1,
                "chapterId": ch["chapterId"],
                "suggested_components": ["narrative_paragraph"],
            }
            for ch in chapters_loop1[:20]  # hard cap at 20 chapters
        ]
    else:
        top_level_sections = [sp for sp in section_patterns if sp.get("level", 2) == 1][:20]
    logger.info("[pass3] L1: Processing %d chapters (of %d chapters total)",
                len(top_level_sections), len(chapters_loop1))
    if top_level_sections:
        pages = [sp["pageRange"][0] for sp in top_level_sections]
        logger.info("[pass3] L1: Chapter page starts: %s", pages)
        titles = [sp["title"][:40] for sp in top_level_sections[:8]]
        logger.info("[pass3] L1: First 8 chapter titles: %s", titles)

    for sp_idx, sp in enumerate(top_level_sections):
        if consecutive_failures >= 3:
            logger.warning("[pass3] L1: %d consecutive failures — stopping", consecutive_failures)
            break

        sec_title = sp.get("title", "Section")
        page_range = sp.get("pageRange", [0, 0])
        pattern = sp.get("pattern", "descriptive")

        # Get context script for first page of section
        ctx = ""
        if page_range[0] < len(context_scripts):
            ctx = context_scripts[page_range[0]]

        # Build section content summary from page_texts
        section_summary = ""
        for p_idx in range(page_range[0], min(page_range[1] + 1, len(page_texts))):
            pt = page_texts[p_idx]
            # Headings
            for h in (pt.get("headings") or [])[:3]:
                section_summary += f"# {h}\n"
            # Table column hints
            for ts in table_structures:
                if ts["page"] == p_idx:
                    section_summary += f"[Table: {', '.join(ts['columns'][:6])}]\n"
            # Short text preview
            raw = (pt.get("raw_text") or "")[:150]
            if raw:
                section_summary += raw + "\n"

        section_summary = section_summary[:600]  # cap

        # Build typed entity context for this section (dimension vs measure)
        sp_page_start = page_range[0]
        sec_typed_ents = []
        for e in all_entities:
            if any(sp_page_start <= p <= page_range[1] for p in e.get("pages", [])):
                etype = e.get("entityType_hint", "")
                label = f"{e['name']}({'measure' if etype == 'measure' else 'dim' if etype == 'dimension' else etype or '?'})"
                sec_typed_ents.append(label)
        typed_entity_context = ", ".join(sec_typed_ents[:15]) or "none detected"

        # Build table structure context
        sec_tables = [ts for ts in table_structures if page_range[0] <= ts["page"] <= page_range[1]]
        table_context_lines = []
        for ts in sec_tables[:3]:
            dims = ", ".join(ts.get("dimensions", [])[:4]) or "—"
            meas = ", ".join(ts.get("measures", [])[:4]) or "—"
            bds = " | ".join(
                f"{b['measure']}×({','.join(b['values'][:3])})"
                for b in (ts.get("breakdowns") or [])[:2]
            )
            line = f"  dims=[{dims}] measures=[{meas}]"
            if bds:
                line += f" breakdowns=[{bds}]"
            table_context_lines.append(line)
        table_context = "\n".join(table_context_lines) or "  (no tables)"

        # Extract keywords from section title to guide question generation
        _sec_title_lower = sec_title.lower()
        _topic_hint = (
            "LFPR/Labour Force Participation" if "lfpr" in _sec_title_lower or "labour force participation" in _sec_title_lower
            else "WPR/Worker Population Ratio" if "wpr" in _sec_title_lower or "worker population" in _sec_title_lower
            else "UR/Unemployment Rate" if "ur" in _sec_title_lower or "unemployment" in _sec_title_lower
            else "Employment status/wage composition" if "wage" in _sec_title_lower or "salary" in _sec_title_lower or "regular" in _sec_title_lower
            else "Sectoral employment distribution" if "manufactur" in _sec_title_lower or "sector" in _sec_title_lower or "agricult" in _sec_title_lower
            else "Earnings/wages by gender" if "earning" in _sec_title_lower or "female worker" in _sec_title_lower
            else "Education attainment" if "education" in _sec_title_lower or "formal" in _sec_title_lower
            else sec_title[:40]
        )

        prompt = (
            f"{ctx}\n\n"
            f"SECTION TOPIC: \"{sec_title}\"\n"
            f"This section is SPECIFICALLY about: {_topic_hint}\n"
            f"Pages: {page_range[0] + 1}-{page_range[1] + 1}\n"
            f"Typed entities: {typed_entity_context}\n"
            f"Table structures:\n{table_context}\n"
            f"Content preview:\n{section_summary}\n\n"
            f"Generate 1-3 analytical questions SPECIFICALLY about '{sec_title}'.\n"
            "CRITICAL RULES:\n"
            f"(1) Questions MUST be about {_topic_hint} — do NOT ask about other sections.\n"
            "(2) Reference the exact entity names listed above.\n"
            "(3) Questions must be quantitative and comparative — MoSPI report style.\n"
            "BAD: 'What does this section show?' or generic LFPR questions for a WPR section.\n"
            f"GOOD example for this section: A question specifically asking about {_topic_hint} by gender or Rural/Urban.\n"
            "Output JSON array (questionType must be one of: comparison, trend, ranking, distribution, describe):\n"
            '[{"questionId":"q1","intent":"Specific question about this section topic?",'
            '"questionType":"comparison","sourceHeading":"exact section title here"}]\n'
            "List 1-3 questions. JSON only."
        )

        # Build multimodal content: always include prompt text; add page image if available
        page_img_idx = page_range[0]
        content_parts: list[dict] = []
        if page_images and 0 <= page_img_idx < len(page_images):
            try:
                img_b64 = base64.b64encode(page_images[page_img_idx]).decode("utf-8")
                content_parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})
            except Exception:
                pass  # image encoding failed — text-only fallback
        content_parts.append({"type": "text", "text": prompt})

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content_parts if len(content_parts) > 1 else prompt}],
            "temperature": 0.15,
            "max_tokens": 600,
        }

        try:
            r = requests.post(endpoint, json=payload, timeout=timeout)
            if r.status_code == 200:
                raw_content = r.json()["choices"][0]["message"]["content"].strip()
                questions = _extract_json_array_from_response(raw_content)
                if questions:
                    for q_i, q in enumerate(questions):
                        # CRITICAL: globally unique IDs — Qwen always returns q1/q2/q3
                        # Duplicate IDs cause topic assignment to skip all but chapter 1
                        q["questionId"] = f"sp{sp_idx + 1:02d}_q{q_i + 1:02d}"
                        q["page"] = page_range[0]
                        q["sectionId"] = sp.get("sectionId", "")
                        q["sectionPattern"] = pattern
                    raw_questions.extend(questions)
                    consecutive_failures = 0
                    logger.debug("[pass3] L1: %d questions from \"%s\"", len(questions), sec_title)
                else:
                    logger.debug("[pass3] L1: No valid JSON from section \"%s\"", sec_title)
            else:
                logger.debug("[pass3] L1: VLM returned %d for section \"%s\"", r.status_code, sec_title)
                consecutive_failures += 1
        except (requests.ConnectionError, requests.Timeout) as exc:
            logger.warning("[pass3] L1: Connection failed: %s", type(exc).__name__)
            consecutive_failures += 1
        except Exception as exc:
            logger.debug("[pass3] L1: Error: %s", exc)
            consecutive_failures += 1

    logger.info("[pass3] L1: Extracted %d raw questions from %d top-level sections", len(raw_questions), len(top_level_sections))

    # ── Deduplicate questions by normalized intent ──
    # Qwen 3B-AWQ often generates identical questions for different chapters.
    # Keep the first occurrence per normalized intent; preserve page diversity.
    import re as _re_dedup
    _seen_intents: set[str] = set()
    _deduped: list[dict[str, Any]] = []
    for _q in raw_questions:
        _intent_key = _re_dedup.sub(r"\s+", " ", (_q.get("intent") or "").lower().strip())[:80]
        if _intent_key not in _seen_intents:
            _seen_intents.add(_intent_key)
            _deduped.append(_q)
    if len(_deduped) < len(raw_questions):
        logger.info("[pass3] L1: Deduped %d → %d unique questions", len(raw_questions), len(_deduped))
    raw_questions = _deduped

    # If Loop 1 produced nothing, fall back
    if not raw_questions:
        logger.warning("[pass3] L1 produced 0 questions — using programmatic fallback")
        return _programmatic_question_fallback(document_map, page_texts)

    # ═══════════════════════════════════════════════════════════════════
    # LOOP 2: Entity Binding + AnswerStructure per Question
    # ═══════════════════════════════════════════════════════════════════
    logger.info("[pass3] ── Loop 2: Entity binding (%d questions) ──", len(raw_questions))
    enriched_questions: list[dict[str, Any]] = []
    consecutive_failures = 0

    for q in raw_questions:
        if consecutive_failures >= 3:
            logger.warning("[pass3] L2: %d consecutive failures — using pattern defaults for remaining", consecutive_failures)
            # Use pattern-based defaults for remaining questions
            for q_remaining in raw_questions[len(enriched_questions):]:
                enriched_questions.append(_default_question_binding(q_remaining, all_entities, section_patterns))
            break

        q_intent = q.get("intent", "")
        q_type = q.get("questionType", "comparison")
        q_page = q.get("page", 0)
        q_pattern = q.get("sectionPattern", "descriptive")

        # Table structures on relevant pages
        relevant_tables = [ts for ts in table_structures if abs(ts["page"] - q_page) <= 2]
        table_hint = ""
        if relevant_tables:
            t = relevant_tables[0]
            table_hint = (
                f"Table: dims=[{', '.join(t['dimensions'][:5])}], "
                f"measures=[{', '.join(t['measures'][:5])}]"
            )

        prompt = (
            f"Question: \"{q_intent}\"\n"
            f"Type: {q_type}\n"
            f"Available entities: {entity_summary}\n"
            f"{table_hint}\n"
            f"Section pattern: {q_pattern}\n\n"
            "Which entities does this question need and what role does each play? "
            "What components should the answer have?\n"
            "Output JSON:\n"
            '{"requiredEntities":[{"entityRef":"entity_name","role":"groupBy|measure|filter|breakdown"}],'
            '"answerStructure":{"layoutType":"single|split|multi-panel",'
            '"components":[{"type":"narrative_paragraph|data_table|grouped_bar_chart|line_chart|pie_chart|metric_card","renderOrder":1}]},'
            '"confidence":0.8}\n'
            "JSON only."
        )

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 384,
        }

        try:
            r = requests.post(endpoint, json=payload, timeout=timeout)
            if r.status_code == 200:
                raw_content = r.json()["choices"][0]["message"]["content"].strip()
                binding = _extract_json_from_response(raw_content)
                if binding:
                    q.update({
                        "requiredEntities": binding.get("requiredEntities") or [],
                        "answerStructure": binding.get("answerStructure") or {},
                        "inferenceConfidence": float(binding.get("confidence", 0.5)),
                    })
                    enriched_questions.append(q)
                    consecutive_failures = 0
                    logger.debug("[pass3] L2: Bound %d entities to \"%s\"",
                                 len(binding.get("requiredEntities") or []), q_intent[:40])
                else:
                    enriched_questions.append(_default_question_binding(q, all_entities, section_patterns))
            else:
                logger.debug("[pass3] L2: VLM returned %d", r.status_code)
                consecutive_failures += 1
                enriched_questions.append(_default_question_binding(q, all_entities, section_patterns))
        except (requests.ConnectionError, requests.Timeout) as exc:
            logger.warning("[pass3] L2: Connection failed: %s", type(exc).__name__)
            consecutive_failures += 1
            enriched_questions.append(_default_question_binding(q, all_entities, section_patterns))
        except Exception as exc:
            logger.debug("[pass3] L2: Error: %s", exc)
            consecutive_failures += 1
            enriched_questions.append(_default_question_binding(q, all_entities, section_patterns))

    # ── Build topics from chapters (exclusive assignment) ──
    # Each question is assigned to the NARROWEST chapter whose pageRange
    # contains the question's page. This prevents the 10k duplication bug
    # that occurs when overlapping chapter ranges all claim the same question.
    def _chapter_span(ch: dict) -> int:
        pr = ch.get("pageRange", [0, 0])
        return pr[1] - pr[0]

    # Sort chapters by span ascending so narrowest gets priority
    chapters_by_narrowness = sorted(chapters, key=_chapter_span)

    question_to_topic: dict[str, str] = {}  # questionId → chapterId
    for q in enriched_questions:
        q_page = q.get("page", -1)
        q_id = q.get("questionId", "")
        if q_id in question_to_topic:
            continue  # already claimed by a narrower chapter
        for ch in chapters_by_narrowness:
            pr = ch.get("pageRange", [0, 0])
            if pr[0] <= q_page <= pr[1]:
                question_to_topic[q_id] = ch["chapterId"]
                break

    # Debug: show how many questions were assigned to each chapter
    _assigned = {}
    for q_id, ch_id in question_to_topic.items():
        _assigned[ch_id] = _assigned.get(ch_id, 0) + 1
    _unassigned = sum(1 for q in enriched_questions if q.get("questionId", "") not in question_to_topic)
    logger.info("[pass3] topic assignment: %d chapters got questions, %d questions unassigned",
                len(_assigned), _unassigned)
    if _unassigned > 0:
        _missing_pages = set(q.get("page", -1) for q in enriched_questions if q.get("questionId", "") not in question_to_topic)
        _chapter_page_spans = [(ch["chapterId"], ch["pageRange"]) for ch in chapters]
        logger.warning("[pass3] Unassigned question pages: %s | chapter spans (first 10): %s",
                       _missing_pages, _chapter_page_spans[:10])

    topics: list[dict[str, Any]] = []
    for ch in chapters:
        ch_id = ch["chapterId"]
        ch_questions = [
            q for q in enriched_questions
            if question_to_topic.get(q.get("questionId", "")) == ch_id
        ]
        if ch_questions:
            topics.append({
                "topicId": ch_id.replace("ch_", "topic_"),
                "title": ch["title"],
                "description": f"Questions from chapter: {ch['title']}",
                "questionIds": [q.get("questionId", f"q_{i}") for i, q in enumerate(ch_questions)],
                "pageRange": ch["pageRange"],
            })

    elapsed = time.monotonic() - t0
    logger.info(
        "[pass3] ✓ Two-loop AST: %d questions in %d topics (%.1fs)",
        len(enriched_questions), len(topics), elapsed,
    )

    return {
        "questions": enriched_questions,
        "topics": topics,
    }


def _extract_json_array_from_response(raw: str) -> list[dict] | None:
    """Extract a JSON array from potentially messy LLM output."""
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # Strip markdown fences
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            inner = parts[1]
            if inner and inner.split("\n", 1)[0].strip().isalpha():
                inner = inner.split("\n", 1)[-1]
            text = inner.strip()

    # Try direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return [item for item in obj if isinstance(item, dict)]
        if isinstance(obj, dict):
            # Maybe it has a "questions" key wrapping the array
            for key in ("questions", "data", "results"):
                if isinstance(obj.get(key), list):
                    return [item for item in obj[key] if isinstance(item, dict)]
            return [obj]
    except json.JSONDecodeError:
        pass

    # Find first [ and try to parse
    bracket_start = text.find("[")
    if bracket_start >= 0:
        candidate = text[bracket_start:]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, list):
                return [item for item in obj if isinstance(item, dict)]
        except json.JSONDecodeError:
            # Try repair
            repaired = _repair_truncated_json(candidate)
            if repaired:
                try:
                    obj = json.loads(repaired)
                    if isinstance(obj, list):
                        return [item for item in obj if isinstance(item, dict)]
                except json.JSONDecodeError:
                    pass

    # Fallback: try extracting a single JSON object
    single = _extract_json_from_response(raw)
    if single:
        return [single]

    return None


def _default_question_binding(
    question: dict[str, Any],
    all_entities: list[dict[str, Any]],
    section_patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate default entity binding + answer structure from pattern when VLM fails."""
    q_type = question.get("questionType", "comparison")
    q_page = question.get("page", 0)
    q_pattern = question.get("sectionPattern", "descriptive")

    # Default entity bindings: first dimension + first measure on same page
    required_entities: list[dict[str, str]] = []
    page_entities = [e for e in all_entities if q_page in e.get("pages", [])]
    table_header_ents = [e for e in page_entities if e.get("source") == "table_header"]
    if table_header_ents:
        # First table header as groupBy, second as measure
        if len(table_header_ents) >= 1:
            required_entities.append({"entityRef": table_header_ents[0]["name"], "role": "groupBy"})
        if len(table_header_ents) >= 2:
            required_entities.append({"entityRef": table_header_ents[1]["name"], "role": "measure"})

    # Default answer structure from section pattern
    pattern_components = {
        "executive_summary": [
            {"type": "narrative_paragraph", "renderOrder": 1},
            {"type": "metric_card", "renderOrder": 2},
        ],
        "trend_analysis": [
            {"type": "narrative_paragraph", "renderOrder": 1},
            {"type": "line_chart", "renderOrder": 2},
            {"type": "data_table", "renderOrder": 3},
        ],
        "state_comparison": [
            {"type": "narrative_paragraph", "renderOrder": 1},
            {"type": "data_table", "renderOrder": 2},
            {"type": "grouped_bar_chart", "renderOrder": 3},
        ],
        "demographic_breakdown": [
            {"type": "narrative_paragraph", "renderOrder": 1},
            {"type": "data_table", "renderOrder": 2},
            {"type": "pie_chart", "renderOrder": 3},
        ],
        "descriptive": [
            {"type": "narrative_paragraph", "renderOrder": 1},
        ],
    }

    components = pattern_components.get(q_pattern, pattern_components["descriptive"])

    question.update({
        "requiredEntities": required_entities,
        "answerStructure": {
            "layoutType": "single" if len(components) <= 2 else "split",
            "components": components,
        },
        "inferenceConfidence": 0.3,
        "inferenceMethod": "pattern",
    })
    return question


_ARCHETYPES_CACHE: dict | None = None


def _load_archetypes() -> dict:
    """Load MoSPI question archetypes JSON (cached after first load)."""
    global _ARCHETYPES_CACHE
    if _ARCHETYPES_CACHE is not None:
        return _ARCHETYPES_CACHE
    try:
        archetypes_path = Path(__file__).resolve().parent / "mospi_question_archetypes.json"
        with open(archetypes_path, encoding="utf-8") as f:
            data = json.load(f)
        _ARCHETYPES_CACHE = {k: v for k, v in data.items() if not k.startswith("_")}
        logger.info("[archetypes] Loaded %d domains from mospi_question_archetypes.json", len(_ARCHETYPES_CACHE))
    except Exception as exc:
        logger.warning("[archetypes] Failed to load archetypes: %s", exc)
        _ARCHETYPES_CACHE = {}
    return _ARCHETYPES_CACHE


def _detect_domain(entity_names: list[str], archetypes: dict) -> str:
    """Detect which archetype domain best matches the entity names."""
    names_lower = {n.lower() for n in entity_names}
    best_domain = "generic_tabular"
    best_hits = 0
    for domain, cfg in archetypes.items():
        if domain == "generic_tabular":
            continue
        triggers = [t.lower() for t in (cfg.get("trigger_entities") or [])]
        hits = sum(1 for t in triggers if any(t in n for n in names_lower))
        if hits > best_hits:
            best_hits = hits
            best_domain = domain
    return best_domain


def _programmatic_question_fallback(
    document_map: dict[str, Any],
    page_texts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate domain-specific questions programmatically using MoSPI archetypes.

    Uses archetype library (mospi_question_archetypes.json) when available,
    falling back to generic templates for unknown document types.
    """
    all_entities = document_map.get("all_entities") or []
    table_structures = document_map.get("table_structures") or []
    section_patterns = document_map.get("section_patterns") or []
    chapters = document_map.get("chapters") or []
    archetypes = _load_archetypes()

    questions: list[dict[str, Any]] = []
    q_counter = 0

    # Generate questions from table structures using domain archetypes
    for ts in table_structures:
        dims = ts.get("dimensions") or []
        measures = ts.get("measures") or []
        breakdowns = ts.get("breakdowns") or []
        if not dims and not measures:
            continue

        # Detect domain from all entity names on this page
        page_ent_names = [e["name"] for e in all_entities if ts["page"] in e.get("pages", [])]
        domain = _detect_domain(page_ent_names + dims + measures, archetypes)
        domain_cfg = archetypes.get(domain) or archetypes.get("generic_tabular", {})
        domain_archetypes = domain_cfg.get("archetypes") or []

        for arch in domain_archetypes[:3]:  # max 3 questions per table
            template = arch.get("template", "")
            if not template:
                continue

            # Fill template slots with real entity names
            measure_val = measures[0] if measures else (dims[1] if len(dims) > 1 else "metric")
            dim_val = dims[0] if dims else "category"
            breakdown_val = breakdowns[0]["values"][0] if breakdowns else "sub-category"
            gender_val = "Male/Female" if any("gender" in d.lower() or "male" in d.lower() or "female" in d.lower() for d in dims + measures) else "Persons"

            intent = template.format(
                measure=measure_val,
                dimension=dim_val,
                breakdown=breakdown_val,
                gender=gender_val,
                sector="Rural/Urban",
                year_start="2018-19",
                year_end="2022-23",
            )

            required_entities = []
            if dims:
                required_entities.append({"entityRef": dims[0], "role": "groupBy"})
            if measures:
                required_entities.append({"entityRef": measures[0], "role": "measure"})
            if breakdowns:
                required_entities.append({"entityRef": breakdowns[0]["measure"], "role": "breakdown"})

            q_counter += 1
            questions.append({
                "questionId": f"q_{q_counter:03d}",
                "intent": intent,
                "questionType": arch.get("questionType", "comparison"),
                "page": ts["page"],
                "sourceHeading": ts.get("description", ""),
                "requiredEntities": required_entities,
                "answerStructure": {
                    "layoutType": arch.get("layout", "split"),
                    "components": [
                        {"type": c, "renderOrder": idx + 1}
                        for idx, c in enumerate(arch.get("components", ["narrative_paragraph", "data_table"]))
                    ],
                },
                "inferenceConfidence": 0.55,  # higher than before: domain-matched
                "inferenceMethod": f"archetype:{domain}",
            })

    # Chapter-based fallback: generate one question per chapter regardless of tables
    # This ensures narrative press releases (0 tables) still get meaningful questions.
    if not questions:
        _MEASURE_HINTS = {"lfpr", "wpr", "ur", "unemployment", "participation", "worker", "earnings",
                          "wage", "salary", "education", "years", "employment", "consumption"}
        for ch in chapters:
            ch_title = ch.get("title", "")
            ch_page = ch["pageRange"][0]
            # Find entities on this chapter's pages
            ch_page_range = ch["pageRange"]
            ch_ents = [e for e in all_entities if any(ch_page_range[0] <= p <= ch_page_range[1] for p in e.get("pages", []))]
            ch_measures = [e["name"] for e in ch_ents if e.get("entityType_hint") == "measure"][:3]
            ch_dims = [e["name"] for e in ch_ents if e.get("entityType_hint") == "dimension"][:2]

            # Pick question type from title keywords
            title_lower = ch_title.lower()
            if any(w in title_lower for w in ("trend", "change", "increase", "decline", "growth")):
                q_type = "trend"
                has_measure = any(w in title_lower for w in _MEASURE_HINTS)
                intent = (
                    f"What is the trend in {ch_measures[0] if ch_measures else 'key indicators'} from 2022 to 2025?"
                    if has_measure else
                    f"What trends are observed in '{ch_title}'?"
                )
            elif any(w in title_lower for w in ("compare", "differ", "rural", "urban", "gender", "male", "female")):
                q_type = "comparison"
                dim = ch_dims[0] if ch_dims else "sector"
                intent = (
                    f"How does {ch_measures[0] if ch_measures else 'the key measure'} vary by {dim}?"
                    if ch_measures else
                    f"How do outcomes compare across groups in '{ch_title}'?"
                )
            else:
                q_type = "describe"
                intent = f"What are the key findings and statistics in the section on '{ch_title}'?"

            req_ents = []
            for ent_name in ch_measures[:2]:
                req_ents.append({"entityRef": ent_name, "role": "measure"})
            for ent_name in ch_dims[:1]:
                req_ents.append({"entityRef": ent_name, "role": "groupBy"})

            q_counter += 1
            questions.append({
                "questionId": f"q_{q_counter:03d}",
                "intent": intent,
                "questionType": q_type,
                "page": ch_page,
                "sourceHeading": ch_title,
                "requiredEntities": req_ents,
                "answerStructure": {
                    "layoutType": "single" if q_type == "describe" else "split",
                    "components": [
                        {"type": "narrative_paragraph", "renderOrder": 1},
                        {"type": "metric_card" if q_type == "describe" else "line_chart" if q_type == "trend" else "grouped_bar_chart", "renderOrder": 2},
                    ],
                },
                "inferenceConfidence": 0.50,
                "inferenceMethod": "programmatic_chapter",
            })

    # Generate summary questions from section patterns (kept as supplementary)
    for sp in section_patterns[:10]:  # cap to avoid hundreds of generic questions
        if sp.get("pattern") in ("executive_summary",) and len(questions) < len(chapters) * 2:
            q_counter += 1
            questions.append({
                "questionId": f"q_{q_counter:03d}",
                "intent": f"What are the key findings in '{sp['title']}'?",
                "questionType": "describe",
                "page": sp["pageRange"][0],
                "sourceHeading": sp["title"],
                "requiredEntities": [],
                "answerStructure": {
                    "layoutType": "single",
                    "components": [
                        {"type": "narrative_paragraph", "renderOrder": 1},
                    ],
                },
                "inferenceConfidence": 0.25,
                "inferenceMethod": "pattern",
            })

    # ── Fact-driven question generation for narrative PDFs ──
    # If we have factGraph facts but no table-driven questions, generate from facts.
    # This is the primary source for PIB press releases, annual reports, etc.
    fact_questions = document_map.get("_fact_questions") or []
    if fact_questions:
        questions.extend(fact_questions)

    # Build topics
    topics: list[dict[str, Any]] = []
    for ch in chapters:
        ch_questions = [
            q for q in questions
            if ch["pageRange"][0] <= q.get("page", -1) <= ch["pageRange"][1]
        ]
        if ch_questions:
            topics.append({
                "topicId": ch["chapterId"].replace("ch_", "topic_"),
                "title": ch["title"],
                "description": f"Programmatic questions from: {ch['title']}",
                "questionIds": [q["questionId"] for q in ch_questions],
                "pageRange": ch["pageRange"],
            })

    logger.info("[pass3] ✓ Programmatic fallback: %d questions in %d topics", len(questions), len(topics))
    return {"questions": questions, "topics": topics}


def _enrich_entity_aliases(entities: list[dict]) -> list[dict]:
    """Extract parenthetical abbreviations as aliases and add to each entity.

    If entity name is "Labour Force Participation Rate (LFPR)", extracts "LFPR" as alias.
    Also applies unicode artifact fix to entity names (Rupee sign, dashes, etc.).
    """
    import re as _re_alias
    _ABBREV_RE = _re_alias.compile(r"\(([A-Z][A-Z0-9\+\-]{1,12})\)")

    for ent in entities:
        # Fix unicode artifacts in entity name (Rupee sign, dashes garbled by pdfplumber)
        raw_name = ent.get("name") or ""
        name = _fix_unicode_artifacts(raw_name)
        if name != raw_name:
            ent["name"] = name
        aliases: list[str] = list(ent.get("aliases") or [])

        # Extract abbreviations like "(LFPR)", "(WPR)", "(ps+ss)"
        for m in _ABBREV_RE.finditer(name):
            abbrev = m.group(1)
            if abbrev not in aliases and abbrev != name:
                aliases.append(abbrev)

        # Add bare name (without parenthetical) as alias — normalize whitespace
        bare = _re_alias.sub(r"\([^)]*\)", "", name)
        bare = _re_alias.sub(r"\s+", " ", bare).strip().rstrip("- ").strip()
        if bare and bare != name and len(bare) >= 4 and bare not in aliases:
            aliases.append(bare)

        ent["aliases"] = aliases

    return entities


def _deduplicate_entities(entities: list[dict]) -> list[dict]:
    """Remove duplicate entities by lowercased name (case-insensitive dedup)."""
    seen: set[str] = set()
    unique: list[dict] = []
    for e in entities:
        key = (e.get("name") or "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


# ─────────────────────────────────────────────────────────────────────────────
# Pass 4: AST Assembly + Embedded Blueprint
# ─────────────────────────────────────────────────────────────────────────────

def pass4_assemble_ast(
    layout_pages: list[dict[str, Any]],
    page_texts: list[dict[str, Any]],
    document_map: dict[str, Any],
    ast_result: dict[str, Any],
    doc_title: str = "Document",
    source_hash: str = "",
    entity_pages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble Enterprise AST + embedded blueprint subtree.

    Merges all extraction passes into the final output:
        - layoutAST, geometryAST from Pass 1
        - contentAST (paragraphs from pdfplumber text, typed by LayoutLM regions)
        - tableAST (table structures from Pass 2.5, NOT values)
        - semanticAST (hierarchy from Pass 2.5 chapters)
        - entityGraph (merged entities)
        - blueprint subtree: TopicNode → QuestionNode → AnswerStructure → AnswerComponent
    """
    logger.info("[pass4] ▶ Assembling Enterprise AST + Blueprint")

    chapters = document_map.get("chapters") or []
    all_entities = document_map.get("all_entities") or []
    table_structures = document_map.get("table_structures") or []
    questions = ast_result.get("questions") or []
    topics_raw = ast_result.get("topics") or []
    page_count = len(page_texts)

    # ── layoutAST ──
    layout_ast_pages = []
    for i, page in enumerate(layout_pages or []):
        blocks = []
        for j, region in enumerate(page.get("regions") or []):
            blocks.append({
                "blockId": f"b{i + 1}_{j + 1}",
                "type": region.get("type", "text"),
                "readingOrder": j + 1,
                "bbox": region.get("bbox", [0, 0, 0, 0]),
                "confidence": region.get("confidence", 0),
            })
        layout_ast_pages.append({
            "pageId": f"page_{i + 1:03d}",
            "width": page.get("width", 595),
            "height": page.get("height", 842),
            "blocks": blocks,
        })

    # ── geometryAST ──
    geometry_nodes = []
    for i, page in enumerate(layout_pages or []):
        for j, region in enumerate(page.get("regions") or []):
            bbox = region.get("bbox") or [0, 0, 0, 0]
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                bbox = [0, 0, 0, 0]
            geometry_nodes.append({
                "nodeId": f"b{i + 1}_{j + 1}",
                "bbox": {
                    "x": bbox[0],
                    "y": bbox[1],
                    "width": bbox[2] - bbox[0],
                    "height": bbox[3] - bbox[1],
                },
                "pageRef": f"page_{i + 1:03d}",
            })

    # ── contentAST (from pdfplumber text, typed by LayoutLM regions) ──
    paragraphs = []
    for i, pt in enumerate(page_texts):
        regions = (layout_pages[i].get("regions") or []) if i < len(layout_pages) else []

        # Create paragraphs from heading regions
        for h_idx, region in enumerate(regions):
            if region.get("type") in ("heading", "title"):
                text = (region.get("text") or "").strip()
                if text:
                    paragraphs.append({
                        "id": f"p_{i + 1:03d}_h{h_idx + 1:02d}",
                        "type": region["type"],
                        "content": text[:500],
                        "pageRef": f"page_{i + 1:03d}",
                        "source": "layoutlm",
                    })

        # Create paragraphs from text regions
        text_regions = [r for r in regions if r.get("type") in ("text", "paragraph")]
        if text_regions:
            for t_idx, region in enumerate(text_regions[:10]):
                text = (region.get("text") or "").strip()
                if text and len(text) > 10:
                    paragraphs.append({
                        "id": f"p_{i + 1:03d}_t{t_idx + 1:02d}",
                        "type": "paragraph",
                        "content": text[:2000],
                        "pageRef": f"page_{i + 1:03d}",
                        "source": "layoutlm",
                    })
        else:
            # Fallback: pdfplumber raw text
            raw = (pt.get("raw_text") or "").strip()
            if raw:
                paragraphs.append({
                    "id": f"p_{i + 1:03d}",
                    "type": "paragraph",
                    "content": raw[:2000],
                    "pageRef": f"page_{i + 1:03d}",
                    "source": "pdfplumber-fallback",
                })

    # ── tableAST (STRUCTURE only, from Pass 2.5 — no values) ──
    tables = []
    for ts in table_structures:
        tables.append({
            "tableId": ts["tableId"],
            "title": ts.get("description", f"Table on page {ts['page'] + 1}"),
            "pageRef": f"page_{ts['page'] + 1:03d}",
            "columns": ts["columns"],
            "dimensions": ts.get("dimensions") or [],
            "measures": ts.get("measures") or [],
            "breakdowns": ts.get("breakdowns") or [],
            "layout": ts.get("layout", "simple"),
            "rowCount": ts.get("row_count", 0),
            "source": "pdfplumber",
        })

    # ── figureAST + chartAST ──
    figures = []
    charts = []
    _seen_figure_pages: set[int] = set()

    # Source 1: LayoutLM-detected chart/figure regions
    for i, page in enumerate(layout_pages or []):
        for j, region in enumerate(page.get("regions") or []):
            if region.get("type") == "chart":
                chart_id = f"chart_{i + 1}_{j + 1}"
                charts.append({
                    "chartId": chart_id,
                    "type": "chart",
                    "chartType": "unknown",
                    "title": (region.get("text") or "")[:200],
                    "page": i,
                    "pageRef": f"page_{i + 1:03d}",
                    "description": "",
                    "detectionSource": "layoutlm",
                })
                _seen_figure_pages.add(i)
            elif region.get("type") == "figure":
                figures.append({
                    "figureId": f"fig_{i + 1}_{j + 1}",
                    "type": "figure",
                    "caption": (region.get("text") or "")[:200],
                    "description": "",
                    "page": i,
                    "pageRef": f"page_{i + 1:03d}",
                    "detectionSource": "layoutlm",
                })
                _seen_figure_pages.add(i)

    # Source 2: VLM-detected charts from pass2 entity_pages
    if entity_pages:
        for ep in entity_pages:
            pg_idx = ep.get("page_index", 0)
            chart_types = ep.get("chart_types") or []
            chart_titles = ep.get("chart_titles") or []
            description = ep.get("description", "")
            if chart_types:
                for ci, ct in enumerate(chart_types):
                    ct_str = str(ct).strip().lower()
                    if not ct_str:
                        continue
                    title = chart_titles[ci] if ci < len(chart_titles) else ""
                    chart_id = f"chart_vlm_{pg_idx + 1}_{ci + 1}"
                    # Avoid exact duplicates with LayoutLM results on same page
                    if pg_idx not in _seen_figure_pages or ci > 0:
                        charts.append({
                            "chartId": chart_id,
                            "type": "chart",
                            "chartType": ct_str,
                            "title": title or description[:120] or f"{ct_str.replace('_', ' ').title()} on page {pg_idx + 1}",
                            "page": pg_idx,
                            "pageRef": f"page_{pg_idx + 1:03d}",
                            "description": description,
                            "detectionSource": "vlm",
                        })
                    _seen_figure_pages.add(pg_idx)
            elif ep.get("structure_type") == "chart_page" and pg_idx not in _seen_figure_pages:
                # VLM said chart_page but couldn't name type — add generic entry
                charts.append({
                    "chartId": f"chart_vlm_{pg_idx + 1}",
                    "type": "chart",
                    "chartType": "chart",
                    "title": description[:120] or f"Chart on page {pg_idx + 1}",
                    "page": pg_idx,
                    "pageRef": f"page_{pg_idx + 1:03d}",
                    "description": description,
                    "detectionSource": "vlm",
                })
                _seen_figure_pages.add(pg_idx)

    # Source 3: pdfplumber embedded images (not yet covered by LayoutLM or VLM)
    for i, pt in enumerate(page_texts):
        for k, emb in enumerate(pt.get("embedded_figures") or []):
            if i not in _seen_figure_pages:
                charts.append({
                    "chartId": f"chart_img_{i + 1}_{k + 1}",
                    "type": "figure",
                    "chartType": "embedded_image",
                    "title": f"Figure on page {i + 1}",
                    "page": i,
                    "pageRef": f"page_{i + 1:03d}",
                    "description": f"Embedded image ({round(emb.get('area_fraction', 0) * 100)}% of page)",
                    "detectionSource": "pdfplumber_image",
                    "bbox": emb.get("bbox"),
                })
                _seen_figure_pages.add(i)

    # Merge figures + charts into the figures list for figureAST
    all_figures = figures + [{**c, "figureId": c.pop("chartId", f"fig_{c.get('page', 0)}")} for c in charts]

    # ── semanticAST (from chapter hierarchy) ──
    # Check if Gemini enrichment has already produced a better hierarchy (via semanticAST.nodes)
    # If it has non-stopword chapter titles, prefer it over the programmatic one.
    _gemini_nodes = ast_result.get("semanticAST_nodes") or []

    semantic_hierarchy = []
    for ch in chapters:
        node = {
            "nodeId": ch["chapterId"],
            "level": 1,
            "title": ch["title"],
            "pageSpan": ch["pageRange"],
            "children": [],
        }
        for sec in ch.get("sections") or []:
            node["children"].append({
                "nodeId": sec["sectionId"],
                "level": sec.get("level", 2),
                "title": sec["title"],
                "pageSpan": [sec.get("page", 0), sec.get("page", 0)],
            })
        semantic_hierarchy.append(node)

    # Quality check: if most chapter titles are single-word stopwords, mark for Gemini override
    bad_titles = sum(
        1 for ch in chapters
        if len(ch.get("title", "").split()) <= 1 and ch.get("title", "").lower() in _ENGLISH_STOPWORDS
    )
    _hierarchy_quality = "poor" if chapters and bad_titles > len(chapters) * 0.4 else "ok"
    logger.info("[pass4] semanticAST hierarchy quality: %s (%d/%d bad titles)",
                _hierarchy_quality, bad_titles, len(chapters))

    # ── entityGraph — use pass2_6 entityType_hint (dimension/measure/filter/metadata) ──
    entity_graph_entries = []
    for ent in all_entities:
        # Use pass2_6 classification if available; fall back to table structure check
        entity_type = ent.get("entityType_hint") or "dimension"
        if entity_type == "dimension":
            # Double-check table structure (may have been updated after pass2_6)
            for ts in table_structures:
                if ent["name"] in ts.get("measures", []):
                    entity_type = "measure"
                    break

        entity_graph_entries.append({
            "entityId": ent["entityId"],
            "name": ent["name"],
            "entityType": entity_type,
            "sourceType": ent.get("source", "unknown"),
            "confidence": 0.8 if ent.get("source") == "table_header" else 0.5,
            "pages": ent.get("pages", []),
            "aliases": ent.get("aliases") or [],
        })

    # ══════════════════════════════════════════════════════════════════
    # BLUEPRINT SUBTREE — the key output for orchestrator.py
    # ══════════════════════════════════════════════════════════════════

    # Build TopicNode → QuestionNode hierarchy
    blueprint_topics = []
    for topic_raw in topics_raw:
        topic_questions = []
        for q in questions:
            q_id = q.get("questionId", "")
            if q_id in (topic_raw.get("questionIds") or []):
                # Build AnswerComponent list
                answer_components = []
                ans_struct = q.get("answerStructure") or {}
                for c_idx, comp in enumerate(ans_struct.get("components") or []):
                    answer_components.append({
                        "componentId": f"{q_id}_c{c_idx + 1}",
                        "renderOrder": comp.get("renderOrder", c_idx + 1),
                        "type": comp.get("type", "narrative_paragraph"),
                        "constraints": comp.get("constraints") or {},
                        "refs": {},
                    })

                # Build entity bindings — fuzzy resolution via _resolve_entity_ref
                entity_bindings = []
                for eb in (q.get("requiredEntities") or []):
                    ref_name = eb.get("entityRef", "")
                    matched_ent = _resolve_entity_ref(ref_name, all_entities)
                    entity_bindings.append({
                        "entityId": matched_ent["entityId"] if matched_ent else f"unresolved_{ref_name[:20]}",
                        "role": eb.get("role", "required"),
                        "confidence": 0.7,
                        "bindingMethod": q.get("inferenceMethod", "vlm"),
                    })

                topic_questions.append({
                    "questionId": q_id,
                    "intent": q.get("intent", ""),
                    "questionType": q.get("questionType", "comparison"),
                    "inferenceMethod": q.get("inferenceMethod", "vlm"),
                    "inferenceConfidence": q.get("inferenceConfidence", 0.5),
                    "requiredEntities": entity_bindings,
                    "answerStructure": {
                        "layoutType": ans_struct.get("layoutType", "single"),
                        "components": answer_components,
                    },
                    "pageIndex": q.get("page", -1),
                    "sourceHeading": q.get("sourceHeading", ""),
                    "priority": "high" if q.get("inferenceConfidence", 0) > 0.7 else "medium",
                })

        if topic_questions:
            blueprint_topics.append({
                "topicId": topic_raw["topicId"],
                "title": topic_raw.get("title", ""),
                "description": topic_raw.get("description", ""),
                "questions": topic_questions,
                "pageRange": topic_raw.get("pageRange", []),
            })

    # Build TemplateEntity list for blueprint
    blueprint_entities = []
    for ent in entity_graph_entries:
        blueprint_entities.append({
            "entityId": ent["entityId"],
            "name": ent["name"],
            "entityType": ent["entityType"],
            "sourceType": ent["sourceType"],
            "confidence": ent["confidence"],
            "aliases": ent.get("aliases") or [],
            "pageIndex": ent["pages"][0] if ent.get("pages") else -1,
            "sourceContext": "",
            "scope": "global",
            "crossRefs": [],
        })

    blueprint = {
        "topics": blueprint_topics,
        "entities": blueprint_entities,
        "tableStructures": [ts for ts in table_structures],
        "documentMap": {
            "title": doc_title,
            "chapters": chapters,
            "sectionPatterns": document_map.get("section_patterns") or [],
        },
    }

    # ── extracted_assets (text per page for frontend) ──
    text_pages = []
    for i, pt in enumerate(page_texts):
        text_pages.append({
            "page_index": i,
            "text": (pt.get("raw_text") or "")[:5000],
        })

    # ── Assemble final AST ──
    ast = {
        "metadata": {
            "documentId": f"doc_{source_hash[:8]}" if source_hash else "doc_001",
            "title": doc_title,
            "pageCount": page_count,
            "checksum": source_hash,
            "extractionMethod": "layoutlm+qwen-vl+knowledge-graph+two-loop",
            "version": "3.0",
        },
        "layoutAST": {"pages": layout_ast_pages},
        "styleAST": {"styles": []},
        "geometryAST": {"nodes": geometry_nodes},
        "assetAST": {"assets": []},
        "annotationAST": {"headers": [], "footers": [], "footnotes": []},
        "semanticAST": {"hierarchy": semantic_hierarchy, "_quality": _hierarchy_quality},
        "contentAST": {"paragraphs": paragraphs, "lists": [], "quotes": []},
        "tableAST": {"tables": tables},
        "figureAST": {"figures": all_figures},
        "chartAST": {"charts": charts},
        "entityGraph": {"entities": entity_graph_entries},
        "knowledgeGraph": {"concepts": [], "relationships": document_map.get("entity_relationships") or []},
        "factGraph": {"facts": []},
        "templateSlots": {"slots": []},
        "questions": [q.get("intent", "") for q in questions],
        "blueprint": blueprint,
        "extracted_assets": {"text_pages": text_pages, "tables": tables, "images": []},
    }

    logger.info(
        "[pass4] ✓ AST assembled: %d layout pages, %d paragraphs, %d tables, "
        "%d figures, %d charts, %d entities, %d topics, %d questions",
        len(layout_ast_pages), len(paragraphs), len(tables),
        len(figures), len(charts),
        len(entity_graph_entries),
        len(blueprint_topics),
        sum(len(t["questions"]) for t in blueprint_topics),
    )
    return ast


# ─────────────────────────────────────────────────────────────────────────────
# Full Pipeline Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def run_extraction_pipeline(
    pdf_path: Path,
    doc_title: str = "Document",
    source_hash: str = "",
    progress_callback: Any = None,
) -> dict[str, Any]:
    """Run the complete 7-pass extraction pipeline.

    Pass 0: Rasterize PDF
    Pass 1: LayoutLM layout detection
    Pass 2: Entity + structure extraction (Qwen-VL, 50-150 tokens/page)
    Pass 2.5: Document Knowledge Graph (programmatic)
    Pass 3: Two-loop AST building (questions + entity bindings)
    Pass 4: Enterprise AST + blueprint assembly
    Pass 5: Optional Gemini enhancement

    Returns:
        Enterprise Document AST dict with embedded blueprint subtree.
    """
    import time as _time

    def _tick(stage: str, pct: int, data: Any = None):
        if progress_callback:
            progress_callback(stage, pct, data)

    pipeline_trace: dict[str, Any] = {"passes": {}, "total_elapsed": 0}
    pipeline_start = _time.monotonic()

    logger.info("═══════════════════════════════════════════════════════════")
    logger.info("  Multi-Pass Extraction Pipeline v3.0")
    logger.info("  File: %s", pdf_path.name)
    logger.info("═══════════════════════════════════════════════════════════")

    # ── Pass 0: Rasterize ──
    _tick("pass0_rasterization", 5)
    t0 = _time.monotonic()
    page_images, page_texts = pass0_rasterize(pdf_path)
    pass0_elapsed = _time.monotonic() - t0
    pipeline_trace["passes"]["pass0_rasterize"] = {
        "elapsed_s": round(pass0_elapsed, 1),
        "images": len(page_images),
        "text_pages": len(page_texts),
    }

    if not page_images and not page_texts:
        raise RuntimeError("Pass 0 failed: could not rasterize or extract text from PDF")

    # Ensure page_texts covers all images
    while len(page_texts) < len(page_images):
        page_texts.append({"raw_text": "", "words": [], "tables": [], "headings": [], "width": 595, "height": 842, "word_count": 0})

    # ── Pass 1: Layout Detection ──
    _tick("pass1_layout_detection", 15)
    t0 = _time.monotonic()
    layout_pages = pass1_layout_detection(pdf_path)
    pass1_elapsed = _time.monotonic() - t0

    layoutlm_used = layout_pages is not None
    if not layout_pages:
        logger.warning("[pipeline] LayoutLM unavailable — building layout from pdfplumber")
        layout_pages = _fallback_layout_from_text(page_texts)

    total_regions = sum(len(p.get("regions") or []) for p in layout_pages)
    pipeline_trace["passes"]["pass1_layout"] = {
        "elapsed_s": round(pass1_elapsed, 1),
        "layoutlm_used": layoutlm_used,
        "pages_with_regions": len(layout_pages),
        "total_regions": total_regions,
    }

    # Build initial ToC from LayoutLM, then improve with hybrid cascade
    toc_layoutlm = build_toc_from_regions(layout_pages, page_texts)
    toc = _extract_toc_hybrid(page_texts, layout_pages, toc_layoutlm)
    pipeline_trace["passes"]["pass1_layout"]["toc_entries"] = len(toc)
    pipeline_trace["passes"]["pass1_layout"]["toc_l1_chapters"] = sum(1 for e in toc if e.level == 1)

    # ── Pass 2: Entity + Structure Extraction ──
    _tick("pass2_entity_extraction", 30)
    t0 = _time.monotonic()
    entity_pages = pass2_entity_structure_extraction(page_images, layout_pages, page_texts, doc_title)
    pass2_elapsed = _time.monotonic() - t0

    vlm_success = sum(1 for p in entity_pages if p.get("vlm_used"))
    total_entities = sum(len(p.get("entities") or []) for p in entity_pages)
    chart_pages_detected = sum(1 for p in entity_pages if p.get("chart_types") or p.get("structure_type") == "chart_page")
    total_charts = sum(len(p.get("chart_types") or []) for p in entity_pages)
    pipeline_trace["passes"]["pass2_entities"] = {
        "elapsed_s": round(pass2_elapsed, 1),
        "pages_total": len(entity_pages),
        "vlm_success": vlm_success,
        "vlm_success_rate": round(vlm_success / max(len(entity_pages), 1) * 100),
        "total_entities": total_entities,
        "chart_pages_detected": chart_pages_detected,
        "total_chart_types": total_charts,
    }

    # ── Pass 2.5: Document Knowledge Graph ──
    _tick("pass2_5_knowledge_graph", 45)
    t0 = _time.monotonic()
    document_map = pass2_5_document_knowledge_graph(entity_pages, layout_pages, page_texts, toc, doc_title)
    pass25_elapsed = _time.monotonic() - t0

    pipeline_trace["passes"]["pass2_5_kg"] = {
        "elapsed_s": round(pass25_elapsed, 1),
        "entities": len(document_map.get("all_entities") or []),
        "table_structures": len(document_map.get("table_structures") or []),
        "chapters": len(document_map.get("chapters") or []),
        "section_patterns": len(document_map.get("section_patterns") or []),
    }

    # ── Pass 2.6: Entity Type Classification ──
    _tick("pass2_6_entity_classification", 55)
    t0 = _time.monotonic()
    document_map = pass2_6_entity_classification(document_map)
    pass26_elapsed = _time.monotonic() - t0
    pipeline_trace["passes"]["pass2_6_classification"] = {
        "elapsed_s": round(pass26_elapsed, 1),
        "measures": sum(1 for e in (document_map.get("all_entities") or []) if e.get("entityType_hint") == "measure"),
        "dimensions": sum(1 for e in (document_map.get("all_entities") or []) if e.get("entityType_hint") == "dimension"),
        "filters": sum(1 for e in (document_map.get("all_entities") or []) if e.get("entityType_hint") == "filter"),
        "metadata": sum(1 for e in (document_map.get("all_entities") or []) if e.get("entityType_hint") == "metadata"),
    }

    # ── Pass 3: Two-Loop AST Building ──
    _tick("pass3_ast_building", 60)
    t0 = _time.monotonic()
    ast_result = pass3_two_loop_ast_building(document_map, page_texts, doc_title, page_images=page_images)
    pass3_elapsed = _time.monotonic() - t0

    # If both loops produced nothing, try Gemini fallback
    if not ast_result.get("questions"):
        logger.info("[pipeline] Pass 3 produced 0 questions — trying Gemini fallback")
        t0_fb = _time.monotonic()
        gemini_result = _gemini_semantic_fallback(document_map, toc, doc_title)
        pass3_elapsed += _time.monotonic() - t0_fb
        if gemini_result.get("questions"):
            ast_result = gemini_result

    pipeline_trace["passes"]["pass3_questions"] = {
        "elapsed_s": round(pass3_elapsed, 1),
        "questions": len(ast_result.get("questions") or []),
        "topics": len(ast_result.get("topics") or []),
    }

    # ── Pass 4: AST Assembly + Blueprint ──
    _tick("pass4_ast_assembly", 80)
    t0 = _time.monotonic()
    ast = pass4_assemble_ast(layout_pages, page_texts, document_map, ast_result, doc_title, source_hash, entity_pages)
    pass4_elapsed = _time.monotonic() - t0
    pipeline_trace["passes"]["pass4_assembly"] = {
        "elapsed_s": round(pass4_elapsed, 1),
        "paragraphs": len(ast.get("contentAST", {}).get("paragraphs") or []),
        "tables": len(ast.get("tableAST", {}).get("tables") or []),
        "figures": len(ast.get("figureAST", {}).get("figures") or []),
        "charts_detected": len([f for f in (ast.get("figureAST", {}).get("figures") or []) if f.get("type") == "chart" or f.get("chartType")]),
        "chart_pages": len(set(f.get("page", -1) for f in (ast.get("figureAST", {}).get("figures") or []) if f.get("type") == "chart" or f.get("chartType"))),
        "blueprint_topics": len(ast.get("blueprint", {}).get("topics") or []),
        "blueprint_entities": len(ast.get("blueprint", {}).get("entities") or []),
    }

    # ── Pass 5: Gemini Enhancement (optional) ──
    _tick("pass5_gemini_enhancement", 90)
    t0 = _time.monotonic()
    try:
        from report_builder.gemini_enrichment import gemini_full_enrichment
        ast = gemini_full_enrichment(ast)
        gemini_status = "success"
    except Exception as exc:
        logger.warning("[pipeline] Gemini enhancement failed (non-fatal): %s", exc)
        gemini_status = f"skipped: {exc}"
    pass5_elapsed = _time.monotonic() - t0
    pipeline_trace["passes"]["pass5_gemini"] = {
        "elapsed_s": round(pass5_elapsed, 1),
        "status": gemini_status,
    }

    # Finalize trace
    pipeline_trace["total_elapsed"] = round(_time.monotonic() - pipeline_start, 1)
    ast["pipeline_trace"] = pipeline_trace

    _tick("completed", 100)
    logger.info("═══════════════════════════════════════════════════════════")
    logger.info("  ✓ Pipeline v3.0 complete — Enterprise AST + Blueprint ready")
    logger.info("  ✓ %d topics, %d questions, %d entities",
                len(ast.get("blueprint", {}).get("topics") or []),
                sum(len(t.get("questions", [])) for t in ast.get("blueprint", {}).get("topics", [])),
                len(ast.get("blueprint", {}).get("entities") or []))
    logger.info("═══════════════════════════════════════════════════════════")

    # ── Persist outputs to disk ──────────────────────────────────────────────
    # Sanitise template name → valid folder name
    import re as _re
    _safe_name = _re.sub(r"[^\w\-]", "_", doc_title).strip("_") or "document"
    _out_dir = Path(__file__).resolve().parent.parent / "outputs" / _safe_name
    _out_dir.mkdir(parents=True, exist_ok=True)

    _ast_path = _out_dir / "enterprise_ast.json"
    _bp_path  = _out_dir / "blueprint.json"

    with open(_ast_path, "w", encoding="utf-8") as _fh:
        json.dump(ast, _fh, ensure_ascii=False, indent=2, default=str)

    with open(_bp_path, "w", encoding="utf-8") as _fh:
        json.dump(ast.get("blueprint", {}), _fh, ensure_ascii=False, indent=2, default=str)

    logger.info("  ✓ Saved enterprise_ast.json  → %s", _ast_path)
    logger.info("  ✓ Saved blueprint.json        → %s", _bp_path)

    return ast


def _fallback_layout_from_text(page_texts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build basic layout page structure from pdfplumber text extraction."""
    pages = []
    for i, pt in enumerate(page_texts):
        regions = []
        # Create heading regions from detected headings
        for h in (pt.get("headings") or [])[:10]:
            regions.append({
                "bbox": [0, 0, 1000, 50],
                "type": "heading",
                "confidence": 0.6,
                "text": h,
            })
        # Create a paragraph region for the body text
        if pt.get("raw_text"):
            regions.append({
                "bbox": [50, 100, 950, 900],
                "type": "text",
                "confidence": 0.5,
                "text": pt["raw_text"][:200],
            })
        # Create table regions
        for j, table in enumerate(pt.get("tables") or []):
            regions.append({
                "bbox": [50, 200 + j * 200, 950, 400 + j * 200],
                "type": "table",
                "confidence": 0.7,
                "text": f"Table with {len(table)} rows",
            })

        pages.append({
            "page_index": i,
            "width": pt.get("width", 595),
            "height": pt.get("height", 842),
            "regions": regions,
        })
    return pages


def _gemini_semantic_fallback(
    document_map: dict[str, Any],
    toc: list[ToCEntry],
    doc_title: str,
) -> dict[str, Any]:
    """Use Gemini as fallback for question generation when local model fails.

    Returns same format as pass3_two_loop_ast_building output.
    """
    try:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("[gemini-fallback] No API key — skipping")
            return {"questions": [], "topics": []}

        gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        # Build entity + table summary from document_map
        all_entities = document_map.get("all_entities") or []
        table_structures = document_map.get("table_structures") or []
        chapters = document_map.get("chapters") or []

        entity_list = ", ".join(e["name"] for e in all_entities[:30])
        table_summary = ""
        for ts in table_structures[:10]:
            table_summary += f"Table p{ts['page'] + 1}: cols=[{', '.join(ts['columns'][:6])}], dims={ts.get('dimensions', [])[:3]}, measures={ts.get('measures', [])[:3]}\n"

        toc_text = "\n".join(f"  {'  ' * (e.level - 1)}{e.title} (p{e.page_index + 1})" for e in toc[:20])

        prompt = (
            f"Document: \"{doc_title}\"\n"
            f"Table of Contents:\n{toc_text}\n\n"
            f"Entities found: {entity_list}\n\n"
            f"Table structures:\n{table_summary}\n\n"
            "Generate analytical questions this document answers. For each question, "
            "specify which entities are needed and what visualization components suit it.\n\n"
            "Output JSON:\n"
            '{"questions":[{"questionId":"q1","intent":"...","questionType":"comparison|trend|ranking|distribution|describe",'
            '"sourceHeading":"...","page":0,'
            '"requiredEntities":[{"entityRef":"entity_name","role":"groupBy|measure|filter"}],'
            '"answerStructure":{"layoutType":"single|split","components":[{"type":"narrative_paragraph|data_table|grouped_bar_chart|line_chart|pie_chart|metric_card","renderOrder":1}]},'
            '"inferenceConfidence":0.6}]}\n'
            "Output 3-8 questions. JSON only."
        )

        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model=gemini_model, contents=prompt)
            text = (response.text or "").strip()
        except ImportError:
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=api_key)
            model_obj = legacy_genai.GenerativeModel(gemini_model)
            response = model_obj.generate_content(prompt)
            text = (response.text or "").strip()

        data = _extract_json_from_response(text)
        if not data:
            return {"questions": [], "topics": []}

        questions = data.get("questions") or []

        # Build topics from chapters
        topics: list[dict[str, Any]] = []
        for ch in chapters:
            ch_questions = [
                q for q in questions
                if ch["pageRange"][0] <= q.get("page", -1) <= ch["pageRange"][1]
            ]
            if ch_questions:
                topics.append({
                    "topicId": ch["chapterId"].replace("ch_", "topic_"),
                    "title": ch["title"],
                    "description": f"Gemini-generated questions for: {ch['title']}",
                    "questionIds": [q.get("questionId", "") for q in ch_questions],
                    "pageRange": ch["pageRange"],
                })

        # If no chapter match, put all in a single topic
        if not topics and questions:
            topics.append({
                "topicId": "topic_gemini",
                "title": doc_title,
                "description": "Gemini-generated questions",
                "questionIds": [q.get("questionId", "") for q in questions],
                "pageRange": [0, document_map.get("page_count", 0) - 1],
            })

        for q in questions:
            q["inferenceMethod"] = "gemini"

        logger.info("[gemini-fallback] ✓ Got %d questions in %d topics", len(questions), len(topics))
        return {"questions": questions, "topics": topics}

    except Exception as exc:
        logger.error("[gemini-fallback] Failed: %s", exc)
        return {"questions": [], "topics": []}
