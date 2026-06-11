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
    SGLANG_TIMEOUT          = 120
    PIPELINE_GPU_MODE       = sequential | concurrent | gemini_only
    GEMINI_MODEL            = gemini-2.5-flash
    GEMINI_API_KEY          (or GOOGLE_API_KEY)
    GROQ_API_KEY
    GROQ_MODEL              = meta-llama/llama-4-scout-17b-16e-instruct
    GROQ_VISION_MODEL       = meta-llama/llama-4-maverick-17b-128e-instruct

Model switching (see report_builder/llm_router.py for full details):
    VLM_PROVIDER            Vision tasks:   qwen (default) | gemini | groq
    REASONING_PROVIDER      Text tasks:     qwen (default) | gemini | groq
    Per-task overrides (override the provider for one task without changing the global):
    PROVIDER_ENTITY_EXTRACTION    (pass 2  — image+entity extraction)
    PROVIDER_QUESTION_GENERATION  (pass 3 L1 — question generation)
    PROVIDER_ENTITY_BINDING       (pass 3 L2 — entity binding)
    PROVIDER_TOC_EXTRACTION       (hybrid ToC L3 — last resort)
    PROVIDER_GAP_FILL             (question gap fill)
    PROVIDER_FACT_EXTRACTION      (fact extraction)
    PROVIDER_SEMANTIC_FALLBACK    (semantic fallback when local model fails)
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from report_builder.chunking import (
    ToCEntry,
    build_toc_from_regions,
    extract_caption_entities_from_layout,
)
from report_builder.llm_router import llm_text_call, llm_vision_call, is_provider_available
from report_builder.llm_schemas import (
    ENTITY_BINDING_SCHEMA,
    ENTITY_CLASSIFICATION_SCHEMA,
    QUESTION_LIST_SCHEMA,
)

logger = logging.getLogger(__name__)

_LAYOUTLM_ENDPOINT = os.getenv("LAYOUTLM_ENDPOINT", "http://localhost:8001")
_SGLANG_ENDPOINT = os.getenv("SGLANG_ENDPOINT", "http://localhost:8002")

# ── LLM call parameters — all read from env, never hardcoded ──────────────────
# Defaults match .env.example. Change via env only.
_T = {
    "entity_extraction":   (int(os.getenv("ENTITY_EXTRACTION_MAX_TOKENS",   "256")),  float(os.getenv("ENTITY_EXTRACTION_TEMPERATURE",   "0.1"))),
    "question_generation": (int(os.getenv("QUESTION_GENERATION_MAX_TOKENS", "600")),  float(os.getenv("QUESTION_GENERATION_TEMPERATURE", "0.15"))),
    "entity_binding":      (int(os.getenv("ENTITY_BINDING_MAX_TOKENS",      "384")),  float(os.getenv("ENTITY_BINDING_TEMPERATURE",      "0.1"))),
    "toc_extraction":      (int(os.getenv("TOC_EXTRACTION_MAX_TOKENS",      "1000")), float(os.getenv("TOC_EXTRACTION_TEMPERATURE",      "0.1"))),
    "gap_fill":            (int(os.getenv("GAP_FILL_MAX_TOKENS",            "1000")), float(os.getenv("GAP_FILL_TEMPERATURE",            "0.2"))),
    "fact_extraction":     (int(os.getenv("FACT_EXTRACTION_MAX_TOKENS",     "1200")), float(os.getenv("FACT_EXTRACTION_TEMPERATURE",     "0.15"))),
    "semantic_fallback":   (int(os.getenv("SEMANTIC_FALLBACK_MAX_TOKENS",   "2000")), float(os.getenv("SEMANTIC_FALLBACK_TEMPERATURE",   "0.2"))),
    "entity_classification":(int(os.getenv("ENTITY_CLASSIFICATION_MAX_TOKENS","600")),float(os.getenv("ENTITY_CLASSIFICATION_TEMPERATURE","0.1"))),
}

def _tok(task: str) -> tuple[int, float]:
    """Return (max_tokens, temperature) for a task from env config."""
    return _T.get(task, (800, 0.15))


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
# Synthetic table-header placeholders emitted when a column has no extractable header
# text (e.g. ``col_0`` … ``col_N``). These are artifacts, not entity candidates.
_PLACEHOLDER_HEADER_RE = _re_entity.compile(r"^col_\d+$", _re_entity.I)

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
    "snapshot", "publications", "reports", "overview", "summary", "highlights",
    "annexure", "appendix", "contents", "introduction", "conclusion",
})

# D1 fix (loop decision Q6): blocklist of PIB / web-export chrome that leaks as "entities".
# Exact multi-word phrases (lowercased, punctuation-stripped) that are never statistical entities.
_ENTITY_BLOCKLIST_PHRASES: frozenset[str] = frozenset({
    "press re", "press release", "press information bureau", "pib delhi",
    "posted on", "release id", "visitor counter", "skip to main content",
    "read more", "click here", "main menu", "last updated", "font size",
    "all rights reserved", "terms of use", "privacy policy", "related links",
    "share on facebook", "print this page", "go to navigation", "site map",
    "screen reader access", "help desk", "contact us", "about us",
})
# Substrings that mark web/markup artifacts anywhere in the candidate.
_ENTITY_BLOCKLIST_SUBSTR: tuple[str, ...] = (
    "javascript", "cookie", "copyright", "breadcrumb", "hyperlink",
    "http", "www.", ".html", ".aspx", "@", "©",
)
# Leading punctuation / time fragments like ":49 AM", "10:49", "- contd" — never entity starts.
_LEADING_PUNCT = ":;,.–—/)]}%&*"
_TIME_FRAGMENT_RE = _re_entity.compile(r"^[:\d]{1,5}\s*(am|pm)?$|^\d{1,2}:\d{2}", _re_entity.I)

import re as _re_entity_extra

# ─────────────────────────────────────────────────────────────────────────────
# Document Type Detection + PLFS Core Entity Seeds
# ─────────────────────────────────────────────────────────────────────────────

# Pre-seeded entities for PLFS press releases — loaded from domain pack
def _load_plfs_entities() -> list[dict[str, Any]]:
    """Load PLFS entities from domain pack (with units, valueDomains, richer aliases)."""
    try:
        from report_builder.domain_packs.plfs_press_release import PLFS_ENTITIES
        return [dict(e) for e in PLFS_ENTITIES]
    except ImportError:
        # Fallback minimal set if domain pack not available
        return [
            {"name": "Labour Force Participation Rate", "aliases": ["LFPR"], "entityType": "measure", "unit": "percent", "source": "pre_seeded"},
            {"name": "Worker Population Ratio", "aliases": ["WPR"], "entityType": "measure", "unit": "percent", "source": "pre_seeded"},
            {"name": "Unemployment Rate", "aliases": ["UR"], "entityType": "measure", "unit": "percent", "source": "pre_seeded"},
            {"name": "Gender", "aliases": ["Male", "Female", "Persons"], "entityType": "dimension", "source": "pre_seeded"},
            {"name": "Sector", "aliases": ["Rural", "Urban"], "entityType": "dimension", "source": "pre_seeded"},
            {"name": "Survey Period", "aliases": ["2024", "2025"], "entityType": "dimension", "source": "pre_seeded"},
            {"name": "Age Group", "aliases": ["15+", "15-29", "15-59"], "entityType": "dimension", "source": "pre_seeded"},
            {"name": "Employment Status", "aliases": ["Self-employed", "Regular wage", "Casual labour"], "entityType": "dimension", "source": "pre_seeded"},
            {"name": "Periodic Labour Force Survey", "aliases": ["PLFS"], "entityType": "metadata", "source": "pre_seeded"},
        ]

_PLFS_CORE_ENTITIES: list[dict[str, Any]] = _load_plfs_entities()

# Document-type-specific configuration
_DOC_TYPE_CONFIG: dict[str, dict[str, Any]] = {
    "pib_press_release": {
        "entity_cap": 30,         # domain pack has ~16 + up to 14 from text extraction
        "table_cap": 0,           # PIB press releases have NO real data tables
        "q_per_chapter": 3,
        "seed_entities": True,    # inject _PLFS_CORE_ENTITIES (from domain pack)
        "text_first_extraction": True,   # prefer text/heading extraction over VLM
        "domain": "labour_force",
    },
    "statistical_annual_report": {
        "entity_cap": 80,
        "table_cap": 30,
        "q_per_chapter": 3,
        "seed_entities": False,
        "text_first_extraction": False,
        "domain": "general",
    },
}


def _detect_document_type(page_texts: list[dict[str, Any]], doc_title: str = "") -> str:
    """Detect whether this PDF is a PIB press release or a statistical annual report.

    Returns 'pib_press_release' or 'statistical_annual_report'.
    Uses page 0 text signals only — no LLM needed.
    """
    import re as _re_dt
    if not page_texts:
        return "statistical_annual_report"

    p0 = (page_texts[0].get("raw_text") or "").lower()
    title_lower = doc_title.lower()

    # Strong PIB press release signals
    pib_signals = [
        "press information bureau",
        "pib delhi",
        "posted on:",
        "press release page",
        "release id:",
        "visitor counter",
    ]
    if any(s in p0 for s in pib_signals):
        return "pib_press_release"

    # Snapshot + LFPR/WPR on short document → PLFS press release
    has_snapshot = "snapshot" in p0 or "key findings" in p0
    has_labour = any(x in p0 for x in ["labour force participation", "lfpr", "wpr", "unemployment rate"])
    if has_snapshot and has_labour and len(page_texts) <= 15:
        return "pib_press_release"

    # Statistical report signals (statement-numbered tables)
    stat_signals = [
        _re_dt.search(r"statement\s+\d+\.\d+", p0),
        _re_dt.search(r"table\s+\d+\.\d+", p0),
        len(page_texts) > 30,
    ]
    if any(stat_signals):
        return "statistical_annual_report"

    return "statistical_annual_report"


def _classify_entity_name(name: str) -> str | None:
    """Classify an entity-name candidate. Returns None if valid, else a short reject reason.

    This is the single source of truth for entity hygiene (D1). ``_is_valid_entity_name``
    is a thin boolean wrapper so existing call sites keep working, while callers that want
    to quarantine rejects (loop decision Q7) can record the reason.
    """
    cleaned = name.strip()
    low = cleaned.lower()
    # Synthetic table-header placeholder (col_0 … col_N): a zero-signal artifact.
    if _PLACEHOLDER_HEADER_RE.match(cleaned):
        return "synthetic_placeholder"
    # Minimum 4 chars
    if len(cleaned) < 4:
        return "too_short"
    if not any(c.isalpha() for c in cleaned):
        return "no_alpha"
    # Max 80 chars — no full sentences or section headings
    if len(cleaned) > 80:
        return "too_long"
    # D1: leading punctuation / time fragments (":49 AM", "10:49", "- contd")
    if cleaned[0] in _LEADING_PUNCT:
        return "leading_punct"
    if _TIME_FRAGMENT_RE.match(cleaned):
        return "time_fragment"
    # D1: PIB / web-export chrome blocklist
    _phrase = _re_entity_extra.sub(r"[^a-z0-9 ]", "", low).strip()
    if _phrase in _ENTITY_BLOCKLIST_PHRASES:
        return "blocklist_phrase"
    if any(s in low for s in _ENTITY_BLOCKLIST_SUBSTR):
        return "blocklist_substr"
    # Reject pure single-word lowercase (likely body-text noise)
    if " " not in cleaned and cleaned == cleaned.lower() and len(cleaned) < 8:
        return "lowercase_fragment"
    if low in _ENGLISH_STOPWORDS:
        return "stopword"
    if low in _PROMPT_ECHO_PHRASES:
        return "prompt_echo"
    if _FIGREF_RE.match(cleaned):
        return "figure_reference"
    if _NUMERIC_ONLY_RE.match(cleaned):
        return "numeric_only"
    if _URL_RE.search(cleaned):
        return "url"
    if _TIMESTAMP_RE.match(cleaned):
        return "timestamp"
    # Section headings like "2. Worker Population Ratio..." — not entities
    if _re_entity_extra.match(r'^\d{1,2}\.\s+[A-Z]', cleaned):
        return "section_heading"
    # Chapter/section headings: "CHAPTER 1 Energy Reserves...", "Chapter 1: Energy..."
    if _re_entity_extra.match(r'^(?:CHAPTER|Chapter|SECTION|Section|PART|Part)\s', cleaned):
        return "chapter_heading"
    # Long multi-word phrases (>38 chars AND >=6 real words) that look like headings/sentences
    # Real entities can be long: "Activity Status - Current Weekly Status" (38 chars, 5 real words)
    _real_words = [w for w in cleaned.split() if any(c.isalpha() for c in w)]
    if len(cleaned) > 38 and len(_real_words) >= 6:
        return "heading_phrase"
    # Instructional / QR / website action phrases
    if any(k in low for k in ("scan the", "click here", "visit our", "access the", "qr code", "download the")):
        return "instructional_phrase"
    # Any entity containing an embedded percentage is a data value fragment, not an entity name
    if _re_entity_extra.search(r'\d+\.?\d*%', cleaned):
        return "embedded_percent"
    # Entities starting with a digit are data values, not entity names
    if _re_entity_extra.match(r'^\d', cleaned) and len(cleaned) > 5:
        return "starts_with_digit"
    # Reject fragment artifacts ending with comma/semicolon
    if cleaned[-1] in ".,;:—–" and len(cleaned.split()) <= 4:
        return "trailing_punct_fragment"
    # Reject pure parenthetical abbreviations like "(PLFS)" "(WPR):"
    if _PAREN_ABBREV_RE.match(cleaned):
        return "paren_abbrev"
    if low in _COMMON_NOISE_WORDS:
        return "noise_word"
    # Reject entity names ending with incomplete parenthesis: "Samrat (Release I"
    if "(" in cleaned and ")" not in cleaned:
        return "incomplete_paren"
    # Reject entity names that are just a definition/expansion: "Labour Force (LFPR):"
    if cleaned.endswith(":") or cleaned.endswith(":-"):
        return "definition_label"
    # Section-title pattern: "ACRONYM: descriptive text" — e.g., "PLFS: Changes in 2025"
    if ": " in cleaned and len(cleaned.split()) >= 3:
        before_colon = cleaned.split(":")[0].strip()
        if before_colon.isupper() or len(before_colon) <= 6:
            return "section_title_pattern"
    # D1: multi-word candidate whose every token is a noise word ("Press Re", "Page Back")
    _tokens = [t for t in _phrase.split() if t]
    if len(_tokens) >= 2 and all(t in _COMMON_NOISE_WORDS for t in _tokens):
        return "all_noise_words"
    # Detect broken word fragments: text starting with lowercase that looks like
    # a mid-word split from a heading ("erves and Introduction", "pter 1: Reserves")
    if cleaned[0].islower() and len(cleaned) > 4 and ' ' in cleaned:
        # Likely a fragment split from a longer heading by ghost table columns
        return "midword_fragment"
    # Detect fragments where the first word is an obvious word-piece (no vowels, or ≤3 chars followed by space)
    if len(_tokens) >= 2:
        first_tok = _tokens[0]
        if len(first_tok) <= 3 and first_tok.isalpha() and first_tok not in ("the", "and", "for", "all", "per", "gdp", "gnp"):
            return "short_prefix_fragment"
    return None


def _is_valid_entity_name(name: str) -> bool:
    """Return True if name is a valid entity (not a stopword / noise / reference)."""
    return _classify_entity_name(name) is None


