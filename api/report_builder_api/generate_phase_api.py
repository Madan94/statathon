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
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from report_builder.binding import review as R
from report_builder.binding.report import build_coverage
from report_builder.binding.question_binder import bind_questions
from report_builder.binding.schema import BindingAST, DatasetAST, EntityBinding
from report_builder.generation import (
    assemble_report,
    apply_edit,
    apply_profile,
    build_plans,
    bump_version,
    current_version,
    deep_merge,
    effective_profile,
    fill_visuals,
    narrate,
    pdf_available,
    render_flags,
    render_html,
    render_pdf,
    run_analytics,
    run_execution,
    attach_insights,
    enrich_report_provenance,
    ensure_lifecycle,
    evaluate_gate,
    validate_report,
    verify_report,
    EditRejected,
    ReportOverrides,
    TemplateProfile,
)
from report_builder.binding.execution_bundle_factory import build_execution_bundle
from report_builder.binding.freeze_store import get_freeze_info, load_frozen_bundle
from report_builder.generation.bundle_adapter import adapt_bundle
from report_builder.generation.run_modes import (
    DataDriftError,
    bundle_data_hash,
    compute_data_content_hash,
    resolve_mode,
    resolve_publish_mode,
    verify_data_hash,
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
    plan_source: Optional[str] = None       # "bundle" (gold, default) | "legacy" (override; else env GENERATION_PLAN_SOURCE)
    mode: Optional[str] = None              # "fresh" (default) | "frozen" | "test" (else env GENERATION_MODE)
    bundle_version: Optional[int] = None    # frozen mode: which frozen version to load (None ⇒ latest)
    publish_mode: Optional[str] = None      # "strict" (default, FAIL→409) | "draft" (FAIL allowed, non-publishable)


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
    plan_source: str = "execution_bundle"   # which planner produced analyticsAST.plans
    mode: str = "fresh"                      # fresh | frozen | test
    data_content_hash: str = ""             # value-level hash of the executed dataset
    bundle_version: Optional[int] = None    # frozen bundle version used (when known)
    verdict: str = "PASS"                    # verifier gate: PASS | WARN | FAIL
    quality_score: float = 0.0              # report quality score 0..100
    publishable: bool = True                # False when verifier FAILed (draft mode)
    publish_mode: str = "strict"            # strict | draft


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


def _profile_path(template_id: str, signature: str) -> Path:
    return _stash_path(template_id, signature, "profile.json")


def _overrides_path(template_id: str, signature: str) -> Path:
    return _stash_path(template_id, signature, "overrides.json")


def _version_path(template_id: str, signature: str, n: int) -> Path:
    return _stash_path(template_id, signature, f"report.v{n}.output.ast.json")


def _list_versions(template_id: str, signature: str) -> list[int]:
    prefix = f"{template_id or 'template'}__{signature}.report.v"
    out: list[int] = []
    for path in R._DEFAULT_STORE.glob(f"{template_id or 'template'}__{signature}.report.v*.output.ast.json"):
        name = path.name[len(prefix):]
        num = name.split(".", 1)[0]
        if num.isdigit():
            out.append(int(num))
    return sorted(out)


def _load_profile(template_id: str, signature: str) -> dict[str, Any]:
    path = _profile_path(template_id, signature)
    if path.exists():
        return TemplateProfile.from_dict(json.loads(path.read_text(encoding="utf-8"))).to_dict()
    return TemplateProfile.default().to_dict()


def _load_overrides(template_id: str, signature: str) -> dict[str, Any]:
    path = _overrides_path(template_id, signature)
    if path.exists():
        return ReportOverrides.from_dict(json.loads(path.read_text(encoding="utf-8"))).to_dict()
    return {}


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


def _plan_source(body: GenerateIn) -> str:
    """Resolve the plan source: request override > env > default 'bundle'.

    'bundle' (gold) sources analyticsAST.plans from the team's ExecutionBundle.
    'legacy' uses the older blueprint+BindingAST planner (fallback only).
    """
    choice = (body.plan_source or os.getenv("GENERATION_PLAN_SOURCE") or "bundle").strip().lower()
    return "legacy" if choice == "legacy" else "bundle"


def _build_bundle(template_id: str, signature: str, dataset: DatasetAST,
                  blueprint: dict[str, Any], df: "Any", data_content_hash: str = ""):
    """Build the canonical ExecutionBundle for this dataset (the S4 input contract).

    Always builds from the *current* stash + review record via the single canonical
    factory, which also freezes the result for reproducibility/audit. We intentionally
    do NOT prefer a previously-frozen bundle here: a stale frozen artifact from an
    earlier blueprint/binding must never silently drive generation.

    ``data_content_hash`` (when provided) is pinned into the frozen bundle's
    ``dataframeRef`` so a later ``frozen`` run can detect data drift.
    """
    record = R.load_record(template_id, signature)
    if record is None:
        raise HTTPException(status_code=404, detail="no binding record — finalize binding first")
    df_path = str(_stash_path(template_id, signature, "data.csv"))
    return build_execution_bundle(
        template_id=template_id,
        signature=signature,
        record=record,
        dataset=dataset,
        blueprint=blueprint,
        dataframe_path=df_path,
        df=df,
        data_content_hash=data_content_hash,
    )


def _load_fixture_bundle(template_id: str, signature: str):
    """Load a fixture ExecutionBundle for ``test`` mode (deterministic regression).

    Reads ``<stash>/<template>__<signature>.bundle.json`` — a pre-built bundle laid
    down alongside the fixture dataset. ``test`` mode runs straight from this fixture
    without rebuilding (no factory/binder) or freezing (no real-storage writes), so a
    regression always executes the exact same plans over the exact same data.
    """
    from report_builder.binding.execution_contracts import ExecutionBundle

    path = _stash_path(template_id, signature, "bundle.json")
    if not path.exists():
        return None
    try:
        return ExecutionBundle.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("[generate-phase] failed to load fixture bundle %s: %s", path, exc)
        return None


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

    # S4 — analytics.
    # GOLD PATH (default): plans come from the team's validated ExecutionBundle, not a
    # re-derived planner. Readiness is honored here: NOT_READY blocks generation, and
    # the adapter never emits BLOCKED plans. LEGACY planner stays behind a flag.
    #
    # Reproducibility (generation modes): the dataset is pinned by a value-level
    # contentHash. `fresh` builds + freezes the bundle with that hash; `frozen` loads a
    # frozen bundle and refuses to run if the live data has drifted from the pinned hash.
    mode = resolve_mode(body.mode)
    data_content_hash = compute_data_content_hash(df)
    plan_source = _plan_source(body)
    bundle_version: Optional[int] = None
    bundle = None
    adapted = None
    if plan_source == "legacy":
        plans = build_plans(blueprint, binding, dataset)
        analytics_obj, evidence_obj, row_index = run_analytics(
            plans, df, question_meta=_question_meta(blueprint))
    else:
        if mode == "frozen":
            bundle = load_frozen_bundle(template_id, signature, body.bundle_version)
            if bundle is None:
                raise HTTPException(
                    status_code=404,
                    detail="no frozen bundle for this dataset — run a fresh generation first",
                )
            # Reproducibility gate: the live data must match the pinned snapshot.
            try:
                verify_data_hash(bundle, df)
            except DataDriftError as drift:
                raise HTTPException(status_code=409, detail=str(drift)) from drift
            info = get_freeze_info(template_id, signature) or {}
            bundle_version = body.bundle_version or info.get("version")
            data_content_hash = bundle_data_hash(bundle) or data_content_hash
        elif mode == "test":
            bundle = _load_fixture_bundle(template_id, signature)
            if bundle is None:
                raise HTTPException(
                    status_code=404,
                    detail="no fixture bundle for this dataset — test mode needs a .bundle.json fixture",
                )
            data_content_hash = bundle_data_hash(bundle) or data_content_hash
        else:  # fresh
            bundle = _build_bundle(template_id, signature, dataset, blueprint, df,
                                   data_content_hash=data_content_hash)
            if bundle.status == "NOT_READY":
                raise HTTPException(
                    status_code=409,
                    detail="execution bundle is NOT_READY — binding has blocking errors; resolve before generating",
                )
            info = get_freeze_info(template_id, signature) or {}
            bundle_version = info.get("version")
        # Adapt the full bundle (carries formulaSpec / normalizationPlan / lineage /
        # multi-measure fan-out) and route each plan through the S4 coordinator, which
        # applies normalization, computes formulas, and runs simple aggregations.
        adapted = adapt_bundle(bundle)
        if not adapted:
            raise HTTPException(
                status_code=409,
                detail="execution bundle has no runnable plans (all BLOCKED) — nothing to generate",
            )
        analytics_obj, evidence_obj, row_index = run_execution(
            adapted, df, question_meta=_question_meta(blueprint))
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

    # S5e — provenance + statistical-context enrichment. Closes the audit chain:
    # per-plan lineage into each artifact's provenance, coverage + dataset identity
    # under auditAST.provenance, and the bundle's StatisticalContext surfaced under
    # auditAST.statisticalContext. Additive — the gold report shape is unchanged.
    enrich_report_provenance(
        report, adapted=adapted, evidence=evidence, bundle=bundle,
        content_hash=data_content_hash,
    )

    # S5d — verify: judge trust without mutating the report's values. The verdict is
    # recorded into auditAST and then enforced by the publish gate below.
    verification = verify_report(
        report, analytics, evidence,
        bundle=bundle, adapted=adapted, dataframe=df,
        row_index=row_index, content_hash=data_content_hash,
    )
    report["auditAST"]["verification"] = verification.to_dict()

    # S5f — BI insights: evidence-backed findings derived from the trusted analytics
    # only (never the raw data). Records machine-readable objects under
    # auditAST.insights + a human "Key Findings" block. Deterministic / offline.
    attach_insights(
        report,
        quality=verification.quality,
        verifier_checks=[c.to_dict() for c in verification.checks],
    )

    # S5g — publish gate. A verifier FAIL is never publishable; in `strict` (official,
    # default) mode it blocks output with 409 and nothing is persisted, in `draft` mode
    # the report is returned but clearly marked non-publishable. WARN never blocks.
    publish_mode = resolve_publish_mode(body.publish_mode)
    gate = evaluate_gate(verification, publish_mode=publish_mode)
    report["auditAST"]["gate"] = gate.to_dict()
    report["auditAST"]["publishable"] = gate.publishable
    if gate.blocked:
        logger.warning("[generate-phase] %s__%s — BLOCKED by verifier gate: %s",
                       template_id, signature, gate.reason)
        raise HTTPException(status_code=409, detail=gate.reason)

    # S5h — lifecycle defaults: a freshly generated, publishable report starts at
    # publishStatus=generated with an empty officer-review/lifecycle audit log.
    ensure_lifecycle(report)

    # S6 — render + persist
    html_str = render_html(report)
    _report_path(template_id, signature).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _html_path(template_id, signature).write_text(html_str, encoding="utf-8")

    logger.info("[generate-phase] %s__%s — report=%s valid=%s errors=%d plans=%s mode=%s hash=%s",
                template_id, signature, report_id, result["ok"], len(result["errors"]),
                plan_source, mode, data_content_hash)

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
        plan_source="execution_bundle" if plan_source == "bundle" else "legacy_planner",
        mode=mode,
        data_content_hash=data_content_hash,
        bundle_version=bundle_version,
        verdict=verification.verdict,
        quality_score=verification.quality.get("finalScore", 0.0),
        publishable=gate.publishable,
        publish_mode=publish_mode,
    )


