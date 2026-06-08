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

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from report_builder.binding import review as R

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-builder/binding-phase", tags=["binding-phase"])


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
# Endpoints
# ---------------------------------------------------------------------------


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
