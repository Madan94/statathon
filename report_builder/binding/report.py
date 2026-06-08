"""B6 — Coverage report (the binding gate).

Folds the entity bindings + question bindings into a single, machine-checkable
:class:`CoverageReport` plus a human-readable markdown digest.

Severity contract (decision-driven):
    * **error** — blocks the pipeline / fails CI. A question is *blocked* because a
      required non-time entity is unresolved.
    * **warn**  — surfaced, does not block. Degraded question (snapshot / widened
      filter), type mismatch, or a summed composite with no explicit total.
    * **info**  — a note. Reshape needed (memberSet/timeSeries), or an unresolved
      entity that no question actually requires.

``report.has_errors`` is the CI gate. Deterministic, offline.
"""
from __future__ import annotations

import logging
from typing import Any

from report_builder.binding.schema import (
    BindingAST,
    CoverageReport,
    EntityBinding,
    QuestionBinding,
)

logger = logging.getLogger(__name__)

_LOW_CONFIDENCE = 0.55
_RESOLVED = ("confirmed", "overridden")


# ─────────────────────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────────────────────


def build_coverage(binding: BindingAST) -> CoverageReport:
    """Compute the :class:`CoverageReport` for a bindingAST."""
    report = CoverageReport()
    _tally_entities(binding.entityBindings, report)
    _tally_questions(binding.questionBindings, report)
    # entity ids already covered by a blocked/degraded question (avoid double-report)
    covered = {
        eid
        for q in binding.questionBindings
        if q.status in ("blocked", "degraded")
        for eid in q.unresolvedEntities
    }
    _entity_issues(binding.entityBindings, report, covered)
    _question_issues(binding.questionBindings, report)
    binding.coverage = report.to_dict()
    logger.info(
        "[coverage] entities bound=%d pending=%d unresolved=%d | questions exec=%d blocked=%d degraded=%d | %d issue(s), errors=%s",
        report.entities.get("bound", 0), report.entities.get("pending", 0),
        report.entities.get("unresolved", 0), report.questions.get("executable", 0),
        report.questions.get("blocked", 0), report.questions.get("degraded", 0),
        len(report.issues), report.has_errors,
    )
    return report


def _tally_entities(bindings: list[EntityBinding], report: CoverageReport) -> None:
    bound = sum(1 for b in bindings if b.status in _RESOLVED)
    pending = sum(1 for b in bindings if b.status == "proposed")
    unresolved = sum(1 for b in bindings if b.status in ("unresolved", "rejected"))
    report.entities = {"bound": bound, "pending": pending, "unresolved": unresolved}


def _tally_questions(bindings: list[QuestionBinding], report: CoverageReport) -> None:
    report.questions = {
        "executable": sum(1 for q in bindings if q.status == "executable"),
        "blocked": sum(1 for q in bindings if q.status == "blocked"),
        "degraded": sum(1 for q in bindings if q.status == "degraded"),
    }


def _entity_issues(
    bindings: list[EntityBinding], report: CoverageReport, covered: set[str]
) -> None:
    for b in bindings:
        # Unresolved / rejected: binding-quality flags are noise (nothing is bound).
        if b.status in ("unresolved", "rejected"):
            if b.entityId not in covered:  # orphan — not required by any question
                report.add(
                    "info", "ENTITY_UNRESOLVED",
                    f"'{b.entityName or b.entityId}' ({b.entityType}) is unresolved "
                    f"but not required by any question.",
                    entity_id=b.entityId,
                )
            continue
        if b.typeMismatch:
            report.add(
                "warn", "TYPE_MISMATCH",
                f"'{b.entityName or b.entityId}' ({b.entityType}) bound to a "
                f"column of a different role — verify.",
                entity_id=b.entityId,
            )
        if b.cardinality == "composite" and b.combine == "sum":
            report.add(
                "warn", "COMPOSITE_SUMMED",
                f"'{b.entityName or b.entityId}' summed from {len(b.columns)} parts "
                f"(no explicit total) — verify the total.",
                entity_id=b.entityId,
            )
        if b.cardinality in ("memberSet", "timeSeries"):
            report.add(
                "info", "RESHAPE_NEEDED",
                f"'{b.entityName or b.entityId}' is {b.cardinality} over "
                f"{len(b.columns)} columns — wide→long reshape at execution.",
                entity_id=b.entityId,
            )
        if b.status == "proposed" and 0 < b.confidence < _LOW_CONFIDENCE:
            report.add(
                "warn", "LOW_CONFIDENCE",
                f"'{b.entityName or b.entityId}' proposed at low confidence "
                f"({b.confidence:.2f}) — review before accepting.",
                entity_id=b.entityId,
            )


def _question_issues(bindings: list[QuestionBinding], report: CoverageReport) -> None:
    for q in bindings:
        if q.status == "blocked":
            refs = ", ".join(q.unresolvedEntities) or "required entity"
            report.add(
                "error", "QUESTION_BLOCKED",
                f"Question '{q.questionId}' is not executable — unresolved: {refs}.",
                question_id=q.questionId,
            )
        elif q.status == "degraded":
            report.add(
                "warn", "QUESTION_DEGRADED",
                f"Question '{q.questionId}' runs degraded "
                f"({'; '.join(q.notes) if q.notes else 'snapshot / widened filter'}).",
                question_id=q.questionId,
            )
        if not q.resolvedRoles.time.timeResolved and q.status != "blocked":
            report.add(
                "info", "SNAPSHOT_MODE",
                f"Question '{q.questionId}' has no time column — single-period snapshot.",
                question_id=q.questionId,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Markdown digest
# ─────────────────────────────────────────────────────────────────────────────

_SEV_ICON = {"error": "🔴", "warn": "🟡", "info": "🔵"}
_SEV_ORDER = {"error": 0, "warn": 1, "info": 2}


def to_markdown(binding: BindingAST, report: CoverageReport | None = None) -> str:
    """Render a human-readable coverage digest."""
    report = report or build_coverage(binding)
    e, q = report.entities, report.questions
    gate = "❌ ERRORS — blocked" if report.has_errors else "✅ PASS"

    lines: list[str] = [
        f"# Binding Coverage — {binding.templateId or 'template'}",
        "",
        f"**Gate:** {gate}  ",
        f"**Dataset:** `{binding.datasetId}`  signature `{binding.datasetSignature}`",
        "",
        "## Entities",
        "",
        "| bound | pending | unresolved |",
        "| ----- | ------- | ---------- |",
        f"| {e.get('bound', 0)} | {e.get('pending', 0)} | {e.get('unresolved', 0)} |",
        "",
        "## Questions",
        "",
        "| executable | blocked | degraded |",
        "| ---------- | ------- | -------- |",
        f"| {q.get('executable', 0)} | {q.get('blocked', 0)} | {q.get('degraded', 0)} |",
        "",
        "## Issues",
        "",
    ]
    if not report.issues:
        lines.append("_None._")
    else:
        ordered = sorted(report.issues, key=lambda i: _SEV_ORDER.get(i.severity, 3))
        lines.append("| sev | code | where | message |")
        lines.append("| --- | ---- | ----- | ------- |")
        for i in ordered:
            where = i.entityId or i.questionId or "—"
            icon = _SEV_ICON.get(i.severity, "")
            msg = i.message.replace("|", "\\|")
            lines.append(f"| {icon} {i.severity} | `{i.code}` | `{where}` | {msg} |")
    lines.append("")
    return "\n".join(lines)
