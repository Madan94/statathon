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
    action: str = "confirm"                 # confirm | override | reject | share | reopen
    columns: Optional[list[str]] = None     # override columns
    note: Optional[str] = None
    force_transfer: bool = False
    transfer_from_entity_ids: Optional[list[str]] = None
    share_policy: Optional[str] = None       # exclusive | shared
    share_reason: Optional[str] = None


class ManualEntityIn(BaseModel):
    entity_name: str
    entity_type: str = "dimension"          # dimension | measure | time | filter | metadata
    columns: list[str]
    cardinality: str = "oneToOne"
    note: Optional[str] = None
    share_policy: Optional[str] = None
    share_reason: Optional[str] = None


class ReviewedPlanNodePatchIn(BaseModel):
    title: Optional[str] = None
    enabled: Optional[bool] = None
    required_entities: Optional[list[dict[str, Any]]] = None


class ReviewedPlanQuestionIn(BaseModel):
    parent_node_id: str
    title: str
    required_entities: list[dict[str, Any]] = []
    analytics_spec: dict[str, Any] = {}


class ReviewedPlanComponentIn(BaseModel):
    component_type: str
    payload: dict[str, Any] = {}


class ReviewedPlanComponentPatchIn(BaseModel):
    required_entities: Optional[list[dict[str, Any]]] = None
    analytics_spec: Optional[dict[str, Any]] = None
    formula_spec: Optional[dict[str, Any]] = None


class ReviewedPlanPromoteIn(BaseModel):
    name: Optional[str] = None


class ProposalsOut(BaseModel):
    template_id: str
    signature: str
    dataset_id: str
    proposals: list[dict[str, Any]]
    confirmations: dict[str, dict[str, Any]]
    pending: list[str]
    column_ownership: dict[str, Any]


class RecordOut(BaseModel):
    template_id: str
    signature: str
    dataset_id: str
    proposals: list[dict[str, Any]]
    confirmations: dict[str, dict[str, Any]]
    column_ownership: dict[str, Any]
    updated_at: float


class StartOut(BaseModel):
    template_id: str
    signature: str
    dataset_id: str
    dataset_ast: dict[str, Any]
    proposals: list[dict[str, Any]]
    confirmations: dict[str, dict[str, Any]]
    pending: list[str]
    column_ownership: dict[str, Any]
    blueprint_qa: dict[str, Any] | None = None
    statistical_qa: dict[str, Any] | None = None


class FinalizeOut(BaseModel):
    template_id: str
    signature: str
    coverage: dict[str, Any]
    question_bindings: list[dict[str, Any]]
    binding_ast: dict[str, Any]
    reviewed_plan: dict[str, Any] | None = None
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


def _ownership(record: R.ReviewRecord) -> dict[str, Any]:
    return R.compute_column_ownership(record)


def _columns_for_decision(record: R.ReviewRecord, entity_id: str, columns: list[str] | None) -> list[str]:
    if columns is not None:
        return [c for c in columns if c]
    prop = next((p for p in record.proposals if str(p.get("entityId") or "") == entity_id), None)
    out: list[str] = []
    for col in (prop or {}).get("columns") or []:
        if isinstance(col, dict):
            name = str(col.get("column") or "")
        else:
            name = str(col or "")
        if name:
            out.append(name)
    return out


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


def _read_optional_stash_json(template_id: str, signature: str, suffix: str) -> dict[str, Any] | None:
    path = _stash_path(template_id, signature, suffix)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _reviewed_plan_payload(reviewed_plan: "Any", path: str | None = None) -> dict[str, Any]:
    semantic_slots = (reviewed_plan.semanticSlotGraph or {}).get("slots") or []
    return {
        "planId": reviewed_plan.planId,
        "status": reviewed_plan.status,
        "bindingAstId": reviewed_plan.bindingAstId,
        "path": path or "",
        "topicCount": len(reviewed_plan.planTree),
        "questionCount": sum(len(topic.children) for topic in reviewed_plan.planTree),
        "componentCount": sum(
            len(question.components)
            for topic in reviewed_plan.planTree
            for question in topic.children
        ),
        "semanticSlotCount": len(semantic_slots),
        "virtualSlotCount": len(reviewed_plan.virtualSlots),
        "virtualSlots": list(reviewed_plan.virtualSlots),
        "planTree": [node.to_dict() for node in reviewed_plan.planTree],
    }


