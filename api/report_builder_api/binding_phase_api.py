"""Binding-phase REST API (signature-keyed, filesystem-backed).

Thin HTTP wrapper over :mod:`report_builder.binding.review`. The binding core
stays free of any web dependency; this router only translates HTTP ⇄ the review
state machine.

Endpoints (prefix ``/report-builder/binding-phase``):
  GET  /{template_id}/{signature}/proposals   S1 proposals + live statuses
  POST /{template_id}/{signature}/confirm      record one confirm/override/reject
  GET  /{template_id}/{signature}              full review record

Note: distinct from the legacy job-id ``/report-builder/bindings`` router; this
one is the value-free binding-phase (datasetAST + bindingAST) review surface.
"""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from report_builder.binding import review as R
from report_builder.binding.report import build_coverage
from report_builder.binding.question_binder import bind_questions
from report_builder.binding.schema import BindingAST, DatasetAST, EntityBinding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-builder/binding-phase", tags=["binding-phase"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GOLD_BLUEPRINT = _REPO_ROOT / "report_builder" / "gold_standard" / "template.blueprint.json"
# Built-in template ids that map to the bundled gold PLFS blueprint (zero-config demo path).
_GOLD_TEMPLATE_IDS = {"tpl_plfs_annual_v1", "gold", "default", ""}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ConfirmIn(BaseModel):
    entity_id: str
    action: str = "confirm"                 # confirm | override | reject
    columns: Optional[list[str]] = None     # override columns
    note: Optional[str] = None


class ProposalsOut(BaseModel):
    template_id: str
    signature: str
    dataset_id: str
    proposals: list[dict[str, Any]]
    confirmations: dict[str, dict[str, Any]]
    pending: list[str]


class RecordOut(BaseModel):
    template_id: str
    signature: str
    dataset_id: str
    proposals: list[dict[str, Any]]
    confirmations: dict[str, dict[str, Any]]
    updated_at: float


class StartOut(BaseModel):
    template_id: str
    signature: str
    dataset_id: str
    dataset_ast: dict[str, Any]
    proposals: list[dict[str, Any]]
    confirmations: dict[str, dict[str, Any]]
    pending: list[str]


class FinalizeOut(BaseModel):
    template_id: str
    signature: str
    coverage: dict[str, Any]
    question_bindings: list[dict[str, Any]]
    binding_ast: dict[str, Any]
    has_errors: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_or_404(template_id: str, signature: str) -> R.ReviewRecord:
    record = R.load_record(template_id, signature)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"no binding review for {template_id}__{signature}",
        )
    return record


def _pending_ids(record: R.ReviewRecord) -> list[str]:
    """Entity ids still needing a decision (proposed/unresolved & not yet confirmed)."""
    pending: list[str] = []
    for prop in record.proposals:
        eid = str(prop.get("entityId") or "")
        status = str(prop.get("status") or "")
        if eid and status in ("proposed", "unresolved") and eid not in record.confirmations:
            pending.append(eid)
    return pending


# ---------------------------------------------------------------------------
# Stash — the review record persists proposals/confirmations only, so the
# orchestrator co-locates the datasetAST + blueprint + a CSV copy next to it so
# /finalize can re-run S3 (question binding) + coverage without re-uploading.
# ---------------------------------------------------------------------------


def _stash_path(template_id: str, signature: str, suffix: str) -> Path:
    safe = template_id or "template"
    return R._DEFAULT_STORE / f"{safe}__{signature}.{suffix}"


