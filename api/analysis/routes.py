import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import Analysis, Dataset
from services.analysis_runner import (
    execute_dataset_analysis_job,
    finalize_successful_analysis,
    mark_dataset_upload_status,
    persist_analysis_failure,
    run_semantic_analysis_pipeline,
)
from services.apply_service import apply_analysis_decisions
from analysis.schemas import AnalysisDecisionsRequest, NormalizationSaveRequest
from auth.permissions import require_analysis_owner, require_dataset_owner
from deps import get_current_user_id
from services.analysis_results_service import (
    enrich_payload_for_dashboard,
    resolve_semantic_analysis_payload,
)
from services.decision_service import DecisionService
from services.normalization_service import NormalizationService

router = APIRouter(prefix="/analysis", tags=["analysis"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _analysis_meta_or_raise(analysis_id: int, db: Session, user_id: int | None = None) -> Analysis:
    if user_id is not None:
        an = require_analysis_owner(db, analysis_id, user_id)
    else:
        an = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not an:
            raise HTTPException(status_code=404, detail="Analysis not found")
    if an.status == "failed":
        raise HTTPException(status_code=409, detail=an.error_message or "Analysis failed")
    if an.status != "complete":
        raise HTTPException(status_code=409, detail="Analysis still running or pending")
    return an


def _normalize_priority_edges(payload: dict) -> list:
    prio = payload.get("priority_dependencies")
    if isinstance(prio, list):
        return prio
    flat: list[dict] = []
    if isinstance(prio, dict):
        for dependent_column, influencers in prio.items():
            if not isinstance(influencers, list):
                continue
            for inf in influencers:
                if not isinstance(inf, dict):
                    continue
                src = inf.get("column") or inf.get("source_column")
                if not src:
                    continue
                flat.append(
                    {
                        "source_column": src,
                        "dependent_column": dependent_column,
                        "influence_score": inf.get("score") or inf.get("influence_score"),
                        "dependency_reason": inf.get("dependency_reason"),
                    }
                )
    return flat


def _payload_for_analysis(db: Session, analysis_id: int) -> dict | None:
    payload = resolve_semantic_analysis_payload(db, analysis_id)
    if not payload:
        return None
    return NormalizationService(db).apply_to_payload(analysis_id, payload)


@router.get("/{analysis_id}/results")
def get_analysis_results(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    payload = _payload_for_analysis(db, analysis_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")
    return enrich_payload_for_dashboard(db, analysis_id, payload)


@router.get("/{analysis_id}/status")
def get_analysis_status(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    an = require_analysis_owner(db, analysis_id, user_id)
    return {
        "analysis_id": an.id,
        "dataset_id": an.dataset_id,
        "status": an.status,
        "error_message": an.error_message,
        "completed_at": an.completed_at.isoformat() if an.completed_at else None,
    }


@router.post("/{analysis_id}/apply")
def apply_decisions(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return apply_analysis_decisions(db, analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{analysis_id}/decisions")
def submit_analysis_decisions(
    analysis_id: int,
    body: AnalysisDecisionsRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        result = DecisionService(db).save_column_decisions(analysis_id, body.decisions)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return result


@router.get("/{analysis_id}/normalization")
def get_analysis_normalization(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    saved = NormalizationService(db).get_saved_decisions(analysis_id)
    if saved:
        return saved
    records = NormalizationService(db)._ensure_columns_seeded(analysis_id)
    return {
        "normalization_version": None,
        "columns": [
            {
                "column_id": c.id,
                "original_name": c.name,
                "normalized_name": c.normalized_name or c.name,
                "is_deleted": c.is_deleted,
                "is_excluded": c.is_excluded,
                "is_active": c.is_active,
            }
            for c in records
        ],
    }


@router.post("/{analysis_id}/normalization")
def save_analysis_normalization(
    analysis_id: int,
    body: NormalizationSaveRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        updates = [c.model_dump() for c in body.columns]
        return NormalizationService(db).save_normalization(analysis_id, user_id, updates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{analysis_id}/summary")
def get_analysis_summary(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    payload = resolve_semantic_analysis_payload(db, analysis_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")
    meta = payload.get("dataset_metadata") or payload.get("meta") or {}
    return {
        "meta": {"analysis_id": analysis_id},
        "dataset_context": payload.get("dataset_context"),
        "dataset_profile": payload.get("dataset_profile"),
        "dataset_name": meta.get("filename") if isinstance(meta, dict) else None,
        "column_profiles_keys": sorted((payload.get("column_profiles") or {}).keys()),
        "profiling_summary": payload.get("profiling_summary"),
        "embedding_cache_refs": payload.get("embedding_cache_refs"),
    }


@router.get("/{analysis_id}/domains")
def get_analysis_domains(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    payload = _payload_for_analysis(db, analysis_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")

    ctx = payload.get("dataset_context") or {}
    archetype = ctx.get("dataset_type") or ctx.get("ontology_macro_type_best_hint") or "unknown"
    ontology_macro = ctx.get("ontology_macro_type_best_hint")

    # Prefer full domain_registry emitted by the new pipeline
    domain_registry = payload.get("domain_registry") or {}

    # Fallback: build from static_domains (raw ontology) filtered for this archetype
    if not domain_registry and payload.get("static_domains"):
        sd = payload["static_domains"]
        archetype_entry = sd.get(archetype) or sd.get("dataset_types", {}).get(archetype, {})
        subdomains = {}
        for k, v in (archetype_entry.get("subdomains") or {}).items():
            subdomains[k] = {"description": f"{k} domain for {archetype}", "keywords": list(v or [])[:8]}
        domain_registry = {
            "active_archetype": archetype,
            "universal_domains": ["identifier", "survey_metadata", "geography", "demographic", "household", "uncorrelated_metadata"],
            "static_ontology": {archetype: {"label": archetype_entry.get("label", archetype), "domains": list(subdomains.keys()), "keywords_sample": {k: v["keywords"] for k, v in subdomains.items()}}},
            "dynamic_domains": {},
        }

    # Legacy flat format: static_domains_taxonomy for old frontends
    static_taxonomy: dict = {}
    for tier_name, tier_data in (domain_registry.get("static_ontology") or {}).items():
        for dom in (tier_data.get("domains") or []):
            kws = (tier_data.get("keywords_sample") or {}).get(dom, [])
            static_taxonomy[dom] = {"description": f"{dom} — {tier_name} dataset domain", "keywords": kws}
    for dom in (domain_registry.get("universal_domains") or []):
        static_taxonomy[dom] = {"description": f"Universal: {dom}", "keywords": []}

    return {
        "meta": {"analysis_id": analysis_id},
        "dataset_context": ctx,
        "domain_registry": domain_registry,
        "static_domains_taxonomy": static_taxonomy,
        "ontology_macro_type_best_hint": ontology_macro or archetype,
        "effective_schema": payload.get("effective_schema"),
    }


@router.get("/{analysis_id}/clusters")
def get_analysis_clusters(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    payload = _payload_for_analysis(db, analysis_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")
    return {"meta": {"analysis_id": analysis_id}, "clusters": payload.get("clusters") or []}


@router.get("/{analysis_id}/graph")
def get_analysis_graph(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    payload = _payload_for_analysis(db, analysis_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")
    graph = payload.get("schema_graph") or {}
    return {
        "meta": {"analysis_id": analysis_id},
        "nodes": graph.get("nodes") or [],
        "edges": graph.get("edges") or [],
        "priority_dependencies": _normalize_priority_edges(payload),
        "dataset_metadata": payload.get("dataset_metadata"),
    }


@router.get("/{analysis_id}/knowledge-graph")
def get_analysis_knowledge_graph(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    payload = resolve_semantic_analysis_payload(db, analysis_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")
    return {
        "meta": {"analysis_id": analysis_id},
        "knowledge_graph": payload.get("knowledge_graph") or {},
    }


@router.get("/{analysis_id}/blueprint")
def get_analysis_blueprint(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    payload = resolve_semantic_analysis_payload(db, analysis_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")
    bp = payload.get("schema_blueprint")
    if bp:
        return {"meta": {"analysis_id": analysis_id}, "schema_blueprint": bp}
    return {
        "meta": {"analysis_id": analysis_id},
        "schema_blueprint": {
            "note": "legacy_checkpoint_missing_blueprint_embedded_below",
            "dataset_context": payload.get("dataset_context"),
            "clusters": payload.get("clusters"),
            "semantic_mapping": payload.get("semantic_mapping"),
            "column_profiles": payload.get("column_profiles"),
        },
    }


@router.post("/{dataset_id}/analyze-async")
def analyze_async(
    dataset_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    ds = require_dataset_owner(db, dataset_id, user_id)
    an = Analysis(dataset_id=dataset_id, status="pending")
    db.add(an)
    db.commit()
    db.refresh(an)
    background_tasks.add_task(execute_dataset_analysis_job, dataset_id, an.id)
    return {"analysis_id": an.id, "id": an.id, "dataset_id": dataset_id, "status": "pending"}


@router.post("/{dataset_id}/analyze")
def analyze(
    dataset_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    ds = require_dataset_owner(db, dataset_id, user_id)
    an = Analysis(dataset_id=dataset_id, status="running")
    db.add(an)
    db.commit()
    db.refresh(an)

    uses_object_storage = bool(ds.object_key)
    if uses_object_storage:
        mark_dataset_upload_status(dataset_id, "PROCESSING")

    try:
        result = run_semantic_analysis_pipeline(
            dataset_id=dataset_id, analysis_id=an.id, db=db
        )
        finalize_successful_analysis(db, dataset_id, an.id, result)
        db.refresh(an)
        report_dir = os.getenv("REPORT_STORAGE_PATH", "./storage/reports")
        return {
            "analysis_id": an.id,
            "id": an.id,
            "dataset_id": dataset_id,
            "result": result,
            "report_storage_path": os.path.join(report_dir, f"report_{an.id}.pdf"),
        }
    except Exception as e:
        db.rollback()
        if uses_object_storage:
            mark_dataset_upload_status(dataset_id, "FAILED")
        persist_analysis_failure(an.id, str(e))
        raise HTTPException(status_code=500, detail=str(e))
