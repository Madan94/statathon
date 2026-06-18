import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from database.database import SessionLocal
from database.models import Analysis, Dataset
from services.analysis_runner import (
    execute_dataset_analysis_job,
    finalize_successful_analysis,
    mark_dataset_upload_status,
    persist_analysis_failure,
    run_semantic_analysis_pipeline,
    supersede_inflight_analyses,
)
from services.apply_service import apply_analysis_decisions, get_lineage
from analysis.schemas import (
    AnalysisDecisionsRequest,
    ColumnAutoNormalizeRequest,
    ImputationDecisionsRequest,
    ImputationMethodRequest,
    NormalizationSaveRequest,
    OutlierDetectRequest,
    OutlierMethodSelectRequest,
    OutlierRowDecisionsRequest,
    ValidationAcknowledgeRequest,
    ValidationCandidatesPageResponse,
    ValidationDecisionsRequest,
    ValidationProceedRequest,
)
from auth.permissions import require_analysis_owner, require_analysis_owner_meta, require_dataset_owner
from deps import get_current_user_id
from services.analysis_light_service import (
    build_clusters_response,
    build_domains_response,
    build_graph_response,
    build_knowledge_graph_response,
    build_summary_response,
)
from services.analysis_results_service import (
    enrich_payload_for_dashboard,
    resolve_semantic_analysis_payload,
)
from analysis_state.cluster_utils import normalize_clusters_payload
from services.decision_service import DecisionService
from services.analysis_query import get_normalization_version
from services.analysis_payload_cache import (
    get_cached_enriched_results,
    set_cached_enriched_results,
)
from services.normalization_service import NormalizationService
from services.column_role_service import ColumnRoleService
from services.outlier_workflow_service import OutlierWorkflowService
from services.validation_workflow_service import ValidationWorkflowService
from services.imputation_workflow_service import ImputationWorkflowService
from services.column_review_auto_service import ColumnReviewAutoService
from services.phase_audit_service import PhaseAuditService
from services.phase_status_service import PhaseStatusService
from review.dataset_review_service import DatasetReviewService