@router.get("/{template_id}/{signature}/report")
def get_report(
    template_id: str, signature: str, version: Optional[int] = None
) -> dict[str, Any]:
    """Return the assembled ``report.output.ast.json`` (latest, or a saved version)."""
    if version is not None:
        vpath = _version_path(template_id, signature, version)
        if not vpath.exists():
            raise HTTPException(status_code=404, detail=f"version {version} not found")
        return json.loads(vpath.read_text(encoding="utf-8"))
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


# ---------------------------------------------------------------------------
# R4 — customization (template profile + report overrides + re-render)
# ---------------------------------------------------------------------------


@router.get("/{template_id}/{signature}/profile")
def get_profile(template_id: str, signature: str) -> dict[str, Any]:
    """Return the author's template profile (defaults if none saved yet)."""
    return _load_profile(template_id, signature)


@router.put("/{template_id}/{signature}/profile")
def put_profile(
    template_id: str, signature: str, payload: dict[str, Any] = Body(default_factory=dict)
) -> dict[str, Any]:
    """Persist the author's template profile (full document of defaults)."""
    profile = TemplateProfile.from_dict(payload).to_dict()
    _profile_path(template_id, signature).write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


@router.patch("/{template_id}/{signature}/overrides")
def patch_overrides(
    template_id: str, signature: str, payload: dict[str, Any] = Body(default_factory=dict)
) -> dict[str, Any]:
    """Merge sparse viewer overrides into the stored overrides for this report."""
    current = _load_overrides(template_id, signature)
    incoming = ReportOverrides.from_dict(payload).to_dict()
    sparse = ReportOverrides.from_dict(deep_merge(current, incoming)).to_dict()
    _overrides_path(template_id, signature).write_text(
        json.dumps(sparse, ensure_ascii=False, indent=2), encoding="utf-8")
    return sparse


