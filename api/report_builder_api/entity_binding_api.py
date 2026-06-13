"""Entity binding API — resolve and manage entity→column mappings.

Endpoints:
  GET    /report-builder/bindings/{job_id}           Get all bindings for a job
  POST   /report-builder/bindings/{job_id}/resolve   Auto-resolve entity bindings
  PUT    /report-builder/bindings/{job_id}/{entity_id}  User override a binding
  POST   /report-builder/bindings/{job_id}/accept    Accept pending bindings
  POST   /report-builder/bindings/{job_id}/reject    Reject pending bindings
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-builder/bindings", tags=["entity-binding"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BindingOut(BaseModel):
    entity_id: str
    entity_name: str
    column_name: Optional[str] = None
    confidence: float = 0.0
    method: str = ""
    auto_accepted: bool = False
    user_override: bool = False
    status: str = "unresolved"  # resolved | pending | unresolved | rejected


class BindingOverrideIn(BaseModel):
    column_name: str
    reason: Optional[str] = None


class BindingBatchAction(BaseModel):
    entity_ids: list[str]


class ResolveRequest(BaseModel):
    dataset_id: Optional[int] = None
    column_names: Optional[list[str]] = None


class BindingResultOut(BaseModel):
    job_id: int
    total: int
    resolved: int
    pending: int
    unresolved: int
    bindings: list[BindingOut]


# ---------------------------------------------------------------------------
# In-memory binding store (per job)
# ---------------------------------------------------------------------------

# In production this would be in the DB; for now store in memory keyed by job_id
_binding_store: dict[int, dict[str, BindingOut]] = {}


def _get_store(job_id: int) -> dict[str, BindingOut]:
    if job_id not in _binding_store:
        _binding_store[job_id] = {}
    return _binding_store[job_id]


def store_bindings(job_id: int, bindings: list[BindingOut]) -> None:
    """Store bindings for a job (called by orchestrator during generation)."""
    store = _get_store(job_id)
    for b in bindings:
        store[b.entity_id] = b


# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------

def _get_db():
    from database.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{job_id}", response_model=BindingResultOut)
def get_bindings(
    job_id: int,
    db: Session = Depends(_get_db),
):
    """Get all entity bindings for a report generation job."""
    from database.models import ReportJob
    job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    store = _get_store(job_id)
    bindings = list(store.values())

    return BindingResultOut(
        job_id=job_id,
        total=len(bindings),
        resolved=sum(1 for b in bindings if b.status == "resolved"),
        pending=sum(1 for b in bindings if b.status == "pending"),
        unresolved=sum(1 for b in bindings if b.status == "unresolved"),
        bindings=bindings,
    )


@router.post("/{job_id}/resolve", response_model=BindingResultOut)
def resolve_bindings(
    job_id: int,
    request: ResolveRequest,
    db: Session = Depends(_get_db),
):
    """Auto-resolve entity bindings using the column resolver cascade."""
    from database.models import ReportJob
    job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    store = _get_store(job_id)
    column_names = request.column_names or []

    # If dataset_id provided, load columns from dataset
    if request.dataset_id and not column_names:
        from database.models import Dataset
        dataset = db.query(Dataset).filter(Dataset.id == request.dataset_id).first()
        if dataset and dataset.columns_json:
            column_names = [c.get("name", "") for c in dataset.columns_json if c.get("name")]

    if not column_names:
        raise HTTPException(status_code=400, detail="No columns available for resolution")

    # Run resolution cascade for unresolved entities
    try:
        from template_engine.binder.column_resolver import ColumnResolver
        resolver = ColumnResolver(column_names)

        for entity_id, binding in store.items():
            if binding.status in ("resolved", "rejected"):
                continue

            result = resolver.resolve(binding.entity_name)
            if result:
                col_name, confidence, method = result
                binding.column_name = col_name
                binding.confidence = confidence
                binding.method = method
                if confidence >= 0.90:
                    binding.auto_accepted = True
                    binding.status = "resolved"
                else:
                    binding.status = "pending"
            else:
                binding.status = "unresolved"
    except ImportError:
        logger.warning("Column resolver not available")

    # Store in LTM for future reuse
    try:
        from template_engine.storage.ltm_store import get_ltm_store
        ltm = get_ltm_store()
        if ltm.is_available:
            for binding in store.values():
                if binding.status == "resolved" and binding.column_name:
                    ltm.store_binding(
                        entity_name=binding.entity_name,
                        column_name=binding.column_name,
                        dataset_id=str(request.dataset_id or ""),
                        confidence=binding.confidence,
                    )
    except Exception:
        pass

    bindings = list(store.values())
    return BindingResultOut(
        job_id=job_id,
        total=len(bindings),
        resolved=sum(1 for b in bindings if b.status == "resolved"),
        pending=sum(1 for b in bindings if b.status == "pending"),
        unresolved=sum(1 for b in bindings if b.status == "unresolved"),
        bindings=bindings,
    )


@router.put("/{job_id}/{entity_id}")
def override_binding(
    job_id: int,
    entity_id: str,
    override: BindingOverrideIn,
    db: Session = Depends(_get_db),
):
    """Manually override an entity binding (user action)."""
    from database.models import ReportJob
    job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    store = _get_store(job_id)
    if entity_id not in store:
        raise HTTPException(status_code=404, detail="Entity binding not found")

    binding = store[entity_id]
    binding.column_name = override.column_name
    binding.confidence = 1.0
    binding.method = "user_override"
    binding.user_override = True
    binding.status = "resolved"

    # Store in LTM for learning
    try:
        from template_engine.storage.ltm_store import get_ltm_store
        ltm = get_ltm_store()
        if ltm.is_available:
            ltm.store_binding(
                entity_name=binding.entity_name,
                column_name=override.column_name,
                confidence=1.0,
                metadata={"source": "user_override", "reason": override.reason},
            )
    except Exception:
        pass

    return {"status": "ok", "entity_id": entity_id, "column_name": override.column_name}


@router.post("/{job_id}/accept")
def accept_bindings(
    job_id: int,
    action: BindingBatchAction,
    db: Session = Depends(_get_db),
):
    """Accept pending entity bindings (batch action)."""
    from database.models import ReportJob
    job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    store = _get_store(job_id)
    accepted = 0
    for eid in action.entity_ids:
        if eid in store and store[eid].status == "pending":
            store[eid].status = "resolved"
            accepted += 1

    return {"status": "ok", "accepted": accepted}


@router.post("/{job_id}/reject")
def reject_bindings(
    job_id: int,
    action: BindingBatchAction,
    db: Session = Depends(_get_db),
):
    """Reject pending entity bindings (batch action)."""
    from database.models import ReportJob
    job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    store = _get_store(job_id)
    rejected = 0
    for eid in action.entity_ids:
        if eid in store and store[eid].status in ("pending", "unresolved"):
            store[eid].status = "rejected"
            store[eid].column_name = None
            rejected += 1

    return {"status": "ok", "rejected": rejected}
