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
    """Blueprint source: an uploaded blueprint.json, else the bundled gold PLFS blueprint."""
    if blueprint_file is not None:
        raw = await blueprint_file.read()
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail=f"invalid blueprint JSON: {exc}") from exc
    if template_id in _GOLD_TEMPLATE_IDS:
        return json.loads(_GOLD_BLUEPRINT.read_text(encoding="utf-8"))
    raise HTTPException(
        status_code=400,
        detail=f"no blueprint for template '{template_id}' — upload a blueprint.json or use a built-in id",
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