@router.get("/{template_id}/{signature}/overrides")
def get_overrides(template_id: str, signature: str) -> dict[str, Any]:
    """Return the sparse viewer overrides saved for this report."""
    return _load_overrides(template_id, signature)


@router.post("/{template_id}/{signature}/render")
def render_customized(
    template_id: str,
    signature: str,
    fmt: str = Query("html", alias="format"),
    engine: str = "weasyprint",
) -> Response:
    """Re-render the stored report through the effective profile (author+overrides).

    ``format=html`` (default) returns the customized standalone HTML; ``format=pdf``
    streams the customized PDF (``503`` when the engine is unavailable).
    """
    path = _report_path(template_id, signature)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no report generated yet — call /generate first")

    report = json.loads(path.read_text(encoding="utf-8"))
    eff = effective_profile(
        _load_profile(template_id, signature),
        _load_overrides(template_id, signature),
    )
    shaped = apply_profile(report, eff)
    flags = render_flags(eff)

    if fmt == "pdf":
        if not pdf_available(engine):
            raise HTTPException(
                status_code=503,
                detail=f"PDF engine '{engine}' is not available on this server; use format=html instead",
            )
        try:
            pdf_bytes = render_pdf(shaped, engine=engine, **flags)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not pdf_bytes:
            raise HTTPException(
                status_code=503,
                detail=f"PDF engine '{engine}' failed to produce output; use format=html instead",
            )
        report_id = (shaped.get("metadata") or {}).get("reportId") or "report"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{report_id}.pdf"'},
        )

    html_str = render_html(shaped, **flags)
    return HTMLResponse(content=html_str)


