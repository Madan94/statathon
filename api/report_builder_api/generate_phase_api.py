"""Generation-phase REST API (signature-keyed, filesystem-backed).

Thin HTTP wrapper over :mod:`report_builder.generation`. The generation core
stays free of any web dependency; this router only translates HTTP ⇄ the S4–S6
pipeline, reusing the binding-phase stash (datasetAST + blueprint + CSV) so a
report can be generated straight after ``/binding-phase/.../finalize`` without
re-uploading anything.

Endpoints (prefix ``/report-builder/generate-phase``):
  POST /{template_id}/{signature}/generate   run S4→S6, persist + return summary
  GET  /{template_id}/{signature}/report      the assembled report.output.ast.json
  GET  /{template_id}/{signature}/report.html the rendered standalone HTML

The binding must be finalized first (its confirmations live in the review record).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from report_builder.binding import review as R
from report_builder.binding.report import build_coverage
from report_builder.binding.question_binder import bind_questions
from report_builder.binding.schema import BindingAST, DatasetAST, EntityBinding
from report_builder.generation import (
    assemble_report,
    build_plans,
    fill_visuals,
    narrate,
    pdf_available,
    render_html,
    render_pdf,
    run_analytics,
    validate_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-builder/generate-phase", tags=["generate-phase"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GOLD_TEMPLATE_AST = _REPO_ROOT / "report_builder" / "gold_standard" / "template.ast.json"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class GenerateIn(BaseModel):
    period: Optional[str] = None            # reference period label, e.g. "2023-24"
    report_id: Optional[str] = None
    use_llm: Optional[bool] = None          # None ⇒ auto (on iff LLM enabled)


class GenerateOut(BaseModel):
    template_id: str
    signature: str
    report_id: str
    valid: bool
    errors: list[str]
    warnings: list[str]
    stats: dict[str, Any]
    coverage: dict[str, Any]
    narrative_trace: list[dict[str, Any]]
    fill_trace: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Stash access (shared with the binding-phase router)
# ---------------------------------------------------------------------------


def _stash_path(template_id: str, signature: str, suffix: str) -> Path:
    safe = template_id or "template"
    return R._DEFAULT_STORE / f"{safe}__{signature}.{suffix}"


def _read_stash(template_id: str, signature: str) -> tuple[DatasetAST, dict[str, Any], "Any"]:
    import pandas as pd

    ds_path = _stash_path(template_id, signature, "dataset.json")
    bp_path = _stash_path(template_id, signature, "blueprint.json")
    csv_path = _stash_path(template_id, signature, "data.csv")
    if not (ds_path.exists() and bp_path.exists() and csv_path.exists()):
        raise HTTPException(
            status_code=409,
            detail="binding session data expired — please re-run binding 'start' for this dataset",
        )
    dataset = DatasetAST.from_dict(json.loads(ds_path.read_text(encoding="utf-8")))
    blueprint = json.loads(bp_path.read_text(encoding="utf-8"))
    df = pd.read_csv(csv_path)
    return dataset, blueprint, df


def _report_path(template_id: str, signature: str) -> Path:
    return _stash_path(template_id, signature, "report.output.ast.json")


def _html_path(template_id: str, signature: str) -> Path:
    return _stash_path(template_id, signature, "report.html")


def _load_template_ast() -> dict[str, Any]:
    return json.loads(_GOLD_TEMPLATE_AST.read_text(encoding="utf-8-sig"))


def _question_meta(blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for topic in blueprint.get("topics") or []:
        for q in topic.get("questions") or []:
            qid = q.get("questionId")
            if qid:
                meta[qid] = {"label": q.get("intent") or q.get("sourceHeading") or qid}
    return meta


def _prose_config(blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ent = {e.get("entityId"): e for e in (blueprint.get("entities") or [])}

    def name(ref: Any) -> str:
        e = ent.get(ref) or {}
        return e.get("canonicalName") or e.get("name") or ""

    cfg: dict[str, dict[str, Any]] = {}
    for topic in blueprint.get("topics") or []:
        for q in topic.get("questions") or []:
            qid = q.get("questionId")
            spec = q.get("analyticsSpec") or {}
            if not qid:
                continue
            measure_ref = (spec.get("measure") or {}).get("entityRef")
            group_refs = [g.get("entityRef") for g in (spec.get("groupBy") or [])]
            agg = (spec.get("measure") or {}).get("agg") or ""
            mlabel = name(measure_ref)
            cfg[qid] = {
                "measureLabel": mlabel or qid,
                "measureShort": mlabel.split("(")[0].strip() if mlabel else "",
                "dimensionNoun": name(group_refs[0]).lower() if group_refs else "",
                "unit": (spec.get("measure") or {}).get("unit")
                or ("percent" if ("ratio" in agg or "share" in agg) else None),
            }
    return cfg


def _rebuild_binding(template_id: str, signature: str, dataset: DatasetAST,
                     blueprint: dict[str, Any], df: "Any") -> BindingAST:
    """Rebuild the finalized binding from the persisted review record + stash."""
    record = R.load_record(template_id, signature)
    if record is None:
        raise HTTPException(status_code=404, detail="no binding record — finalize binding first")
    entity_bindings = [EntityBinding.from_dict(p) for p in record.proposals]
    binding = BindingAST(
        templateId=record.templateId,
        datasetId=record.datasetId,
        datasetSignature=signature,
        entityBindings=entity_bindings,
    )
    R.apply_confirmations(binding, record)
    binding.questionBindings = bind_questions(blueprint, binding.entityBindings, dataset, df=df)
    build_coverage(binding)
    return binding


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{template_id}/{signature}/generate", response_model=GenerateOut)
def generate_report(template_id: str, signature: str, body: GenerateIn) -> GenerateOut:
    """Run the full generation pipeline (S4→S6) and persist the report.

    Reuses the binding-phase stash (datasetAST + blueprint + CSV) and the
    finalized binding (review record). Produces analyticsAST + evidenceAST →
    filled visuals + narrative → assembled ``report.output.ast.json`` (validated)
    → standalone HTML. Idempotent: overwrites the prior report for this dataset.
    """
    dataset, blueprint, df = _read_stash(template_id, signature)
    binding = _rebuild_binding(template_id, signature, dataset, blueprint, df)
    if any(i.get("severity") == "error" for i in binding.coverage.get("issues", [])):
        raise HTTPException(status_code=409, detail="binding coverage gate has errors — resolve before generating")

    template = _load_template_ast()
    context = {
        "dataset": {"title": (blueprint.get("metadata") or {}).get("title") or dataset.datasetId},
        "period": {"current": body.period or ""},
    }

    # S4 — analytics
    plans = build_plans(blueprint, binding, dataset)
    analytics_obj, evidence_obj, row_index = run_analytics(
        plans, df, question_meta=_question_meta(blueprint))
    analytics, evidence = analytics_obj.to_dict(), evidence_obj.to_dict()

    # S5a — fill visuals; S5b — narrate
    visuals = fill_visuals(template, analytics, evidence, context=context)
    narrated = narrate(template, analytics, evidence, context=context,
                       questions=_prose_config(blueprint), use_llm=body.use_llm)

    # S5c — assemble + validate
    report_id = body.report_id or f"rpt_{template_id or 'generated'}_{signature[:8]}"
    report = assemble_report(
        template,
        datasetAST=dataset,
        bindingAST=binding,
        analyticsAST=analytics,
        evidenceAST=evidence,
        visuals=visuals,
        contentAST=narrated["contentAST"],
        report_id=report_id,
        period={"current": body.period} if body.period else None,
    )
    result = validate_report(report, row_index=row_index)
    report["auditAST"]["warnings"] = result["warnings"]

    # S6 — render + persist
    html_str = render_html(report)
    _report_path(template_id, signature).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _html_path(template_id, signature).write_text(html_str, encoding="utf-8")

    logger.info("[generate-phase] %s__%s — report=%s valid=%s errors=%d",
                template_id, signature, report_id, result["ok"], len(result["errors"]))

    return GenerateOut(
        template_id=template_id,
        signature=signature,
        report_id=report_id,
        valid=result["ok"],
        errors=result["errors"],
        warnings=result["warnings"],
        stats=result["stats"],
        coverage=report["metadata"]["coverage"],
        narrative_trace=narrated["narrativeTrace"],
        fill_trace=visuals["fillTrace"],
    )


@router.get("/{template_id}/{signature}/report")
def get_report(template_id: str, signature: str) -> dict[str, Any]:
    """Return the assembled ``report.output.ast.json`` for this dataset."""
    path = _report_path(template_id, signature)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no report generated yet — call /generate first")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/{template_id}/{signature}/report.html", response_class=HTMLResponse)
def get_report_html(template_id: str, signature: str) -> HTMLResponse:
    """Return the rendered standalone HTML report."""
    path = _html_path(template_id, signature)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no report generated yet — call /generate first")
    return HTMLResponse(content=path.read_text(encoding="utf-8"))


@router.get("/{template_id}/{signature}/report.pdf")
def get_report_pdf(
    template_id: str,
    signature: str,
    engine: str = "weasyprint",
    locale: str = "en-IN",
    theme: Optional[str] = None,
) -> Response:
    """Stream the report as PDF (regenerated on demand from the stored AST).

    Document chrome (cover, TOC, provenance appendix, figure/table numbering) is
    on for the PDF deliverable. Returns ``503`` when the selected PDF engine is
    unavailable on the host (e.g. WeasyPrint native libs missing) so the caller
    can fall back to the HTML report.
    """
    path = _report_path(template_id, signature)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no report generated yet — call /generate first")

    if not pdf_available(engine):
        raise HTTPException(
            status_code=503,
            detail=f"PDF engine '{engine}' is not available on this server; use report.html instead",
        )

    report = json.loads(path.read_text(encoding="utf-8"))
    try:
        pdf_bytes = render_pdf(report, engine=engine, locale=locale, theme=theme)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not pdf_bytes:
        raise HTTPException(
            status_code=503,
            detail=f"PDF engine '{engine}' failed to produce output; use report.html instead",
        )

    report_id = (report.get("metadata") or {}).get("reportId") or "report"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{report_id}.pdf"'},
    )