def _looks_like_data_row(row: list, min_numeric_frac: float = 0.5) -> bool:
    """True if a row is mostly numeric cells (i.e. a data row, not a header row).

    Year-like values (2020-2099) and short 2-digit strings in a row with mostly-None
    cells are treated as sub-header qualifiers, not data.
    Newline-joined cells (collapsed tables) are treated as data.
    """
    import re as _re_dh
    cells = [str(c or "").strip() for c in row]
    nonempty = [c for c in cells if c]
    if not nonempty:
        return False
    # Collapsed table detection: if any cell contains 3+ newlines with numeric lines,
    # this is a data row with multiple values packed into one cell (MoSPI common pattern)
    for c in nonempty:
        if c.count("\n") >= 3:
            lines = [l.strip().replace(",", "") for l in c.split("\n") if l.strip()]
            numeric_lines = sum(1 for l in lines if l.replace(".", "").replace("-", "").isdigit())
            if numeric_lines >= len(lines) * 0.5:
                return True  # Collapsed numeric data
    # If most cells are empty and the non-empty ones are short years/qualifiers → header
    none_count = sum(1 for c in cells if not c)
    if none_count > len(cells) * 0.4:
        # Mostly empty → likely a sub-header row with spanning qualifiers
        all_years_or_short = all(
            _re_dh.match(r'^(?:20\d{2}(?:-\d{2})?|FY\d{4}|\d{2}-\d{2})$', c)
            for c in nonempty
        )
        if all_years_or_short:
            return False  # This is a year sub-header, not data
    numeric = 0
    for c in nonempty:
        v = c.replace(",", "").replace("%", "").replace("\u20b9", "").replace("(", "").replace(")", "").strip()
        # Year values in headers should not count as numeric data
        if _re_dh.match(r'^20\d{2}(?:-\d{2})?$', v):
            continue  # Skip — year-like, treated as header qualifier
        try:
            float(v)
            numeric += 1
        except (ValueError, TypeError):
            pass
    return numeric >= len(nonempty) * min_numeric_frac


def _forward_fill_row(row: list, width: int) -> list[str]:
    """Forward-fill a header row so a spanning label propagates across its empty cells."""
    out: list[str] = []
    last = ""
    for j in range(width):
        cell = str(row[j] or "").strip() if j < len(row) else ""
        if cell:
            last = cell
        out.append(cell if cell else last)
    return out


def _detect_header_row_count(table: list[list], max_header_rows: int = 3) -> int:
    """Number of leading header rows = rows before the first data-looking row (1..max)."""
    n = 0
    for r in range(min(max_header_rows, max(1, len(table) - 1))):
        if _looks_like_data_row(table[r]):
            break
        n += 1
    return max(1, n)


def _analyze_table_header(table: list[list]) -> dict[str, Any]:
    """Analyze an N-row spanning header (D2 fix).

    Handles the 1\u20133 row fragmented headers common in MoSPI/NSSO/PIB exports by
    forward-filling spanning bands and merging top\u2192bottom into flat column names,
    while also emitting ``columnGroups`` for the spanning bands (loop decision Q9:
    geometry-span + repetition).

    Returns: {headers, columnGroups, data_start, headerRows, tableTitle}
    """
    if not table:
        return {"headers": [], "columnGroups": [], "data_start": 0, "headerRows": 0, "tableTitle": ""}

    total_cols = max((len(r) for r in table), default=0)
    if total_cols == 0:
        return {"headers": [], "columnGroups": [], "data_start": 1, "headerRows": 1, "tableTitle": ""}

    # ── Title row detection ──
    # MoSPI tables often have row[0] = ["Table 1.1: Title...", None, None, None...]
    # This is a title spanning all columns, NOT a header row.
    table_title = ""
    title_rows_skip = 0
    import re as _re_th
    _TABLE_TITLE_RE = _re_th.compile(
        r"^(?:Table|Statement|Annexure|Appendix)\s+\d+[\.\d]*\s*[:\.\-—–]?\s*",
        _re_th.I,
    )
    for skip_r in range(min(2, len(table))):
        row = table[skip_r]
        non_null_cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
        if len(non_null_cells) == 1 and _TABLE_TITLE_RE.match(non_null_cells[0]):
            table_title = non_null_cells[0].strip()
            title_rows_skip = skip_r + 1

    # Work with table after skipping title row(s)
    working_table = table[title_rows_skip:] if title_rows_skip else table

    n_header = _detect_header_row_count(working_table)
    filled = [_forward_fill_row(working_table[r], total_cols) for r in range(n_header)]
    raw = [[str(working_table[r][j] or "").strip() if j < len(working_table[r]) else "" for j in range(total_cols)]
           for r in range(n_header)]

    # Merge each column top→bottom, de-duplicating consecutive equal parts.
    headers: list[str] = []
    for j in range(total_cols):
        parts: list[str] = []
        for r in range(n_header):
            val = filled[r][j]
            if val and (not parts or parts[-1].lower() != val.lower()):
                parts.append(val)
        headers.append(" ".join(parts).strip() or f"col_{j}")

    # columnGroups: maximal runs of consecutive columns sharing the same top-band label,
    # where the band genuinely spans (>= 2 columns). Repetition of the leaf qualifiers
    # under each band corroborates a real cross-tabulation.
    column_groups: list[dict[str, Any]] = []
    if n_header >= 2:
        top = filled[0]
        j = 0
        gid = 0
        while j < total_cols:
            label = top[j]
            k = j
            while k + 1 < total_cols and top[k + 1] == label:
                k += 1
            span = k - j + 1
            if label and span >= 2:
                gid += 1
                column_groups.append({
                    "groupId": f"grp_{gid}",
                    "label": label,
                    "columnIndices": list(range(j, k + 1)),
                    "span": span,
                })
            j = k + 1

    return {
        "headers": headers,
        "columnGroups": column_groups,
        "data_start": n_header + title_rows_skip,
        "headerRows": n_header,
        "tableTitle": table_title,
    }


def _merge_multirow_headers(table: list[list]) -> tuple[list[str], int]:
    """Backward-compatible wrapper around :func:`_analyze_table_header`.

    Returns ``(merged_header_list, data_start_row_index)`` for the many call sites that
    only need the flat header list (entity collection, etc.).
    """
    info = _analyze_table_header(table)
    return info["headers"], info["data_start"]


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
    # Energy domain
    "reserves", "potential", "capacity", "generation", "distribution",
    "installed", "estimated", "proved", "indicated", "inferred",
    "tonnes", "mw", "gwh", "bcm", "mtoe",
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


