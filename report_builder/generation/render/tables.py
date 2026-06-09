"""R1.3 — MoSPI table renderer for the render layer.

Print-correct statistical tables: multi-row column-group headers, right-aligned
measure cells with Indian-grouped/percent formatting, **bold subtotal/total
rows**, em-dash for blanks, footnotes with markers, and a header that repeats on
every printed page (via ``display:table-header-group`` from the theme CSS).

Reads only the §0 ``tableAST`` contract::

    table {tableId, title, columnGroups[]{groupId,label,spanRefs[]},
           columns[]{columnId,header,role,entityRef,group?,unit?,format?,align},
           rows[]{<colId>:value, rowIds[], isTotal?/isSubtotal?},
           footnotes[]{noteId,text}}

Subtotal detection is **opt-in** (a row flag or a configurable matcher on the
first dimension value), so existing reports without totals are unchanged.
"""
from __future__ import annotations

from typing import Any, Callable

from .numbers import esc, format_value, loc

# Default phrases that mark an aggregate row when no explicit flag is present.
_DEFAULT_TOTAL_LABELS = frozenset({
    "all-india", "all india", "total", "grand total", "overall", "india",
})


def _is_measure(col: dict[str, Any]) -> bool:
    return col.get("role") == "measure"


def _align_class(col: dict[str, Any]) -> str:
    align = col.get("align")
    if align == "right" or _is_measure(col):
        return "measure"
    if align == "center":
        return "center"
    return ""


def _row_is_total(row: dict[str, Any], columns: list[dict[str, Any]],
                  matcher: Callable[[dict[str, Any]], bool] | None) -> bool:
    if row.get("isTotal") or row.get("isSubtotal"):
        return True
    if matcher is not None:
        return bool(matcher(row))
    # Fallback: first dimension cell matches a known total label.
    for col in columns:
        if not _is_measure(col):
            val = row.get(col.get("columnId"))
            if isinstance(val, str) and val.strip().lower() in _DEFAULT_TOTAL_LABELS:
                return True
            break
    return False


def _group_header_row(columns: list[dict[str, Any]],
                      groups: list[dict[str, Any]],
                      locale: str = "en-IN") -> str:
    """Top header row spanning column groups (e.g. Rural / Urban)."""
    group_of: dict[str, dict[str, Any]] = {}
    for g in groups:
        for ref in g.get("spanRefs") or []:
            group_of[ref] = g
    parts = ['<tr class="colgroup-head">']
    i = 0
    while i < len(columns):
        col = columns[i]
        g = group_of.get(col.get("columnId"))
        if g:
            span = len(g.get("spanRefs") or []) or 1
            parts.append(f'<th colspan="{span}">{esc(loc(g.get("label"), locale))}</th>')
            i += span
        else:
            parts.append("<th></th>")
            i += 1
    parts.append("</tr>")
    return "".join(parts)


def render_table(
    table: dict[str, Any],
    theme: Any = None,  # accepted for API symmetry; styling comes from theme CSS
    *,
    locale: str = "en-IN",
    number_system: str = "indian",
    empty: str = "\u2014",
    total_matcher: Callable[[dict[str, Any]], bool] | None = None,
) -> str:
    """Render a ``tableAST`` table to print-correct HTML."""
    columns = table.get("columns") or []
    groups = table.get("columnGroups") or []
    rows = table.get("rows") or []
    title = table.get("title")

    if not columns:
        return '<div class="empty-slot">[table has no columns]</div>'

    parts = ['<table class="data-table">']
    if title:
        parts.append(f"<caption>{esc(loc(title, locale))}</caption>")

    # <thead> is marked repeatable by theme CSS (table-header-group) for print.
    parts.append("<thead>")
    if groups:
        parts.append(_group_header_row(columns, groups, locale))
    parts.append("<tr>")
    for col in columns:
        cls = _align_class(col)
        scope = ' scope="col"'
        parts.append(f'<th class="{cls}"{scope}>{esc(loc(col.get("header"), locale))}</th>')
    parts.append("</tr></thead>")

    parts.append("<tbody>")
    for row in rows:
        is_total = _row_is_total(row, columns, total_matcher)
        tr_cls = ' class="subtotal"' if is_total else ""
        parts.append(f"<tr{tr_cls}>")
        for col in columns:
            cid = col.get("columnId")
            cls = _align_class(col)
            raw = row.get(cid)
            if _is_measure(col):
                val = format_value(
                    raw, unit=col.get("unit"), fmt=col.get("format"),
                    system=number_system, locale=locale, empty=empty,
                )
            else:
                val = esc(loc(raw, locale)) if raw is not None else empty
            parts.append(f'<td class="{cls}">{val}</td>')
        parts.append("</tr>")
    parts.append("</tbody></table>")

    # Footnotes with source/note markers.
    notes = [fn for fn in (table.get("footnotes") or []) if fn.get("text")]
    if notes:
        parts.append('<ul class="footnotes">')
        for fn in notes:
            nid = (fn.get("noteId") or "").lower()
            raw_text = loc(fn.get("text"), locale)
            marker = ""
            if "source" in nid:
                marker = '<span class="fn-marker">Source:</span> '
            elif "note" in nid:
                marker = '<span class="fn-marker">Note:</span> '
            text = esc(raw_text)
            # Avoid doubling 'Source:'/'Note:' if the text already starts with it.
            low = raw_text.strip().lower()
            if low.startswith("source:") or low.startswith("note:"):
                marker = ""
            parts.append(f'<li>{marker}{text}</li>')
        parts.append("</ul>")
    return "".join(parts)
