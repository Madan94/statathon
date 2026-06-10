"""E3 — Table Header Semantic Compiler.

Converts pdfplumber/raw table structures into binder-ready TableSemanticModel objects.

Handles MoSPI table complexities:
- Multi-row spanning headers (Proved / 2024 / 2025)
- Wide year columns (period detection)
- Unit inheritance from table title
- headerPath for every column
- columnGroups from spanning parents
- Ghost table filtering
- Footnote marker extraction
- Serial number / total row detection

Usage:
    from report_builder.table_semantic_compiler import compile_tables, compile_table_semantics
    result = compile_tables(table_candidates, page_contexts)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class TableClass(Enum):
    REAL_TABLE = "real"
    GHOST_TABLE = "ghost"
    LAYOUT_GRID = "layout"
    FORM_BOX = "form"
    TOC_TABLE = "toc"
    INDEX_TABLE = "index"
    UNKNOWN = "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class HeaderNode:
    """One node in the header hierarchy tree."""
    text: str = ""
    rawText: str = ""
    role: str = "unknown"           # dimension | measure_group | period | unit_note | total | serial_number | unknown
    children: list["HeaderNode"] = field(default_factory=list)
    span: int = 1
    entityRef: str | None = None
    unit: str | None = None
    footnoteMarkers: list[str] = field(default_factory=list)
    level: int = 0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"text": self.text, "role": self.role, "span": self.span, "level": self.level}
        if self.unit:
            d["unit"] = self.unit
        if self.footnoteMarkers:
            d["footnoteMarkers"] = self.footnoteMarkers
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        if self.entityRef:
            d["entityRef"] = self.entityRef
        return d


@dataclass
class ColumnSpec:
    """One column in the compiled table model."""
    columnId: str = ""
    header: str = ""
    rawHeader: str = ""
    entityRef: str | None = None
    period: str | None = None
    headerPath: list[str] = field(default_factory=list)
    unit: str | None = None
    role: str = "measure"           # measure | dimension | total | serial_number | metadata
    footnoteMarkers: list[str] = field(default_factory=list)
    dtype: str | None = None
    nullRatio: float | None = None
    sourceColumn: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "columnId": self.columnId,
            "header": self.header,
            "role": self.role,
            "headerPath": list(self.headerPath),
        }
        if self.entityRef:
            d["entityRef"] = self.entityRef
        if self.period:
            d["period"] = self.period
        if self.unit:
            d["unit"] = self.unit
        if self.footnoteMarkers:
            d["footnoteMarkers"] = self.footnoteMarkers
        if self.dtype:
            d["dtype"] = self.dtype
        return d


@dataclass
class ColumnGroupSpec:
    """A spanning column group (e.g., 'Proved' spanning 2024+2025)."""
    groupId: str = ""
    label: str = ""
    entityRef: str | None = None
    periods: list[str] = field(default_factory=list)
    unit: str | None = None
    span: int = 1
    familyRef: str | None = None
    columnRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "groupId": self.groupId,
            "label": self.label,
            "span": self.span,
        }
        if self.entityRef:
            d["entityRef"] = self.entityRef
        if self.periods:
            d["periods"] = list(self.periods)
        if self.unit:
            d["unit"] = self.unit
        if self.columnRefs:
            d["columnRefs"] = list(self.columnRefs)
        if self.familyRef:
            d["familyRef"] = self.familyRef
        return d


@dataclass
class FootnoteSpec:
    """A footnote marker and its meaning."""
    marker: str = ""
    text: str = ""
    scope: str = "table"            # column | row | table | cell
    affectedColumns: list[str] = field(default_factory=list)
    semanticMeaning: str | None = None  # provisional | revised | excluded | estimated

    def to_dict(self) -> dict[str, Any]:
        return {"marker": self.marker, "text": self.text, "scope": self.scope, "semanticMeaning": self.semanticMeaning}


@dataclass
class TableSemanticModel:
    """Full semantic model for one real table."""
    tableId: str = ""
    tableTitle: str = ""
    page: int = 0
    tableNumber: str = ""
    tableClass: TableClass = TableClass.REAL_TABLE

    # Header hierarchy
    headerTree: list[HeaderNode] = field(default_factory=list)

    # Semantic roles
    dimensions: list[str] = field(default_factory=list)         # entity IDs or column names
    measures: list[str] = field(default_factory=list)
    timeDimension: str | None = None

    # Columns
    columnGroups: list[ColumnGroupSpec] = field(default_factory=list)
    columns: list[ColumnSpec] = field(default_factory=list)

    # Row metadata
    totalRowLabels: list[str] = field(default_factory=list)
    stubHierarchy: bool = False

    # Context
    unitNote: str | None = None
    footnotes: list[FootnoteSpec] = field(default_factory=list)
    sourceNote: str | None = None
    estimateStatus: str | None = None
    referenceDate: str | None = None

    # Normalization
    normalizationAdvice: str = "NONE"   # NONE | WIDE_TO_LONG | PIVOT | JOIN | UNION
    normalizationReason: str = ""
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tableId": self.tableId,
            "tableTitle": self.tableTitle,
            "page": self.page,
            "tableNumber": self.tableNumber,
            "tableClass": self.tableClass.value,
            "dimensions": list(self.dimensions),
            "measures": list(self.measures),
            "timeDimension": self.timeDimension,
            "columnGroups": [g.to_dict() for g in self.columnGroups],
            "columns": [c.to_dict() for c in self.columns],
            "totalRowLabels": list(self.totalRowLabels),
            "unitNote": self.unitNote,
            "footnotes": [f.to_dict() for f in self.footnotes],
            "sourceNote": self.sourceNote,
            "estimateStatus": self.estimateStatus,
            "referenceDate": self.referenceDate,
            "normalizationAdvice": self.normalizationAdvice,
            "normalizationReason": self.normalizationReason,
        }


@dataclass
class TableSemanticResult:
    """Batch compilation result."""
    tables: list[TableSemanticModel] = field(default_factory=list)
    ghostTables: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tableCount": len(self.tables),
            "ghostCount": len(self.ghostTables),
            "counts": dict(self.counts),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Patterns
# ─────────────────────────────────────────────────────────────────────────────

_YEAR_RE = re.compile(r'^(19|20)\d{2}(-\d{2,4})?$')
_TABLE_NUM_RE = re.compile(r'(Table|TABLE)\s+(\d+(\.\d+)?)', re.IGNORECASE)
_UNIT_PAREN_RE = re.compile(r'\((?:in\s+)?(.+?)\)\s*$')
_REFERENCE_DATE_RE = re.compile(r'\(([Aa]s\s+on\s+.+?)\)')
_FOOTNOTE_MARKER_RE = re.compile(r'([*#@†‡§¶]+|\bP\b|\bR\b|\bE\b)$')
_SERIAL_PATTERNS = re.compile(r'^(Sl\.?\s*No\.?|S\.?\s*No\.?|Sr\.?\s*No\.?|#)$', re.IGNORECASE)

_DIMENSION_KEYWORDS = frozenset({
    "state", "states", "ut", "uts", "region", "district", "sector",
    "category", "source", "fuel", "mineral", "commodity", "country",
})
_TOTAL_LABELS = frozenset({"total", "grand total", "all india", "sub-total", "sub total", "india"})

_UNIT_MAP: dict[str, str] = {
    "million tonnes": "million_tonnes",
    "mt": "million_tonnes",
    "billion cubic metres": "billion_cubic_metres",
    "bcm": "billion_cubic_metres",
    "mw": "MW",
    "gw": "GW",
    "kwh": "kWh",
    "%": "percent",
    "percentage": "percent",
    "per cent": "percent",
    "crore": "crore_inr",
    "lakh": "lakh",
    "per 1000": "per_1000",
}


# ─────────────────────────────────────────────────────────────────────────────
# Table classification
# ─────────────────────────────────────────────────────────────────────────────


def classify_table_candidate(
    table_data: dict[str, Any],
    page_context: dict[str, Any] | None = None,
) -> TableClass:
    """Classify a table candidate as REAL, GHOST, LAYOUT, etc.

    Args:
        table_data: Dict with keys like 'rows', 'cols', 'row_count', 'col_count',
                    'filled_cells', 'cells', 'title', 'bbox', etc.
        page_context: Optional page-level context (nearby headings, page number).

    Returns:
        TableClass enum value.
    """
    rows = table_data.get("rows") or table_data.get("data") or []
    row_count = table_data.get("row_count") or len(rows)
    col_count = table_data.get("col_count") or (len(rows[0]) if rows else 0)
    filled_cells = table_data.get("filled_cells") or table_data.get("filled") or 0
    total_cells = row_count * col_count if row_count and col_count else 1

    # If filled_cells not provided, count non-empty cells
    if not filled_cells and rows:
        filled_cells = sum(1 for row in rows for cell in (row if isinstance(row, list) else [row]) if cell)

    fill_ratio = filled_cells / max(total_cells, 1)

    # ── GHOST_TABLE: huge + nearly empty ──
    if total_cells > 500 and fill_ratio < 0.05:
        return TableClass.GHOST_TABLE
    if row_count > 50 and col_count > 30 and fill_ratio < 0.10:
        return TableClass.GHOST_TABLE

    # ── Too small to be meaningful ──
    if row_count < 2 or col_count < 2:
        return TableClass.UNKNOWN

    # ── TOC_TABLE: very long single column or page-number patterns ──
    if col_count <= 2 and row_count > 20:
        return TableClass.TOC_TABLE

    # ── REAL_TABLE: has content, reasonable size ──
    if fill_ratio > 0.20 and row_count >= 3 and col_count >= 2:
        return TableClass.REAL_TABLE

    # ── LAYOUT_GRID: uniform cells, no numeric content ──
    if fill_ratio > 0.50 and col_count >= 3:
        # Check if any cells look numeric
        has_numeric = False
        for row in rows[:5]:
            if isinstance(row, list):
                for cell in row[1:]:
                    if isinstance(cell, (int, float)) or (isinstance(cell, str) and re.search(r'\d+\.?\d*', cell)):
                        has_numeric = True
                        break
        if not has_numeric:
            return TableClass.LAYOUT_GRID

    if fill_ratio > 0.15:
        return TableClass.REAL_TABLE

    return TableClass.UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# Title parsing
# ─────────────────────────────────────────────────────────────────────────────


def parse_table_title(text: str) -> dict[str, str | None]:
    """Extract structured info from a table title string.

    Example: "Table 1.1: Statewise Estimated Reserves of Coal (As on 1st April 2025) (in Million Tonnes)"
    → tableNumber="Table 1.1", tableTitle="Statewise Estimated Reserves of Coal",
      referenceDate="As on 1st April 2025", unitNote="million_tonnes"
    """
    result: dict[str, str | None] = {
        "tableNumber": None, "tableTitle": None,
        "unitNote": None, "referenceDate": None,
    }
    if not text:
        return result

    working = text.strip()

    # Extract table number
    m = _TABLE_NUM_RE.search(working)
    if m:
        result["tableNumber"] = m.group(0).strip()
        working = working[m.end():].strip()
        # Remove leading colon/dash
        working = re.sub(r'^[:\-–—]\s*', '', working)

    # Extract reference date (As on ...)
    m = _REFERENCE_DATE_RE.search(working)
    if m:
        result["referenceDate"] = m.group(1).strip()
        working = working[:m.start()] + working[m.end():]
        working = working.strip()

    # Extract unit from trailing parenthetical
    m = _UNIT_PAREN_RE.search(working)
    if m:
        raw_unit = m.group(1).strip().lower()
        result["unitNote"] = _UNIT_MAP.get(raw_unit, raw_unit)
        working = working[:m.start()].strip()

    # What remains is the title
    result["tableTitle"] = working.strip() if working.strip() else text.strip()

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Footnote extraction
# ─────────────────────────────────────────────────────────────────────────────


def extract_footnote_markers(text: str) -> tuple[str, list[str]]:
    """Extract footnote markers from a header string.

    "Small Hydro Power*" → ("Small Hydro Power", ["*"])
    "Large Hydro#" → ("Large Hydro", ["#"])
    "Wind Power @ 150m" → ("Wind Power", ["@"])

    Returns (cleaned_text, markers).
    """
    markers: list[str] = []
    cleaned = text.strip()

    # Trailing markers: *, #, @, †, etc.
    m = _FOOTNOTE_MARKER_RE.search(cleaned)
    if m:
        markers.append(m.group(1))
        cleaned = cleaned[:m.start()].strip()

    # "@ NNm" pattern (Wind Power @ 150m)
    at_match = re.search(r'\s*@\s*\d+\w*$', cleaned)
    if at_match:
        markers.append("@")
        cleaned = cleaned[:at_match.start()].strip()

    return cleaned, markers


# ─────────────────────────────────────────────────────────────────────────────
# Header hierarchy parsing
# ─────────────────────────────────────────────────────────────────────────────


def parse_header_hierarchy(
    header_rows: list[list[str]],
) -> tuple[list[HeaderNode], list[list[str]]]:
    """Parse multi-row table headers into a hierarchy tree.

    Args:
        header_rows: List of header row lists (outermost = top spanning row,
                     innermost = leaf column headers).

    Returns:
        (header_nodes, header_paths) where header_paths[col_index] = ["parent", "child"]
    """
    if not header_rows:
        return [], []

    # Single row: each cell is a leaf node
    if len(header_rows) == 1:
        nodes = []
        paths: list[list[str]] = []
        for cell in header_rows[0]:
            cleaned, markers = extract_footnote_markers(str(cell).strip())
            nodes.append(HeaderNode(text=cleaned, rawText=str(cell), footnoteMarkers=markers, level=0))
            paths.append([cleaned])
        return nodes, paths

    # Multi-row: build parent→child relationships
    # Row 0 = top spanning parents, Row 1 = leaf headers (simplified 2-row model)
    # For deeper hierarchies, can be extended
    top_row = header_rows[0]
    leaf_row = header_rows[-1]
    col_count = max(len(top_row), len(leaf_row))

    # Expand rows to same length
    top_cells = list(top_row) + [""] * (col_count - len(top_row))
    leaf_cells = list(leaf_row) + [""] * (col_count - len(leaf_row))

    # Fill forward blank cells in top row (spanning)
    filled_top: list[str] = []
    last_non_empty = ""
    for cell in top_cells:
        s = str(cell).strip()
        if s:
            last_non_empty = s
        filled_top.append(last_non_empty)

    # Build paths and nodes
    nodes: list[HeaderNode] = []
    paths = []
    groups: dict[str, HeaderNode] = {}

    for i in range(col_count):
        parent_text = filled_top[i] if i < len(filled_top) else ""
        leaf_text = str(leaf_cells[i]).strip() if i < len(leaf_cells) else ""

        parent_cleaned, parent_markers = extract_footnote_markers(parent_text)
        leaf_cleaned, leaf_markers = extract_footnote_markers(leaf_text)

        # If leaf is empty, use parent as leaf
        if not leaf_cleaned:
            leaf_cleaned = parent_cleaned

        path = [parent_cleaned, leaf_cleaned] if parent_cleaned and parent_cleaned != leaf_cleaned else [leaf_cleaned]
        paths.append(path)

        # Build/find parent node
        if parent_cleaned and parent_cleaned not in groups:
            groups[parent_cleaned] = HeaderNode(
                text=parent_cleaned, rawText=parent_text,
                footnoteMarkers=parent_markers, level=0, span=0,
            )
        if parent_cleaned:
            groups[parent_cleaned].span += 1

        # Create leaf node
        leaf_node = HeaderNode(
            text=leaf_cleaned, rawText=leaf_text,
            footnoteMarkers=leaf_markers, level=1,
        )
        if parent_cleaned and parent_cleaned in groups:
            groups[parent_cleaned].children.append(leaf_node)

    nodes = list(groups.values()) if groups else [
        HeaderNode(text=str(c).strip(), rawText=str(c), level=0)
        for c in leaf_cells if str(c).strip()
    ]

    return nodes, paths


# ─────────────────────────────────────────────────────────────────────────────
# Column role inference
# ─────────────────────────────────────────────────────────────────────────────


def _infer_column_role(header: str, col_index: int, header_path: list[str]) -> str:
    """Infer column role from header text and position."""
    h_lower = header.lower().strip()

    # Serial number
    if _SERIAL_PATTERNS.match(header.strip()) or (col_index == 0 and h_lower in ("sl", "sr", "#", "s.no")):
        return "serial_number"

    # Dimension keywords
    words = re.split(r'[\s/]+', h_lower)
    if any(w in _DIMENSION_KEYWORDS for w in words):
        return "dimension"

    # Year/period as standalone column → this is a measure leaf under a group
    if _YEAR_RE.match(header.strip()):
        return "measure"

    # Total
    if h_lower in _TOTAL_LABELS:
        return "total"

    # Default: measure for numeric-looking, dimension for text
    if col_index == 0:
        return "dimension"

    return "measure"


def _normalize_unit(raw: str) -> str:
    """Normalize a raw unit string."""
    low = raw.lower().strip()
    return _UNIT_MAP.get(low, low)


# ─────────────────────────────────────────────────────────────────────────────
# Main compiler
# ─────────────────────────────────────────────────────────────────────────────


def compile_table_semantics(
    table_data: dict[str, Any],
    page_context: dict[str, Any] | None = None,
    entities: list[Any] | None = None,
) -> TableSemanticModel | None:
    """Compile one table into a TableSemanticModel.

    Args:
        table_data: Dict with 'rows', 'header_rows', 'title', 'page', 'tableId', etc.
        page_context: Optional page context (title, below-table text, etc.)
        entities: Optional canonical entities from E2 for entityRef linking.

    Returns:
        TableSemanticModel or None if ghost/invalid.
    """
    # Step 1: Classify
    table_class = classify_table_candidate(table_data, page_context)
    if table_class in (TableClass.GHOST_TABLE, TableClass.LAYOUT_GRID, TableClass.UNKNOWN):
        return None

    model = TableSemanticModel(
        tableId=table_data.get("tableId") or f"table_{table_data.get('page', 0)}",
        page=table_data.get("page") or 0,
        tableClass=table_class,
    )

    # Step 2: Parse title
    title_text = table_data.get("title") or ""
    if title_text:
        title_info = parse_table_title(title_text)
        model.tableTitle = title_info["tableTitle"] or title_text
        model.tableNumber = title_info["tableNumber"] or ""
        model.unitNote = title_info["unitNote"]
        model.referenceDate = title_info["referenceDate"]
    elif page_context and page_context.get("title"):
        title_info = parse_table_title(page_context["title"])
        model.tableTitle = title_info["tableTitle"] or ""
        model.tableNumber = title_info["tableNumber"] or ""
        model.unitNote = title_info["unitNote"]
        model.referenceDate = title_info["referenceDate"]

    # Step 3: Parse header hierarchy
    header_rows = table_data.get("header_rows") or []
    if not header_rows:
        # Try to infer from first 1-2 rows
        rows = table_data.get("rows") or []
        if rows and len(rows) >= 2:
            # Heuristic: if first row has text and second row looks like sub-headers or years
            header_rows = [rows[0]]
            if len(rows) >= 3 and _looks_like_header_row(rows[1]):
                header_rows.append(rows[1])

    header_nodes, header_paths = parse_header_hierarchy(header_rows)
    model.headerTree = header_nodes

    # Step 4: Build columns
    all_periods: list[str] = []
    col_count = len(header_paths) if header_paths else (
        table_data.get("col_count") or len(header_rows[0]) if header_rows else 0
    )

    # Build a raw header lookup for marker extraction
    raw_headers: list[str] = []
    if header_rows:
        # Use the leaf row (last header row) for raw text
        leaf_row = header_rows[-1] if len(header_rows) > 1 else header_rows[0]
        raw_headers = [str(c) for c in leaf_row]

    for i in range(col_count):
        path = header_paths[i] if i < len(header_paths) else [f"col_{i}"]
        leaf = path[-1] if path else f"col_{i}"

        # Get raw text for marker extraction (before cleaning by parse_header_hierarchy)
        raw_text = raw_headers[i] if i < len(raw_headers) else leaf
        cleaned_leaf, markers = extract_footnote_markers(raw_text.strip())

        # If parse_header_hierarchy already cleaned it, use the path leaf but keep markers
        if not markers:
            cleaned_leaf = leaf

        role = _infer_column_role(cleaned_leaf, i, path)

        # Detect period in leaf
        period = None
        if _YEAR_RE.match(cleaned_leaf.strip()):
            period = cleaned_leaf.strip()
            all_periods.append(period)

        # Determine unit for this column
        col_unit = None
        # Check if parent/path contains unit hint
        for p in path:
            if "(%)" in p or "percent" in p.lower():
                col_unit = "percent"
                break
        # Inherit from table if not set
        if not col_unit and model.unitNote and role == "measure":
            col_unit = model.unitNote

        col_spec = ColumnSpec(
            columnId=f"col_{model.tableId}_{i}",
            header=cleaned_leaf,
            rawHeader=leaf,
            period=period,
            headerPath=list(path),
            unit=col_unit,
            role=role,
            footnoteMarkers=markers,
        )
        model.columns.append(col_spec)

        # Track dimensions and measures
        if role == "dimension":
            model.dimensions.append(cleaned_leaf)
        elif role in ("measure", "total"):
            if cleaned_leaf and not _YEAR_RE.match(cleaned_leaf.strip()):
                model.measures.append(cleaned_leaf)

    # Step 5: Build column groups from header tree
    for node in header_nodes:
        if node.span >= 2 and not _YEAR_RE.match(node.text.strip()):
            # This is a spanning group
            group_unit = None
            if "(%)" in node.text or "percent" in node.text.lower():
                group_unit = "percent"
            elif model.unitNote:
                group_unit = model.unitNote

            periods_in_group = [
                c.text for c in node.children if _YEAR_RE.match(c.text.strip())
            ]

            col_refs = [
                f"col_{model.tableId}_{i}" for i, c in enumerate(model.columns)
                if c.headerPath and len(c.headerPath) > 1 and c.headerPath[0] == node.text
            ]

            group = ColumnGroupSpec(
                groupId=f"cg_{model.tableId}_{_slugify(node.text)}",
                label=node.text,
                periods=periods_in_group,
                unit=group_unit,
                span=node.span,
                columnRefs=col_refs,
            )
            model.columnGroups.append(group)

    # Step 6: Period/time detection
    if all_periods:
        model.timeDimension = "ent_period"

    # Step 7: Normalization advice
    if len(all_periods) >= 2 or len(model.columnGroups) >= 2:
        model.normalizationAdvice = "WIDE_TO_LONG"
        model.normalizationReason = f"Wide table with {len(model.columnGroups)} column groups and {len(set(all_periods))} periods"
    else:
        model.normalizationAdvice = "NONE"

    # Step 8: Total row labels
    model.totalRowLabels = list(_TOTAL_LABELS)

    # Step 9: Deduplicate measures
    model.measures = list(dict.fromkeys(model.measures))
    model.dimensions = list(dict.fromkeys(model.dimensions))

    return model


def compile_tables(
    table_candidates: list[dict[str, Any]],
    page_contexts: list[dict[str, Any]] | None = None,
    entities: list[Any] | None = None,
) -> TableSemanticResult:
    """Compile all table candidates into semantic models.

    Args:
        table_candidates: List of raw table dicts from extraction.
        page_contexts: Optional per-page context list.
        entities: Optional canonical entities for linking.

    Returns:
        TableSemanticResult with compiled tables and filtered ghosts.
    """
    result = TableSemanticResult()

    for i, table_data in enumerate(table_candidates):
        page = table_data.get("page") or 0
        page_ctx = None
        if page_contexts and page < len(page_contexts):
            page_ctx = page_contexts[page]

        table_class = classify_table_candidate(table_data)

        if table_class == TableClass.GHOST_TABLE:
            result.ghostTables.append({
                "index": i, "page": page,
                "rows": table_data.get("row_count", 0),
                "cols": table_data.get("col_count", 0),
                "reason": "ghost",
            })
            continue

        model = compile_table_semantics(table_data, page_ctx, entities)
        if model:
            result.tables.append(model)
        else:
            result.ghostTables.append({
                "index": i, "page": page, "reason": "unclassifiable",
            })

    result.counts = {
        "input": len(table_candidates),
        "real": len(result.tables),
        "ghost": len(result.ghostTables),
    }
    result.diagnostics.append(
        f"Compiled {len(result.tables)} real tables, filtered {len(result.ghostTables)} ghost/invalid"
    )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _looks_like_header_row(row: list) -> bool:
    """Check if a row looks like a sub-header (years, short labels)."""
    if not row:
        return False
    text_cells = [str(c).strip() for c in row if str(c).strip()]
    if not text_cells:
        return False
    # If most cells are years or short labels
    year_count = sum(1 for c in text_cells if _YEAR_RE.match(c))
    if year_count >= len(text_cells) * 0.5:
        return True
    # Short labels (< 15 chars each)
    if all(len(c) < 15 for c in text_cells):
        return True
    return False


def _slugify(text: str) -> str:
    """Simple slug for IDs."""
    slug = re.sub(r'[^a-z0-9]+', '_', text.lower().strip()).strip('_')
    return slug[:25] if slug else "unknown"