def _is_ghost_table(table: list[list]) -> bool:
    """Return True if this table is a page-spanning ghost artifact.

    MoSPI/govt styled PDFs often produce ghost grids (125×89, 97% null) from
    background drawing objects. Characteristics:
      - Very wide (>30 columns) AND very sparse (<20% non-null cells)
      - OR first 3 rows are entirely None (no header content at all)
      - OR headers are fragmented (many short broken word pieces)
      - BUT small tables with genuinely sparse data are preserved

    This filter NEVER rejects tables with ≤30 columns that have well-formed headers.
    """
    if not table:
        return True
    rows = len(table)
    cols = len(table[0]) if table else 0
    total_cells = rows * cols

    # Check fill rate for any table
    non_null = sum(1 for row in table for c in row if c is not None and str(c).strip())
    fill_rate = non_null / max(total_cells, 1)

    # Very wide tables (>30 cols): original ghost filter
    if cols > 30:
        if fill_rate < 0.20:
            return True
        # Wide table with all-None first 3 rows = no header
        header_rows = table[:min(3, rows)]
        header_non_null = sum(1 for row in header_rows for c in row if c is not None)
        if header_non_null == 0:
            return True
        return False

    # For narrower tables: detect fragmented header artifacts
    # Chart-drawn ghost tables have cells with broken word fragments
    if cols >= 3 and rows >= 2:
        # Check first 2 rows for fragmented text patterns
        header_cells = []
        for r in range(min(2, rows)):
            for c in table[r]:
                if c is not None and str(c).strip():
                    header_cells.append(str(c).strip())

        if header_cells:
            # Count cells that look like word fragments (short, no space, lowercase-starting mid-word)
            fragments = 0
            for cell in header_cells:
                # Fragment indicators: starts with lowercase, or very short (1-4 chars non-numeric)
                if len(cell) <= 4 and not cell.replace('.', '').replace(',', '').isdigit():
                    fragments += 1
                elif cell[0].islower() and not cell.isdigit():
                    fragments += 1
                elif '\n' in cell and len(cell.split('\n')) > 3:
                    # Multi-line collapsed cells (newline-joined garbage)
                    fragments += 1

            frag_ratio = fragments / max(len(header_cells), 1)
            # If >50% of header cells are fragments AND table is very sparse → ghost
            if frag_ratio > 0.5 and fill_rate < 0.30:
                return True

    # Tables with extremely low fill rate (<5%) regardless of width are likely artifacts
    if fill_rate < 0.05 and rows > 5:
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
    # Normalize Unicode dashes/quotes to ASCII for clean display
    text = text.replace('\u2013', '-')    # en dash -> hyphen
    text = text.replace('\u2014', '-')    # em dash -> hyphen
    text = text.replace('\u2018', "'")    # left single quote
    text = text.replace('\u2019', "'")    # right single quote / apostrophe
    text = text.replace('\u201c', '"')    # left double quote
    text = text.replace('\u201d', '"')    # right double quote
    text = text.replace('\u00a0', ' ')    # non-breaking space
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

    # L3: LLM last resort (provider = PROVIDER_TOC_EXTRACTION or REASONING_PROVIDER, default gemini)
    l3_entries: list[ToCEntry] = []
    combined_so_far = len(l1_entries) + len(l2_entries) + len(toc_layoutlm)
    if combined_so_far < 3:
        try:
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
            raw = llm_text_call(prompt, task="toc_extraction", max_tokens=_tok("toc_extraction")[0], temperature=_tok("toc_extraction")[1])
            if raw:
                parsed = _extract_json_array_from_response(raw)
                if parsed:
                    for item in parsed:
                        if not isinstance(item, dict):
                            continue
                        title = (item.get("title") or "").strip()
                        page = int(item.get("page") or 1) - 1
                        level = int(item.get("level") or 1)
                        if title and 0 <= page < len(page_texts):
                            l3_entries.append(ToCEntry(title=title, page_index=max(0, page), level=level, region_type="llm_l3"))
                    logger.info("[toc_hybrid] L3 LLM: %d entries", len(l3_entries))
        except Exception as exc:
            logger.warning("[toc_hybrid] L3 LLM failed (non-fatal): %s", exc)

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

    # ── Step 2: LLM batch classification for ambiguous entities ──
    ambiguous_to_classify = [e for e in ambiguous if e.get("entityType_hint") == "dimension"][:40]
    if ambiguous_to_classify:
        try:
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
            raw = llm_text_call(prompt, task="entity_classification", max_tokens=_tok("entity_classification")[0], temperature=_tok("entity_classification")[1], schema=ENTITY_CLASSIFICATION_SCHEMA)
            if raw:
                classifications = _extract_json_array_from_response(raw)
                if classifications:
                    name_to_type: dict[str, str] = {
                        item.get("name", "").lower(): item.get("type", "dimension")
                        for item in classifications
                        if isinstance(item, dict)
                    }
                    updated = 0
                    for ent in ambiguous_to_classify:
                        name_key = ent["name"].lower()
                        classified = name_to_type.get(name_key)
                        if not classified:
                            # Prefix fallback: "labour force participation rate" → "labour force"
                            classified = next(
                                (v for k, v in name_to_type.items() if name_key[:20] in k or k[:20] in name_key),
                                None,
                            )
                        if classified in ("dimension", "measure", "filter", "metadata"):
                            ent["entityType_hint"] = classified
                            updated += 1
                        else:
                            logger.debug("[pass2.6]   No classification for entity '%s'", ent["name"])
                    logger.info("[pass2.6]   Step 2 LLM: classified %d ambiguous entities", updated)
        except Exception as exc:
            logger.warning("[pass2.6]   Step 2 LLM failed (non-fatal): %s", exc)

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
        _pdf_dpi = int(os.getenv("PDF_DPI", "150"))
        images = pdf2image.convert_from_path(str(pdf_path), dpi=_pdf_dpi, fmt="png", poppler_path=poppler_path)
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
                # Filter ghost tables: page-spanning grids from PDF drawing objects
                # (e.g. 125×89, 97% null cells — common in MoSPI/govt styled PDFs)
                tables = [t for t in tables if not _is_ghost_table(t)]
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

                # Detect headings from font analysis — group bold words by line (y-position)
                # Individual bold single words ("areas", "workers") are noise; require 2+ words.
                _bold_lines: dict[int, list[str]] = {}
                for w in words:
                    if w.get("size", 0) >= 12 or "Bold" in str(w.get("fontname", "")):
                        wtext = str(w.get("text", "")).strip()
                        if wtext and len(wtext) > 1:
                            y_key = int((w.get("top") or 0) // 3) * 3
                            _bold_lines.setdefault(y_key, []).append(wtext)
                headings: list[str] = []
                for _line_words in _bold_lines.values():
                    _phrase = " ".join(_line_words).strip()
                    # Only include multi-word phrases (single words are noisy)
                    # OR known short statistical abbreviations
                    _known_abbrevs = {"LFPR", "WPR", "UR", "MPCE", "CPI", "GDP", "NSO", "PLFS", "CWS"}
                    if len(_line_words) >= 2 and len(_phrase) > 5:
                        headings.append(_phrase)
                    elif _phrase.upper() in _known_abbrevs:
                        headings.append(_phrase)

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
    # Offline / air-gapped: skip the LayoutLM service entirely (caller falls back
    # to pdfplumber-derived layout). Treats LayoutLM like an LLM service for
    # reproducible no-network simulations.
    if (os.getenv("LLM_DISABLED") or "").strip().lower() in ("1", "true", "yes", "on"):
        logger.info("[pass1] LLM_DISABLED set — skipping LayoutLM, using pdfplumber layout")
        return None

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
    doc_type: str = "statistical_annual_report",
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
    total_pages = len(page_images)

    # Pre-flight: check if the configured VLM provider is reachable
    import os as _os_p2
    _p2_provider = (_os_p2.getenv("PROVIDER_ENTITY_EXTRACTION") or _os_p2.getenv("VLM_PROVIDER", "qwen")).strip().lower()
    vlm_alive = is_provider_available(_p2_provider, vision=True)
    if total_pages > 0 and not vlm_alive:
        logger.warning("[pass2] Provider '%s' not reachable — falling back to pdfplumber-only entities", _p2_provider)

    # If provider is down, extract entities from pdfplumber only
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

    logger.info("[pass2] ▶ Entity+structure extraction: %d pages via %s", total_pages, _p2_provider)
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
                # Concise region hint from LayoutLM
                region_types = ", ".join(set(r.get("type", "?") for r in regions[:10])) or "none"
                # Hint if pdfplumber detected embedded images (likely charts)
                n_embedded = len(page_text.get("embedded_figures") or [])
                image_hint = f" (PDF has {n_embedded} embedded image(s) — likely charts/figures)" if n_embedded else ""

                # Build doc-type-aware entity extraction prompt
                if doc_type == "pib_press_release":
                    prompt = (
                        f"Page {i + 1}/{total_pages} of \"{doc_title}\" (PIB Press Release).\n"
                        f"Layout: {region_types}{image_hint}\n\n"
                        "This is a government press release. Extract ONLY:\n"
                        "entities: Statistical indicator names and dimension names ONLY. "
                        "Examples: 'LFPR', 'WPR', 'Unemployment Rate', 'Gender', 'Rural', 'Urban', "
                        "'Age Group', 'Self-employed', 'Regular wage'. "
                        "DO NOT include: website text, dates, percentages, full sentences, "
                        "figure references, or nav-bar fragments.\n"
                        "section_heading: The numbered section title if visible (e.g. '1. Stable LFPR...'). "
                        "Empty string otherwise.\n"
                        "chart_types: list each DISTINCT chart actually visible, once each "
                        "(bar_chart, line_chart, pie_chart, …). [] if none. Do NOT guess and "
                        "do NOT copy the example below.\n"
                        "structure_type: narrative (most pages), chart_page (if chart dominates), "
                        "title_page (cover), appendix (endnote).\n"
                        "Output ONLY this JSON:\n"
                        '{"entities":["LFPR","WPR","Gender","Rural","Urban"],'
                        '"structure_type":"narrative|chart_page|title_page|appendix|mixed",'
                        '"description":"one-line summary",'
                        '"table_title":"",'
                        '"section_heading":"numbered section title if visible else empty",'
                        '"chart_types":[],'
                        '"chart_titles":[]}\n'
                        "JSON only."
                    )
                else:
                    # Statistical annual report — rich table extraction prompt
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
                        "3. If a section/chapter heading is visible, extract it exactly. "
                        "Use empty string if none.\n"
                        "4. Identify charts/graphs ONLY if actually visible: bar, line, pie, "
                        "scatter, area, map. List each DISTINCT chart once; do not guess.\n"
                        "5. Provide visible chart titles if any.\n"
                        "6. Classify the dominant page structure.\n"
                        "Output ONLY this JSON (no prose, no markdown):\n"
                        '{"entities":["ExactColumnHeader","MetricName"],'
                        '"structure_type":"data_table|chart_page|narrative|title_page|appendix|mixed",'
                        '"description":"one-line summary",'
                        '"table_title":"Statement X.Y or table title if present else empty",'
                        '"section_heading":"Chapter or section heading if present else empty",'
                        '"chart_types":[],'
                        '"chart_titles":[]}\n'
                        "chart_types MUST be [] if no charts visible; one entry per distinct "
                        "chart, never a guessed pair. Do NOT copy the example. JSON only."
                    )

                raw = llm_vision_call(
                    prompt=prompt,
                    image_bytes=img_bytes,
                    task="entity_extraction",
                    max_tokens=_tok("entity_extraction")[0],
                    temperature=_tok("entity_extraction")[1],
                )
                if raw:
                    vlm_result = _extract_json_from_response(raw)
                    if vlm_result:
                        hard_failures = 0
                        logger.debug("[pass2] Page %d OK — %d entities", i,
                                     len(vlm_result.get("entities") or []))
                    else:
                        logger.info("[pass2] Page %d returned text but no valid JSON", i)
                        hard_failures += 1
                else:
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
            # Skip ghost tables
            if _is_ghost_table(table):
                continue
            headers, _ = _merge_multirow_headers(table)
            # Detect split-heading artifact: if most headers share a common suffix word,
            # they're fragments of a single heading split across ghost table cells
            if headers and len(headers) >= 3:
                suffix_counts: dict[str, int] = {}
                for h in headers:
                    if h and ' ' in h:
                        last_word = h.rsplit(' ', 1)[-1].lower()
                        suffix_counts[last_word] = suffix_counts.get(last_word, 0) + 1
                # If >50% of headers share the same suffix → fragmented heading, skip all
                max_shared = max(suffix_counts.values()) if suffix_counts else 0
                if max_shared >= len(headers) * 0.5:
                    continue
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
    doc_type: str = "statistical_annual_report",
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
    rejected_index: dict[str, dict[str, Any]] = {}  # key=lowered name → reject record (D1 quarantine, Q7)

    _entity_id_seq = [len(_PLFS_CORE_ENTITIES) + 1]  # start after pre-seeded IDs

    def _register_entity(name: str, source: str, page: int, priority: int):
        key = name.lower().strip()
        if not key:
            return
        # Reject stopwords, noise, figure refs, web chrome — quarantine with reason (Q7), don't drop
        reason = _classify_entity_name(name) if len(name) < 100 else "too_long"
        if reason is not None:
            # Synthetic placeholders (col_N) carry no signal — drop entirely, don't even quarantine.
            if reason == "synthetic_placeholder":
                return
            if key not in entity_index and key not in rejected_index:
                rejected_index[key] = {
                    "name": name.strip(), "reason": reason, "source": source, "page": page,
                }
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
            eid = _entity_id_seq[0]
            _entity_id_seq[0] += 1
            entity_index[key] = {
                "entityId": f"ent_{eid:03d}",
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

    # Resolve doc-type config early (needed by text-first extraction + pre-seeding)
    cfg = _DOC_TYPE_CONFIG.get(doc_type, _DOC_TYPE_CONFIG["statistical_annual_report"])

    # Source 5 (text-first): For PIB press releases, extract entities from page text
    # using domain-specific regex patterns. This catches entities the VLM misses.
    if cfg.get("text_first_extraction"):
        try:
            import re as _re_tf
            from report_builder.domain_packs.plfs_press_release import PIB_TEXT_ENTITY_PATTERNS
            _text_entities_found = 0
            for page_idx, pt in enumerate(page_texts):
                raw_text = (pt.get("raw_text") or "") if isinstance(pt, dict) else ""
                for pat in PIB_TEXT_ENTITY_PATTERNS:
                    if _re_tf.search(pat["pattern"], raw_text, _re_tf.IGNORECASE):
                        _register_entity(pat["entity"], "text_pattern", page_idx, 1)
                        _text_entities_found += 1
            if _text_entities_found:
                logger.info("[pass2.5]   Text-first extraction: %d pattern matches across %d pages", _text_entities_found, len(page_texts))
        except Exception as _tf_exc:
            logger.debug("[pass2.5]   Text-first extraction skipped: %s", _tf_exc)

    # ── Pre-seed known entities for PIB press releases ──
    # These entities are guaranteed to appear in PLFS press releases and anchor
    # the entity graph even when extraction quality is poor.
    all_entities: list[dict[str, Any]] = []
    _ent_id_counter = 1

    if cfg.get("seed_entities"):
        for _seed in _PLFS_CORE_ENTITIES:
            _eid = f"ent_{_ent_id_counter:03d}"
            _ent_id_counter += 1
            _ent_dict: dict[str, Any] = {
                "entityId": _eid,
                "name": _seed["name"],
                "source": _seed.get("source", "domain_pack"),
                "pages": list(range(len(page_texts))),  # appears across all pages
                "entityType_hint": _seed["entityType"],
                "aliases": list(_seed.get("aliases") or []),
                "_priority_protect": True,
            }
            # Carry unit and valueDomain from domain pack
            if _seed.get("unit"):
                _ent_dict["unit"] = _seed["unit"]
            if _seed.get("valueDomain"):
                _ent_dict["valueDomain"] = _seed["valueDomain"]
            all_entities.append(_ent_dict)
        logger.info("[pass2.5]   Pre-seeded %d core entities for %s", len(all_entities), doc_type)

    # Finalize entities from extraction
    for ent in entity_index.values():
        del ent["_priority"]
        all_entities.append(ent)

    all_entities = _deduplicate_entities(all_entities)
    all_entities = _enrich_entity_aliases(all_entities)

    # Quarantined rejects (D1/Q7) — surfaced for audit + threshold tuning, never silently dropped.
    entities_rejected = sorted(
        rejected_index.values(), key=lambda r: (r["reason"], r["name"].lower())
    )[:200]
    if entities_rejected:
        logger.info("[pass2.5]   Quarantined %d noisy entity candidate(s)", len(rejected_index))

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
        if not _ent.get("_priority_protect"):
            _ent["_priority_protect"] = any(k in _n for k in _MOSPI_CORE_KEYWORDS)

    _ent_cap = cfg.get("entity_cap", 60)
    if len(all_entities) > _ent_cap:
        _protected = [e for e in all_entities if e.get("_priority_protect")]
        _remainder = [e for e in all_entities if not e.get("_priority_protect")]
        _ENT_PRIORITY = {"table_header": 0, "heading": 1, "vlm": 2, "bold_word": 3, "pre_seeded": -1}
        _remainder.sort(key=lambda e: (_ENT_PRIORITY.get(e.get("source", "vlm"), 2), -len(e.get("pages") or [0])))
        _cap = max(0, _ent_cap - len(_protected))
        all_entities = _protected + _remainder[:_cap]
        logger.info("[pass2.5]   Entity count capped to %d (protected=%d, others=%d)", _ent_cap, len(_protected), _cap)

    logger.info("[pass2.5]   Step 1: %d unique entities from %d pages", len(all_entities), total_pages)

    # ── Step 2: Table Structure Analysis ──
    table_structures: list[dict[str, Any]] = []
    for i, pt in enumerate(page_texts):
        for t_idx, table in enumerate(pt.get("tables") or []):
            if not table or len(table) < 2:
                continue

            # Merge multi-row spanning headers (critical for MoSPI/NSSO PDFs)
            header_info = _analyze_table_header(table)
            headers = header_info["headers"]
            data_start = header_info["data_start"]
            column_groups = header_info["columnGroups"]
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

                # Keyword backstop (D2): when data sampling is inconclusive, fall back to
                # the header's domain keywords so measures are not lost on sparse tables.
                hl = header.lower()
                kw_measure = any(k in hl for k in _MOSPI_MEASURE_KEYWORDS)
                kw_dimension = any(k in hl for k in _MOSPI_DIMENSION_KEYWORDS)
                if numeric_count > text_count:
                    measures.append(header)
                elif numeric_count == text_count and kw_measure and not kw_dimension:
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
                "columnGroups": column_groups,
                "dimensions": dimensions,
                "measures": measures,
                "breakdowns": breakdowns,
                "layout": layout_type,
                "row_count": len(table) - 1,
                "headerRows": header_info["headerRows"],
                "needsReview": not measures,  # Q10: flag, do not drop
                "description": header_info.get("tableTitle") or f"Table with {len(headers)} columns, {len(table) - 1} rows",
                "tableTitle": header_info.get("tableTitle", ""),
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
                        "columnGroups": [],
                        "dimensions": [],
                        "measures": [],
                        "breakdowns": [],
                        "layout": "simple",
                        "row_count": parsed["row_count"],
                        "headerRows": 1,
                        "needsReview": True,
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
    # Footnote/disclaimer patterns: "2 Total may not tally...", "* Brief about..."
    _FOOTNOTE_RE_CH = _re_ch_filter.compile(
        r"^\d{1,2}\s+(?:Total|Note|Source|Figures?|Data|Numbers?|Values?|may|includes?|exclud)",
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
            and not _FOOTNOTE_RE_CH.match(ch["title"])
        )
    ]
    if chapters_before_filter != len(chapters):
        logger.info("[pass2.5]   Chapter filter: %d → %d (removed %d junk chapters)",
                    chapters_before_filter, len(chapters), chapters_before_filter - len(chapters))

    # ── Chapter deduplication ──
    # Merge chapters that are the same content with different formats:
    # "CHAPTER 1" + "Energy Reserves and Potential" on same page → merge title
    # "Energy Reserves and Potential" + "1 Energy Reserves and Potential" → keep numbered one
    import re as _re_ch_dedup
    _BARE_CHAPTER_RE = _re_ch_dedup.compile(r'^(?:CHAPTER|Chapter|PART|Part|Section)\s+\d+\s*$', _re_ch_dedup.I)

    # Step 1: Remove bare "CHAPTER N" entries if there's a real title on the same or adjacent page
    _bare_chapters = [ch for ch in chapters if _BARE_CHAPTER_RE.match(ch["title"].strip())]
    if _bare_chapters:
        _real_chapters = [ch for ch in chapters if not _BARE_CHAPTER_RE.match(ch["title"].strip())]
        for bare in _bare_chapters:
            bare_page = bare["pageRange"][0]
            # Check if any real chapter starts on same or next page
            has_real = any(abs(rc["pageRange"][0] - bare_page) <= 1 for rc in _real_chapters)
            if has_real:
                chapters = [ch for ch in chapters if ch is not bare]

    # Step 2: Merge numbered prefix duplicates ONLY if they overlap in page range
    # "1 Energy Reserves" on p2-p7 vs "Energy Reserves" on p2-p7 → merge (same content)
    # "1 Energy Reserves" on p9-p9 vs "Energy Reserves" on p2-p7 → KEEP BOTH (different sections)
    _numbered_prefix_re = _re_ch_dedup.compile(r'^\d{1,2}[\.\s]+(.+)$')
    _dedup_chapters: list[dict] = []
    for ch in chapters:
        title_clean = ch["title"].strip()
        m = _numbered_prefix_re.match(title_clean)
        base_title = m.group(1).strip().lower() if m else title_clean.lower()
        ch_start = ch["pageRange"][0]
        ch_end = ch["pageRange"][1]

        # Check if an existing chapter with same base title OVERLAPS this one's page range
        is_duplicate = False
        for existing in _dedup_chapters:
            ex_title = existing["title"].strip()
            ex_m = _numbered_prefix_re.match(ex_title)
            ex_base = ex_m.group(1).strip().lower() if ex_m else ex_title.lower()
            if base_title == ex_base:
                # Check page range overlap
                ex_start = existing["pageRange"][0]
                ex_end = existing["pageRange"][1]
                if (ch_start <= ex_end + 1 and ch_end >= ex_start - 1):
                    # Overlapping or adjacent → merge (extend the existing range)
                    existing["pageRange"] = [min(ch_start, ex_start), max(ch_end, ex_end)]
                    is_duplicate = True
                    break
        if not is_duplicate:
            _dedup_chapters.append(ch)

    if len(_dedup_chapters) < len(chapters):
        logger.info("[pass2.5]   Chapter dedup: %d → %d (merged duplicates)",
                    len(chapters), len(_dedup_chapters))
    chapters = _dedup_chapters

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
        "entities_rejected": entities_rejected,
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
    import os as _os_p3
    _p3_qgen_provider = (_os_p3.getenv("PROVIDER_QUESTION_GENERATION") or _os_p3.getenv("VLM_PROVIDER", "qwen")).strip().lower()
    _p3_bind_provider = (_os_p3.getenv("PROVIDER_ENTITY_BINDING") or _os_p3.getenv("REASONING_PROVIDER", "qwen")).strip().lower()

    from report_builder.question_quality import (
        archetype_questions,
        build_analytics_spec,
        is_stub_question,
        normalise_question_type,
        route_unassigned,
    )

    logger.info("[pass3] ▶ Two-loop AST building | question_gen=%s entity_binding=%s",
                _p3_qgen_provider, _p3_bind_provider)
    t0 = time.monotonic()

    chapters = document_map.get("chapters") or []
    all_entities = document_map.get("all_entities") or []
    table_structures = document_map.get("table_structures") or []
    section_patterns = document_map.get("section_patterns") or []
    context_scripts = document_map.get("per_page_context_scripts") or []

    # Pre-flight: check if the configured provider is reachable
    vlm_alive = is_provider_available(_p3_qgen_provider, vision=True)

    if not vlm_alive:
        logger.warning("[pass3] Provider '%s' not reachable — generating stub questions programmatically", _p3_qgen_provider)
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
            "Output a JSON array. Each item has keys: questionId, intent, questionType, sourceHeading.\n"
            "  - intent: a complete, quantitative question ending in '?' that names real entities.\n"
            "  - questionType: EXACTLY ONE of comparison, trend, ranking, distribution, composition, correlation, describe.\n"
            "  - sourceHeading: the exact section title.\n"
            "Do NOT copy these instructions or any placeholder text into the output.\n"
            "List 1-3 questions. JSON only."
        )

        # Attach page image if available
        page_img_idx = page_range[0]
        img_bytes_l1: bytes | None = None
        if page_images and 0 <= page_img_idx < len(page_images):
            try:
                img_bytes_l1 = page_images[page_img_idx]
            except Exception:
                pass

        try:
            raw_content = llm_vision_call(
                prompt=prompt,
                image_bytes=img_bytes_l1,
                task="question_generation",
                max_tokens=_tok("question_generation")[0],
                temperature=_tok("question_generation")[1],
                schema=QUESTION_LIST_SCHEMA,
            )
            if raw_content:
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

    # ── D3/D4 post-validation: drop stub/echoed intents; normalise questionType ──
    _validated: list[dict[str, Any]] = []
    _stub_dropped = 0
    for _q in raw_questions:
        if is_stub_question(_q.get("intent", "")):
            _stub_dropped += 1
            continue
        _q["questionType"] = normalise_question_type(_q.get("questionType"))
        _validated.append(_q)
    if _stub_dropped:
        logger.info("[pass3] L1: Dropped %d stub/echoed question(s) (D3)", _stub_dropped)
    raw_questions = _validated

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

        try:
            raw_content = llm_text_call(
                prompt=prompt,
                task="entity_binding",
                max_tokens=_tok("entity_binding")[0],
                temperature=_tok("entity_binding")[1],
                schema=ENTITY_BINDING_SCHEMA,
            )
            if raw_content:
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

    # ── D5/Q15: route unassigned questions to nearest topic; NEVER drop ──
    _general_topic: dict[str, Any] | None = None
    for q in enriched_questions:
        q_id = q.get("questionId", "")
        if q_id in question_to_topic:
            continue
        target = route_unassigned(q, topics)
        _dest = next((t for t in topics if t.get("topicId") == target), None)
        if _dest is None:
            if _general_topic is None:
                _general_topic = {
                    "topicId": "topic_general",
                    "title": "General",
                    "description": "Questions not matched to a specific chapter.",
                    "questionIds": [],
                    "pageRange": [0, 0],
                }
                topics.append(_general_topic)
            _dest = _general_topic
        _dest["questionIds"].append(q_id)
        question_to_topic[q_id] = _dest["topicId"]
    if _general_topic is not None:
        logger.info("[pass3] D5: routed %d unassigned question(s) (General topic created)",
                    len(_general_topic["questionIds"]))

    # ── Q12: guarantee ≥1 question per topic that has a measure (archetype fallback) ──
    _arch_added = 0
    _qid_seq = len(enriched_questions)
    for t in topics:
        if t.get("questionIds"):
            continue
        pr = t.get("pageRange", [0, 0])
        topic_ents = [
            {
                "name": e["name"],
                "entityId": e.get("entityId") or e["name"],
                "entityType": e.get("entityType_hint", "dimension"),
            }
            for e in all_entities
            if any(pr[0] <= p <= pr[1] for p in e.get("pages", []))
        ]
        for aq in archetype_questions(t.get("title", ""), topic_ents):
            _qid_seq += 1
            qid = f"arch_q{_qid_seq}"
            aq["questionId"] = qid
            aq.setdefault("answerStructure", {})
            aq.setdefault("inferenceConfidence", 0.4)
            enriched_questions.append(aq)
            t["questionIds"].append(qid)
            question_to_topic[qid] = t["topicId"]
            _arch_added += 1
    if _arch_added:
        logger.info("[pass3] Q12: added %d archetype question(s) for empty topics", _arch_added)

    # ── D8/Q13: attach a deterministic analyticsSpec to every question ──
    for q in enriched_questions:
        if not q.get("analyticsSpec"):
            q["analyticsSpec"] = build_analytics_spec(
                q.get("questionType", "comparison"), q.get("requiredEntities") or [])

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


