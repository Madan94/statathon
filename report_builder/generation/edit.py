"""R5 — human editing with validation, override-audit and versioning.

``apply_edit(report, edit)`` returns ``(new_report, audit_entry)`` without
mutating the input. Edits are classified by their target:

* **prose** (a ``contentAST`` block's ``content``) — free to reword, but
  re-validated with :func:`narrator.validate_numbers` against the question's
  allowed value set, so a human cannot introduce a number the data doesn't
  support (raises :class:`EditRejected`).
* **number override** (a measured table cell, chart point or metric) — requires a
  ``reason``; records the ``old→new`` change, marks the element ``overridden`` and
  appends an entry to ``auditAST.humanReview.edits[]``.
* **free text** (caption / footnote / header / title) — applied directly, still
  audited.

Versioning is filesystem-level (handled by the API), but the version *number*
lives on ``metadata.version``; :func:`bump_version` advances it.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Optional

from .narrator import validate_numbers, _NUMBER_RE


class EditRejected(ValueError):
    """Raised when an edit violates the data contract (e.g. hallucinated number)."""

    def __init__(self, message: str, offending: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.offending = offending or []


# ---------------------------------------------------------------------------
# Allowed-value set (for prose re-validation)
# ---------------------------------------------------------------------------


def _allowed_values(report: dict[str, Any], qid: Optional[str]) -> set[float]:
    """Every number the prose for ``qid`` may state.

    Mirrors the narrator's :meth:`QuestionFacts.allowed_values` so prose the
    generator itself wrote (and validated) always re-validates on edit. That
    means the measure values and the pairwise gaps a desk officer derives from
    them, PLUS the supporting integers the narrative legitimately cites — group
    sample sizes (``n``), ranks, and filter bounds (e.g. ``age>=15`` lets an
    officer keep "persons aged 15 years and above"). Without these the firewall
    would reject the system's own sentences on the first re-edit.
    """
    vals: set[float] = set()
    measures: list[float] = []

    def add(v: Any, *, measure: bool = False) -> None:
        try:
            f = round(float(v), 1)
        except (TypeError, ValueError):
            return
        vals.add(f)
        if measure:
            measures.append(f)

    an = report.get("analyticsAST") or {}
    for agg in an.get("aggregations") or []:
        if qid and agg.get("questionId") != qid:
            continue
        for row in agg.get("rows") or []:
            add(row.get("value"), measure=True)
            add(row.get("n"))
    for rk in an.get("rankings") or []:
        if qid and rk.get("questionId") != qid:
            continue
        for item in rk.get("items") or []:
            add(item.get("value"), measure=True)
            add(item.get("rank"))
    for metric in an.get("metrics") or []:
        if qid and metric.get("questionId") != qid:
            continue
        add(metric.get("value"), measure=True)
    for tr in an.get("trends") or []:
        if qid and tr.get("questionId") != qid:
            continue
        for pt in tr.get("points") or []:
            add(pt.get("value"), measure=True)
    # Filter bounds (e.g. "age>=15" -> the officer may write "aged 15 years").
    for plan in an.get("plans") or []:
        if qid and plan.get("questionId") != qid:
            continue
        for expr in plan.get("filters") or []:
            for tok in _NUMBER_RE.findall(str(expr)):
                add(tok)

    # Allow stated differences between MEASURE values only (e.g. "a gap of 9.2
    # percentage points") — never cross-differences with the supporting
    # integers, so a hallucinated figure still can't slip through as a "gap".
    for a in measures:
        for b in measures:
            if a != b:
                add(round(a - b, 1))
    return vals


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


def _find(items: Optional[list[dict]], key: str, value: Any) -> Optional[dict]:
    for item in items or []:
        if item.get(key) == value:
            return item
    return None


def _locate(report: dict[str, Any], target: dict[str, Any]) -> tuple[Optional[dict], Optional[dict], Optional[str], bool]:
    """Resolve ``target`` → (owner_element, container, key, is_measure).

    ``container[key]`` is the editable value; ``owner`` is the element that carries
    the ``overridden`` flag. Returns ``(None, …)`` when the target can't be found.
    """
    kind = target.get("kind")
    tid = target.get("id")

    if kind == "block":
        block = _find((report.get("contentAST") or {}).get("blocks"), "blockId", tid)
        return block, block, "content", False

    if kind == "section_title":
        sec = _find((report.get("semanticAST") or {}).get("sections"), "sectionId", tid)
        return sec, sec, "title", False

    if kind == "figure_caption":
        fig = _find((report.get("figureAST") or {}).get("figures"), "figureId", tid)
        return fig, fig, "caption", False

    if kind == "chart_title":
        chart = _find((report.get("chartAST") or {}).get("charts"), "chartId", tid)
        return chart, chart, "title", False

    if kind == "chart_point":
        chart = _find((report.get("chartAST") or {}).get("charts"), "chartId", tid)
        if not chart:
            return None, None, None, False
        series = (chart.get("series") or [])
        si = int(target.get("series", 0))
        pi = int(target.get("point", 0))
        if si >= len(series):
            return None, None, None, False
        points = series[si].get("points") or []
        if pi >= len(points):
            return None, None, None, False
        return chart, points[pi], "y", True

    if kind == "metric":
        metric = _find((report.get("analyticsAST") or {}).get("metrics"), "metricId", tid)
        return metric, metric, "value", True

    if kind in ("table_cell", "table_header", "table_footnote"):
        table = _find((report.get("tableAST") or {}).get("tables"), "tableId", tid)
        if not table:
            return None, None, None, False
        if kind == "table_header":
            col = _find(table.get("columns"), "columnId", target.get("col"))
            return table, col, "header", False
        if kind == "table_footnote":
            note = _find(table.get("footnotes"), "noteId", target.get("note"))
            return table, note, "text", False
        # table_cell
        col = _find(table.get("columns"), "columnId", target.get("col"))
        is_measure = bool(col and col.get("role") == "measure")
        row = _resolve_row(table.get("rows") or [], target)
        return table, row, target.get("col"), is_measure

    return None, None, None, False


def _resolve_row(rows: list[dict], target: dict[str, Any]) -> Optional[dict]:
    if "row" in target:
        idx = int(target["row"])
        return rows[idx] if 0 <= idx < len(rows) else None
    row_ids = target.get("rowIds")
    if row_ids is not None:
        for row in rows:
            if row.get("rowIds") == row_ids:
                return row
    return None


def _flag_overridden(owner: Optional[dict], container: dict, key: Optional[str], kind: str) -> None:
    if kind == "table_cell":
        marks = container.setdefault("overridden", [])
        if isinstance(marks, list) and key not in marks:
            marks.append(key)
    else:
        container["overridden"] = True


# ---------------------------------------------------------------------------
# Audit + versioning
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_entry(field: str, old: Any, new: Any, by: str,
                 reason: Optional[str], *, overridden: bool, target: dict[str, Any]) -> dict[str, Any]:
    return {
        "field": field,
        "old": old,
        "new": new,
        "by": by,
        "at": _now(),
        "reason": reason,
        "overridden": overridden,
        "target": target,
    }


def _append_audit(report: dict[str, Any], entry: dict[str, Any]) -> None:
    audit = report.setdefault("auditAST", {})
    human = audit.setdefault("humanReview", {})
    human.setdefault("edits", []).append(entry)


def current_version(report: dict[str, Any]) -> int:
    return int((report.get("metadata") or {}).get("version") or 1)


def bump_version(report: dict[str, Any], n: int) -> dict[str, Any]:
    report.setdefault("metadata", {})["version"] = int(n)
    return report


# ---------------------------------------------------------------------------
# apply_edit
# ---------------------------------------------------------------------------


def apply_edit(report: dict[str, Any], edit: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply one edit; return ``(new_report, audit_entry)``. Never mutates input."""
    report = copy.deepcopy(report)
    target = edit.get("target") or {}
    kind = target.get("kind")
    by = edit.get("by") or "unknown"
    reason = edit.get("reason")
    value = edit.get("value")

    owner, container, key, is_measure = _locate(report, target)
    if container is None or key is None:
        raise EditRejected(f"edit target not found: {target}")

    field = edit.get("field") or (kind or "value")

    # 1) Prose — re-validate numbers.
    if kind == "block":
        qid = (owner.get("provenance") or {}).get("questionId") or owner.get("biQuery") if owner else None
        period = ((report.get("metadata") or {}).get("period") or {}).get("current") or ""
        ok, bad = validate_numbers(str(value), _allowed_values(report, qid), ignore=[period])
        if not ok:
            raise EditRejected(
                f"prose states numbers not supported by the data: {', '.join(bad)}", bad
            )
        old = container.get(key)
        container[key] = value
        entry = _audit_entry(field, old, value, by, reason, overridden=False, target=target)
        _append_audit(report, entry)
        return report, entry

    # 2) Number override — reason required, flag + audit.
    if is_measure:
        if not reason:
            raise EditRejected("number override requires a reason")
        old = container.get(key)
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise EditRejected("override value must be numeric")
        container[key] = value
        _flag_overridden(owner, container, key, kind)
        entry = _audit_entry(field, old, value, by, reason, overridden=True, target=target)
        _append_audit(report, entry)
        return report, entry

    # 3) Free text (caption / footnote / header / title).
    old = container.get(key)
    container[key] = value
    entry = _audit_entry(field, old, value, by, reason, overridden=False, target=target)
    _append_audit(report, entry)
    return report, entry