def _load_reviewed_plan_or_404(template_id: str, signature: str) -> "Any":
    from report_builder.binding.reviewed_plan import load_reviewed_plan

    plan = load_reviewed_plan(template_id, signature)
    if plan is None:
        raise HTTPException(status_code=404, detail="no reviewed plan for this binding session; finalize first")
    return plan


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

    # ── BlueprintQA gate: validate before binding starts ──
    from report_builder.binding.blueprint_qa import validate_blueprint_qa, validate_statistical_concepts
    blueprint_qa = validate_blueprint_qa(bp)
    if blueprint_qa.status == "INVALID":
        raise HTTPException(
            status_code=422,
            detail=f"Blueprint is INVALID for binding: {[e['message'] for e in blueprint_qa.errors]}",
        )
    statistical_qa = validate_statistical_concepts(bp)

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
        column_ownership=_ownership(record),
        blueprint_qa=blueprint_qa.to_dict(),
        statistical_qa=statistical_qa.to_dict(),
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
        column_ownership=_ownership(record),
    )


@router.post("/{template_id}/{signature}/confirm", response_model=RecordOut)
def post_confirm(template_id: str, signature: str, body: ConfirmIn) -> RecordOut:
    """Record one human decision (confirm / override / reject) and persist it."""
    record = _load_or_404(template_id, signature)
    action = body.action.lower()
    if action == "reject":
        R.reject(record, body.entity_id, note=body.note or "")
    elif action == "reopen":
        R.reopen(record, body.entity_id)
    elif action in ("confirm", "override", "share"):
        selected_columns = _columns_for_decision(record, body.entity_id, body.columns)
        share_policy = body.share_policy or ("shared" if action == "share" else "exclusive")
        conflicts = R.find_exclusive_column_conflicts(record, body.entity_id, selected_columns)
        if conflicts and share_policy == "shared" and not body.share_reason:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "SHARE_REASON_REQUIRED",
                    "message": "sharing an already-owned column requires a reason",
                    "conflicts": conflicts,
                    "column_ownership": _ownership(record),
                },
            )
        if conflicts and share_policy != "shared":
            if body.force_transfer:
                transfer_from = body.transfer_from_entity_ids or sorted({
                    owner.get("entityId")
                    for conflict in conflicts
                    for owner in conflict.get("owners", [])
                    if owner.get("entityId")
                })
                R.move_columns_from_entities(
                    record,
                    columns=selected_columns,
                    from_entity_ids=transfer_from,
                    note=f"column moved to {body.entity_id}",
                )
            else:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "COLUMN_ALREADY_OWNED",
                        "message": "column is already assigned to another exclusive entity",
                        "conflicts": conflicts,
                        "column_ownership": _ownership(record),
                    },
                )
        try:
            R.confirm(
                record,
                body.entity_id,
                columns=body.columns,
                note=body.note or "",
                share_policy=share_policy,
                share_reason=body.share_reason or "",
            )
        except R.ColumnOwnershipConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COLUMN_ALREADY_OWNED",
                    "message": str(exc),
                    "conflicts": exc.conflicts,
                    "column_ownership": _ownership(record),
                },
            ) from exc
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
        column_ownership=_ownership(record),
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
        column_ownership=_ownership(record),
        updated_at=record.updatedAt,
    )


