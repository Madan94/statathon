"""TC1 — Table Candidate Adapter.

Converts extraction pipeline table data (Pass 0 pdfplumber + Pass 2.5 table_structures)
into the format expected by E3 table_semantic_compiler.compile_table_semantics().

The adapter is defensive: unknown shapes produce empty list, never throws.

Usage:
    from report_builder.table_candidate_adapter import table_candidates_from_pipeline
    candidates = table_candidates_from_pipeline(table_structures=doc_map["table_structures"], page_texts=page_texts)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def table_candidates_from_pipeline(
    *,
    table_structures: list[dict[str, Any]] | None = None,
    page_texts: list[dict[str, Any]] | None = None,
    ast_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Convert pipeline table data into E3-compatible table candidates.

    Sources (priority order):
    1. table_structures from Pass 2.5 document_map (richest metadata)
    2. page_texts[page]["tables"] from Pass 0 pdfplumber (raw row data)
    3. ast_result tableAST (fallback, minimal)

    Each output candidate has:
        tableId, page, title, row_count, col_count, filled_cells,
        header_rows (actual row data if available), source
    """
    candidates: list[dict[str, Any]] = []

    try:
        if table_structures:
            candidates = _from_table_structures(table_structures, page_texts)
        elif page_texts:
            candidates = _from_page_texts(page_texts)
        elif ast_result:
            candidates = _from_ast(ast_result)
    except Exception as e:
        logger.warning("[table_candidate_adapter] Failed (returning empty): %s", e)
        return []

    return candidates