router = APIRouter(prefix="/analysis", tags=["analysis"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _analysis_meta_or_raise(analysis_id: int, db: Session, user_id: int | None = None) -> Analysis:
    if user_id is not None:
        an = require_analysis_owner_meta(db, analysis_id, user_id)
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


def _payload_for_analysis(
    db: Session,
    analysis_id: int,
    *,
    include_phase3: bool = False,
) -> dict | None:
    payload = resolve_semantic_analysis_payload(
        db,
        analysis_id,
        include_phase3=include_phase3,
    )
    if not payload:
        return None
    return NormalizationService(db).apply_to_payload(analysis_id, payload)


@router.get("/{analysis_id}/results")
def get_analysis_results(
    analysis_id: int,
    include_phase3: bool = False,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    norm_version = get_normalization_version(db, analysis_id)
    cached = get_cached_enriched_results(
        analysis_id, norm_version, include_phase3=include_phase3
    )
    if cached:
        return cached
    payload = _payload_for_analysis(db, analysis_id, include_phase3=include_phase3)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")
    enriched = enrich_payload_for_dashboard(
        db,
        analysis_id,
        payload,
        include_phase3=include_phase3,
    )
    set_cached_enriched_results(
        analysis_id,
        norm_version,
        include_phase3=include_phase3,
        payload=enriched,
    )
    return enriched


@router.get("/{analysis_id}/bootstrap")
def get_analysis_bootstrap(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    summary = build_summary_response(db, analysis_id)
    normalization = NormalizationService(db).get_step2_normalization(analysis_id)
    return {
        "analysis_id": analysis_id,
        "summary": summary,
        "normalization": normalization,
    }


@router.get("/{analysis_id}/status")
def get_analysis_status(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    an = require_analysis_owner_meta(db, analysis_id, user_id)
    return {
        "analysis_id": an.id,
        "dataset_id": an.dataset_id,
        "status": an.status,
        "error_message": an.error_message,
        "completed_at": an.completed_at.isoformat() if an.completed_at else None,
    }


@router.post("/{analysis_id}/apply")
async def apply_decisions(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return await run_in_threadpool(
            apply_analysis_decisions, db, analysis_id, user_id=user_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{analysis_id}/lineage")
def get_dataset_lineage(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return get_lineage(db, analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{analysis_id}/audit")
def list_audit_events(
    analysis_id: int,
    phase: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return PhaseAuditService(db).list_events(analysis_id, phase=phase)


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


@router.get("/{analysis_id}/phase-status")
def get_phase_status(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return PhaseStatusService(db).get_status_payload(analysis_id)


@router.get("/{analysis_id}/dataset-review")
def get_dataset_review(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return DatasetReviewService(db).get_review_payload(analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{analysis_id}/dataset-review/rows")
def get_dataset_review_rows(
    analysis_id: int,
    side: str,
    offset: int = 0,
    limit: int = 50,
    search: str | None = None,
    column_filter: str | None = None,
    row_filter: str | None = None,
    columns: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    col_list = [c.strip() for c in columns.split(",") if c.strip()] if columns else None
    try:
        return DatasetReviewService(db).get_rows(
            analysis_id,
            side,
            offset=offset,
            limit=limit,
            columns=col_list,
            search=search,
            column_filter=column_filter,
            row_filter=row_filter,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{analysis_id}/dataset-review/column/{column_name}")
def get_dataset_review_column(
    analysis_id: int,
    column_name: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return DatasetReviewService(db).get_column_changes(analysis_id, column_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{analysis_id}/dataset-review/row/{row_index}")
def get_dataset_review_row(
    analysis_id: int,
    row_index: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return DatasetReviewService(db).get_row_inspection(analysis_id, row_index)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{analysis_id}/dataset-review/approve")
def approve_dataset_review(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return DatasetReviewService(db).approve_dataset(analysis_id, user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{analysis_id}/dataset-review/download/{kind}")
def download_dataset_review_artifact(
    analysis_id: int,
    kind: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        data, mime, filename = DatasetReviewService(db).build_download(analysis_id, kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{analysis_id}/validation/candidates", response_model=ValidationCandidatesPageResponse)
def list_validation_candidates(
    analysis_id: int,
    page: int = 1,
    page_size: int = 50,
    severity: str | None = None,
    column: str | None = None,
    rule_id: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    from services.analysis_query import list_validation_candidates_paginated

    return list_validation_candidates_paginated(
        db,
        analysis_id,
        page=page,
        page_size=page_size,
        severity=severity,
        column=column,
        rule_id=rule_id,
    )


@router.get("/{analysis_id}/validation/review-progress")
def get_validation_review_progress(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return ValidationWorkflowService(db).review_progress(analysis_id)


@router.post("/{analysis_id}/validation/proceed")
def proceed_validation_to_anomaly(
    analysis_id: int,
    body: ValidationProceedRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return ValidationWorkflowService(db).proceed_to_anomaly(
            analysis_id,
            [d.model_dump() for d in body.decisions],
            user_id=user_id,
            meta=body.model_dump(exclude={"decisions"}),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{analysis_id}/validation/acknowledge")
def acknowledge_validation_gate(
    analysis_id: int,
    body: ValidationAcknowledgeRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return ValidationWorkflowService(db).acknowledge_validation(
        analysis_id,
        user_id=user_id,
        meta=body.model_dump(),
    )


@router.post("/{analysis_id}/validation/decisions")
def save_validation_decisions(
    analysis_id: int,
    body: ValidationDecisionsRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return ValidationWorkflowService(db).save_decisions(
        analysis_id,
        [d.model_dump() for d in body.decisions],
        user_id=user_id,
    )


def _demo_noise_or_http(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.get("/{analysis_id}/validation/demo-noise/status")
def validation_demo_noise_status(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    from services.validation_demo_noise_service import ValidationDemoNoiseService

    try:
        return ValidationDemoNoiseService(db).status(analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{analysis_id}/validation/demo-noise/inject")
def validation_demo_noise_inject(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    from services.validation_demo_noise_service import ValidationDemoNoiseService

    try:
        return ValidationDemoNoiseService(db).inject(analysis_id)
    except (PermissionError, ValueError) as e:
        raise _demo_noise_or_http(e) from e


@router.post("/{analysis_id}/validation/demo-noise/refresh")
def validation_demo_noise_refresh(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    from services.validation_demo_noise_service import ValidationDemoNoiseService

    try:
        return ValidationDemoNoiseService(db).refresh(analysis_id)
    except (PermissionError, ValueError) as e:
        raise _demo_noise_or_http(e) from e


@router.post("/{analysis_id}/validation/demo-noise/remove")
def validation_demo_noise_remove(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    from services.validation_demo_noise_service import ValidationDemoNoiseService

    try:
        return ValidationDemoNoiseService(db).remove(analysis_id)
    except (PermissionError, ValueError) as e:
        raise _demo_noise_or_http(e) from e


@router.post("/{analysis_id}/imputation/method")
def select_imputation_method(
    analysis_id: int,
    body: ImputationMethodRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return ImputationWorkflowService(db).select_method(analysis_id, body.column, body.method)


@router.post("/{analysis_id}/imputation/decisions")
def save_imputation_decisions(
    analysis_id: int,
    body: ImputationDecisionsRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return ImputationWorkflowService(db).save_decisions(
        analysis_id,
        body.column,
        method=body.method,
        decisions=body.decisions if body.decisions else None,
        user_id=user_id,
    )


@router.post("/{analysis_id}/column-review/auto-normalize")
def auto_normalize_column_review(
    analysis_id: int,
    body: ColumnAutoNormalizeRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return ColumnReviewAutoService(db).auto_normalize_column(
            analysis_id,
            body.column,
            phases=body.phases,
            user_id=user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{analysis_id}/anomaly/review-progress")
def get_anomaly_review_progress(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return OutlierWorkflowService(db).review_progress(analysis_id)


@router.get("/{analysis_id}/imputation/missing-rows")
def list_imputation_missing_rows(
    analysis_id: int,
    column: str,
    method: str | None = None,
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return ImputationWorkflowService(db).list_missing_rows(
            analysis_id,
            column,
            method=method,
            offset=offset,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{analysis_id}/imputation/review-progress")
def get_imputation_review_progress(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return ImputationWorkflowService(db).review_progress(analysis_id)


@router.post("/{analysis_id}/outliers/method")
def select_outlier_method(
    analysis_id: int,
    body: OutlierMethodSelectRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return OutlierWorkflowService(db).select_method(analysis_id, body.column, body.method)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{analysis_id}/outliers/detect")
async def run_outlier_detection(
    analysis_id: int,
    body: OutlierDetectRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return await run_in_threadpool(
            OutlierWorkflowService(db).run_detection,
            analysis_id,
            body.column,
            body.method,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{analysis_id}/outliers/decisions")
def save_outlier_row_decisions(
    analysis_id: int,
    body: OutlierRowDecisionsRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return OutlierWorkflowService(db).save_row_decisions(
            analysis_id,
            body.column,
            [d.model_dump() for d in body.decisions],
            user_id=user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{analysis_id}/outliers/decisions")
def list_outlier_row_decisions(
    analysis_id: int,
    column: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return OutlierWorkflowService(db).list_decisions(analysis_id, column)


@router.get("/{analysis_id}/normalization")
def get_analysis_normalization(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return NormalizationService(db).get_step2_normalization(analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{analysis_id}/normalization/apply-dictionary")
def apply_analysis_dictionary(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return NormalizationService(db).apply_dictionary_to_analysis(analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


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


@router.get("/{analysis_id}/column-roles")
def get_column_roles(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    try:
        return ColumnRoleService(db).get_roles(analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{analysis_id}/column-roles/confirm")
def confirm_column_roles(
    analysis_id: int,
    body: dict,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    overrides = body.get("overrides") if isinstance(body, dict) else {}
    if not isinstance(overrides, dict):
        overrides = {}
    try:
        return ColumnRoleService(db).confirm_roles(
            analysis_id,
            overrides,
            user_id=user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{analysis_id}/summary")
def get_analysis_summary(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return build_summary_response(db, analysis_id)


@router.get("/{analysis_id}/domains")
def get_analysis_domains(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return build_domains_response(db, analysis_id)


@router.get("/{analysis_id}/clusters")
def get_analysis_clusters(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    payload = build_clusters_response(db, analysis_id)
    return {
        "meta": payload["meta"],
        "clusters": normalize_clusters_payload(payload.get("clusters") or []),
    }


@router.get("/{analysis_id}/graph")
def get_analysis_graph(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return build_graph_response(db, analysis_id)


@router.get("/{analysis_id}/knowledge-graph")
def get_analysis_knowledge_graph(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    return build_knowledge_graph_response(db, analysis_id)


@router.get("/{analysis_id}/blueprint")
def get_analysis_blueprint(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _analysis_meta_or_raise(analysis_id, db, user_id)
    payload = resolve_semantic_analysis_payload(db, analysis_id, include_phase3=False)
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
async def analyze_async(
    dataset_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    ds = require_dataset_owner(db, dataset_id, user_id)
    supersede_inflight_analyses(db, dataset_id)

    an = Analysis(dataset_id=dataset_id, status="pending")
    db.add(an)
    db.commit()
    db.refresh(an)

    async def _run_job() -> None:
        await run_in_threadpool(execute_dataset_analysis_job, dataset_id, an.id)

    background_tasks.add_task(_run_job)
    return {"analysis_id": an.id, "id": an.id, "dataset_id": dataset_id, "status": "pending"}


@router.post("/{dataset_id}/analyze")
def analyze(
    dataset_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    allow_sync = os.getenv("ALLOW_SYNC_ANALYZE", "false").lower() in ("1", "true", "yes")
    if not allow_sync:
        ds = require_dataset_owner(db, dataset_id, user_id)
        supersede_inflight_analyses(db, dataset_id)
        an = Analysis(dataset_id=dataset_id, status="pending")
        db.add(an)
        db.commit()
        db.refresh(an)
        background_tasks.add_task(execute_dataset_analysis_job, dataset_id, an.id)
        return {"analysis_id": an.id, "id": an.id, "dataset_id": dataset_id, "status": "pending"}

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
