"""E4 — Statistical Context Extraction + Inheritance.

Captures MoSPI statistical meaning that lives OUTSIDE table cells and propagates
it down the hierarchy:

    document → chapter → table → column group → column → entity

Enriches E3 TableSemanticModels with resolved units, estimate status, reference
dates, geography level, source notes, and footnote meanings.

Usage:
    from report_builder.statistical_context_extractor import (
        build_statistical_context, apply_context_to_tables, resolve_unit_for_column,
    )
    ctx = build_statistical_context(doc_info, chapters, table_models)
    table_models = apply_context_to_tables(table_models, ctx)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class UnitResolution:
    """Resolved unit for one column with provenance."""
    unit: str = ""
    unitSource: str = "unknown"         # column_header | column_group | table_title | chapter_context | unknown
    confidence: float = 0.5
    conflict: bool = False
    parentUnit: str | None = None
    childUnit: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"unit": self.unit, "unitSource": self.unitSource, "confidence": self.confidence}
        if self.conflict:
            d["conflict"] = True
            d["parentUnit"] = self.parentUnit
            d["childUnit"] = self.childUnit
            d["message"] = self.message
        return d


@dataclass
class ContextConflict:
    """A detected conflict in context inheritance."""
    code: str = ""
    severity: str = "warn"
    tableId: str | None = None
    columnId: str | None = None
    parentValue: str | None = None
    childValue: str | None = None
    resolution: str = ""                # column_wins | parent_wins | manual
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "severity": self.severity,
            "tableId": self.tableId, "columnId": self.columnId,
            "parentValue": self.parentValue, "childValue": self.childValue,
            "resolution": self.resolution, "message": self.message,
        }


@dataclass
class FootnoteMeaning:
    """Interpreted meaning of a footnote marker."""
    marker: str = ""
    text: str = ""
    semanticMeaning: str = "unknown"    # provisional | revised | final | excluded | estimated | source | note | unknown
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {"marker": self.marker, "text": self.text, "semanticMeaning": self.semanticMeaning, "confidence": self.confidence}


@dataclass
class ChapterContext:
    """Context for one chapter/section."""
    chapterId: str = ""
    chapterNumber: int | None = None
    chapterTitle: str = ""
    domain: str = ""
    pageRange: tuple[int, int] | None = None
    tableRefs: list[str] = field(default_factory=list)
    figureRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"chapterId": self.chapterId, "chapterTitle": self.chapterTitle, "domain": self.domain}
        if self.chapterNumber is not None:
            d["chapterNumber"] = self.chapterNumber
        if self.tableRefs:
            d["tableRefs"] = list(self.tableRefs)
        return d


@dataclass
class TableContext:
    """Statistical context for one table."""
    tableId: str = ""
    tableNumber: str | None = None
    tableTitle: str = ""
    page: int | None = None
    unitNote: str | None = None
    referenceDate: str | None = None
    estimateStatus: str | None = None
    footnotes: list[FootnoteMeaning] = field(default_factory=list)
    sourceNotes: list[str] = field(default_factory=list)
    geographyLevel: str | None = None
    domain: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"tableId": self.tableId, "tableTitle": self.tableTitle}
        if self.tableNumber:
            d["tableNumber"] = self.tableNumber
        if self.page is not None:
            d["page"] = self.page
        if self.unitNote:
            d["unitNote"] = self.unitNote
        if self.referenceDate:
            d["referenceDate"] = self.referenceDate
        if self.estimateStatus:
            d["estimateStatus"] = self.estimateStatus
        if self.footnotes:
            d["footnotes"] = [f.to_dict() for f in self.footnotes]
        if self.sourceNotes:
            d["sourceNotes"] = list(self.sourceNotes)
        if self.geographyLevel:
            d["geographyLevel"] = self.geographyLevel
        return d


@dataclass
class MoSPIStatisticalContext:
    """Full hierarchical statistical context for a document extraction."""
    sourceDocument: str = ""
    ministry: str | None = None
    publicationYear: str | None = None
    domain: str = ""
    chapters: list[ChapterContext] = field(default_factory=list)
    tableContexts: list[TableContext] = field(default_factory=list)
    unitRegistry: dict[str, str] = field(default_factory=dict)  # columnId/entityRef → unit
    sourceNotes: list[str] = field(default_factory=list)
    footnotes: list[FootnoteMeaning] = field(default_factory=list)
    conflicts: list[ContextConflict] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceDocument": self.sourceDocument,
            "ministry": self.ministry,
            "publicationYear": self.publicationYear,
            "domain": self.domain,
            "chapters": [c.to_dict() for c in self.chapters],
            "tableContexts": [t.to_dict() for t in self.tableContexts],
            "unitRegistry": dict(self.unitRegistry),
            "sourceNotes": list(self.sourceNotes),
            "footnotes": [f.to_dict() for f in self.footnotes],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "diagnostics": self.diagnostics,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Unit normalization
# ─────────────────────────────────────────────────────────────────────────────

_UNIT_MAP: dict[str, str] = {
    # Physical
    "million tonnes": "million_tonnes",
    "in million tonnes": "million_tonnes",
    "mt": "million_tonnes",
    "billion cubic metres": "billion_cubic_metres",
    "in billion cubic metres": "billion_cubic_metres",
    "bcm": "billion_cubic_metres",
    "mw": "MW",
    "in mw": "MW",
    "gw": "GW",
    "kwh": "kWh",
    "gwh": "GWh",
    "twh": "TWh",
    "btu": "BTU",
    # Percentage
    "%": "percent",
    "percentage": "percent",
    "per cent": "percent",
    "percent": "percent",
    "in %": "percent",
    "in percentage": "percent",
    # Currency
    "crore": "crore_inr",
    "₹ crore": "crore_inr",
    "rs. crore": "crore_inr",
    "rs crore": "crore_inr",
    "in crore": "crore_inr",
    "lakh": "lakh_inr",
    "₹ lakh": "lakh_inr",
    "rs. lakh": "lakh_inr",
    "rs lakh": "lakh_inr",
    # Rate
    "per 1000": "per_1000",
    "per lakh": "per_lakh",
    "per 100000": "per_lakh",
    # Area/volume
    "sq km": "sq_km",
    "hectares": "hectares",
    "km": "km",
    # Count
    "numbers": "count",
    "nos": "count",
    "persons": "persons",
    "lakhs": "lakh_count",
}


def normalize_unit(raw: str) -> str:
    """Normalize a raw unit string to standard form.

    "Million Tonnes" → "million_tonnes"
    "in MW" → "MW"
    "₹ crore" → "crore_inr"
    "%" → "percent"

    Falls back to slugified form if unknown.
    """
    if not raw:
        return ""
    cleaned = raw.strip().lower()
    # Remove leading "in "
    if cleaned.startswith("in "):
        cleaned_no_in = cleaned[3:].strip()
        if cleaned_no_in in _UNIT_MAP:
            return _UNIT_MAP[cleaned_no_in]

    if cleaned in _UNIT_MAP:
        return _UNIT_MAP[cleaned]

    # Slugify unknown
    slug = re.sub(r'[^a-z0-9]+', '_', cleaned).strip('_')
    return slug or raw.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Reference date extraction
# ─────────────────────────────────────────────────────────────────────────────

_REFERENCE_DATE_PATTERNS = [
    re.compile(r'[Aa]s\s+on\s+(.+?)(?:\)|$)'),
    re.compile(r'[Aa]s\s+of\s+(.+?)(?:\)|$)'),
    re.compile(r'((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\s*[-–]\s*(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})', re.IGNORECASE),
    re.compile(r'(\d{1,2}[./]\d{1,2}[./]\d{4})'),
]


def extract_reference_date(text: str) -> str | None:
    """Extract reference date from text.

    "As on 1st April 2025" → "As on 1st April 2025"
    "as on 31.03.2025" → "31.03.2025"
    """
    if not text:
        return None
    for pattern in _REFERENCE_DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).strip() if m.lastindex else m.group(0).strip()
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Estimate status inference
# ─────────────────────────────────────────────────────────────────────────────

_ESTIMATE_PATTERNS = [
    (re.compile(r'\bProvisional\b', re.IGNORECASE), "provisional"),
    (re.compile(r'\bRevised\b', re.IGNORECASE), "revised"),
    (re.compile(r'\bQuick\s+Estimate\b', re.IGNORECASE), "quick_estimate"),
    (re.compile(r'\bAdvance\s+Estimate\b', re.IGNORECASE), "advance_estimate"),
    (re.compile(r'\bFinal\b', re.IGNORECASE), "final"),
    (re.compile(r'\bActual\b', re.IGNORECASE), "final"),
]

_MARKER_STATUS: dict[str, str] = {
    "P": "provisional",
    "R": "revised",
    "E": "estimated",
    "QE": "quick_estimate",
    "AE": "advance_estimate",
    "F": "final",
}


def infer_estimate_status(text_or_markers: str) -> str | None:
    """Infer estimate status from text or footnote markers.

    "P" → "provisional"
    "Provisional estimates" → "provisional"
    "R" → "revised"
    """
    if not text_or_markers:
        return None

    t = text_or_markers.strip()

    # Check single marker
    if t.upper() in _MARKER_STATUS:
        return _MARKER_STATUS[t.upper()]

    # Check patterns in text
    for pattern, status in _ESTIMATE_PATTERNS:
        if pattern.search(t):
            return status

    return None


def interpret_footnote_marker(marker: str, footnote_text: str | None = None) -> FootnoteMeaning:
    """Interpret a footnote marker with optional explanatory text.

    "P" → provisional
    "*" with "Provisional" text → provisional
    "#" alone → unknown/note
    """
    meaning = FootnoteMeaning(marker=marker, text=footnote_text or "")

    # Check marker directly
    status = infer_estimate_status(marker)
    if status:
        meaning.semanticMeaning = status
        meaning.confidence = 0.85
        return meaning

    # Check footnote text
    if footnote_text:
        status = infer_estimate_status(footnote_text)
        if status:
            meaning.semanticMeaning = status
            meaning.confidence = 0.75
            return meaning

        # Source note pattern
        if re.match(r'^(Source|Data\s+source)\s*[:\-]', footnote_text, re.IGNORECASE):
            meaning.semanticMeaning = "source"
            meaning.confidence = 0.90
            return meaning

    meaning.semanticMeaning = "note"
    meaning.confidence = 0.3
    return meaning


# ─────────────────────────────────────────────────────────────────────────────
# Geography level inference
# ─────────────────────────────────────────────────────────────────────────────

_GEO_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bdistrict\b', re.IGNORECASE), "district"),
    (re.compile(r'\bstate|states|ut|uts\b', re.IGNORECASE), "state_ut"),
    (re.compile(r'\bregion\b', re.IGNORECASE), "region"),
    (re.compile(r'\brural|urban\b', re.IGNORECASE), "rural_urban"),
    (re.compile(r'\ball\s+india\b', re.IGNORECASE), "all_india"),
]


def infer_geography_level(table_model: Any) -> str:
    """Infer geography level from table dimensions.

    Looks at dimension names and first-column content.
    """
    dims = []
    if hasattr(table_model, "dimensions"):
        dims = table_model.dimensions
    elif isinstance(table_model, dict):
        dims = table_model.get("dimensions") or []

    for dim in dims:
        dim_lower = dim.lower() if isinstance(dim, str) else ""
        for pattern, level in _GEO_PATTERNS:
            if pattern.search(dim_lower):
                return level

    # Check table title
    title = ""
    if hasattr(table_model, "tableTitle"):
        title = table_model.tableTitle or ""
    elif isinstance(table_model, dict):
        title = table_model.get("tableTitle") or ""

    if "statewise" in title.lower() or "state" in title.lower():
        return "state_ut"
    if "district" in title.lower():
        return "district"

    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Unit resolution with inheritance
# ─────────────────────────────────────────────────────────────────────────────


def resolve_unit_for_column(
    column: Any,
    column_group: Any | None = None,
    table_model: Any = None,
    chapter_context: ChapterContext | None = None,
) -> UnitResolution:
    """Resolve unit for a column through the inheritance chain.

    Priority (highest wins):
    1. Explicit column unit (e.g., Distribution (%) → percent)
    2. Column group unit (from parent spanning header)
    3. Table unitNote (from table title)
    4. Chapter/domain default (rare)
    5. Unknown

    Conflict: if column says "percent" but table says "million_tonnes" → column wins, conflict logged.
    """
    # Get values from various formats (dict or object)
    col_unit = _get_attr(column, "unit")
    group_unit = _get_attr(column_group, "unit") if column_group else None
    table_unit = _get_attr(table_model, "unitNote") if table_model else None

    # Priority 1: Column explicit
    if col_unit:
        result = UnitResolution(unit=col_unit, unitSource="column_header", confidence=0.95)
        # Check conflict with parent
        parent_unit = group_unit or table_unit
        if parent_unit and parent_unit != col_unit:
            result.conflict = True
            result.parentUnit = parent_unit
            result.childUnit = col_unit
            result.message = f"Column unit '{col_unit}' overrides parent '{parent_unit}'"
        return result

    # Priority 2: Column group
    if group_unit:
        return UnitResolution(unit=group_unit, unitSource="column_group", confidence=0.85)

    # Priority 3: Table unitNote
    if table_unit:
        return UnitResolution(unit=table_unit, unitSource="table_title", confidence=0.80)

    # Priority 4: Chapter context
    # (not implemented deeply yet — E4 foundation)

    return UnitResolution(unit="", unitSource="unknown", confidence=0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Table context extraction
# ─────────────────────────────────────────────────────────────────────────────


def extract_table_context(
    table_model: Any,
    page_text: str | None = None,
) -> TableContext:
    """Build TableContext from a TableSemanticModel.

    Uses table title, number, unitNote, referenceDate, footnotes, and page text.
    """
    ctx = TableContext()

    # Basic fields
    ctx.tableId = _get_attr(table_model, "tableId") or ""
    ctx.tableNumber = _get_attr(table_model, "tableNumber")
    ctx.tableTitle = _get_attr(table_model, "tableTitle") or ""
    ctx.page = _get_attr(table_model, "page")
    ctx.unitNote = _get_attr(table_model, "unitNote")
    ctx.referenceDate = _get_attr(table_model, "referenceDate")

    # Geography level
    ctx.geographyLevel = infer_geography_level(table_model)

    # Estimate status from reference date or footnote markers
    if ctx.referenceDate:
        status = infer_estimate_status(ctx.referenceDate)
        if status:
            ctx.estimateStatus = status

    # Footnote meanings
    footnotes = _get_attr(table_model, "footnotes") or []
    if isinstance(footnotes, list):
        for fn in footnotes:
            marker = fn.get("marker") if isinstance(fn, dict) else (fn.marker if hasattr(fn, "marker") else "")
            text = fn.get("text") if isinstance(fn, dict) else (fn.text if hasattr(fn, "text") else "")
            if marker:
                meaning = interpret_footnote_marker(marker, text)
                ctx.footnotes.append(meaning)
                if meaning.semanticMeaning in ("provisional", "revised", "final"):
                    ctx.estimateStatus = meaning.semanticMeaning

    # Also check column footnote markers
    columns = _get_attr(table_model, "columns") or []
    for col in columns:
        markers = col.footnoteMarkers if hasattr(col, "footnoteMarkers") else (col.get("footnoteMarkers") if isinstance(col, dict) else [])
        for m in (markers or []):
            if m.upper() in ("P", "R", "E"):
                meaning = interpret_footnote_marker(m)
                if meaning.semanticMeaning not in [f.semanticMeaning for f in ctx.footnotes]:
                    ctx.footnotes.append(meaning)

    # Source notes from page text
    if page_text:
        for line in page_text.split("\n"):
            if re.match(r'^(Source|Data\s+source|Note)\s*[:\-]', line.strip(), re.IGNORECASE):
                ctx.sourceNotes.append(line.strip())

    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Main builder
# ─────────────────────────────────────────────────────────────────────────────


def build_statistical_context(
    document_info: dict[str, Any],
    chapters: list[dict[str, Any]] | None = None,
    table_models: list[Any] | None = None,
    page_texts: list[str] | None = None,
) -> MoSPIStatisticalContext:
    """Build full statistical context from document, chapters, and table models.

    Args:
        document_info: {title, domain, ministry, year, sourceDocument}
        chapters: Optional chapter list from extraction.
        table_models: TableSemanticModel list from E3.
        page_texts: Optional per-page text for source note extraction.

    Returns:
        MoSPIStatisticalContext with everything populated.
    """
    ctx = MoSPIStatisticalContext()

    # Document level
    ctx.sourceDocument = document_info.get("sourceDocument") or document_info.get("title") or ""
    ctx.ministry = document_info.get("ministry")
    ctx.publicationYear = document_info.get("year") or document_info.get("publicationYear")
    ctx.domain = document_info.get("domain") or ""

    # Chapter contexts
    if chapters:
        for ch in chapters:
            ctx.chapters.append(ChapterContext(
                chapterId=ch.get("chapterId") or "",
                chapterNumber=ch.get("chapterNumber"),
                chapterTitle=ch.get("chapterTitle") or ch.get("title") or "",
                domain=ch.get("domain") or ctx.domain,
                tableRefs=ch.get("tableRefs") or [],
            ))

    # Table contexts + unit registry
    if table_models:
        for table in table_models:
            page = _get_attr(table, "page") or 0
            page_text = page_texts[page] if page_texts and page < len(page_texts) else None
            table_ctx = extract_table_context(table, page_text)
            ctx.tableContexts.append(table_ctx)

            # Build unit registry from columns
            columns = _get_attr(table, "columns") or []
            column_groups = _get_attr(table, "columnGroups") or []

            # Find column group for each column
            for col in columns:
                col_id = col.columnId if hasattr(col, "columnId") else (col.get("columnId") or "")
                col_unit_attr = col.unit if hasattr(col, "unit") else (col.get("unit") if isinstance(col, dict) else None)

                # Find parent group
                parent_group = None
                for g in column_groups:
                    col_refs = g.columnRefs if hasattr(g, "columnRefs") else (g.get("columnRefs") or [])
                    if col_id in col_refs:
                        parent_group = g
                        break

                resolution = resolve_unit_for_column(col, parent_group, table)

                if resolution.unit and col_id:
                    ctx.unitRegistry[col_id] = resolution.unit

                if resolution.conflict:
                    ctx.conflicts.append(ContextConflict(
                        code="UNIT_OVERRIDE",
                        severity="info",
                        tableId=_get_attr(table, "tableId"),
                        columnId=col_id,
                        parentValue=resolution.parentUnit,
                        childValue=resolution.childUnit,
                        resolution="column_wins",
                        message=resolution.message,
                    ))

    # Diagnostics
    ctx.diagnostics = {
        "tableCount": len(ctx.tableContexts),
        "unitRegistrySize": len(ctx.unitRegistry),
        "conflictCount": len(ctx.conflicts),
        "footnoteCount": sum(len(t.footnotes) for t in ctx.tableContexts),
        "sourceNoteCount": sum(len(t.sourceNotes) for t in ctx.tableContexts),
    }

    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Apply context back to tables
# ─────────────────────────────────────────────────────────────────────────────


def apply_context_to_tables(
    table_models: list[Any],
    statistical_context: MoSPIStatisticalContext,
) -> list[Any]:
    """Update table models with resolved context (units, status, geography).

    Mutates table_models in place and returns them.
    """
    # Build table context lookup
    ctx_by_id = {tc.tableId: tc for tc in statistical_context.tableContexts}

    for table in table_models:
        table_id = _get_attr(table, "tableId") or ""
        tc = ctx_by_id.get(table_id)
        if not tc:
            continue

        # Apply geography level
        if tc.geographyLevel and tc.geographyLevel != "unknown":
            if hasattr(table, "geographyLevel"):
                table.geographyLevel = tc.geographyLevel

        # Apply estimate status
        if tc.estimateStatus:
            if hasattr(table, "estimateStatus"):
                table.estimateStatus = tc.estimateStatus

        # Apply resolved units to columns from registry
        columns = _get_attr(table, "columns") or []
        for col in columns:
            col_id = col.columnId if hasattr(col, "columnId") else (col.get("columnId") or "")
            if col_id in statistical_context.unitRegistry:
                resolved_unit = statistical_context.unitRegistry[col_id]
                if hasattr(col, "unit"):
                    if not col.unit:
                        col.unit = resolved_unit
                elif isinstance(col, dict):
                    if not col.get("unit"):
                        col["unit"] = resolved_unit

    return table_models


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _get_attr(obj: Any, attr: str) -> Any:
    """Get attribute from object or dict."""
    if obj is None:
        return None
    if hasattr(obj, attr):
        return getattr(obj, attr)
    if isinstance(obj, dict):
        return obj.get(attr)
    return None
