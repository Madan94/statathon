import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import Analysis, Dataset
from services.analysis_runner import (
    finalize_successful_analysis,
    mark_dataset_upload_status,
    persist_analysis_failure,
    run_semantic_analysis_pipeline,
)
from services.analysis_results_service import resolve_semantic_analysis_payload

router = APIRouter(prefix="/analysis", tags=["analysis"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _analysis_meta_or_raise(analysis_id: int, db: Session) -> Analysis:
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


@router.get("/{analysis_id}/results")
def get_analysis_results(analysis_id: int, db: Session = Depends(get_db)):
    _analysis_meta_or_raise(analysis_id, db)
    payload = resolve_semantic_analysis_payload(db, analysis_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")
    return payload


@router.get("/{analysis_id}/summary")
def get_analysis_summary(analysis_id: int, db: Session = Depends(get_db)):
    _analysis_meta_or_raise(analysis_id, db)
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
def get_analysis_domains(analysis_id: int, db: Session = Depends(get_db)):
    _analysis_meta_or_raise(analysis_id, db)
    payload = resolve_semantic_analysis_payload(db, analysis_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")
    return {
        "meta": {"analysis_id": analysis_id},
        "dataset_context": payload.get("dataset_context"),
        "static_domains_taxonomy": payload.get("static_domains"),
        "ontology_macro_type_best_hint": (payload.get("dataset_context") or {}).get(
            "ontology_macro_type_best_hint"
        ),
    }


@router.get("/{analysis_id}/clusters")
def get_analysis_clusters(analysis_id: int, db: Session = Depends(get_db)):
    _analysis_meta_or_raise(analysis_id, db)
    payload = resolve_semantic_analysis_payload(db, analysis_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")
    return {"meta": {"analysis_id": analysis_id}, "clusters": payload.get("clusters") or []}


@router.get("/{analysis_id}/graph")
def get_analysis_graph(analysis_id: int, db: Session = Depends(get_db)):
    _analysis_meta_or_raise(analysis_id, db)
    payload = resolve_semantic_analysis_payload(db, analysis_id)
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
def get_analysis_knowledge_graph(analysis_id: int, db: Session = Depends(get_db)):
    _analysis_meta_or_raise(analysis_id, db)
    payload = resolve_semantic_analysis_payload(db, analysis_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")
    return {
        "meta": {"analysis_id": analysis_id},
        "knowledge_graph": payload.get("knowledge_graph") or {},
    }


@router.get("/{analysis_id}/blueprint")
def get_analysis_blueprint(analysis_id: int, db: Session = Depends(get_db)):
    _analysis_meta_or_raise(analysis_id, db)
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


@router.post("/{dataset_id}/analyze")
def analyze(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(404, "Dataset not found")
    an = Analysis(dataset_id=dataset_id, status="running")
    db.add(an)
    db.commit()
    db.refresh(an)

    if ds.object_key:
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
        if ds.object_key:
            mark_dataset_upload_status(dataset_id, "FAILED")
        persist_analysis_failure(an.id, str(e))
        raise HTTPException(status_code=500, detail=str(e))