def _write_stash(
    template_id: str, signature: str, dataset: DatasetAST, blueprint: dict[str, Any], csv_bytes: bytes
) -> None:
    R._DEFAULT_STORE.mkdir(parents=True, exist_ok=True)
    _stash_path(template_id, signature, "dataset.json").write_text(
        json.dumps(dataset.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    _stash_path(template_id, signature, "blueprint.json").write_text(
        json.dumps(blueprint, ensure_ascii=False), encoding="utf-8"
    )
    _stash_path(template_id, signature, "data.csv").write_bytes(csv_bytes)


def _read_stash(template_id: str, signature: str) -> tuple[DatasetAST, dict[str, Any], "Any"]:
    import pandas as pd

    ds_path = _stash_path(template_id, signature, "dataset.json")
    bp_path = _stash_path(template_id, signature, "blueprint.json")
    csv_path = _stash_path(template_id, signature, "data.csv")
    if not (ds_path.exists() and bp_path.exists() and csv_path.exists()):
        raise HTTPException(
            status_code=409,
            detail="binding session data expired — please re-run 'start' for this dataset",
        )
    dataset = DatasetAST.from_dict(json.loads(ds_path.read_text(encoding="utf-8")))
    blueprint = json.loads(bp_path.read_text(encoding="utf-8"))
    df = pd.read_csv(csv_path)
    return dataset, blueprint, df


async def _resolve_blueprint(template_id: str, blueprint_file: Optional[UploadFile]) -> dict[str, Any]:
    """Blueprint source priority: uploaded file → DB template → bundled gold.

    For DB-stored templates (numeric IDs), loads blueprint from the template's
    ast_json.blueprint field — no manual upload needed after extraction.
    """
    # 1. Explicit upload takes priority
    if blueprint_file is not None:
        raw = await blueprint_file.read()
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail=f"invalid blueprint JSON: {exc}") from exc

    # 2. Try loading from DB if template_id is numeric (extracted template)
    if template_id.isdigit():
        try:
            from database.database import SessionLocal
            from database.models import ReportTemplate
            db = SessionLocal()
            try:
                tpl = db.query(ReportTemplate).filter(ReportTemplate.id == int(template_id)).first()
                if tpl and tpl.ast_json:
                    ast_json = tpl.ast_json if isinstance(tpl.ast_json, dict) else {}
                    # Blueprint lives at ast_json.blueprint
                    bp = ast_json.get("blueprint")
                    if bp and isinstance(bp, dict) and bp.get("entities"):
                        logger.info("[binding-phase] Blueprint auto-loaded from DB template %s", template_id)
                        return bp
            finally:
                db.close()
        except Exception as exc:
            logger.warning("[binding-phase] DB blueprint load failed for %s: %s", template_id, exc)

    # 3. Bundled gold templates
    if template_id in _GOLD_TEMPLATE_IDS:
        return json.loads(_GOLD_BLUEPRINT.read_text(encoding="utf-8"))

    raise HTTPException(
        status_code=400,
        detail=f"no blueprint for template '{template_id}' — upload a blueprint.json, use a numeric template ID, or use a built-in id",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/start", response_model=StartOut)
async def start_binding(
    template_id: str = Form("tpl_plfs_annual_v1"),
    dataset: UploadFile = File(...),
    blueprint: Optional[UploadFile] = File(None),
) -> StartOut:
    """Begin a binding session: profile the dataset (S0) + propose entity bindings (S1).

    Persists a review record (so the confirm endpoints work) and stashes the
    datasetAST + blueprint + CSV so ``/finalize`` can re-run S3 + coverage. The
    blueprint comes from the uploaded ``blueprint`` file, or the bundled gold
    PLFS blueprint for a built-in ``template_id``.
    """
    import pandas as pd

    from report_builder.binding.profiler import profile_dataframe
    from report_builder.binding.resolver import resolve_entities

    bp = await _resolve_blueprint(template_id, blueprint)
    raw = await dataset.read()
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001 — surface any parse failure to the client
        raise HTTPException(status_code=400, detail=f"could not read CSV: {exc}") from exc
    if df.empty:
        raise HTTPException(status_code=400, detail="dataset has no rows")

    dataset_id = Path(dataset.filename or "dataset").stem
    profile = profile_dataframe(df, dataset_id=dataset_id, source_file=dataset.filename or "")
    entity_bindings = resolve_entities(bp.get("entities") or [], profile)

    signature = R.dataset_signature(profile)
    binding = BindingAST(
        templateId=template_id or "template",
        datasetId=profile.datasetId,
        datasetSignature=signature,
        entityBindings=entity_bindings,
    )
    binding, record, _deltas = R.open_review(binding, profile)
    R.save_record(record)
    _write_stash(binding.templateId, signature, profile, bp, raw)

    logger.info(
        "[binding-phase] start %s__%s — %d entities proposed (%d pending)",
        binding.templateId, signature, len(entity_bindings), len(_pending_ids(record)),
    )
    return StartOut(
        template_id=binding.templateId,
        signature=signature,
        dataset_id=profile.datasetId,
        dataset_ast=profile.to_dict(),
        proposals=record.proposals,
        confirmations={k: v.to_dict() for k, v in record.confirmations.items()},
        pending=_pending_ids(record),
    )


@router.get("/{template_id}/{signature}/proposals", response_model=ProposalsOut)
def get_proposals(template_id: str, signature: str) -> ProposalsOut:
    """Return the S1 proposals plus any confirmations recorded so far."""
    record = _load_or_404(template_id, signature)
    return ProposalsOut(
        template_id=record.templateId,
        signature=record.datasetSignature,
        dataset_id=record.datasetId,
        proposals=record.proposals,
        confirmations={k: v.to_dict() for k, v in record.confirmations.items()},
        pending=_pending_ids(record),
    )


@router.post("/{template_id}/{signature}/confirm", response_model=RecordOut)
def post_confirm(template_id: str, signature: str, body: ConfirmIn) -> RecordOut:
    """Record one human decision (confirm / override / reject) and persist it."""
    record = _load_or_404(template_id, signature)
    action = body.action.lower()
    if action == "reject":
        R.reject(record, body.entity_id, note=body.note or "")
    elif action in ("confirm", "override"):
        R.confirm(record, body.entity_id, columns=body.columns, note=body.note or "")
    else:
        raise HTTPException(status_code=400, detail=f"unknown action '{body.action}'")

    path = R.save_record(record)
    logger.info("[binding-phase] %s %s on %s → %s",
                action, body.entity_id, signature, path.name)
    return RecordOut(
        template_id=record.templateId,
        signature=record.datasetSignature,
        dataset_id=record.datasetId,
        proposals=record.proposals,
        confirmations={k: v.to_dict() for k, v in record.confirmations.items()},
        updated_at=record.updatedAt,
    )


@router.get("/{template_id}/{signature}", response_model=RecordOut)
def get_record(template_id: str, signature: str) -> RecordOut:
    """Return the full persisted review record."""
    record = _load_or_404(template_id, signature)
    return RecordOut(
        template_id=record.templateId,
        signature=record.datasetSignature,
        dataset_id=record.datasetId,
        proposals=record.proposals,
        confirmations={k: v.to_dict() for k, v in record.confirmations.items()},
        updated_at=record.updatedAt,
    )


@router.post("/{template_id}/{signature}/finalize", response_model=FinalizeOut)
def finalize_binding(template_id: str, signature: str) -> FinalizeOut:
    """Apply confirmations, resolve every question (S3), and compute coverage (B6).

    Rebuilds the binding from the stored proposals + confirmations, then re-runs
    question binding against the stashed datasetAST + CSV. Returns the coverage
    gate and the full bindingAST. Idempotent — safe to call after each change.
    """
    record = _load_or_404(template_id, signature)
    dataset, blueprint, df = _read_stash(template_id, signature)

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

    has_errors = any(i.get("severity") == "error" for i in binding.coverage.get("issues", []))
    logger.info(
        "[binding-phase] finalize %s__%s — gate=%s",
        record.templateId, signature, "ERRORS" if has_errors else "PASS",
    )
    return FinalizeOut(
        template_id=record.templateId,
        signature=signature,
        coverage=binding.coverage,
        question_bindings=[q.to_dict() for q in binding.questionBindings],
        binding_ast=binding.to_dict(),
        has_errors=has_errors,
    )


# ─────────────────────────────────────────────────────────────────────────────
# S4 HANDOFF: Execution-Ready Endpoint
# ─────────────────────────────────────────────────────────────────────────────
# This is the S4 team's ONLY input contract.
# Returns a validated ExecutionBundle or NOT_READY with diagnostics.


class ExecutionReadyOut(BaseModel):
    contract_version: str
    template_id: str
    dataset_id: str
    binding_ast_id: str
    status: str  # READY | NOT_READY | DEGRADED
    dataset_ast: dict
    binding_ast: dict
    statistical_context: dict
    plans: list[dict]
    blocked_questions: list[dict]
    readiness_report: dict
    dataframe_ref: dict
    lineage_index: dict
    frozen_at: str


@router.get("/{template_id}/{signature}/execution-ready", response_model=ExecutionReadyOut)
def get_execution_bundle(template_id: str, signature: str) -> ExecutionReadyOut:
    """S4 Handoff: Return the validated ExecutionBundle for downstream execution.

    This is the S4 team's only input. Contains everything needed to execute
    analytics without interpretation: confirmed bindings, execution plans,
    normalization recipes, formula specs, output contracts, and lineage.

    Returns NOT_READY if the binding gate has errors.
    """
    from report_builder.binding.execution_contracts import (
        ExecutionBundle,
        ExecutionReadinessReport,
        QuestionExecutionPlan,
        StatisticalContext,
        FormulaSpec,
        NormalizationPlan,
        LineageRef,
    )
    from report_builder.binding.schema import ResolvedRoles

    record = _load_or_404(template_id, signature)
    dataset, blueprint, df = _read_stash(template_id, signature)

    # Re-run finalization to get current state
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

    has_errors = any(i.get("severity") == "error" for i in binding.coverage.get("issues", []))

    # Build execution plans from question bindings
    plans: list[QuestionExecutionPlan] = []
    blocked: list[dict] = []

    for qb in binding.questionBindings:
        if qb.status == "blocked":
            blocked.append({"questionId": qb.questionId, "reason": "; ".join(qb.notes), "unresolvedEntities": qb.unresolvedEntities})
            continue

        # Find the matching blueprint question for analyticsSpec + outputContract
        bp_question = None
        for topic in (blueprint.get("topics") or []):
            for q in (topic.get("questions") or []):
                if q.get("questionId") == qb.questionId:
                    bp_question = q
                    break
            if bp_question:
                break

        # Build the plan
        analytics_spec = (bp_question or {}).get("analyticsSpec", {})
        answer_structure = (bp_question or {}).get("answerStructure", {})
        output_contract = answer_structure.get("components", []) if isinstance(answer_structure, dict) else []
        required_entities = (bp_question or {}).get("requiredEntities", [])

        # Determine formula type from analyticsSpec
        operation = analytics_spec.get("operation", "group_aggregate")
        formula_type = "DIRECT"
        if operation in ("growth", "derive") or "growth" in (bp_question or {}).get("questionText", "").lower():
            formula_type = "GROWTH"
        elif "share" in (bp_question or {}).get("questionText", "").lower() or "distribution" in (bp_question or {}).get("questionText", "").lower():
            formula_type = "SHARE"
        elif "rate" in (bp_question or {}).get("questionText", "").lower():
            formula_type = "RATE"

        plan = QuestionExecutionPlan(
            planId=f"plan_{qb.questionId}",
            questionId=qb.questionId,
            questionText=(bp_question or {}).get("questionText") or (bp_question or {}).get("intent", ""),
            status="EXECUTABLE" if qb.status == "executable" else "DEGRADED",
            analyticsSpec=analytics_spec,
            resolvedRoles=qb.resolvedRoles,
            normalizationPlan=NormalizationPlan(type="NONE"),
            formulaSpec=FormulaSpec(type=formula_type),
            outputContract={"components": output_contract} if output_contract else {},
            lineage=LineageRef(
                sourceQuestionId=qb.questionId,
                sourceEntityIds=[r.get("entityId", "") for r in required_entities],
                sourceColumnIds=qb.resolvedRoles.measures + qb.resolvedRoles.dimensions,
            ),
        )
        plans.append(plan)

    # Build readiness report
    readiness = ExecutionReadinessReport(
        executableCount=sum(1 for p in plans if p.status == "EXECUTABLE"),
        degradedCount=sum(1 for p in plans if p.status == "DEGRADED"),
        blockedCount=len(blocked),
        errors=["Binding gate has errors — resolve before execution"] if has_errors else [],
    )

    # Build statistical context from dataset + blueprint
    unit_registry = {}
    for col in dataset.columns:
        if col.unit:
            unit_registry[col.name] = col.unit

    stat_ctx = StatisticalContext(
        geographyLevel="state_ut" if any("state" in c.name.lower() for c in dataset.columns) else "",
        unitRegistry=unit_registry,
        sourceNotes=[blueprint.get("templateMeta", {}).get("sourceDocument", "")],
    )

    bundle_status = "NOT_READY" if has_errors else readiness.status
    binding_ast_id = f"bind_{template_id}_{signature[:8]}"

    # Stash path for dataframe
    stash_dir = _stash_dir(template_id, signature)
    df_path = str(stash_dir / "data.csv") if stash_dir.exists() else ""

    from datetime import datetime as _dt
    bundle = ExecutionBundle(
        templateId=template_id,
        datasetId=record.datasetId,
        bindingAstId=binding_ast_id,
        status=bundle_status,
        datasetAst=dataset,
        bindingAst=binding,
        statisticalContext=stat_ctx,
        plans=plans,
        blockedQuestions=blocked,
        readinessReport=readiness,
        dataframeRef={"type": "csv", "path": df_path},
        frozenAt=_dt.utcnow().isoformat() + "Z",
    )

    logger.info(
        "[binding-phase] execution-ready %s__%s — status=%s plans=%d blocked=%d",
        template_id, signature, bundle_status, len(plans), len(blocked),
    )

    return ExecutionReadyOut(
        contract_version=bundle.contractVersion,
        template_id=bundle.templateId,
        dataset_id=bundle.datasetId,
        binding_ast_id=bundle.bindingAstId,
        status=bundle.status,
        dataset_ast=bundle.datasetAst.to_dict(),
        binding_ast=bundle.bindingAst.to_dict(),
        statistical_context=bundle.statisticalContext.to_dict(),
        plans=[p.to_dict() for p in bundle.plans],
        blocked_questions=bundle.blockedQuestions,
        readiness_report=bundle.readinessReport.to_dict(),
        dataframe_ref=bundle.dataframeRef,
        lineage_index={p.questionId: p.lineage.to_dict() for p in bundle.plans},
        frozen_at=bundle.frozenAt,
    )
