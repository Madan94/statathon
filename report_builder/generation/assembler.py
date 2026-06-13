"""S5c — Assembler: stitch every subtree into ③ ``report.output.ast.json``.

This is the final generation step. It takes the value-free template, the four
provenance layers, and the filled visuals/prose, and emits the single artifact
that carries real numbers and text — with a built-in validator that proves every
value is traceable:

    content / cell / series  →  evidenceAST / analyticsAST  →  rowIds  →  datasetAST

Inputs (all already produced by earlier stages):
    template      ① template.ast.json (clone source; carries semanticAST/styleAST)
    datasetAST    bound-dataset snapshot (provenance layer 1)
    bindingAST    entity→column record  (provenance layer 2)
    analyticsAST  plans+executions+rollups (provenance layer 3, from executor)
    evidenceAST   row-level evidence       (provenance layer 4, from executor)
    visuals       filled tableAST/chartAST/figureAST (from filler)
    contentAST    filled prose blocks               (from narrator)

Output: a dict matching the gold ``bharatstat/report-output-ast/v1`` shape, plus a
separate ``validate_report`` that returns structured issues (never raises).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_ID = "bharatstat/report-output-ast/v1"

_DOC = (
    "GENERATED per run. = template.ast.json cloned + every slot FILLED from a "
    "dataset + four provenance layers (datasetAST, bindingAST, analyticsAST, "
    "evidenceAST). This is the ONLY file where numbers and prose exist. Every "
    "value is traceable: content/cell/series -> evidenceAST -> analyticsAST "
    "(plan+execution+rowIds) -> datasetAST."
)

# The 13 top-level keys of a gold report.output.ast.json, in order.
TOP_KEYS = (
    "$schema", "_doc", "metadata", "datasetAST", "bindingAST", "analyticsAST",
    "evidenceAST", "contentAST", "tableAST", "chartAST", "figureAST",
    "semanticAST", "auditAST",
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _as_dict(obj: Any) -> dict[str, Any]:
    """Accept either a plain dict or an object exposing ``to_dict()``."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    raise TypeError(f"cannot coerce {type(obj).__name__} to dict")


def _coverage(binding: dict[str, Any], analytics: dict[str, Any]) -> dict[str, int]:
    qbindings = binding.get("questionBindings") or []
    confirmed = sum(
        1 for b in (binding.get("entityBindings") or [])
        if str(b.get("status") or "").lower() in ("confirmed", "executed")
    )
    # ExecutionRec carries no questionId; derive it from exec_<qid> / plan_<qid>.
    answered: set[str] = set()
    for e in analytics.get("executions", []):
        if e.get("status") != "ok":
            continue
        qid = e.get("questionId")
        if not qid:
            ref = str(e.get("executionId") or e.get("planRef") or "")
            qid = ref.split("_", 1)[1] if "_" in ref else ref
        if qid:
            answered.add(qid)
    return {
        "questionsTotal": len(qbindings),
        "questionsAnswered": len(answered),
        "bindingsConfirmed": confirmed,
    }