def _from_table_structures(
    structures: list[dict[str, Any]],
    page_texts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Convert Pass 2.5 table_structures into E3 candidates.

    Pass 2.5 shape:
        tableId, page, columns[], columnGroups[], dimensions[], measures[],
        row_count, headerRows (int count), tableTitle, layout

    E3 expects:
        tableId, page, title, row_count, col_count, filled_cells,
        header_rows (list[list[str]]), source
    """
    candidates: list[dict[str, Any]] = []

    for ts in structures:
        page = ts.get("page") or 0
        columns = ts.get("columns") or []
        col_count = len(columns)
        row_count = ts.get("row_count") or 0
        title = ts.get("tableTitle") or ts.get("description") or ""
        table_id = ts.get("tableId") or f"tbl_p{page}"

        # pass2_5 tables with title but 0 row_count are real tables whose row count
        # wasn't stored. Set minimum to 10 so E3 doesn't reject them.
        if row_count == 0 and title and col_count >= 3:
            row_count = 10  # Reasonable default for MoSPI tables

        # Try to get actual header rows from pdfplumber raw data
        header_rows = _extract_header_rows_from_page(page, page_texts, ts)

        # If no raw header rows, construct from columns metadata
        if not header_rows and columns:
            header_rows = [columns]
            # If columnGroups exist, try to build multi-row header
            col_groups = ts.get("columnGroups") or []
            if col_groups:
                parent_row = _build_parent_row_from_groups(col_groups, col_count)
                if parent_row:
                    header_rows = [parent_row, columns]

        # Compute filled_cells estimate
        filled_cells = row_count * col_count if row_count and col_count else 0
        # Adjust: if we know about ghost tables, row_count*col_count is already reasonable
        if row_count >= 3 and col_count >= 2:
            filled_cells = max(filled_cells, row_count * col_count * 7 // 10)

        candidate: dict[str, Any] = {
            "tableId": table_id,
            "page": page,
            "title": title,
            "row_count": row_count,
            "col_count": col_count,
            "filled_cells": filled_cells,
            "header_rows": header_rows,
            "columns": columns,
            "source": "table_structure",
        }

        # Preserve Pass 2.5 metadata for E3 enrichment
        if ts.get("dimensions"):
            candidate["_dimensions"] = ts["dimensions"]
        if ts.get("measures"):
            candidate["_measures"] = ts["measures"]
        if ts.get("columnGroups"):
            candidate["_columnGroups"] = ts["columnGroups"]

        candidates.append(candidate)

    return candidates


def _from_page_texts(page_texts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract table candidates directly from pdfplumber page_texts.

    Each page_texts[i]["tables"] is a list of tables (list[list[str|None]]).
    """
    candidates: list[dict[str, Any]] = []

    for page_idx, pt in enumerate(page_texts):
        tables = pt.get("tables") or []
        for t_idx, table in enumerate(tables):
            if not table or not isinstance(table, list):
                continue

            row_count = len(table)
            col_count = len(table[0]) if table else 0
            filled_cells = sum(1 for row in table for cell in row if cell)

            # Skip tiny/ghost tables
            if row_count < 3 or col_count < 2:
                continue
            if filled_cells < row_count:
                continue

            # First 1-2 rows as header
            header_rows = [table[0]]
            if row_count >= 3 and _looks_like_subheader(table[1], table[0]):
                header_rows.append(table[1])

            candidates.append({
                "tableId": f"tbl_p{page_idx}_{t_idx}",
                "page": page_idx,
                "title": "",
                "row_count": row_count,
                "col_count": col_count,
                "filled_cells": filled_cells,
                "header_rows": header_rows,
                "source": "pdfplumber",
            })

    return candidates


def _from_ast(ast_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Fallback: extract minimal candidates from AST tableAST."""
    candidates: list[dict[str, Any]] = []
    table_ast = ast_result.get("tableAST") or {}
    for table in (table_ast.get("tables") or []):
        tid = table.get("tableId") or ""
        if tid:
            candidates.append({
                "tableId": tid,
                "page": 0,
                "title": "",
                "row_count": 5,
                "col_count": 5,
                "filled_cells": 20,
                "header_rows": [],
                "source": "ast_fallback",
            })
    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _extract_header_rows_from_page(
    page: int,
    page_texts: list[dict[str, Any]] | None,
    table_structure: dict[str, Any],
) -> list[list[str]]:
    """Try to extract actual header rows from pdfplumber raw table on a given page.

    Uses the headerRows count from table_structure to determine how many rows.
    """
    if not page_texts or page >= len(page_texts):
        return []

    pt = page_texts[page]
    tables = pt.get("tables") or []
    if not tables:
        return []

    # Find the best matching raw table (by column count match)
    expected_cols = len(table_structure.get("columns") or [])
    header_count = table_structure.get("headerRows") or 1

    for raw_table in tables:
        if not raw_table or not isinstance(raw_table, list):
            continue
        raw_cols = len(raw_table[0]) if raw_table else 0
        # Match by column count (allow +/- 1 for edge merges)
        if expected_cols and abs(raw_cols - expected_cols) <= 1:
            # Extract header rows
            rows = []
            for row in raw_table[:min(header_count, 3)]:
                rows.append([str(cell) if cell is not None else "" for cell in row])
            return rows

    # Fallback: use first table on that page
    if tables:
        raw_table = tables[0]
        if isinstance(raw_table, list) and raw_table:
            rows = []
            for row in raw_table[:min(header_count, 2)]:
                rows.append([str(cell) if cell is not None else "" for cell in row])
            return rows

    return []


def _build_parent_row_from_groups(
    column_groups: list[dict[str, Any]],
    col_count: int,
) -> list[str]:
    """Build a parent spanning header row from columnGroups metadata.

    Example: columnGroups = [{"label": "Proved", "span": 2}, {"label": "Indicated", "span": 2}]
    → ["Proved", "Proved", "Indicated", "Indicated"]
    """
    if not column_groups:
        return []

    row: list[str] = []
    for group in column_groups:
        label = group.get("label") or ""
        span = group.get("span") or group.get("count") or 1
        row.extend([label] * span)

    # Pad or truncate to col_count
    if len(row) < col_count:
        # Prepend empty cells for dimension column(s)
        row = [""] * (col_count - len(row)) + row

    return row[:col_count]


def _looks_like_subheader(row: list, first_row: list) -> bool:
    """Heuristic: does the second row look like a sub-header (years, short labels)?"""
    if not row:
        return False
    import re
    year_re = re.compile(r'^(19|20)\d{2}(-\d{2,4})?$')
    text_cells = [str(c).strip() for c in row if c]
    if not text_cells:
        return False
    year_count = sum(1 for c in text_cells if year_re.match(c))
    if year_count >= len(text_cells) * 0.4:
        return True
    if all(len(str(c)) < 12 for c in text_cells):
        return True
    return False