# ---------------------------------------------------------------------------
# R5 — editing with lock + audit + versioned report instances
# ---------------------------------------------------------------------------


class EditIn(BaseModel):
    target: dict[str, Any]                 # {kind, id, ...} — see edit._locate
    field: Optional[str] = None
    value: Any = None
    by: Optional[str] = None
    reason: Optional[str] = None


class EditOut(BaseModel):
    ok: bool
    version: int
    audit: dict[str, Any]


@router.post("/{template_id}/{signature}/edit", response_model=EditOut)
def edit_report(template_id: str, signature: str, body: EditIn) -> EditOut:
    """Apply one human edit, persist a new immutable version, return the audit entry.

    Prose edits are re-validated against the data (``400`` on a hallucinated
    number); number overrides require a ``reason`` and are flagged + audited. The
    pre-edit report is preserved as ``v1`` the first time it is edited.
    """
    path = _report_path(template_id, signature)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no report generated yet — call /generate first")
    report = json.loads(path.read_text(encoding="utf-8"))

    try:
        edited, audit = apply_edit(report, body.model_dump())
    except EditRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    versions = _list_versions(template_id, signature)
    if not versions:
        # Preserve the original as v1 before recording the first edit.
        v1 = bump_version(json.loads(json.dumps(report)), 1)
        _version_path(template_id, signature, 1).write_text(
            json.dumps(v1, ensure_ascii=False, indent=2), encoding="utf-8")
        versions = [1]

    n = max(versions) + 1
    bump_version(edited, n)
    _version_path(template_id, signature, n).write_text(
        json.dumps(edited, ensure_ascii=False, indent=2), encoding="utf-8")
    # Latest becomes the current report + re-rendered HTML.
    path.write_text(json.dumps(edited, ensure_ascii=False, indent=2), encoding="utf-8")
    _html_path(template_id, signature).write_text(render_html(edited), encoding="utf-8")

    return EditOut(ok=True, version=n, audit=audit)


@router.get("/{template_id}/{signature}/versions")
def get_versions(template_id: str, signature: str) -> dict[str, Any]:
    """List the saved version numbers (ascending); ``current`` is the latest."""
    versions = _list_versions(template_id, signature)
    path = _report_path(template_id, signature)
    current = None
    if path.exists():
        current = current_version(json.loads(path.read_text(encoding="utf-8")))
    return {"versions": versions, "current": current}