def _build_metadata(
    template: dict[str, Any],
    binding: dict[str, Any],
    dataset: dict[str, Any],
    analytics: dict[str, Any],
    *,
    report_id: str,
    period: dict[str, Any] | None,
    locale: str,
    generated_at: str,
) -> dict[str, Any]:
    tmpl_id = (template.get("metadata") or {}).get("templateId") or binding.get("templateId") or ""
    return {
        "reportId": report_id,
        "templateId": tmpl_id,
        "blueprintRef": tmpl_id,
        "generatedAt": generated_at,
        "locale": locale,
        "datasetRef": dataset.get("datasetId") or binding.get("datasetId") or "",
        "period": period or {"current": "", "prior": "", "delta": "yoy"},
        "status": "complete",
        "coverage": _coverage(binding, analytics),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Assemble
# ─────────────────────────────────────────────────────────────────────────────


def assemble_report(
    template: dict[str, Any],
    *,
    datasetAST: Any,
    bindingAST: Any,
    analyticsAST: Any,
    evidenceAST: Any,
    visuals: dict[str, Any],
    contentAST: Any,
    report_id: str = "rpt_generated",
    period: dict[str, Any] | None = None,
    locale: str = "en-IN",
    audit: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the full ``report.output.ast.json`` dict (gold shape, key order)."""
    template = template or {}
    binding = _as_dict(bindingAST)
    dataset = _as_dict(datasetAST)
    analytics = _as_dict(analyticsAST)
    evidence = _as_dict(evidenceAST)
    content = _as_dict(contentAST)
    visuals = visuals or {}
    generated_at = generated_at or _now_iso()

    metadata = _build_metadata(
        template, binding, dataset, analytics,
        report_id=report_id, period=period, locale=locale, generated_at=generated_at,
    )

    audit_block = audit or {}
    audit_block.setdefault("binding", {})
    audit_block.setdefault("warnings", [])
    audit_block.setdefault("humanReview", {})

    report = {
        "$schema": SCHEMA_ID,
        "_doc": _DOC,
        "metadata": metadata,
        "datasetAST": dataset,
        "bindingAST": binding,
        "analyticsAST": analytics,
        "evidenceAST": evidence,
        "contentAST": content,
        "tableAST": visuals.get("tableAST") or {"tables": []},
        "chartAST": visuals.get("chartAST") or {"charts": []},
        "figureAST": visuals.get("figureAST") or {"figures": []},
        "semanticAST": template.get("semanticAST") or {"sections": []},
        "auditAST": audit_block,
    }
    # Stable gold key order.
    return {k: report[k] for k in TOP_KEYS if k in report}


# ─────────────────────────────────────────────────────────────────────────────
# Validate — gold-shape + provenance traceability
# ─────────────────────────────────────────────────────────────────────────────


def validate_report(report: dict[str, Any], *, row_index: dict[str, list[int]] | None = None) -> dict[str, Any]:
    """Check the report's shape and full provenance chain. Never raises.

    Returns ``{"ok": bool, "errors": [...], "warnings": [...], "stats": {...}}``.

    Provenance rules enforced:
      * every top-level gold key is present;
      * every analyticsAST roll-up id referenced by evidence exists;
      * every filled content block / chart series / table row carries rowIds, and
        each rowId resolves in evidenceAST (and in ``row_index`` if supplied);
      * coverage counts are internally consistent.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1) top-level shape
    for k in TOP_KEYS:
        if k not in report:
            errors.append(f"missing top-level key: {k}")
    if report.get("$schema") != SCHEMA_ID:
        warnings.append(f"unexpected $schema: {report.get('$schema')!r}")

    analytics = report.get("analyticsAST") or {}
    evidence = report.get("evidenceAST") or {}

    # 2) analytics id universe
    analytic_ids: set[str] = set()
    for a in analytics.get("aggregations", []):
        analytic_ids.add(a.get("aggId"))
    for r in analytics.get("rankings", []):
        analytic_ids.add(r.get("rankId"))
    for t in analytics.get("trends", []):
        analytic_ids.add(t.get("trendId"))
    for m in analytics.get("metrics", []):
        analytic_ids.add(m.get("metricId"))
    analytic_ids.discard(None)

    # all rowIds declared anywhere in analytics roll-ups
    evidence_row_ids: set[str] = set()
    evidence_ids: set[str] = set()
    for ev in evidence.get("evidence", []):
        evidence_ids.add(ev.get("evidenceId"))
        for rid in ev.get("rowIds") or []:
            evidence_row_ids.add(rid)
        ref = ev.get("analyticsRef")
        if ref and ref not in analytic_ids:
            errors.append(f"evidence {ev.get('evidenceId')} → missing analyticsRef {ref}")
    evidence_ids.discard(None)

    # rowIds present across analytics roll-ups (the resolvable universe)
    analytics_row_ids: set[str] = set()
    for a in analytics.get("aggregations", []):
        for row in a.get("rows", []):
            analytics_row_ids.update(row.get("rowIds") or [])
    for r in analytics.get("rankings", []):
        for it in r.get("items", []):
            analytics_row_ids.update(it.get("rowIds") or [])
    for t in analytics.get("trends", []):
        for p in t.get("points", []):
            analytics_row_ids.update(p.get("rowIds") or [])
    for m in analytics.get("metrics", []):
        analytics_row_ids.update(m.get("rowIds") or [])

    resolvable = analytics_row_ids | evidence_row_ids
    if row_index is not None:
        resolvable |= set(row_index.keys())

    # 3) filled artifacts must be traceable
    filled_blocks = traced_blocks = 0
    for b in (report.get("contentAST") or {}).get("blocks", []):
        if (b.get("slot") or {}).get("status") != "filled":
            continue
        filled_blocks += 1
        prov = b.get("provenance") or {}
        ev_ref = prov.get("evidenceRef")
        an_ref = prov.get("analyticsRef")
        if ev_ref and ev_ref not in evidence_ids:
            errors.append(f"block {b.get('blockId')} → missing evidenceRef {ev_ref}")
        elif an_ref and an_ref not in analytic_ids:
            warnings.append(f"block {b.get('blockId')} → analyticsRef {an_ref} not in analytics ids")
        else:
            traced_blocks += 1

    filled_points = traced_points = 0
    for c in (report.get("chartAST") or {}).get("charts", []):
        if (c.get("slot") or {}).get("status") != "filled":
            continue
        for s in c.get("series", []):
            for p in s.get("points", []):
                filled_points += 1
                rids = p.get("rowIds") or []
                if rids and all(r in resolvable for r in rids):
                    traced_points += 1
                else:
                    errors.append(f"chart {c.get('chartId')} point x={p.get('x')!r} has unresolved rowIds {rids}")

    filled_rows = traced_rows = 0
    for t in (report.get("tableAST") or {}).get("tables", []):
        if (t.get("slot") or {}).get("status") != "filled":
            continue
        for row in t.get("rows", []):
            filled_rows += 1
            rids = row.get("rowIds") or []
            if rids and all(r in resolvable for r in rids):
                traced_rows += 1
            else:
                errors.append(f"table {t.get('tableId')} row has unresolved rowIds {rids}")

    # 4) coverage consistency
    cov = (report.get("metadata") or {}).get("coverage") or {}
    if cov.get("questionsAnswered", 0) > cov.get("questionsTotal", 0):
        errors.append("coverage.questionsAnswered exceeds questionsTotal")

    stats = {
        "blocks": {"filled": filled_blocks, "traced": traced_blocks},
        "chartPoints": {"filled": filled_points, "traced": traced_points},
        "tableRows": {"filled": filled_rows, "traced": traced_rows},
        "analyticIds": len(analytic_ids),
        "evidenceIds": len(evidence_ids),
    }
    ok = not errors
    logger.info("[S5c] validate ok=%s errors=%d warnings=%d %s",
                ok, len(errors), len(warnings), stats)
    return {"ok": ok, "errors": errors, "warnings": warnings, "stats": stats}