@router.post("/{template_id}/{signature}/entities", response_model=RecordOut)
def post_manual_entity(template_id: str, signature: str, body: ManualEntityIn) -> RecordOut:
    """Add an officer-created entity from one or more dataset columns."""
    record = _load_or_404(template_id, signature)
    if not body.entity_name.strip():
        raise HTTPException(status_code=400, detail="entity_name is required")
    if not [c for c in body.columns if c]:
        raise HTTPException(status_code=400, detail="at least one column is required")
    try:
        R.add_manual_entity(
            record,
            entity_name=body.entity_name.strip(),
            entity_type=body.entity_type,
            columns=body.columns,
            cardinality=body.cardinality,
            note=body.note or "",
            share_policy=body.share_policy or "exclusive",
            share_reason=body.share_reason or "",
        )
    except R.ColumnOwnershipConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COLUMN_ALREADY_OWNED",
                "message": str(exc),
                "conflicts": exc.conflicts,
                "column_ownership": _ownership(record),
            },
        ) from exc
    path = R.save_record(record)
    logger.info("[binding-phase] manual entity %s on %s → %s", body.entity_name, signature, path.name)
    return RecordOut(
        template_id=record.templateId,
        signature=record.datasetSignature,
        dataset_id=record.datasetId,
        proposals=record.proposals,
        confirmations={k: v.to_dict() for k, v in record.confirmations.items()},
        column_ownership=_ownership(record),
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

    reviewed_plan_payload: dict[str, Any] | None = None
    try:
        from report_builder.binding.reviewed_plan import build_reviewed_plan, save_reviewed_plan

        semantic_slot_graph = _read_optional_stash_json(template_id, signature, "semantic_slot_graph.json")
        template_ast = _read_optional_stash_json(template_id, signature, "template_ast.json")
        reviewed_plan = build_reviewed_plan(
            template_id=record.templateId,
            signature=signature,
            dataset=dataset,
            blueprint=blueprint,
            binding=binding,
            semantic_slot_graph=semantic_slot_graph,
            template_ast=template_ast,
        )
        reviewed_plan_path = save_reviewed_plan(reviewed_plan)
        reviewed_plan_payload = _reviewed_plan_payload(reviewed_plan, str(reviewed_plan_path))
    except Exception as exc:  # noqa: BLE001 - finalize should stay compatible if plan sidecar fails
        logger.warning("[binding-phase] reviewed plan build failed for %s__%s: %s", template_id, signature, exc)

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
        reviewed_plan=reviewed_plan_payload,
        has_errors=has_errors,
    )


@router.get("/{template_id}/{signature}/reviewed-plan")
def get_reviewed_plan(template_id: str, signature: str) -> dict[str, Any]:
    plan = _load_reviewed_plan_or_404(template_id, signature)
    return _reviewed_plan_payload(plan)


@router.patch("/{template_id}/{signature}/reviewed-plan/nodes/{node_id}")
def patch_reviewed_plan_node(
    template_id: str,
    signature: str,
    node_id: str,
    body: ReviewedPlanNodePatchIn,
) -> dict[str, Any]:
    from report_builder.binding.reviewed_plan import patch_plan_node, save_reviewed_plan

    plan = _load_reviewed_plan_or_404(template_id, signature)
    try:
        patch_plan_node(
            plan,
            node_id,
            title=body.title,
            enabled=body.enabled,
            required_entities=body.required_entities,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"plan node not found: {node_id}") from exc
    path = save_reviewed_plan(plan)
    return _reviewed_plan_payload(plan, str(path))