def _extract_facts_programmatic(page_texts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract numeric facts from page texts using regex patterns.

    Targets PLFS-style facts: LFPR X.X%, WPR X.X%, etc.
    Returns fact dicts compatible with factGraph schema.
    """
    import re as _re_facts
    facts: list[dict[str, Any]] = []
    seen_values: set[str] = set()

    _FACT_PATS = [
        # "LFPR ... X.X% in 2025"
        (r"(?P<entity>LFPR|WPR|Unemployment Rate|UR)\b.*?(?P<value>\d+\.\d)\s*%.*?(?:in\s+)?(?P<year>20\d\d)",
         "rate_fact"),
        # "Labour Force Participation Rate ... X.X%"
        (r"Labour Force Participation Rate.*?(?P<value>\d+\.\d)\s*%",
         "lfpr_fact"),
        # "Worker Population Ratio ... X.X%"
        (r"Worker Population Ratio.*?(?P<value>\d+\.\d)\s*%",
         "wpr_fact"),
        # "rural male ... X.X%"
        (r"rural\s+male.*?(?P<value>\d+\.\d)\s*%",
         "rural_male_fact"),
        # "rural female ... X.X%"
        (r"rural\s+female.*?(?P<value>\d+\.\d)\s*%",
         "rural_female_fact"),
        # "urban ... X.X%"
        (r"urban.*?(?P<value>\d+\.\d)\s*%.*?(?:in\s+)?(?P<year>20\d\d)",
         "urban_fact"),
    ]

    fact_id = 1
    for page_idx, pt in enumerate(page_texts):
        raw = (pt.get("raw_text") or "").replace("\n", " ")
        if not raw:
            continue
        for pat, fact_type in _FACT_PATS:
            for m in _re_facts.finditer(pat, raw, _re_facts.I):
                try:
                    value = float(m.group("value"))
                    year = int(m.group("year")) if "year" in m.groupdict() and m.group("year") else None
                    val_key = f"{fact_type}_{value}_{year}"
                    if val_key in seen_values:
                        continue
                    seen_values.add(val_key)

                    # Build statement from context (30 chars before + match + 30 chars after)
                    start = max(0, m.start() - 30)
                    end = min(len(raw), m.end() + 30)
                    statement = raw[start:end].strip()

                    facts.append({
                        "factId": f"pf_{fact_id:03d}",
                        "statement": statement[:200],
                        "entityRef": m.group("entity") if "entity" in m.groupdict() and m.group("entity") else fact_type,
                        "numericValue": value,
                        "unit": "%",
                        "year": year,
                        "sourcePageIndex": page_idx,
                        "extractionMethod": "programmatic",
                    })
                    fact_id += 1
                except (IndexError, ValueError, AttributeError):
                    continue
        if len(facts) >= 20:  # cap at 20 programmatic facts
            break

    return facts


_PLACEHOLDER_COL_RE = re.compile(
    r"^(?:unnamed(?:[_\s:]?\d+)?|(?:col|column|field|c)[_\s]?\d+)$",
    re.IGNORECASE,
)


def _is_placeholder_colname(name: str) -> bool:
    """True for generic positional column names (col_0, column_3, unnamed, field 2…).

    Such names appear when header detection fails on borderless/garbled tables; they
    must never become question entity references.
    """
    s = (name or "").strip()
    if not s:
        return True
    return bool(_PLACEHOLDER_COL_RE.match(s))


def _is_clean_qlabel(name: str) -> bool:
    """True if a column label is safe to use as a question entity reference.

    Rejects placeholders (col_0…) and anything failing entity hygiene (D1) — too long
    (>80 chars / blobs), numeric-only, noise, etc. Keeps real short labels like
    "States/ UTs" or "Coal Reserves".
    """
    return bool(name) and not _is_placeholder_colname(name) and _is_valid_entity_name(name)


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
        # Only build questions from clean, short, real column labels. This drops both
        # generic placeholders (col_0, column_3…) and garbled blobs (whole-page text or
        # multi-line table titles >80 chars) that pdfplumber sometimes yields offline,
        # so questions never embed "How does col_1 vary by col_0" or paragraph blobs.
        dims = [d for d in (ts.get("dimensions") or []) if _is_clean_qlabel(d)]
        measures = [m for m in (ts.get("measures") or []) if _is_clean_qlabel(m)]
        breakdowns = [
            b for b in (ts.get("breakdowns") or [])
            if _is_clean_qlabel(b.get("measure", ""))
        ]
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

    # ── D4/D8: normalise questionType + attach analyticsSpec to every question ──
    from report_builder.question_quality import (
        build_analytics_spec as _bas_pf,
        normalise_question_type as _normqt_pf,
    )
    for _q in questions:
        _q["questionType"] = _normqt_pf(_q.get("questionType"))
        if not _q.get("analyticsSpec"):
            _q["analyticsSpec"] = _bas_pf(_q["questionType"], _q.get("requiredEntities") or [])

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
    doc_type: str = "statistical_annual_report",
) -> dict[str, Any]:
    """Assemble Enterprise AST + embedded blueprint subtree (gold-standard shape).

    Produces two cross-referenced structures:
        template.ast.json  — VALUE-FREE render skeleton (slots empty)
        template.blueprint.json — VALUE-FREE analytic brain (entities, questions, analytics)

    Both are embedded in the returned dict for unified pipeline output,
    and also saved as separate files by the orchestrator.
    """
    logger.info("[pass4] ▶ Assembling Gold-Standard Enterprise AST + Blueprint")

    chapters = document_map.get("chapters") or []
    all_entities = document_map.get("all_entities") or []
    table_structures = document_map.get("table_structures") or []
    questions = ast_result.get("questions") or []
    topics_raw = ast_result.get("topics") or []
    page_count = len(page_texts)
    doc_id = f"doc_{source_hash[:8]}" if source_hash else "doc_001"
    template_id = f"tpl_{re.sub(r'[^a-z0-9]', '_', doc_title.lower())[:30]}_v1"

    # ════════════════════════════════════════════════════════════════════════════
    # ENTITY RESOLUTION — build stable entityId mapping for cross-referencing
    # ════════════════════════════════════════════════════════════════════════════
    entity_map: dict[str, dict[str, Any]] = {}  # entityId → entity dict
    entity_name_map: dict[str, str] = {}  # lowered name → entityId
    for ent in all_entities:
        eid = ent.get("entityId", f"ent_{len(entity_map)+1:03d}")
        entity_map[eid] = ent
        entity_name_map[ent.get("name", "").lower().strip()] = eid
        for alias in (ent.get("aliases") or []):
            entity_name_map[alias.lower().strip()] = eid

    def _resolve_eid(name: str) -> str:
        """Resolve entity name to entityId via fuzzy matching."""
        if not name:
            return ""
        key = name.lower().strip().rstrip(":")
        if key in entity_name_map:
            return entity_name_map[key]
        # Try with common suffixes/prefixes stripped
        key_no_paren = key.split("(")[0].strip()
        if key_no_paren and key_no_paren in entity_name_map:
            return entity_name_map[key_no_paren]
        # Acronym extraction: "SEEA-Energy" → try "seea", "seea energy"
        key_normalized = key.replace("-", " ").replace("_", " ")
        if key_normalized in entity_name_map:
            return entity_name_map[key_normalized]
        # Substring match (both directions)
        for k, v in entity_name_map.items():
            if key in k or k in key:
                return v
            # Acronym in canonical name's alias list
            if key_normalized in k or k in key_normalized:
                return v
        # Abbreviated match: "types of fossil" → match entity containing "fossil"
        key_words = set(key_normalized.split())
        key_words -= {"of", "the", "in", "for", "and", "by", "to", "a", "an", "types", "class"}
        if key_words:
            for k, v in entity_name_map.items():
                k_words = set(k.split())
                if key_words & k_words:  # any overlap
                    return v
        # Last resort: return empty string instead of ent_unresolved (cleaner in UI)
        return ""

    # ════════════════════════════════════════════════════════════════════════════
    # styleAST — 4 standard MoSPI styles
    # ════════════════════════════════════════════════════════════════════════════
    style_ast = {
        "styles": [
            {"styleId": "s_h1", "role": "heading1", "font": "Noto Sans", "sizePt": 18, "bold": True, "color": "#0B5394"},
            {"styleId": "s_h2", "role": "heading2", "font": "Noto Sans", "sizePt": 14, "bold": True, "color": "#1155CC"},
            {"styleId": "s_body", "role": "body", "font": "Noto Sans", "sizePt": 11, "bold": False, "color": "#222222"},
            {"styleId": "s_table", "role": "tableCell", "font": "Noto Sans", "sizePt": 9, "align": "right"},
            {"styleId": "s_caption", "role": "caption", "font": "Noto Sans", "sizePt": 9, "italic": True, "color": "#555555"},
        ]
    }

    # ════════════════════════════════════════════════════════════════════════════
    # TOPIC → QUESTION mapping (for cross-referencing)
    # ════════════════════════════════════════════════════════════════════════════
    topic_question_map: dict[str, list[dict]] = {}  # topicId → [question dicts]
    for topic_raw in topics_raw:
        tid = topic_raw.get("topicId", f"topic_{len(topic_question_map)+1:02d}")
        tqs = []
        for q in questions:
            if q.get("questionId", "") in (topic_raw.get("questionIds") or []):
                tqs.append(q)
        topic_question_map[tid] = tqs

    # ════════════════════════════════════════════════════════════════════════════
    # tableAST — gold-standard structured columns with entityRef, role, format
    # ════════════════════════════════════════════════════════════════════════════
    tables_ast = []
    table_templates = []
    for ts in table_structures:
        t_id = ts["tableId"].replace("tbl_", "table_")
        tt_id = t_id.replace("table_", "tt_")

        # Build structured columns
        columns = []
        column_groups = []
        dimensions_list = ts.get("dimensions") if isinstance(ts.get("dimensions"), list) else []
        measures_list = ts.get("measures") if isinstance(ts.get("measures"), list) else []
        breakdowns = ts.get("breakdowns") if isinstance(ts.get("breakdowns"), list) else []

        # ── Gold-standard enhancement: cross-reference table columns with classified entities ──
        # If measures_list is empty but columns match known measure entities, reclassify
        if not measures_list and dimensions_list:
            _entity_measures = {e.get("name", "").lower() for e in all_entities if e.get("entityType_hint") == "measure"}
            _entity_dimensions = {e.get("name", "").lower() for e in all_entities if e.get("entityType_hint") == "dimension"}
            _new_dims = []
            _new_meas = []
            for col in dimensions_list:
                col_low = col.lower().strip()
                if col_low in _entity_measures or any(m in col_low for m in _entity_measures if len(m) > 3):
                    _new_meas.append(col)
                elif col_low in _entity_dimensions or any(d in col_low for d in _entity_dimensions if len(d) > 3):
                    _new_dims.append(col)
                else:
                    # Heuristic: if column name contains numeric keywords, it's likely a measure
                    _num_kw = ("total", "amount", "value", "rate", "ratio", "percentage", "number", "count",
                               "production", "capacity", "reserves", "potential", "estimate", "generation")
                    if any(k in col_low for k in _num_kw):
                        _new_meas.append(col)
                    else:
                        _new_dims.append(col)
            if _new_meas:
                dimensions_list = _new_dims
                measures_list = _new_meas

        # Build column groups from breakdowns
        for bd in breakdowns:
            for val in (bd.get("values") or []):
                grp_id = f"grp_{re.sub(r'[^a-z0-9]', '_', val.lower())[:15]}"
                column_groups.append({
                    "groupId": grp_id,
                    "label": val,
                    "spanRefs": [],
                })

        col_idx = 0
        for dim in dimensions_list:
            col_id = f"col_{re.sub(r'[^a-z0-9]', '_', dim.lower())[:20]}"
            ent_ref = _resolve_eid(dim)
            columns.append({
                "columnId": col_id,
                "header": dim,
                "role": "dimension",
                "entityRef": ent_ref,
                "dtype": "string",
                "align": "left",
                "format": None,
            })
            col_idx += 1

        for meas in measures_list:
            col_id = f"col_{re.sub(r'[^a-z0-9]', '_', meas.lower())[:20]}"
            ent_ref = _resolve_eid(meas)
            # Check if this measure has breakdown variants
            meas_lower = meas.lower()
            parent_bd = next((bd for bd in breakdowns if bd.get("measure", "").lower() in meas_lower), None)
            group_ref = None
            filter_context = {}
            if parent_bd:
                # Find matching group
                for val in (parent_bd.get("values") or []):
                    if val.lower() in meas_lower:
                        grp_id = f"grp_{re.sub(r'[^a-z0-9]', '_', val.lower())[:15]}"
                        group_ref = grp_id
                        # Find the breakdown dimension entity
                        bd_ent = _resolve_eid(parent_bd.get("measure", meas))
                        filter_context = {bd_ent: val}
                        # Add to group spanRefs
                        for grp in column_groups:
                            if grp["groupId"] == grp_id:
                                grp["spanRefs"].append(col_id)
                        break

            col_entry: dict[str, Any] = {
                "columnId": col_id,
                "header": meas,
                "role": "measure",
                "entityRef": ent_ref,
                "dtype": "number",
                "unit": "percent" if "%" in meas or "rate" in meas_lower or "ratio" in meas_lower else None,
                "format": "percent.1" if "%" in meas or "rate" in meas_lower or "ratio" in meas_lower else "number",
                "align": "right",
            }
            if group_ref:
                col_entry["group"] = group_ref
            if filter_context:
                col_entry["filterContext"] = filter_context
            columns.append(col_entry)
            col_idx += 1

        # If no structured dims/measures, fall back to raw columns
        if not columns:
            for ci, col_name in enumerate(ts.get("columns") or []):
                col_id = f"col_{ci+1}"
                columns.append({
                    "columnId": col_id,
                    "header": col_name,
                    "role": "dimension" if ci == 0 else "measure",
                    "entityRef": _resolve_eid(col_name),
                    "dtype": "string" if ci == 0 else "number",
                    "align": "left" if ci == 0 else "right",
                    "format": None,
                })

        # Find the question that references this table
        bi_query = ""
        for q in questions:
            for re_ent in (q.get("requiredEntities") or []):
                ref_name = re_ent.get("entityRef", "")
                if ref_name.lower() in [d.lower() for d in dimensions_list + measures_list]:
                    bi_query = q.get("questionId", "")
                    break
            if bi_query:
                break

        table_title = (ts.get("tableTitle") or ts.get("description") or "").strip()
        # Use VLM table_title if available and current is generic
        if entity_pages and ts["page"] < len(entity_pages):
            vlm_title = (entity_pages[ts["page"]].get("table_title") or "").strip()
            if vlm_title:
                table_title = vlm_title
        # If still empty, build from column analysis
        if not table_title or table_title.startswith("Table with"):
            dims = ts.get("dimensions") or []
            meas = ts.get("measures") or []
            if meas and dims:
                table_title = f"{meas[0]} by {dims[0]}" + (f" ({len(ts.get('columns',[]))} cols, p.{ts['page']+1})" if len(dims) > 1 else "")
            elif ts.get("columns"):
                cols = ts["columns"]
                col_sample = ", ".join(str(c) for c in cols[:3])
                table_title = f"Table p.{ts['page']+1}: {col_sample}{'...' if len(cols)>3 else ''} ({len(cols)} cols, {ts.get('row_count',0)} rows)"
            else:
                table_title = f"Table on page {ts['page'] + 1}"

        tables_ast.append({
            "tableId": t_id,
            "templateRef": tt_id,
            "biQuery": bi_query,
            "title": table_title,
            "columnGroups": column_groups,
            "columns": columns,
            "rows": [],
            "footnotes": [
                {"noteId": f"fn_{t_id}_src", "text": "", "textTemplate": "Source: {{dataset.title}}, {{period.current}}."},
            ],
            "slot": {"fillFrom": bi_query, "status": "empty"},
        })

        # Build table template for blueprint
        table_templates.append({
            "tableTemplateId": tt_id,
            "title": table_title,
            "columnGroups": column_groups,
            "columns": columns,
            "dimensions": [c["columnId"] for c in columns if c.get("role") == "dimension"],
            "measures": [c["columnId"] for c in columns if c.get("role") == "measure"],
            "breakdowns": [_resolve_eid(bd.get("measure", "")) for bd in breakdowns],
            "footnotes": [
                {"noteId": f"fn_{tt_id}_src", "marker": "Source", "textTemplate": "Source: {{dataset.title}}, {{period.current}}."},
            ],
            "sort": {"by": columns[1]["columnId"] if len(columns) > 1 else "col_1", "order": "desc"},
            "emptyPolicy": "show_dash",
        })

    # ════════════════════════════════════════════════════════════════════════════
    # chartAST — axis wiring, paletteRef, slot, series:[]
    # ════════════════════════════════════════════════════════════════════════════
    charts_ast = []
    _seen_chart_pages: set[int] = set()

    # Generate charts from questions that have chart components
    chart_seq = 0
    for q in questions:
        ans = q.get("answerStructure") or {}
        for comp in (ans.get("components") or []):
            comp_type = comp.get("type", "")
            if "chart" in comp_type or "bar" in comp_type or "line" in comp_type or "pie" in comp_type:
                chart_seq += 1
                q_id = q.get("questionId", f"q_{chart_seq}")
                chart_id = f"chart_{q_id}"

                # Determine chart type from component type
                if "bar" in comp_type:
                    chart_type = "grouped_bar"
                elif "line" in comp_type:
                    chart_type = "line"
                elif "pie" in comp_type:
                    chart_type = "pie"
                else:
                    chart_type = "grouped_bar"

                # Resolve axes from requiredEntities
                req_ents = q.get("requiredEntities") or []
                x_entity = ""
                y_entity = ""
                for re_ent in req_ents:
                    role = re_ent.get("role", "")
                    eid = re_ent.get("entityId") or _resolve_eid(re_ent.get("entityRef", ""))
                    if role in ("groupBy", "grouping", "dimension"):
                        x_entity = eid
                    elif role == "measure":
                        y_entity = eid

                # Get labels from entity names
                x_label = entity_map.get(x_entity, {}).get("name", "Category")
                y_label = entity_map.get(y_entity, {}).get("name", "Value")
                y_unit = entity_map.get(y_entity, {}).get("unit", "")

                # Build a better title: use question text if y/x labels are generic
                _chart_title = f"{y_label} by {x_label}"
                if y_label == "Value" or x_label == "Category":
                    # Fall back to question text for a meaningful title
                    _q_text = q.get("questionText", "")
                    if _q_text and len(_q_text) < 60:
                        _chart_title = _q_text.rstrip("?.").strip()
                    elif y_label != "Value":
                        _chart_title = y_label

                charts_ast.append({
                    "chartId": chart_id,
                    "biQuery": q_id,
                    "chartType": chart_type,
                    "title": _chart_title,
                    "xAxis": {"entityRef": x_entity, "label": x_label},
                    "yAxis": {"entityRef": y_entity, "label": f"{y_label} ({y_unit})" if y_unit else y_label, "unit": y_unit or None},
                    "paletteRef": "pal_mospi_default",
                    "series": [],
                    "slot": {"fillFrom": f"{q_id}_c{comp.get('renderOrder', chart_seq)}", "status": "empty"},
                })

    # Also add VLM-detected charts that aren't already covered
    if entity_pages:
        for ep in (entity_pages or []):
            pg_idx = ep.get("page_index", 0)
            chart_types = ep.get("chart_types") or []
            if chart_types and pg_idx not in _seen_chart_pages:
                for ci, ct in enumerate(chart_types):
                    ct_str = str(ct).strip().lower()
                    if not ct_str:
                        continue
                    chart_seq += 1
                    charts_ast.append({
                        "chartId": f"chart_vlm_{pg_idx+1}_{ci+1}",
                        "biQuery": "",
                        "chartType": ct_str,
                        "title": (ep.get("chart_titles") or [""])[ci] if ci < len(ep.get("chart_titles") or []) else f"Chart p.{pg_idx+1}",
                        "xAxis": {"entityRef": "", "label": ""},
                        "yAxis": {"entityRef": "", "label": "", "unit": None},
                        "paletteRef": "pal_mospi_default",
                        "series": [],
                        "slot": {"status": "empty"},
                    })
                _seen_chart_pages.add(pg_idx)

    # ════════════════════════════════════════════════════════════════════════════
    # figureAST — chartRef, captionTemplate, templateRef, slot
    # ════════════════════════════════════════════════════════════════════════════
    figures_ast = []
    figure_templates = []
    for fig_idx, chart in enumerate(charts_ast):
        fig_id = chart["chartId"].replace("chart_", "fig_")
        ft_id = chart["chartId"].replace("chart_", "ft_")
        caption_tpl = f"{chart.get('title', 'Figure')}, {{{{period.current}}}}"

        figures_ast.append({
            "figureId": fig_id,
            "templateRef": ft_id,
            "type": "chart",
            "title": chart.get("title", ""),
            "caption": caption_tpl,
            "captionTemplate": caption_tpl,
            "chartRef": chart["chartId"],
            "chartType": chart.get("chartType", "bar"),
            "page": chart.get("page"),
            "styleRef": "s_caption",
            "slot": {"status": "empty"},
        })

        figure_templates.append({
            "figureTemplateId": ft_id,
            "captionTemplate": caption_tpl,
            "chartId": chart["chartId"],
            "numbering": f"Figure {{{{topic.order}}}}.{fig_idx+1}",
        })

    # ════════════════════════════════════════════════════════════════════════════
    # contentAST — blocks with biQuery, templateQuestion, slot wiring
    # ════════════════════════════════════════════════════════════════════════════
    content_blocks = []
    for q in questions:
        ans = q.get("answerStructure") or {}
        q_id = q.get("questionId", "")
        for comp in (ans.get("components") or []):
            comp_type = comp.get("type", "")
            if "narrative" in comp_type or "paragraph" in comp_type:
                block_id = f"p_{q_id}"
                comp_order = comp.get("renderOrder", 1)
                content_blocks.append({
                    "blockId": block_id,
                    "kind": "paragraph",
                    "styleRef": "s_body",
                    "content": "",
                    "biQuery": q_id,
                    "templateQuestion": q.get("intent", ""),
                    "slot": {"fillFrom": f"{q_id}_c{comp_order}", "status": "empty"},
                })
                break  # One narrative block per question

    # ════════════════════════════════════════════════════════════════════════════
    # semanticAST — sections[] with topicRef, children linking to content/fig/table
    # ════════════════════════════════════════════════════════════════════════════
    semantic_sections = []
    for t_idx, topic_raw in enumerate(topics_raw):
        tid = topic_raw.get("topicId", f"topic_{t_idx+1:02d}")
        sec_id = tid.replace("topic_", "sec_")
        topic_title = topic_raw.get("title", f"Section {t_idx+1}")

        # Collect children IDs (content blocks, figures, tables) for this topic
        children_ids = []
        topic_qs = topic_question_map.get(tid, [])
        for q in topic_qs:
            q_id = q.get("questionId", "")
            # Narrative block
            children_ids.append(f"p_{q_id}")
            # Figures (charts linked to this question)
            for chart in charts_ast:
                if chart.get("biQuery") == q_id:
                    fig_id = chart["chartId"].replace("chart_", "fig_")
                    children_ids.append(fig_id)
            # Tables linked to this question
            for tbl in tables_ast:
                if tbl.get("biQuery") == q_id:
                    children_ids.append(tbl["tableId"])

        semantic_sections.append({
            "sectionId": sec_id,
            "title": topic_title,
            "level": 1,
            "order": t_idx + 1,
            "styleRef": "s_h1",
            "topicRef": tid,
            "children": children_ids,
        })

    # ════════════════════════════════════════════════════════════════════════════
    # layoutAST + geometryAST
    # ════════════════════════════════════════════════════════════════════════════
    layout_pages_ast = []
    geometry_flow = []
    for sec in semantic_sections:
        page_id = f"pg_{sec['order']}"
        regions = []
        for child_id in sec.get("children", []):
            if child_id.startswith("p_"):
                role = "body"
            elif child_id.startswith("fig_"):
                role = "figure"
            elif child_id.startswith("table_"):
                role = "table"
            else:
                role = "content"
            rg_id = f"rg_{child_id}"
            regions.append({"regionId": rg_id, "role": role, "bindsTo": child_id, "bbox": None})
            geometry_flow.append(rg_id)

        # Add heading region
        rg_title = f"rg_{sec['sectionId']}_title"
        regions.insert(0, {"regionId": rg_title, "role": "heading", "bindsTo": sec["sectionId"], "bbox": None})
        geometry_flow.insert(len(geometry_flow) - len(regions) + 1, rg_title)

        layout_pages_ast.append({
            "pageId": page_id,
            "size": "A4",
            "regions": regions,
        })

    # ════════════════════════════════════════════════════════════════════════════
    # BLUEPRINT — the analytic brain
    # ════════════════════════════════════════════════════════════════════════════

    def _compute_entity_confidence(ent: dict) -> float:
        """Differentiated confidence based on source and page coverage."""
        source = ent.get("source", "vlm")
        pages = ent.get("pages") or []
        page_count_e = len(pages) if isinstance(pages, list) else 1
        if source == "table_header":
            return 0.85
        if source == "pre_seeded":
            return 0.65
        if page_count_e >= 5:
            return 0.80
        if page_count_e >= 3:
            return 0.70
        if page_count_e >= 2:
            return 0.60
        return 0.45  # single-mention VLM entity

    # Build blueprint entities with full gold-standard fields
    # ── Entity deduplication: merge entities whose names are aliases of another ──
    _dedup_names: dict[str, int] = {}  # lowercase name -> index in all_entities
    _to_remove: set[int] = set()
    for idx, ent in enumerate(all_entities):
        name_low = (ent.get("name") or "").strip().lower().rstrip(":")
        aliases_low = {a.lower() for a in (ent.get("aliases") or [])}
        # Check if this entity's name is an alias of an existing one
        if name_low in _dedup_names:
            # Merge: keep the first, absorb this one's pages
            first_idx = _dedup_names[name_low]
            first_pages = set(all_entities[first_idx].get("pages") or [])
            first_pages.update(ent.get("pages") or [])
            all_entities[first_idx]["pages"] = sorted(first_pages)
            _to_remove.add(idx)
            continue
        # Check if any existing entity has this name as an alias
        for prev_name, prev_idx in _dedup_names.items():
            prev_aliases = {a.lower() for a in (all_entities[prev_idx].get("aliases") or [])}
            if name_low in prev_aliases or prev_name in aliases_low:
                first_pages = set(all_entities[prev_idx].get("pages") or [])
                first_pages.update(ent.get("pages") or [])
                all_entities[prev_idx]["pages"] = sorted(first_pages)
                _to_remove.add(idx)
                break
        else:
            _dedup_names[name_low] = idx
            # Also register aliases
            for a in aliases_low:
                if a and a not in _dedup_names:
                    _dedup_names[a] = idx

    if _to_remove:
        all_entities = [e for i, e in enumerate(all_entities) if i not in _to_remove]
        logger.info("[pass4] Deduplicated %d entities (merged into existing)", len(_to_remove))

    blueprint_entities = []
    for ent in all_entities:
        eid = ent.get("entityId", "")
        # Clean trailing colon/space from entity names
        _ent_name = (ent.get("canonicalName") or ent.get("name", "")).rstrip(": ")
        ent["name"] = _ent_name
        ent["canonicalName"] = _ent_name
        e_type = ent.get("entityType_hint") or ent.get("entityType") or "dimension"
        # Infer from table structures
        if e_type == "dimension":
            for ts in table_structures:
                if ent.get("name", "") in (ts.get("measures") or []):
                    e_type = "measure"
                    break

        # Build valueDomain
        value_domain: dict[str, Any] | None = None
        if ent.get("valueDomain"):
            value_domain = ent["valueDomain"]
        elif e_type == "measure":
            name_lower = ent.get("name", "").lower()
            if "rate" in name_lower or "ratio" in name_lower or "%" in name_lower:
                value_domain = {"kind": "ratio", "min": 0, "max": 100}
        elif e_type == "dimension":
            aliases = ent.get("aliases") or []
            if aliases:
                value_domain = {"kind": "categorical", "members": aliases[:10], "allowOther": True}

        blueprint_entities.append({
            "entityId": eid,
            "canonicalName": ent.get("canonicalName") or ent.get("name", ""),
            "entityType": e_type,
            "aliases": ent.get("aliases") or [],
            "unit": ent.get("unit") or ("percent" if e_type == "measure" and ("rate" in ent.get("name", "").lower() or "ratio" in ent.get("name", "").lower()) else None),
            "format": ent.get("defaultFormat") or ("percent.1" if e_type == "measure" and ("rate" in ent.get("name", "").lower() or "ratio" in ent.get("name", "").lower()) else None),
            "valueDomain": value_domain,
            "aggregation": "weighted_ratio" if e_type == "measure" and ("rate" in ent.get("name", "").lower() or "ratio" in ent.get("name", "").lower()) else None,
            "glossaryRef": ent.get("glossaryRef"),
            "scope": "indicator" if e_type == "measure" else ("classifier" if e_type == "dimension" else "filter" if e_type == "filter" else "time"),
            "cardinalityHint": "high" if "state" in ent.get("name", "").lower() else "low",
            "confidence": ent.get("confidence") or _compute_entity_confidence(ent),
        })

    # Build blueprint topics with full question structure
    blueprint_topics = []
    for t_idx, topic_raw in enumerate(topics_raw):
        tid = topic_raw.get("topicId", f"topic_{t_idx+1:02d}")
        sec_id = tid.replace("topic_", "sec_")
        topic_title = topic_raw.get("title", "")
        topic_qs = topic_question_map.get(tid, [])

        bp_questions = []
        for q_idx, q in enumerate(topic_qs):
            q_id = q.get("questionId", "")
            q_type = q.get("questionType", "comparison")

            # Build requiredEntities with gold-standard fields
            req_entities = []
            for re_ent in (q.get("requiredEntities") or []):
                eid = re_ent.get("entityId") or _resolve_eid(re_ent.get("entityRef", ""))
                role = re_ent.get("role", "measure")
                req_entities.append({
                    "entityId": eid,
                    "role": role,
                    "required": role in ("measure", "groupBy", "grouping", "time"),
                    **({"defaultMember": re_ent.get("defaultMember")} if re_ent.get("defaultMember") else {}),
                    **({"periodRole": "current"} if role == "time" else {}),
                })

            # Build analyticsSpec (gold-standard shape)
            raw_spec = q.get("analyticsSpec") or {}
            if not isinstance(raw_spec, dict):
                raw_spec = {}
            measure_ent = next((r for r in req_entities if r["role"] == "measure"), None)
            groupby_ent = next((r for r in req_entities if r["role"] in ("groupBy", "grouping")), None)
            filter_ents = [r for r in req_entities if r["role"] == "filter"]

            # Safely extract agg from raw_spec.measure (may be a string or dict or None)
            _raw_measure = raw_spec.get("measure")
            _agg = _raw_measure.get("agg") if isinstance(_raw_measure, dict) else None

            analytics_spec = {
                "operation": raw_spec.get("operation") or ("rank" if q_type == "ranking" else "time_series" if q_type == "trend" else "group_aggregate"),
                "measure": {
                    "entityRef": measure_ent["entityId"] if measure_ent else "",
                    "agg": _agg or "weighted_ratio",
                },
                "groupBy": [{"entityRef": groupby_ent["entityId"]}] if groupby_ent else [],
                "filters": [{"entityRef": f["entityId"], "op": "eq", "valueFrom": f.get("defaultMember") or "defaultMember"} for f in filter_ents],
                "sort": raw_spec.get("sort") or {"by": "measure", "order": "desc"},
                "topN": raw_spec.get("topN") or (10 if q_type == "ranking" else None),
                "compare": raw_spec.get("compare") or {"kind": "across_group" if q_type == "comparison" else "none", "baseline": None},
            }

            # Build answerStructure with gold-standard components
            ans = q.get("answerStructure") or {}
            components = []
            for c_idx, comp in enumerate(ans.get("components") or []):
                comp_type = comp.get("type", "narrative_paragraph")
                comp_id = f"{q_id}_c{c_idx+1}"
                order = comp.get("renderOrder", c_idx + 1)

                # Determine kind and outputContract
                if "narrative" in comp_type or "paragraph" in comp_type:
                    kind = "narrative"
                    output_contract = {"type": "prose", "minWords": 40, "maxWords": 90}
                    refs = {"contentRef": f"p_{q_id}", "analyticsRef": "", "evidenceRef": ""}
                    narrative_tpl = {
                        "tone": "formal-analytical",
                        "mustMention": [r["entityId"] for r in req_entities[:2]],
                        "pattern": "headline_then_gap",
                        "maxWords": 90,
                    }
                    comp_entry: dict[str, Any] = {
                        "componentId": comp_id,
                        "kind": kind,
                        "order": order,
                        "outputContract": output_contract,
                        "narrativeTemplate": narrative_tpl,
                        "refs": refs,
                    }
                elif "table" in comp_type:
                    kind = "table"
                    # Find matching table template
                    tt_ref = ""
                    tbl_ref = ""
                    for tbl in tables_ast:
                        if tbl.get("biQuery") == q_id:
                            tt_ref = tbl.get("templateRef", "")
                            tbl_ref = tbl["tableId"]
                            break
                    output_contract = {"type": "table", "tableTemplateRef": tt_ref}
                    refs = {"tableRef": tbl_ref, "analyticsRef": "", "evidenceRef": ""}
                    comp_entry = {
                        "componentId": comp_id,
                        "kind": kind,
                        "order": order,
                        "outputContract": output_contract,
                        "refs": refs,
                    }
                elif "chart" in comp_type or "bar" in comp_type or "line" in comp_type or "pie" in comp_type:
                    kind = "chart"
                    # Determine chart type
                    if "bar" in comp_type:
                        ct = "grouped_bar"
                    elif "line" in comp_type:
                        ct = "line"
                    elif "pie" in comp_type:
                        ct = "pie"
                    else:
                        ct = "grouped_bar"
                    # Find matching chart/figure
                    chart_ref = ""
                    fig_ref = ""
                    for chart in charts_ast:
                        if chart.get("biQuery") == q_id:
                            chart_ref = chart["chartId"]
                            fig_ref = chart["chartId"].replace("chart_", "fig_")
                            break
                    output_contract = {
                        "type": "chart",
                        "chartType": ct,
                        "xAxis": groupby_ent["entityId"] if groupby_ent else "",
                        "yAxis": measure_ent["entityId"] if measure_ent else "",
                    }
                    refs = {"chartRef": chart_ref, "figureRef": fig_ref, "analyticsRef": "", "evidenceRef": ""}
                    comp_entry = {
                        "componentId": comp_id,
                        "kind": kind,
                        "order": order,
                        "outputContract": output_contract,
                        "refs": refs,
                    }
                else:
                    kind = "metric_card"
                    output_contract = {"type": "metric"}
                    refs = {"analyticsRef": "", "evidenceRef": ""}
                    comp_entry = {
                        "componentId": comp_id,
                        "kind": kind,
                        "order": order,
                        "outputContract": output_contract,
                        "refs": refs,
                    }
                components.append(comp_entry)

            # If no components from LLM, add default narrative
            if not components:
                components.append({
                    "componentId": f"{q_id}_c1",
                    "kind": "narrative",
                    "order": 1,
                    "outputContract": {"type": "prose", "minWords": 40, "maxWords": 90},
                    "narrativeTemplate": {"tone": "formal-analytical", "mustMention": [], "pattern": "headline_then_gap", "maxWords": 90},
                    "refs": {"contentRef": f"p_{q_id}", "analyticsRef": "", "evidenceRef": ""},
                })

            bp_questions.append({
                "questionId": q_id,
                "intent": q.get("intent", ""),
                "questionType": q_type,
                "priority": q_idx + 1,
                "requiredEntities": req_entities,
                "analyticsSpec": analytics_spec,
                "answerStructure": {"components": components},
            })

        if bp_questions:
            # ── Topic title improvement: derive meaningful title ──
            # If title is bare chapter marker ("CHAPTER 1"), use the dominant measure entity
            _improved_title = topic_title
            import re as _re_topic_title
            if _re_topic_title.match(r'^(?:CHAPTER|Chapter|PART|Part|Section)\s+\d+\s*$', topic_title.strip()):
                # Find the primary measure entity for this topic's questions
                _topic_measures = []
                for q in bp_questions:
                    for re_ent in q.get("requiredEntities", []):
                        if re_ent.get("role") == "measure" and re_ent.get("entityId"):
                            _m_name = entity_map.get(re_ent["entityId"], {}).get("name", "")
                            if _m_name:
                                _topic_measures.append(_m_name)
                if _topic_measures:
                    # Use most common measure as topic title
                    from collections import Counter as _Counter_tt
                    _improved_title = _Counter_tt(_topic_measures).most_common(1)[0][0]
                else:
                    # Fall back to first sub-heading in that chapter's page range
                    pass

            blueprint_topics.append({
                "topicId": tid,
                "title": _improved_title,
                "order": t_idx + 1,
                "semanticRef": sec_id,
                "questions": bp_questions,
            })

    # Glossary — domain-enriched with MoSPI/NSSO/PLFS statistical terminology
    # Seed with known official statistical definitions; augment with extracted entities
    _MOSPI_GLOSSARY_SEED: dict[str, str] = {
        "LFPR": "Labour Force Participation Rate - percentage of the population in the labour force (working or seeking work).",
        "WPR": "Worker Population Ratio - percentage of employed persons in the population of age 15 years and above.",
        "UR": "Unemployment Rate - percentage of the labour force that is unemployed.",
        "PLFS": "Periodic Labour Force Survey - annual household survey conducted by NSO for employment/unemployment indicators.",
        "NSO": "National Statistical Office - apex statistical body under MoSPI, Government of India.",
        "MoSPI": "Ministry of Statistics and Programme Implementation - responsible for official statistics in India.",
        "NSSO": "National Sample Survey Office - field survey arm of NSO, conducts large-scale sample surveys.",
        "CWS": "Current Weekly Status - activity status of a person during the reference week preceding the date of survey.",
        "usual_status": "Usual Status (ps+ss) - activity status over the 365 days preceding the survey (principal + subsidiary economic activity).",
        "UNFC": "United Nations Framework Classification for Fossil Energy and Mineral Reserves and Resources (2009) - international standard for resource classification.",
        "SEEA": "System of Environmental-Economic Accounting - UN statistical framework integrating economic and environmental data.",
        "GDP": "Gross Domestic Product - total value of goods and services produced within a country in a year.",
        "GVA": "Gross Value Added - measure of contribution to GDP by individual sectors.",
        "CPI": "Consumer Price Index - measure of average change in prices paid by consumers for a basket of goods and services.",
        "WPI": "Wholesale Price Index - measure of average change in prices at the wholesale level.",
        "NAS": "National Accounts Statistics - official annual compendium of macroeconomic indicators.",
        "ASI": "Annual Survey of Industries - census of registered manufacturing sector.",
        "EAC": "Economic Advisory Council - advisory body to the Prime Minister on economic matters.",
        "MW": "Megawatt - unit of power (1 MW = 1,000 kW), used for energy generation capacity.",
        "MT": "Million Tonnes - unit of weight used for commodity production/reserves statistics.",
        "BCM": "Billion Cubic Metres - unit used for natural gas reserves.",
        "MMT": "Million Metric Tonnes - variant of MT used in energy/mining statistics.",
        "MTOE": "Million Tonnes of Oil Equivalent - standardized energy measurement unit.",
    }

    glossary: dict[str, str] = {}
    # Add relevant seed terms based on document entities — strict matching only
    _ent_names_lower = {e["canonicalName"].lower() for e in blueprint_entities}
    _ent_aliases_lower = set()
    for e in blueprint_entities:
        for a in (e.get("aliases") or []):
            _ent_aliases_lower.add(a.lower())
    # Combine all entity text for word-boundary matching
    _all_ent_text = _ent_names_lower | _ent_aliases_lower

    for term, defn in _MOSPI_GLOSSARY_SEED.items():
        term_low = term.lower()
        # Strict: term must be an exact match in entity names/aliases (not substring)
        if term_low in _all_ent_text:
            glossary[term] = defn
        # Or the full expansion in the definition must match an entity name
        elif len(term_low) <= 5:
            # For short acronyms, check if any entity alias is this exact acronym
            if term_low in _ent_aliases_lower:
                glossary[term] = defn

    # Generate definitions for extracted measure entities not in seed
    for ent in blueprint_entities:
        if ent.get("entityType") == "measure" and ent.get("canonicalName"):
            name = ent["canonicalName"]
            aliases = ent.get("aliases") or []
            abbrev = aliases[0] if aliases and len(aliases[0]) <= 8 else ""
            glossary_key = abbrev or name

            if glossary_key not in glossary:
                unit_str = f" ({ent['unit']})" if ent.get("unit") else ""
                scope_str = "indicator" if ent.get("scope") == "indicator" else "measure"
                glossary[glossary_key] = f"{name}{unit_str} - statistical {scope_str} extracted from the source document."

    # Add dimension entities with categorical domains
    for ent in blueprint_entities:
        if ent.get("entityType") == "dimension" and ent.get("valueDomain"):
            vd = ent["valueDomain"]
            if isinstance(vd, dict) and vd.get("members") and isinstance(vd["members"], list):
                name = ent["canonicalName"]
                members = ", ".join(str(m) for m in vd["members"][:5])
                glossary[name] = f"{name} - classification dimension with categories: {members}."

    # Palette
    palette = {
        "paletteId": "pal_mospi_default",
        "sequential": ["#0B5394", "#3D85C6", "#6FA8DC", "#9FC5E8", "#CFE2F3"],
        "categorical": {
            "Rural": "#1F7A1F",
            "Urban": "#0B5394",
            "Male": "#0B5394",
            "Female": "#CC4125",
            "Total": "#666666",
        },
        "semantic": {"positive": "#1F7A1F", "negative": "#CC0000", "neutral": "#666666"},
    }

    # Render profile
    render_profile = {
        "numberFormat": {"locale": "en-IN", "grouping": "lakh-crore", "decimalSeparator": "."},
        "percentFormat": {"decimals": 1, "suffix": "%"},
        "currencyFormat": {"symbol": "₹", "grouping": "lakh-crore", "decimals": 0},
        "fontFamily": "Noto Sans",
        "pageSize": "A4",
    }

    # Document map
    document_map_out = {
        "order": [t["topicId"] for t in blueprint_topics],
        "frontMatter": ["title_page", "toc"],
        "backMatter": ["glossary", "notes"],
    }

    # ════════════════════════════════════════════════════════════════════════════
    # ASSEMBLE FINAL OUTPUT
    # ════════════════════════════════════════════════════════════════════════════
    cfg = _DOC_TYPE_CONFIG.get(doc_type, _DOC_TYPE_CONFIG["statistical_annual_report"])
    blueprint = {
        "$schema": "bharatstat/template-blueprint/v1",
        "templateMeta": {
            "templateId": template_id,
            "name": doc_title or "Document",
            "domain": cfg.get("domain", "general"),
            "reportType": doc_type,
            "locale": "en-IN",
            "version": "3.0",
            "valueFree": True,
            "proseFree": True,
            "sourceDocument": doc_title or "Document",
        },
        "glossary": glossary,
        "palette": palette,
        "renderProfile": render_profile,
        "entities": blueprint_entities,
        "topics": blueprint_topics,
        "tableTemplates": table_templates,
        "figureTemplates": figure_templates,
        "documentMap": document_map_out,
    }

    # ── extracted_assets (text per page for frontend) ──
    text_pages = []
    for i, pt in enumerate(page_texts):
        text_pages.append({
            "page_index": i,
            "text": (pt.get("raw_text") or "")[:5000],
        })

    # Assemble template.ast.json shape
    ast = {
        "$schema": "bharatstat/template-ast/v1",
        "metadata": {
            "templateId": template_id,
            "blueprintRef": template_id,
            "name": doc_title,
            "locale": "en-IN",
            "version": "3.0",
            "valueFree": True,
            "generatedFrom": doc_title,
        },
        "styleAST": style_ast,
        "semanticAST": {
            "sections": semantic_sections,
            "entities": [{"entityId": e["entityId"], "name": e["canonicalName"], "type": e["entityType"], "confidence": e.get("confidence", 0.5)} for e in blueprint_entities],
            "topics": [{"topicId": t["topicId"], "title": t["title"]} for t in blueprint_topics],
        },
        "contentAST": {"blocks": content_blocks},
        "tableAST": {"tables": tables_ast},
        "chartAST": {"charts": charts_ast},
        "figureAST": {"figures": figures_ast},
        "layoutAST": {"pages": layout_pages_ast},
        "geometryAST": {
            "_doc": "Relative flow only. Absolute bounding boxes are computed by the layout engine at render time.",
            "flow": geometry_flow,
        },
        # Additional fields for backward compat / frontend
        "page_count": page_count,
        "extraction_method": "layoutlm+qwen-vl+knowledge-graph+two-loop",
        "blueprint": blueprint,
        "extracted_assets": {"text_pages": text_pages},
        "pipeline_trace": {},  # filled by orchestrator
        "questions": [q.get("intent", "") for q in questions],
        # entityGraph: UI expects {entityId, name, type, context} per entity
        "entityGraph": {"entities": [
            {
                "entityId": e["entityId"],
                "name": e["canonicalName"],
                "type": e["entityType"],
                "entityType": e["entityType"],
                "confidence": e.get("confidence", 0.5),
                "context": ", ".join(e.get("aliases") or [])[:80] or e["entityType"],
            }
            for e in blueprint_entities
        ]},
    }

    logger.info(
        "[pass4] ✓ Gold-standard AST: %d sections, %d blocks, %d tables, "
        "%d charts, %d figures, %d entities, %d topics (%d questions)",
        len(semantic_sections), len(content_blocks), len(tables_ast),
        len(charts_ast), len(figures_ast), len(blueprint_entities),
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
    resume_from: str = "",
) -> dict[str, Any]:
    """Run the complete 7-pass extraction pipeline.

    Pass 0: Rasterize PDF
    Pass 1: LayoutLM layout detection
    Pass 2: Entity + structure extraction (Qwen-VL, 50-150 tokens/page)
    Pass 2.5: Document Knowledge Graph (programmatic)
    Pass 3: Two-loop AST building (questions + entity bindings)
    Pass 4: Enterprise AST + blueprint assembly
    Pass 5: Optional Gemini enhancement

    Args:
        resume_from: Pass name to resume from (e.g. "pass3", "pass4").
                     Clears that pass's checkpoint so it re-runs.
                     All passes before it use cache.
                     Empty string = normal run (use all available cache).

    Returns:
        Enterprise Document AST dict with embedded blueprint subtree.
    """
    import time as _time

    def _tick(stage: str, pct: int, data: Any = None):
        if progress_callback:
            progress_callback(stage, pct, data)

    pipeline_trace: dict[str, Any] = {"passes": {}, "total_elapsed": 0}
    pipeline_start = _time.monotonic()

    # ── Checkpoint system (Redis primary, file fallback) ──
    from report_builder.checkpoint_store import CheckpointStore
    _ckpt_hash = source_hash if source_hash else pdf_path.stem[:20]
    # Determine mode: "resume" only when explicitly resuming from a midway break
    _ckpt_mode = "resume" if resume_from else "fresh"
    ckpt = CheckpointStore(_ckpt_hash, mode=_ckpt_mode)

    # If resuming from a specific pass, invalidate that pass + all after it
    _PASS_ORDER = ["pass0", "pass1", "pass2_entities", "pass2_5", "pass2_6", "pass3_questions", "pass4", "pass5"]
    if resume_from:
        _resume_idx = next((i for i, p in enumerate(_PASS_ORDER) if resume_from in p), -1)
        if _resume_idx >= 0:
            for p in _PASS_ORDER[_resume_idx:]:
                ckpt.invalidate(p)
            logger.info("[pipeline] Resuming from %s — cleared cache for passes %s",
                        resume_from, _PASS_ORDER[_resume_idx:])

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

    # ── Document Type Detection (programmatic, no LLM) ──
    doc_type = _detect_document_type(page_texts, doc_title)
    logger.info("[pipeline] Document type: %s (pages=%d)", doc_type, len(page_texts))
    pipeline_trace["doc_type"] = doc_type

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

    # ── LayoutLM OCR Fallback ──
    # If pdfplumber returned empty text (scanned/image-only PDF or pdfminer version issue),
    # reconstruct page_texts from LayoutLM OCR output. LayoutLMv3 with apply_ocr=True runs
    # pytesseract internally and returns region text. This ensures the ToC cascade and
    # entity extraction always have raw_text to work with, regardless of PDF type.
    _total_pdfplumber_chars = sum(len(pt.get("raw_text") or "") for pt in page_texts)
    if _total_pdfplumber_chars == 0 and layoutlm_used and layout_pages:
        logger.warning("[pipeline] ⚠ pdfplumber returned 0 text — using LayoutLM OCR as text source")
        page_texts = _reconstruct_page_texts_from_layoutlm(layout_pages, page_texts)
        _total_reconstructed = sum(len(pt.get("raw_text") or "") for pt in page_texts)
        logger.info("[pipeline] Reconstructed %d chars of text from LayoutLM OCR across %d pages",
                    _total_reconstructed, len(page_texts))
        pipeline_trace["passes"]["pass1_layout"]["ocr_fallback"] = True
        pipeline_trace["passes"]["pass1_layout"]["ocr_fallback_chars"] = _total_reconstructed
        # Re-detect document type with the reconstructed text
        doc_type = _detect_document_type(page_texts, doc_title)
        pipeline_trace["doc_type"] = doc_type

    # ── Save LayoutLM diagnostic JSON ──
    _diag_dir = Path(__file__).resolve().parent.parent / "outputs" / "_diagnostics"
    _diag_dir.mkdir(parents=True, exist_ok=True)
    _diag_file = _diag_dir / f"layoutlm_{(source_hash or pdf_path.stem)[:16]}.json"
    try:
        _diag_payload = {
            "pdf": pdf_path.name,
            "source_hash": source_hash[:12] if source_hash else "",
            "layoutlm_used": layoutlm_used,
            "total_regions": total_regions,
            "pdfplumber_chars": _total_pdfplumber_chars,
            "pages": layout_pages,
        }
        with open(_diag_file, "w", encoding="utf-8") as _fh:
            json.dump(_diag_payload, _fh, ensure_ascii=False, indent=2, default=str)
        logger.info("[pipeline] LayoutLM diagnostic saved: %s", _diag_file.name)
    except Exception as _diag_exc:
        logger.debug("[pipeline] Diagnostic save failed: %s", _diag_exc)

    # Build initial ToC from LayoutLM, then improve with hybrid cascade
    toc_layoutlm = build_toc_from_regions(layout_pages, page_texts)
    toc = _extract_toc_hybrid(page_texts, layout_pages, toc_layoutlm)
    pipeline_trace["passes"]["pass1_layout"]["toc_entries"] = len(toc)
    pipeline_trace["passes"]["pass1_layout"]["toc_l1_chapters"] = sum(1 for e in toc if e.level == 1)

    # ── Pass 2: Entity + Structure Extraction ──
    _tick("pass2_entity_extraction", 30)
    t0 = _time.monotonic()
    _cached_pass2 = ckpt.load("pass2_entities")
    if _cached_pass2:
        entity_pages = _cached_pass2
    else:
        entity_pages = pass2_entity_structure_extraction(page_images, layout_pages, page_texts, doc_title, doc_type=doc_type)
        ckpt.save("pass2_entities", entity_pages)
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
        "vlm_provider": (os.getenv("PROVIDER_ENTITY_EXTRACTION") or os.getenv("VLM_PROVIDER", "qwen")).strip().lower(),
        "vlm_fallback_used": vlm_success > 0 and any(
            p.get("vlm_used") for p in entity_pages
        ),
    }

    # ── Pass 2.5: Document Knowledge Graph ──
    _tick("pass2_5_knowledge_graph", 45)
    t0 = _time.monotonic()
    document_map = pass2_5_document_knowledge_graph(entity_pages, layout_pages, page_texts, toc, doc_title, doc_type=doc_type)
    pass25_elapsed = _time.monotonic() - t0

    pipeline_trace["passes"]["pass2_5_kg"] = {
        "elapsed_s": round(pass25_elapsed, 1),
        "entities": len(document_map.get("all_entities") or []),
        "total_entities": len(document_map.get("all_entities") or []),
        "hierarchy_nodes": len(document_map.get("all_entities") or []),
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

    # ── Pass 2.7: Entity Enrichment (units/format/valueDomain + glossary + palette) ──
    _tick("pass2_7_entity_enrichment", 58)
    t0 = _time.monotonic()
    try:
        from report_builder.entity_enrichment import enrich_document_map as _enrich_dm
        document_map = _enrich_dm(document_map)
        _enrich_ok = True
    except Exception as _enrich_exc:
        logger.warning("[pass2.7] Enrichment failed (non-fatal): %s", _enrich_exc)
        _enrich_ok = False
    pass27_elapsed = _time.monotonic() - t0
    _enr_ents = document_map.get("all_entities") or []
    pipeline_trace["passes"]["pass2_7_enrichment"] = {
        "elapsed_s": round(pass27_elapsed, 1),
        "ok": _enrich_ok,
        "with_unit": sum(1 for e in _enr_ents if e.get("unit")),
        "with_value_domain": sum(1 for e in _enr_ents if e.get("valueDomain")),
        "glossary_terms": len(document_map.get("glossary") or []),
    }

    # ── Pass 3: Two-Loop AST Building ──
    _tick("pass3_ast_building", 60)
    t0 = _time.monotonic()
    _cached_pass3 = ckpt.load("pass3_questions")
    if _cached_pass3:
        ast_result = _cached_pass3
    else:
        ast_result = pass3_two_loop_ast_building(document_map, page_texts, doc_title, page_images=page_images)
        ckpt.save("pass3_questions", ast_result)
    pass3_elapsed = _time.monotonic() - t0

    # ── Gemini Safety: Question gap fill (Mode 2) ──
    # Only trigger if <50% of chapters have questions assigned
    chapters_count = len(document_map.get("chapters") or [])
    topics_count = len(ast_result.get("topics") or [])
    coverage = topics_count / max(chapters_count, 1)

    if coverage < 0.5:
        logger.info("[pipeline] Question coverage %.0f%% (%d/%d chapters) — triggering Gemini gap fill",
                    coverage * 100, topics_count, chapters_count)
        ast_result = _gemini_question_gap_fill(ast_result, document_map, doc_title)
    elif not ast_result.get("questions"):
        # Complete failure — use full Gemini fallback
        logger.info("[pipeline] Pass 3 produced 0 questions — trying Gemini semantic fallback")
        gemini_result = _gemini_semantic_fallback(document_map, toc, doc_title)
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
    ast = pass4_assemble_ast(layout_pages, page_texts, document_map, ast_result, doc_title, source_hash, entity_pages, doc_type=doc_type)
    pass4_elapsed = _time.monotonic() - t0
    pipeline_trace["passes"]["pass4_assembly"] = {
        "elapsed_s": round(pass4_elapsed, 1),
        "paragraphs": len(ast.get("contentAST", {}).get("blocks") or []),
        "tables": len(ast.get("tableAST", {}).get("tables") or []),
        "figures": len(ast.get("figureAST", {}).get("figures") or []),
        "charts_detected": len(ast.get("chartAST", {}).get("charts") or []),
        "chart_pages": len(set(f.get("page", -1) for f in (ast.get("chartAST", {}).get("charts") or []) if f.get("chartId"))),
        "blueprint_topics": len(ast.get("blueprint", {}).get("topics") or []),
        "blueprint_entities": len(ast.get("blueprint", {}).get("entities") or []),
    }

    # ── Gemini Safety: Fact extraction (Mode 4) ──
    # Only if factGraph is empty AND API key available
    if not (ast.get("factGraph") or {}).get("facts"):
        logger.info("[pipeline] factGraph empty — triggering Gemini fact extraction")
        ast = _gemini_fact_extraction(ast, page_texts[:4])

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

    # ── Final Unicode sanitization on all string values in the AST ──
    def _sanitize_strings(obj: Any) -> Any:
        if isinstance(obj, str):
            return obj.replace('\u2013', '-').replace('\u2014', '-').replace('\u2018', "'").replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"').replace('\u00a0', ' ')
        elif isinstance(obj, dict):
            return {k: _sanitize_strings(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_sanitize_strings(v) for v in obj]
        return obj

    ast = _sanitize_strings(ast)

    _tick("completed", 100)
    logger.info("═══════════════════════════════════════════════════════════")
    logger.info("  ✓ Pipeline v3.0 complete — Enterprise AST + Blueprint ready")
    logger.info("  ✓ %d topics, %d questions, %d entities",
                len(ast.get("blueprint", {}).get("topics") or []),
                sum(len(t.get("questions", [])) for t in ast.get("blueprint", {}).get("topics", [])),
                len(ast.get("blueprint", {}).get("entities") or []))
    logger.info("  ✓ Document type: %s | Facts: %d",
                doc_type,
                len((ast.get("factGraph") or {}).get("facts") or []))
    # Coverage check
    _bp_topics = len(ast.get("blueprint", {}).get("topics") or [])
    _ch_count = len(document_map.get("chapters") or [])
    _coverage = f"{_bp_topics}/{_ch_count}"
    logger.info("  ✓ Chapter coverage: %s | Tables: %d | Charts: %d",
                _coverage,
                len(ast.get("blueprint", {}).get("tableStructures") or []),
                len(ast.get("chartAST", {}).get("charts") or []))
    logger.info("═══════════════════════════════════════════════════════════")

    # ── Persist outputs to disk ──────────────────────────────────────────────
    # Sanitise template name → valid folder name
    import re as _re
    _safe_name = _re.sub(r"[^\w\-]", "_", doc_title).strip("_") or "document"
    _out_dir = Path(__file__).resolve().parent.parent / "outputs" / _safe_name
    _out_dir.mkdir(parents=True, exist_ok=True)

    # ── Per-pass diagnostic dump (all intermediate outputs) ──
    _pass_dump_dir = _out_dir / "_pass_outputs"
    _pass_dump_dir.mkdir(parents=True, exist_ok=True)
    try:
        # Pass 0: page text extraction summary
        _p0 = {
            "page_count": len(page_texts),
            "total_chars": sum(len(pt.get("raw_text", "")) for pt in page_texts),
            "pages": [
                {
                    "page": i,
                    "chars": len(pt.get("raw_text", "")),
                    "words": pt.get("word_count", 0),
                    "tables": len(pt.get("tables", [])),
                    "headings": pt.get("headings", []),
                    "embedded_figures": len(pt.get("embedded_figures", [])),
                }
                for i, pt in enumerate(page_texts)
            ],
        }
        with open(_pass_dump_dir / "pass0_text_extraction.json", "w", encoding="utf-8") as f:
            json.dump(_p0, f, ensure_ascii=False, indent=2, default=str)

        # Pass 1: LayoutLM regions
        _p1 = {
            "layoutlm_used": layoutlm_used,
            "total_regions": total_regions,
            "toc_entries": [{"title": e.title, "page": e.page_index, "level": e.level} for e in toc],
            "pages": [
                {
                    "page": i,
                    "regions": [
                        {"type": r.get("type"), "confidence": round(r.get("confidence", 0), 3), "text": (r.get("text") or "")[:100]}
                        for r in (lp.get("regions") or [])
                    ],
                }
                for i, lp in enumerate(layout_pages)
            ],
        }
        with open(_pass_dump_dir / "pass1_layout_regions.json", "w", encoding="utf-8") as f:
            json.dump(_p1, f, ensure_ascii=False, indent=2, default=str)

        # Pass 2: VLM entity extraction
        _p2 = {
            "vlm_success_count": vlm_success,
            "total_entities": total_entities,
            "chart_pages": chart_pages_detected,
            "pages": [
                {
                    "page": ep.get("page_index"),
                    "vlm_used": ep.get("vlm_used", False),
                    "structure_type": ep.get("structure_type"),
                    "entities": [e.get("name") if isinstance(e, dict) else e for e in (ep.get("entities") or [])][:20],
                    "chart_types": ep.get("chart_types", []),
                    "chart_titles": ep.get("chart_titles", []),
                    "table_title": ep.get("table_title", ""),
                    "section_heading": ep.get("section_heading", ""),
                }
                for ep in entity_pages
            ],
        }
        with open(_pass_dump_dir / "pass2_vlm_entities.json", "w", encoding="utf-8") as f:
            json.dump(_p2, f, ensure_ascii=False, indent=2, default=str)

        # Pass 2.5: Document Knowledge Graph
        _p25 = {
            "entities_count": len(document_map.get("all_entities", [])),
            "table_structures_count": len(document_map.get("table_structures", [])),
            "chapters_count": len(document_map.get("chapters", [])),
            "entities": [
                {
                    "entityId": e.get("entityId"),
                    "name": e.get("name"),
                    "source": e.get("source"),
                    "entityType_hint": e.get("entityType_hint"),
                    "pages": e.get("pages", []),
                }
                for e in (document_map.get("all_entities") or [])
            ],
            "table_structures": [
                {
                    "tableId": ts.get("tableId"),
                    "page": ts.get("page"),
                    "tableTitle": ts.get("tableTitle", ""),
                    "columns": ts.get("columns", [])[:15],
                    "dimensions": ts.get("dimensions", []),
                    "measures": ts.get("measures", []),
                    "breakdowns": ts.get("breakdowns", []),
                    "layout": ts.get("layout"),
                    "columnGroups": ts.get("columnGroups", []),
                }
                for ts in (document_map.get("table_structures") or [])
            ],
            "chapters": document_map.get("chapters", []),
        }
        with open(_pass_dump_dir / "pass2_5_knowledge_graph.json", "w", encoding="utf-8") as f:
            json.dump(_p25, f, ensure_ascii=False, indent=2, default=str)

        # Pass 2.6: Entity classification
        _p26 = {
            "classified_entities": [
                {
                    "entityId": e.get("entityId"),
                    "name": e.get("name"),
                    "entityType_hint": e.get("entityType_hint"),
                    "source": e.get("source"),
                    "unit": e.get("unit"),
                    "confidence": e.get("confidence"),
                }
                for e in (document_map.get("all_entities") or [])
            ],
        }
        with open(_pass_dump_dir / "pass2_6_entity_classification.json", "w", encoding="utf-8") as f:
            json.dump(_p26, f, ensure_ascii=False, indent=2, default=str)

        # Pass 3: Questions + topics
        _p3 = {
            "questions_count": len(ast_result.get("questions", [])),
            "topics_count": len(ast_result.get("topics", [])),
            "questions": [
                {
                    "questionId": q.get("questionId"),
                    "intent": q.get("intent"),
                    "questionType": q.get("questionType"),
                    "page": q.get("page"),
                    "sourceHeading": q.get("sourceHeading"),
                    "requiredEntities": q.get("requiredEntities", []),
                    "analyticsSpec": q.get("analyticsSpec"),
                    "answerStructure": q.get("answerStructure"),
                    "inferenceMethod": q.get("inferenceMethod"),
                    "inferenceConfidence": q.get("inferenceConfidence"),
                }
                for q in (ast_result.get("questions") or [])
            ],
            "topics": ast_result.get("topics", []),
        }
        with open(_pass_dump_dir / "pass3_questions_topics.json", "w", encoding="utf-8") as f:
            json.dump(_p3, f, ensure_ascii=False, indent=2, default=str)

        # Pipeline trace summary
        with open(_pass_dump_dir / "pipeline_trace.json", "w", encoding="utf-8") as f:
            json.dump(pipeline_trace, f, ensure_ascii=False, indent=2, default=str)

        logger.info("  ✓ Per-pass diagnostics saved → %s/", _pass_dump_dir.name)
    except Exception as _dump_exc:
        logger.warning("[pipeline] Per-pass dump failed (non-fatal): %s", _dump_exc)

    # New canonical output (migration plan P1): value-free ① template.ast.json + ② template.blueprint.json
    from report_builder.template_emit import emit_templates, legacy_emit_enabled
    _emit_report = emit_templates(ast, _out_dir)

    # ── I6: Template Compiler V2 (optional, behind feature flag) ──────────────
    # When EXTRACTION_COMPILER_V2=true, re-processes the emitted artifacts through
    # the E1-E12 compiler modules for improved entity quality, deterministic
    # questions, slot wiring, and diagnostics scoring.
    _compiler_v2 = (os.getenv("EXTRACTION_COMPILER_V2") or "").strip().lower() in ("1", "true", "yes", "on")
    _compiler_strict = (os.getenv("EXTRACTION_COMPILER_STRICT") or "").strip().lower() in ("1", "true", "yes", "on")

    if _compiler_v2:
        try:
            from report_builder.template_compiler import compile_template_artifacts

            # Load the just-emitted value-free artifacts as compiler input
            _skeleton_path = _out_dir / "template.ast.json"
            _bp_path = _out_dir / "template.blueprint.json"
            with open(_skeleton_path, "r", encoding="utf-8") as _fh:
                _raw_skeleton = json.load(_fh)
            with open(_bp_path, "r", encoding="utf-8") as _fh:
                _raw_blueprint = json.load(_fh)

            # Gather table candidates if available from pass 0/2.5
            _table_candidates = None
            _page_text_list = None
            # Build rich table candidates from pass 2.5 + pass 0 raw data
            if "document_map" in dir() and document_map and document_map.get("table_structures"):
                from report_builder.table_candidate_adapter import table_candidates_from_pipeline
                _table_candidates = table_candidates_from_pipeline(
                    table_structures=document_map.get("table_structures"),
                    page_texts=page_texts if "page_texts" in dir() else None,
                )
                logger.info("[pipeline] Compiler V2: %d table candidates (%d with header_rows)",
                            len(_table_candidates),
                            sum(1 for t in _table_candidates if t.get("header_rows")))
            # page texts from pass 0 if available
            if "page_texts" in dir() and page_texts:
                _page_text_list = [p.get("raw_text", "") for p in page_texts if isinstance(p, dict)]

            _compiled = compile_template_artifacts(
                raw_ast=_raw_skeleton,
                blueprint=_raw_blueprint,
                table_candidates=_table_candidates,
                page_texts=_page_text_list,
            )

            # Overwrite emitted files with compiled versions
            with open(_skeleton_path, "w", encoding="utf-8") as _fh:
                json.dump(_compiled["template_ast"], _fh, ensure_ascii=False, indent=2, default=str)
            with open(_bp_path, "w", encoding="utf-8") as _fh:
                json.dump(_compiled["template_blueprint"], _fh, ensure_ascii=False, indent=2, default=str)

            # Write diagnostics
            _diag = _compiled["diagnostics"]
            _diag_path = _out_dir / "template.diagnostics.json"
            with open(_diag_path, "w", encoding="utf-8") as _fh:
                json.dump(_diag.to_dict(), _fh, ensure_ascii=False, indent=2, default=str)

            logger.info(
                "[pipeline] ✓ Compiler V2: score=%.3f status=%s entities=%d questions=%d",
                _diag.binderReadinessScore, _diag.status,
                _diag.counts.entities, _diag.counts.questions,
            )
            _emit_report["compiler_v2"] = {
                "enabled": True,
                "score": _diag.binderReadinessScore,
                "status": _diag.status,
                "tableCandidatesCount": len(_table_candidates) if _table_candidates else 0,
            }
        except Exception as _compiler_exc:
            if _compiler_strict:
                raise
            logger.warning("[pipeline] Compiler V2 failed (non-fatal, using legacy artifacts): %s", _compiler_exc)
            _emit_report["compiler_v2"] = {"enabled": True, "error": str(_compiler_exc)}
    else:
        _emit_report["compiler_v2"] = {"enabled": False}

    # Legacy blended AST — emitted only when EXTRACTION_EMIT_LEGACY is set (loop decision Q3).
    if legacy_emit_enabled():
        _ast_path = _out_dir / "enterprise_ast.json"
        _bp_path = _out_dir / "blueprint.json"
        with open(_ast_path, "w", encoding="utf-8") as _fh:
            json.dump(ast, _fh, ensure_ascii=False, indent=2, default=str)
        with open(_bp_path, "w", encoding="utf-8") as _fh:
            json.dump(ast.get("blueprint", {}), _fh, ensure_ascii=False, indent=2, default=str)
        logger.info("  ✓ Saved enterprise_ast.json  → %s (legacy)", _ast_path)
        logger.info("  ✓ Saved blueprint.json        → %s (legacy)", _bp_path)

    ast["_template_emit"] = _emit_report
    return ast


def _reconstruct_page_texts_from_layoutlm(
    layout_pages: list[dict[str, Any]],
    original_page_texts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reconstruct page_texts from LayoutLM OCR when pdfplumber returns empty.

    This handles scanned/image-only PDFs and pdfminer version mismatches where
    pdfplumber silently returns 0 chars. LayoutLMv3 with apply_ocr=True runs
    pytesseract internally and provides region text.

    Preserves the same dict shape as pass0 pdfplumber output:
        {raw_text, words, tables, headings, width, height, word_count}
    """
    reconstructed: list[dict[str, Any]] = []

    for i, layout_page in enumerate(layout_pages):
        regions = layout_page.get("regions") or []
        page_w = float(layout_page.get("width") or 595)
        page_h = float(layout_page.get("height") or 842)

        # Sort regions top-to-bottom for reading order
        sorted_regions = sorted(regions, key=lambda r: (r.get("bbox") or [0, 0, 0, 0])[1])

        # Collect text from all regions
        all_text_parts: list[str] = []
        headings: list[str] = []
        words_synthetic: list[dict[str, Any]] = []

        for reg in sorted_regions:
            text = (reg.get("text") or "").strip()
            if not text:
                continue
            all_text_parts.append(text)
            rtype = reg.get("type", "text")
            bbox = reg.get("bbox") or [0, 0, 1000, 50]

            # Headings and titles → feed into ToC cascade
            if rtype in ("heading", "title"):
                headings.append(text)

            # Build synthetic word entries with estimated font size from region type
            # Headings get larger size → triggers L2 font-size cascade
            estimated_size = 14.0 if rtype in ("heading", "title") else 9.0 if rtype == "text" else 10.0
            for word_text in text.split():
                if word_text.strip():
                    words_synthetic.append({
                        "text": word_text,
                        "x0": float(bbox[0]),
                        "top": float(bbox[1]),
                        "x1": float(bbox[2]),
                        "bottom": float(bbox[3]),
                        "fontname": "OCR",
                        "size": estimated_size,
                    })

        raw_text = "\n".join(all_text_parts)

        # Preserve any tables that the original pdfplumber might have found
        # (usually empty for scanned PDFs, but keep for safety)
        orig = original_page_texts[i] if i < len(original_page_texts) else {}

        reconstructed.append({
            "raw_text": raw_text,
            "words": words_synthetic,
            "tables": orig.get("tables") or [],
            "headings": headings,
            "embedded_figures": orig.get("embedded_figures") or [],
            "width": page_w,
            "height": page_h,
            "word_count": len(raw_text.split()),
            "_source": "layoutlm_ocr",
        })

    return reconstructed


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


def _gemini_question_gap_fill(
    ast_result: dict[str, Any],
    document_map: dict[str, Any],
    doc_title: str,
) -> dict[str, Any]:
    """Gemini Mode 2: Generate 1 question per chapter that has no questions yet.

    Only called when <50% of chapters have questions assigned.
    Generates minimally — 1 question per uncovered chapter, not full extraction.
    """
    covered_chapter_ids = {
        topic.get("topicId", "").replace("topic_", "ch_")
        for topic in (ast_result.get("topics") or [])
    }
    chapters = document_map.get("chapters") or []
    uncovered = [ch for ch in chapters if ch["chapterId"] not in covered_chapter_ids]

    if not uncovered:
        return ast_result

    all_entities = document_map.get("all_entities") or []
    entity_names = ", ".join(e["name"] for e in all_entities[:15]) or "LFPR, WPR, UR"

    chapter_list = "\n".join(
        f"- Chapter '{ch['title']}' (pages {ch['pageRange'][0]+1}-{ch['pageRange'][1]+1})"
        for ch in uncovered[:10]
    )

    prompt = (
        f"Document: \"{doc_title}\" (Indian government statistical report)\n"
        f"Available entities: {entity_names}\n\n"
        f"These chapters have no analytical questions yet. Generate exactly 1 specific "
        f"analytical question per chapter. Questions must reference real entities and be "
        f"quantitative/comparative in MoSPI style.\n\n"
        f"Chapters:\n{chapter_list}\n\n"
        f"Output JSON array — one entry per chapter:\n"
        f'[{{"chapter": "chapter title", "question": "specific analytical question?",'
        f'"questionType": "comparison|trend|ranking|describe"}}]\n'
        f"JSON only."
    )

    try:
        raw = llm_text_call(prompt, task="gap_fill", max_tokens=_tok("gap_fill")[0], temperature=_tok("gap_fill")[1])
        if not raw:
            logger.info("[gap_fill] No response from LLM — skipping")
            return ast_result

        parsed = _extract_json_array_from_response(raw)
        if not parsed:
            logger.warning("[gap_fill] Could not parse JSON array from response: %s", raw[:200])
            return ast_result

        # Build synthetic questions + topics for uncovered chapters
        import uuid as _uuid
        new_questions = []
        new_topics = []
        existing_questions = list(ast_result.get("questions") or [])
        existing_topics = list(ast_result.get("topics") or [])

        for item in parsed:
            if not isinstance(item, dict):
                continue
            ch_title = item.get("chapter", "")
            q_intent = item.get("question", "")
            q_type = item.get("questionType", "describe")
            if not q_intent:
                continue

            # Find the matching chapter
            matched_ch = next(
                (ch for ch in uncovered if ch_title.lower()[:30] in ch["title"].lower()[:30] or
                 ch["title"].lower()[:30] in ch_title.lower()[:30]),
                None
            )
            if not matched_ch:
                continue

            q_id = f"gemini_gf_{_uuid.uuid4().hex[:6]}"
            q = {
                "questionId": q_id,
                "intent": q_intent,
                "questionType": q_type,
                "page": matched_ch["pageRange"][0],
                "sourceHeading": matched_ch["title"],
                "requiredEntities": [],
                "answerStructure": {
                    "layoutType": "single",
                    "components": [{"type": "narrative_paragraph", "renderOrder": 1}],
                },
                "inferenceConfidence": 0.45,
                "inferenceMethod": "gemini_gap_fill",
            }
            new_questions.append(q)
            new_topics.append({
                "topicId": matched_ch["chapterId"].replace("ch_", "topic_"),
                "title": matched_ch["title"],
                "description": f"Questions from chapter: {matched_ch['title']}",
                "questionIds": [q_id],
                "pageRange": matched_ch["pageRange"],
            })

        logger.info("[gemini] Question gap fill: added %d questions for %d uncovered chapters",
                    len(new_questions), len(uncovered))
        return {
            "questions": existing_questions + new_questions,
            "topics": existing_topics + new_topics,
        }

    except Exception as exc:
        logger.warning("[gemini] Question gap fill failed (non-fatal): %s", exc)
        return ast_result


def _gemini_fact_extraction(
    ast: dict[str, Any],
    page_texts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Gemini Mode 4: Extract numeric facts from the document text.

    Only called when factGraph.facts is empty. Costs 1 Gemini call (~800 tokens).
    """
    # Build context from first 3 pages
    context_text = "\n\n".join(
        (pt.get("raw_text") or "")[:1200]
        for pt in page_texts[:3]
    )[:4000]

    entity_names = ", ".join(
        e.get("name", "") for e in (ast.get("blueprint", {}).get("entities") or [])[:15]
    ) or "LFPR, WPR, UR"

    prompt = (
        f"Extract 5-10 numeric facts from this government statistical document.\n"
        f"Focus on: {entity_names}\n\n"
        f"For each fact, include the numeric value and the year.\n"
        f"Output JSON array:\n"
        f'[{{"factId":"f1","statement":"LFPR was 59.3% in 2025",'
        f'"entityRef":"Labour Force Participation Rate",'
        f'"numericValue":59.3,"unit":"%","year":2025,"sourcePageIndex":0}}]\n'
        f"JSON only. Text:\n\n{context_text}"
    )

    try:
        raw = llm_text_call(prompt, task="fact_extraction", max_tokens=_tok("fact_extraction")[0], temperature=_tok("fact_extraction")[1])
        if not raw:
            logger.info("[fact_extraction] No response from LLM provider")
            return ast
        parsed = _extract_json_array_from_response(raw)
        if parsed:
            ast["factGraph"] = {"facts": parsed}
            logger.info("[fact_extraction] %d facts extracted", len(parsed))
        else:
            logger.warning("[fact_extraction] Could not parse JSON array from response (first 200 chars): %s", raw[:200])
        return ast

    except Exception as exc:
        logger.warning("[fact_extraction] Failed (non-fatal): %s", exc)
        return ast


def _gemini_semantic_fallback(
    document_map: dict[str, Any],
    toc: list[ToCEntry],
    doc_title: str,
) -> dict[str, Any]:
    """Use Gemini as fallback for question generation when local model fails.

    Returns same format as pass3_two_loop_ast_building output.
    """
    try:
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
            "Each question's intent must be a complete, quantitative question ending in '?' that names "
            "real entities from the list above. questionType must be EXACTLY ONE of: comparison, trend, "
            "ranking, distribution, composition, correlation, describe. Do NOT copy placeholder text.\n\n"
            "Output JSON with this shape (replace all placeholders with real values):\n"
            '{"questions":[{"questionId":"q1","intent":"<real question>?","questionType":"<one type>",'
            '"sourceHeading":"<section title>","page":0,'
            '"requiredEntities":[{"entityRef":"<real entity name>","role":"groupBy|measure|filter"}],'
            '"answerStructure":{"layoutType":"single|split","components":[{"type":"narrative_paragraph|data_table|grouped_bar_chart|line_chart|pie_chart|metric_card","renderOrder":1}]},'
            '"inferenceConfidence":0.6}]}\n'
            "Output 3-8 questions. JSON only."
        )

        text = llm_text_call(prompt, task="semantic_fallback", max_tokens=_tok("semantic_fallback")[0], temperature=_tok("semantic_fallback")[1])
        if not text:
            return {"questions": [], "topics": []}

        data = _extract_json_from_response(text)
        if not data:
            return {"questions": [], "topics": []}

        questions = data.get("questions") or []

        # ── D3/D4/D8: drop stubs, normalise questionType, attach analyticsSpec ──
        from report_builder.question_quality import (
            build_analytics_spec as _bas,
            is_stub_question as _isstub,
            normalise_question_type as _normqt,
        )
        _clean: list[dict[str, Any]] = []
        for _q in questions:
            if _isstub(_q.get("intent", "")):
                continue
            _q["questionType"] = _normqt(_q.get("questionType"))
            if not _q.get("analyticsSpec"):
                _q["analyticsSpec"] = _bas(_q["questionType"], _q.get("requiredEntities") or [])
            _clean.append(_q)
        questions = _clean
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

        logger.info("[semantic_fallback] ✓ Got %d questions in %d topics", len(questions), len(topics))
        return {"questions": questions, "topics": topics}

    except Exception as exc:
        logger.error("[semantic_fallback] Failed: %s", exc)
        return {"questions": [], "topics": []}