@router.post("/{template_id}/{signature}/reviewed-plan/questions")
def post_reviewed_plan_question(
    template_id: str,
    signature: str,
    body: ReviewedPlanQuestionIn,
) -> dict[str, Any]:
    from report_builder.binding.reviewed_plan import add_question_to_plan, save_reviewed_plan

    plan = _load_reviewed_plan_or_404(template_id, signature)
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="question title is required")
    try:
        add_question_to_plan(
            plan,
            parent_node_id=body.parent_node_id,
            title=body.title,
            required_entities=body.required_entities,
            analytics_spec=body.analytics_spec,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"parent node not found: {body.parent_node_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    path = save_reviewed_plan(plan)
    return _reviewed_plan_payload(plan, str(path))


@router.get("/component-registry")
def get_component_registry() -> list[dict[str, Any]]:
    from report_builder.binding.component_registry import list_component_definitions

    return list_component_definitions()


@router.post("/{template_id}/{signature}/reviewed-plan/nodes/{node_id}/components")
def post_reviewed_plan_component(
    template_id: str,
    signature: str,
    node_id: str,
    body: ReviewedPlanComponentIn,
) -> dict[str, Any]:
    from report_builder.binding.reviewed_plan import add_component_to_plan_node, save_reviewed_plan

    plan = _load_reviewed_plan_or_404(template_id, signature)
    try:
        add_component_to_plan_node(
            plan,
            node_id=node_id,
            component_type=body.component_type,
            payload=body.payload,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"plan node not found: {node_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    path = save_reviewed_plan(plan)
    return _reviewed_plan_payload(plan, str(path))


@router.patch("/{template_id}/{signature}/reviewed-plan/nodes/{node_id}/components/{component_id}")
def patch_reviewed_plan_component(
    template_id: str,
    signature: str,
    node_id: str,
    component_id: str,
    body: ReviewedPlanComponentPatchIn,
) -> dict[str, Any]:
    from report_builder.binding.reviewed_plan import patch_plan_component, save_reviewed_plan

    plan = _load_reviewed_plan_or_404(template_id, signature)
    try:
        patch_plan_component(
            plan,
            node_id=node_id,
            component_id=component_id,
            required_entities=body.required_entities,
            analytics_spec=body.analytics_spec,
            formula_spec=body.formula_spec,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"plan component not found: {exc}") from exc
    path = save_reviewed_plan(plan)
    return _reviewed_plan_payload(plan, str(path))


@router.post("/{template_id}/{signature}/reviewed-plan/promote")
def post_reviewed_plan_promote(
    template_id: str,
    signature: str,
    body: ReviewedPlanPromoteIn,
) -> dict[str, Any]:
    from report_builder.binding.reviewed_plan import promote_reviewed_plan, reviewed_plan_to_template_ast

    plan = _load_reviewed_plan_or_404(template_id, signature)
    result = promote_reviewed_plan(plan, name=body.name)
    try:
        from database.database import SessionLocal
        from database.models import ReportTemplate

        db = SessionLocal()
        try:
            row = ReportTemplate(
                user_id=None,
                name=body.name or f"Derived {plan.templatePackageRef.templateId}",
                description=f"Derived from reviewed plan {plan.planId}",
                source_filename=f"{plan.planId}.reviewed_plan.json",
                source_storage_path=result.get("path"),
                source_hash=plan.planId,
                ast_json=reviewed_plan_to_template_ast(plan),
                extraction_method="reviewed_plan_promotion",
                page_count=None,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            result["templateId"] = row.id
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - sidecar promotion remains valid without DB
        logger.warning("[binding-phase] DB template promotion failed for %s: %s", plan.planId, exc)
        result["templateId"] = None
        result["dbWarning"] = str(exc)
    return result


@router.get("/learned-entities")
def get_learned_entities(template_id: str | None = None) -> list[dict[str, Any]]:
    from report_builder.binding.reviewed_plan import list_learned_entities

    return list_learned_entities(template_id)


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

    This is the S4 team's ONLY input contract. Uses the canonical ExecutionBundle
    factory — no plan-building logic in this endpoint.

    Returns NOT_READY if the binding gate or readiness gate has errors.
    """
    from report_builder.binding.execution_bundle_factory import build_execution_bundle

    record = _load_or_404(template_id, signature)
    dataset, blueprint, df = _read_stash(template_id, signature)

    # Resolve dataframe path from stash
    df_path = str(_stash_path(template_id, signature, "data.csv"))

    # Build bundle via canonical factory (single source of truth)
    bundle = build_execution_bundle(
        template_id=template_id,
        signature=signature,
        record=record,
        dataset=dataset,
        blueprint=blueprint,
        dataframe_path=df_path,
        df=df,
    )

    logger.info(
        "[binding-phase] execution-ready %s__%s — status=%s plans=%d blocked=%d",
        template_id, signature, bundle.status, len(bundle.plans), len(bundle.blockedQuestions),
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
        lineage_index=bundle.lineageIndex,
        frozen_at=bundle.frozenAt,
    )
