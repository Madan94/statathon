"""Report Builder API routes.

Endpoints
---------
POST   /report-builder/templates/upload         multipart PDF + name -> compile AST
GET    /report-builder/templates                list templates
GET    /report-builder/templates/{id}           full AST
DELETE /report-builder/templates/{id}           delete

POST   /report-builder/generate                 {analysis_id, template_id?} -> job
GET    /report-builder/jobs                     list jobs (optional analysis_id filter)
GET    /report-builder/jobs/{id}                job status
GET    /report-builder/jobs/{id}/canvas         full BlockCanvas JSON
GET    /report-builder/jobs/{id}/download       PDF download
POST   /report-builder/jobs/{id}/blocks/{block_id}/regenerate   re-run Scribe for a block
POST   /report-builder/jobs/{id}/blocks/{block_id}/correction   log human correction to LTM
"""
from __future__ import annotations

import logging
import os
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile,
    WebSocket, WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import Analysis, Dataset, ReportCorrection, ReportJob, ReportTemplate
from database.models import ReportTemplateExtractionJob
from deps import get_current_user_id
from auth.permissions import require_analysis_owner
from services.analysis_results_service import resolve_semantic_analysis_payload, enrich_payload_for_dashboard
from core.ingestion import dataframe_for_uploaded_dataset
from object_storage.object_store import try_build_default_store
from utils.datetime_json import isoformat_utc

from report_builder import bi_chat
from report_builder import blueprint as bp
from report_builder import firewall as fw
from report_builder.memory import ReflectionLedger, STM
from report_builder.pipeline import generate_report

from .access import filter_config_dict, require_job_access, require_template_access
from .template_validation import validate_ast_payload
from .schemas import (
    ChatIn, CoordGenerateOut, CoordGenerateRequest, CorrectionIn, DeliverRequest,
    GenerateRequest, InsertBlockIn, JobOut, MoveBlockIn, ReadyAnalysisOut,
    TemplateCreateOut, TemplateExtractionJobOut, TemplateImportJsonIn, TemplateOut,
    TemplateUpdateIn,
)
from . import delivery as delivery_mod

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-builder", tags=["report-builder"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _template_to_out(row: ReportTemplate) -> TemplateOut:
    ast = row.ast_json or {}
    return TemplateOut(
        id=row.id,
        name=row.name,
        description=row.description,
        page_count=row.page_count,
        extraction_method=row.extraction_method,
        block_count=len((ast.get("blocks") or []) if isinstance(ast, dict) else []),
        source_hash=row.source_hash,
        filter_config=row.filter_config if isinstance(row.filter_config, dict) else None,
        created_at=isoformat_utc(row.created_at),
    )


def _job_to_out(row: ReportJob) -> JobOut:
    delivery_log = row.delivery_log if isinstance(row.delivery_log, list) else None
    return JobOut(
        id=row.id,
        analysis_id=row.analysis_id,
        template_id=row.template_id,
        status=row.status,
        stage=row.stage,
        content_hash=row.content_hash,
        final_pdf_path=row.final_pdf_path,
        kg_export_path=row.kg_export_path,
        error_message=row.error_message,
        filter_config=row.filter_config if isinstance(row.filter_config, dict) else None,
        delivery_log=delivery_log,
        created_at=isoformat_utc(row.created_at),
        updated_at=isoformat_utc(row.updated_at),
    )


def _extract_job_to_out(row: ReportTemplateExtractionJob) -> TemplateExtractionJobOut:
    return TemplateExtractionJobOut(
        id=row.id,
        status=row.status,
        stage=row.stage,
        progress_pct=row.progress_pct or 0,
        template_name=row.template_name,
        source_filename=row.source_filename,
        source_hash=row.source_hash,
        vault_object_key=row.vault_object_key,
        extraction_method=row.extraction_method,
        stage_diagnostics=row.stage_diagnostics if isinstance(row.stage_diagnostics, dict) else None,
        error_message=row.error_message,
        created_template_id=row.created_template_id,
        created_at=isoformat_utc(row.created_at),
        updated_at=isoformat_utc(row.updated_at),
    )


def _update_extract_job(
    db: Session,
    row: ReportTemplateExtractionJob,
    *,
    status: str | None = None,
    stage: str | None = None,
    progress_pct: int | None = None,
    diagnostics: dict | None = None,
    error_message: str | None = None,
) -> None:
    if status is not None:
        row.status = status
    if stage is not None:
        row.stage = stage
    if progress_pct is not None:
        row.progress_pct = max(0, min(100, int(progress_pct)))
    if diagnostics is not None:
        merged = dict(row.stage_diagnostics or {}) if isinstance(row.stage_diagnostics, dict) else {}
        merged[str(stage or row.stage or "unknown")] = diagnostics
        row.stage_diagnostics = merged
    if error_message is not None:
        row.error_message = error_message
    db.commit()


# ---------------- Ready analyses (wizard data source) ----------------


@router.get("/ready-analyses", response_model=list[ReadyAnalysisOut])
def list_ready_analyses(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    rows = (
        db.query(Analysis, Dataset)
        .join(Dataset, Analysis.dataset_id == Dataset.id)
        .filter(Dataset.user_id == user_id, Analysis.status == "complete")
        .order_by(Analysis.id.desc())
        .limit(100)
        .all()
    )
    return [
        ReadyAnalysisOut(
            analysis_id=an.id,
            dataset_id=ds.id,
            filename=ds.filename,
            row_count=ds.row_count or 0,
            column_count=ds.column_count or 0,
            status=an.status,
            upload_status=ds.upload_status,
            created_at=isoformat_utc(an.created_at),
        )
        for an, ds in rows
    ]


# ---------------- Templates ----------------


def _run_template_extraction_job(extract_job_id: int) -> None:
    db = SessionLocal()
    try:
        row = db.query(ReportTemplateExtractionJob).filter(
            ReportTemplateExtractionJob.id == extract_job_id
        ).first()
        if not row:
            return
        _update_extract_job(
            db,
            row,
            status="running",
            stage="stage1_immutable_ingestion_vaulting",
            progress_pct=5,
            diagnostics={"status": "started"},
        )

        src_path = Path(row.source_storage_path or "")
        raw = src_path.read_bytes() if src_path.is_file() else b""
        source_hash = hashlib.sha256(raw).hexdigest() if raw else ""
        row.source_hash = source_hash
        vault_object_key = ""
        store = try_build_default_store()
        if store and raw:
            vault_object_key = (
                f"report_templates/immutable/{source_hash[:2]}/{source_hash}/"
                f"{Path(row.source_filename or 'template.pdf').name}"
            )
            try:
                store.upload_object_body(vault_object_key, raw, "application/pdf")
            except Exception as exc:
                logger.warning("Immutable vault upload failed: %s", exc)
                vault_object_key = ""
        row.vault_object_key = vault_object_key or None
        _update_extract_job(
            db,
            row,
            stage="stage1_immutable_ingestion_vaulting",
            progress_pct=20,
            diagnostics={
                "status": "completed",
                "sha256": source_hash,
                "vault_object_key": vault_object_key,
            },
        )

        def _progress(stage: str, pct: int, payload: dict[str, object]):
            _update_extract_job(db, row, stage=stage, progress_pct=pct, diagnostics=dict(payload))

        ast, diagnostics = bp.compile_template_production(src_path, row.template_name, progress=_progress)
        ast_payload = diagnostics.get("blueprint_payload") if isinstance(diagnostics, dict) else None
        if not isinstance(ast_payload, dict):
            ast_payload = ast.to_dict()
            ast_payload["doc_id"] = diagnostics.get("doc_id") if isinstance(diagnostics, dict) else "MOSPI_TPL_01"
        ast_payload["production_stages"] = diagnostics.get("stages") if isinstance(diagnostics, dict) else {}

        template = ReportTemplate(
            user_id=row.user_id,
            name=row.template_name,
            description="Production extracted template",
            source_filename=row.source_filename,
            source_storage_path=row.source_storage_path,
            source_hash=ast.source_hash,
            ast_json=ast_payload,
            extraction_method=ast.extraction_method,
            page_count=ast.page_count,
        )
        db.add(template)
        db.commit()
        db.refresh(template)

        row.created_template_id = template.id
        row.extraction_method = ast.extraction_method
        _update_extract_job(
            db,
            row,
            status="completed",
            stage="stage6_final_ast_json_layout",
            progress_pct=100,
            diagnostics={"status": "completed", "created_template_id": template.id},
        )
    except Exception as exc:
        logger.exception("Template extraction job %s failed", extract_job_id)
        row = db.query(ReportTemplateExtractionJob).filter(
            ReportTemplateExtractionJob.id == extract_job_id
        ).first()
        if row:
            _update_extract_job(
                db,
                row,
                status="failed",
                error_message=str(exc)[:8000],
            )
    finally:
        db.close()


@router.post("/templates/extract-async", response_model=TemplateExtractionJobOut)
async def extract_template_async(
    background: BackgroundTasks,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    upload_dir = Path(os.getenv("REPORT_TEMPLATE_DIR", "./storage/templates"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{int(datetime.utcnow().timestamp())}_{uuid4().hex}_{Path(file.filename or 'template.pdf').name}"
    dest = upload_dir / safe_name
    raw = await file.read()
    dest.write_bytes(raw)

    row = ReportTemplateExtractionJob(
        user_id=user_id,
        status="pending",
        stage="queued",
        progress_pct=0,
        template_name=name.strip(),
        source_filename=file.filename,
        source_storage_path=str(dest),
        stage_diagnostics={"queued": {"description": description or ""}},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    background.add_task(_run_template_extraction_job, row.id)
    return _extract_job_to_out(row)


@router.get("/templates/extract-jobs", response_model=list[TemplateExtractionJobOut])
def list_template_extract_jobs(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    rows = (
        db.query(ReportTemplateExtractionJob)
        .filter(ReportTemplateExtractionJob.user_id == user_id)
        .order_by(ReportTemplateExtractionJob.id.desc())
        .limit(50)
        .all()
    )
    return [_extract_job_to_out(r) for r in rows]


@router.get("/templates/extract-jobs/{job_id}", response_model=TemplateExtractionJobOut)
def get_template_extract_job(
    job_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    row = db.query(ReportTemplateExtractionJob).filter(
        ReportTemplateExtractionJob.id == job_id,
        ReportTemplateExtractionJob.user_id == user_id,
    ).first()
    if not row:
        raise HTTPException(404, "Extraction job not found")
    return _extract_job_to_out(row)


@router.post("/templates/upload", response_model=TemplateCreateOut)
async def upload_template(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Phase 0 entry point — upload a historical/government PDF, compile to AST."""
    upload_dir = Path(os.getenv("REPORT_TEMPLATE_DIR", "./storage/templates"))
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = f"{int(datetime.utcnow().timestamp())}_{Path(file.filename or 'template.pdf').name}"
    dest = upload_dir / safe_name
    raw = await file.read()
    dest.write_bytes(raw)

    ast = bp.compile_template(dest, template_name=name)
    ast_payload = ast.to_dict()

    row = ReportTemplate(
        user_id=user_id,
        name=name,
        description=description,
        source_filename=file.filename,
        source_storage_path=str(dest),
        source_hash=ast.source_hash,
        ast_json=ast_payload,
        extraction_method=ast.extraction_method,
        page_count=ast.page_count,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    out = _template_to_out(row).model_dump()
    out["ast"] = ast_payload
    return TemplateCreateOut(**out)


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    rows = (
        db.query(ReportTemplate)
        .filter(
            (ReportTemplate.user_id == user_id) | (ReportTemplate.user_id.is_(None))
        )
        .order_by(ReportTemplate.id.desc())
        .all()
    )
    return [_template_to_out(r) for r in rows]


@router.post("/templates/clone-default", response_model=TemplateCreateOut)
def clone_default_template(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    ast_payload = bp.DEFAULT_MOSPI_TEMPLATE.to_dict()
    row = ReportTemplate(
        user_id=user_id,
        name=ast_payload.get("name") or "MoSPI Standard Report",
        description="Cloned from built-in default template",
        ast_json=ast_payload,
        extraction_method=ast_payload.get("extraction_method"),
        page_count=ast_payload.get("page_count"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    out = _template_to_out(row).model_dump()
    out["ast"] = ast_payload
    return TemplateCreateOut(**out)


@router.post("/templates/import-json", response_model=TemplateCreateOut)
def import_template_json(
    body: TemplateImportJsonIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Import AST from JSON — supports report-builder blocks or energy chapter document AST."""
    from report_builder.energy_ast_converter import document_ast_to_report_blocks

    raw = body.ast
    if body.document_format == "energy_chapter" or (
        isinstance(raw, dict) and "document" in raw and "blocks" not in raw
    ):
        raw = document_ast_to_report_blocks(raw)

    validated = validate_ast_payload(raw)
    row = ReportTemplate(
        user_id=user_id,
        name=body.name.strip(),
        description=(body.description or "Imported from JSON AST").strip(),
        ast_json=validated,
        extraction_method=validated.get("extraction_method") or "json_import",
        page_count=validated.get("page_count"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    out = _template_to_out(row).model_dump()
    out["ast"] = validated
    return TemplateCreateOut(**out)


@router.get("/templates/default/preview")
def default_template_preview():
    """Returns the builtin MoSPI default AST (no DB row)."""
    return bp.DEFAULT_MOSPI_TEMPLATE.to_dict()


@router.get("/templates/{template_id}")
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    row = require_template_access(db, template_id, user_id)
    return {
        **_template_to_out(row).model_dump(),
        "ast": row.ast_json,
        "filter_config": row.filter_config,
    }


@router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: int,
    body: TemplateUpdateIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    row = require_template_access(db, template_id, user_id, allow_shared=True)
    if row.user_id is not None and row.user_id != user_id:
        raise HTTPException(403, "Not allowed to edit this template")
    if row.user_id is None:
        row.user_id = user_id
    if body.name is not None:
        row.name = body.name.strip()
    if body.description is not None:
        row.description = body.description
    if body.ast is not None:
        validated = validate_ast_payload(body.ast)
        row.ast_json = validated
        row.page_count = validated.get("page_count") or row.page_count
    fc = filter_config_dict(body.filter_config)
    if fc is not None:
        row.filter_config = fc
    db.commit()
    db.refresh(row)
    return _template_to_out(row)


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    row = require_template_access(db, template_id, user_id, allow_shared=False)
    if row.user_id is None:
        raise HTTPException(403, "Cannot delete shared legacy templates")
    db.delete(row)
    db.commit()
    return {"deleted": template_id}


# ---------------- Jobs ----------------

def _run_job(job_id: int):
    """Background runner — opens its own DB session."""
    db = SessionLocal()
    try:
        job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
        if not job:
            return
        analysis = db.query(Analysis).filter(Analysis.id == job.analysis_id).first()
        if not analysis:
            job.status = "failed"
            job.error_message = "Analysis not found"
            db.commit()
            return
        if analysis.status != "complete":
            job.status = "failed"
            job.error_message = f"Analysis is {analysis.status}, must be 'complete'"
            db.commit()
            return

        dataset = db.query(Dataset).filter(Dataset.id == analysis.dataset_id).first()
        if not dataset:
            job.status = "failed"
            job.error_message = "Dataset row missing"
            db.commit()
            return

        payload = resolve_semantic_analysis_payload(db, analysis.id) or {}
        payload = enrich_payload_for_dashboard(db, analysis.id, payload)

        # Lazy DataFrame loader (Phase 3 kernel caches it)
        def _load_df():
            store = None
            if dataset.object_key:
                store = try_build_default_store()
            return dataframe_for_uploaded_dataset(
                dataset_storage_path=dataset.storage_path,
                dataset_object_key=dataset.object_key,
                filename=dataset.filename,
                object_store=store,
            )

        template_ast = None
        if job.template_id:
            tpl = db.query(ReportTemplate).filter(ReportTemplate.id == job.template_id).first()
            if tpl:
                template_ast = tpl.ast_json

        fc = job.filter_config
        if not fc and job.template_id:
            tpl = db.query(ReportTemplate).filter(ReportTemplate.id == job.template_id).first()
            if tpl and isinstance(tpl.filter_config, dict):
                fc = tpl.filter_config

        generate_report(
            db=db,
            job_id=job.id,
            analysis_id=analysis.id,
            dataset_id=dataset.id,
            analysis_payload=payload,
            df_loader=_load_df,
            template_ast=template_ast,
            dataset_filename=dataset.filename,
            filter_config=fc,
        )
    except Exception as exc:
        logger.exception("Report builder job %s failed", job_id)
        try:
            job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_message = str(exc)[:8000]
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _run_coord_report_job(job_id: int, ast_path: str, domain: str, use_gemini: bool) -> None:
    """Background: coordinate AST + Deep BI → PDF (same pipeline as CLI)."""
    db = SessionLocal()
    try:
        job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
        if not job:
            return
        analysis = db.query(Analysis).filter(Analysis.id == job.analysis_id).first()
        dataset = (
            db.query(Dataset).filter(Dataset.id == analysis.dataset_id).first()
            if analysis
            else None
        )
        if not analysis or not dataset:
            job.status = "failed"
            job.error_message = "Analysis or dataset missing"
            db.commit()
            return

        job.status = "running"
        job.stage = "coord_load_ast"
        db.commit()

        repo = Path(__file__).resolve().parents[2]
        ast_file = Path(ast_path) if ast_path else repo / "test_data" / "fina-ast.json"
        if not ast_file.is_absolute():
            ast_file = repo / ast_file
        if domain == "economics":
            data_file = repo / "test_data" / "Economics - MoSPI.csv"
        else:
            store = try_build_default_store() if dataset.object_key else None
            df = dataframe_for_uploaded_dataset(
                dataset_storage_path=dataset.storage_path,
                dataset_object_key=dataset.object_key,
                filename=dataset.filename,
                object_store=store,
            )
            tmp = repo / "storage" / "reports" / f"_coord_tmp_{job_id}.csv"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(tmp, index=False)
            data_file = tmp

        out_dir = Path(os.getenv("REPORT_STORAGE_PATH", str(repo / "storage" / "reports")))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_pdf = out_dir / f"coord_report_job_{job_id}.pdf"

        from ast_core.coord_deep_bi_orchestrator import run_coord_report_strict

        job.stage = "coord_deep_bi"
        db.commit()

        result = run_coord_report_strict(
            ast_path=str(ast_file),
            data_path=str(data_file),
            out_pdf=str(out_pdf),
            domain=domain,
            use_gemini=use_gemini,
        )
        job.status = "exported"
        job.stage = "coord_done"
        job.final_pdf_path = result.pdf_path
        job.content_hash = hashlib.sha256(
            Path(result.pdf_path).read_bytes()
        ).hexdigest()
        br = result.bind_report
        job.blocks_json = {
            "pipeline": "coord_report_strict_deep_bi",
            "domain": domain,
            "bound_ast_path": result.bound_ast_path,
            "content_bound": br.content.paragraphs_bound,
            "tables_bound": br.tables.tables_bound,
            "figures_bound": br.figures.figures_bound,
            "figures_fallback": br.figures.figures_from_fallback,
            "errors": br.errors[:20],
        }
        db.commit()
    except Exception as exc:
        logger.exception("Coord report job %s failed", job_id)
        try:
            job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_message = str(exc)[:8000]
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/coord-generate", response_model=CoordGenerateOut)
def coord_generate(
    req: CoordGenerateRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Coordinate-exact MoSPI PDF from fina-ast + dataset (economics domain default)."""
    require_analysis_owner(db, req.analysis_id, user_id)
    analysis = db.query(Analysis).filter(Analysis.id == req.analysis_id).first()
    if analysis.status != "complete":
        raise HTTPException(409, f"Analysis status is '{analysis.status}', must be 'complete'")

    job = ReportJob(
        analysis_id=req.analysis_id,
        template_id=None,
        status="pending",
        stage="coord_queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    ast_path = req.ast_path or "test_data/fina-ast.json"
    background.add_task(
        _run_coord_report_job, job.id, ast_path, req.domain, req.use_gemini,
    )
    return CoordGenerateOut(
        job_id=job.id,
        status=job.status,
        stage=job.stage,
        message="Coordinate report job queued (same pipeline as generate_coord_report.py CLI).",
    )


@router.post("/generate", response_model=JobOut)
def generate(
    req: GenerateRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    analysis = require_analysis_owner(db, req.analysis_id, user_id)
    if analysis.status != "complete":
        raise HTTPException(409, f"Analysis status is '{analysis.status}', must be 'complete'")
    if req.template_id is not None:
        require_template_access(db, req.template_id, user_id)

    job = ReportJob(
        analysis_id=req.analysis_id,
        template_id=req.template_id,
        status="pending",
        stage="queued",
        filter_config=filter_config_dict(req.filter_config),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background.add_task(_run_job, job.id)
    return _job_to_out(job)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    analysis_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    q = (
        db.query(ReportJob)
        .join(Analysis, ReportJob.analysis_id == Analysis.id)
        .join(Dataset, Analysis.dataset_id == Dataset.id)
        .filter(Dataset.user_id == user_id)
        .order_by(ReportJob.id.desc())
    )
    if analysis_id is not None:
        require_analysis_owner(db, analysis_id, user_id)
        q = q.filter(ReportJob.analysis_id == analysis_id)
    return [_job_to_out(r) for r in q.limit(100).all()]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    return _job_to_out(require_job_access(db, job_id, user_id))


@router.get("/jobs/{job_id}/canvas")
def get_canvas(
    job_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    row = require_job_access(db, job_id, user_id)
    return {
        **_job_to_out(row).model_dump(),
        "canvas": row.blocks_json or None,
        "verifier_report": row.verifier_report or None,
    }


@router.post("/jobs/{job_id}/deliver")
def deliver_job(
    job_id: int,
    body: DeliverRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    row = require_job_access(db, job_id, user_id)
    result = delivery_mod.deliver_report(job=row, request=body)
    log = list(row.delivery_log) if isinstance(row.delivery_log, list) else []
    log.append(result)
    row.delivery_log = log
    db.commit()
    return {"ok": True, "entry": result}


@router.get("/jobs/{job_id}/download")
def download_job_pdf(
    job_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    row = require_job_access(db, job_id, user_id)
    if not row.final_pdf_path:
        raise HTTPException(409, "PDF not yet generated")
    path = Path(row.final_pdf_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        raise HTTPException(404, "Generated PDF not found on disk")
    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=f"statathon-report-{job_id}.pdf",
    )


# ---------------- Block-level ops ----------------

@router.post("/jobs/{job_id}/blocks/{block_id}/regenerate")
def regenerate_block(
    job_id: int,
    block_id: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    job = require_job_access(db, job_id, user_id)
    if not job.blocks_json:
        raise HTTPException(404, "Job or canvas not found")
    canvas = dict(job.blocks_json)
    sections = canvas.get("sections") or []
    target_block = None
    for sect in sections:
        for blk in sect.get("blocks") or []:
            if blk.get("block_id") == block_id:
                target_block = blk
                break
        if target_block:
            break
    if not target_block:
        raise HTTPException(404, "Block not found")

    if target_block.get("kind") != "narrative":
        raise HTTPException(409, "Only narrative blocks can be regenerated")

    payload_obj = resolve_semantic_analysis_payload(db, job.analysis_id) or {}
    payload_obj = enrich_payload_for_dashboard(db, job.analysis_id, payload_obj)

    ledger = ReflectionLedger(db)
    reflections = ledger.retrieve_similar(block_id, target_block.get("title") or "")
    facts: dict = {}
    for k in ("row_count", "column_count", "missing_pct"):
        v = (payload_obj.get("health") or {}).get(k)
        if v is not None:
            facts[k] = v

    new_text = fw.scribe_narrative(
        block_id=block_id,
        block_title=target_block.get("title") or "",
        block_section=target_block.get("section") or "body",
        hints={"max_words": 240},
        facts=facts,
        reflections=reflections,
    )
    old = target_block.get("payload", {}).get("text")
    target_block["payload"] = {"text": new_text}
    target_block["version"] = int(target_block.get("version") or 1) + 1
    target_block["generated_at"] = datetime.utcnow().isoformat()

    verdict = fw.verify_block(
        block_id=block_id, narrative=new_text, df=None, expected_facts=facts,
    )
    target_block["verifier"] = verdict.to_dict()

    job.blocks_json = canvas
    db.commit()

    ledger.record_correction(
        job_id=job_id, block_id=block_id, kind="regenerate",
        before=old, after=new_text, diagnostics={"verdict": verdict.overall_status},
    )
    return target_block


@router.post("/jobs/{job_id}/blocks/{block_id}/correction")
def record_correction(
    job_id: int,
    block_id: str,
    body: CorrectionIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    job = require_job_access(db, job_id, user_id)
    ledger = ReflectionLedger(db)
    new_id = ledger.record_correction(
        job_id=job_id, block_id=block_id, kind=body.kind,
        before=body.before, after=body.after, diagnostics=body.diagnostics,
    )
    # Apply correction text to the block if provided
    if body.after and job.blocks_json:
        canvas = dict(job.blocks_json)
        for sect in canvas.get("sections") or []:
            for blk in sect.get("blocks") or []:
                if blk.get("block_id") == block_id and blk.get("kind") == "narrative":
                    blk.setdefault("payload", {})["text"] = body.after
                    blk["version"] = int(blk.get("version") or 1) + 1
                    blk["generated_at"] = datetime.utcnow().isoformat()
        job.blocks_json = canvas
        db.commit()
    return {"correction_id": new_id}


# ---------------- Canvas mutation (insert / move / delete) ----------------


def _load_job_or_404(db: Session, job_id: int, user_id: int) -> ReportJob:
    return require_job_access(db, job_id, user_id)


def _ensure_section(canvas: dict, section: str) -> dict:
    for s in canvas.get("sections") or []:
        if s.get("section") == section:
            return s
    new_section = {"section": section, "blocks": []}
    canvas.setdefault("sections", []).append(new_section)
    return new_section


def _find_block(canvas: dict, block_id: str) -> tuple[dict, dict, int] | None:
    for s in canvas.get("sections") or []:
        for i, b in enumerate(s.get("blocks") or []):
            if b.get("block_id") == block_id:
                return s, b, i
    return None


@router.post("/jobs/{job_id}/blocks/insert")
def insert_block(
    job_id: int,
    body: InsertBlockIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Insert a chat-proposed (or freshly drafted) block into the canvas."""
    job = _load_job_or_404(db, job_id, user_id)
    canvas = dict(job.blocks_json or {"job_id": job.id, "analysis_id": job.analysis_id,
                                       "template_name": "", "summary": {}, "sections": []})
    sect = _ensure_section(canvas, body.section)
    block = dict(body.block)
    block.setdefault("block_id", f"chat_{int(datetime.utcnow().timestamp() * 1000)}")
    block.setdefault("version", 1)
    block.setdefault("generated_at", datetime.utcnow().isoformat())
    pos = body.position
    blocks = sect.setdefault("blocks", [])
    if pos is None or pos >= len(blocks) or pos < 0:
        blocks.append(block)
    else:
        blocks.insert(pos, block)
    job.blocks_json = canvas
    db.commit()
    return block


@router.post("/jobs/{job_id}/blocks/move")
def move_block(
    job_id: int,
    body: MoveBlockIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    job = _load_job_or_404(db, job_id, user_id)
    canvas = dict(job.blocks_json or {})
    found = _find_block(canvas, body.block_id)
    if not found:
        raise HTTPException(404, "Block not found")
    sect_src, block, idx = found
    sect_src["blocks"].pop(idx)
    sect_target = _ensure_section(canvas, body.target_section)
    blocks = sect_target.setdefault("blocks", [])
    pos = body.target_position
    if pos is None or pos >= len(blocks) or pos < 0:
        blocks.append(block)
    else:
        blocks.insert(pos, block)
    block["version"] = int(block.get("version") or 1) + 1
    job.blocks_json = canvas
    db.commit()
    return {"ok": True}


@router.delete("/jobs/{job_id}/blocks/{block_id}")
def delete_block(
    job_id: int,
    block_id: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    job = _load_job_or_404(db, job_id, user_id)
    canvas = dict(job.blocks_json or {})
    found = _find_block(canvas, block_id)
    if not found:
        raise HTTPException(404, "Block not found")
    sect, _block, idx = found
    sect["blocks"].pop(idx)
    job.blocks_json = canvas
    db.commit()
    return {"deleted": block_id}


@router.post("/jobs/{job_id}/re-export")
def re_export(
    job_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Re-render the PDF from the current canvas after edits / inserts."""
    from report_builder.exporter import export_pdf

    job = _load_job_or_404(db, job_id, user_id)
    if not job.blocks_json:
        raise HTTPException(409, "No canvas to export")
    out_dir = Path(os.getenv("REPORT_STORAGE_PATH", "./storage/reports"))
    pdf_path = out_dir / f"report_builder_{job.id}.pdf"
    dataset_filename = None
    analysis = db.query(Analysis).filter(Analysis.id == job.analysis_id).first()
    if analysis:
        ds = db.query(Dataset).filter(Dataset.id == analysis.dataset_id).first()
        if ds:
            dataset_filename = ds.filename
    storage_path, digest = export_pdf(
        canvas_dict=job.blocks_json, out_path=pdf_path,
        dataset_filename=dataset_filename,
    )
    job.final_pdf_path = storage_path
    job.content_hash = digest
    job.status = "exported"
    db.commit()
    return {"content_hash": digest, "final_pdf_path": storage_path}


# ---------------- DeepAgent BI Chat ----------------


@router.get("/jobs/{job_id}/context")
def deep_context(
    job_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Return the DeepAgent context panel status — which data sources are loaded."""
    job = _load_job_or_404(db, job_id, user_id)
    analysis = db.query(Analysis).filter(Analysis.id == job.analysis_id).first()
    if not analysis:
        raise HTTPException(404, "Analysis not found")
    dataset = db.query(Dataset).filter(Dataset.id == analysis.dataset_id).first()
    if not dataset:
        raise HTTPException(404, "Dataset not found")

    payload = resolve_semantic_analysis_payload(db, analysis.id) or {}
    payload = enrich_payload_for_dashboard(db, analysis.id, payload)

    def _load_df():
        store = try_build_default_store() if dataset.object_key else None
        return dataframe_for_uploaded_dataset(
            dataset_storage_path=dataset.storage_path,
            dataset_object_key=dataset.object_key,
            filename=dataset.filename,
            object_store=store,
        )

    from report_builder.deep_bi import get_context_status
    return get_context_status(
        analysis_id=analysis.id,
        analysis_payload=payload,
        df_loader=_load_df,
        db=db,
    )


@router.post("/jobs/{job_id}/deep-chat")
def deep_chat(
    job_id: int,
    body: ChatIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """DeepAgent BI chat — full PlannerAgent → RetrievalAgent → AnalyticsAgent → Scribe → Verifier pipeline.

    Returns multiple RenderedBlocks (narrative + table + chart + metrics)
    that can be dragged into any section of the report canvas.
    """
    job = _load_job_or_404(db, job_id, user_id)
    if not body.query or not body.query.strip():
        raise HTTPException(400, "Empty query")

    analysis = db.query(Analysis).filter(Analysis.id == job.analysis_id).first()
    if not analysis:
        raise HTTPException(404, "Underlying analysis not found")
    dataset = db.query(Dataset).filter(Dataset.id == analysis.dataset_id).first()
    if not dataset:
        raise HTTPException(404, "Underlying dataset not found")

    payload = resolve_semantic_analysis_payload(db, analysis.id) or {}
    payload = enrich_payload_for_dashboard(db, analysis.id, payload)

    def _load_df():
        store = try_build_default_store() if dataset.object_key else None
        return dataframe_for_uploaded_dataset(
            dataset_storage_path=dataset.storage_path,
            dataset_object_key=dataset.object_key,
            filename=dataset.filename,
            object_store=store,
        )

    ledger = ReflectionLedger(db)
    stm = STM()

    from report_builder.deep_bi import deep_chat as _deep_chat
    result = _deep_chat(
        job_id=job.id,
        analysis_id=analysis.id,
        query=body.query.strip(),
        analysis_payload=payload,
        df_loader=_load_df,
        db=db,
        stm=stm,
        ledger=ledger,
    )
    return result


# ---------------- Classic BI Chat (kept for backward compat) ----------------


@router.get("/jobs/{job_id}/chat/history")
def chat_history(
    job_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _load_job_or_404(db, job_id, user_id)
    return {"turns": bi_chat.get_history(job_id)}


@router.post("/jobs/{job_id}/chat")
def chat(
    job_id: int,
    body: ChatIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """One BI chat turn — runs through Phases 1-5 and returns a draggable block."""
    job = _load_job_or_404(db, job_id, user_id)
    if not body.query or not body.query.strip():
        raise HTTPException(400, "Empty query")

    analysis = db.query(Analysis).filter(Analysis.id == job.analysis_id).first()
    if not analysis:
        raise HTTPException(404, "Underlying analysis not found")
    dataset = db.query(Dataset).filter(Dataset.id == analysis.dataset_id).first()
    if not dataset:
        raise HTTPException(404, "Underlying dataset not found")

    payload = resolve_semantic_analysis_payload(db, analysis.id) or {}
    payload = enrich_payload_for_dashboard(db, analysis.id, payload)

    def _load_df():
        store = try_build_default_store() if dataset.object_key else None
        return dataframe_for_uploaded_dataset(
            dataset_storage_path=dataset.storage_path,
            dataset_object_key=dataset.object_key,
            filename=dataset.filename,
            object_store=store,
        )

    turn = bi_chat.chat_query(
        job_id=job.id,
        analysis_id=analysis.id,
        query=body.query.strip(),
        analysis_payload=payload,
        df_loader=_load_df,
        ledger=ReflectionLedger(db),
        stm=STM(),
    )
    return turn.to_dict()


# ---------------- WebSocket: real-time canvas + chat updates ----------------


class _ConnectionRegistry:
    def __init__(self):
        self._by_job: dict[int, set[WebSocket]] = {}

    async def connect(self, job_id: int, ws: WebSocket):
        await ws.accept()
        self._by_job.setdefault(job_id, set()).add(ws)

    def disconnect(self, job_id: int, ws: WebSocket):
        peers = self._by_job.get(job_id)
        if peers:
            peers.discard(ws)
            if not peers:
                self._by_job.pop(job_id, None)

    async def broadcast(self, job_id: int, payload: dict):
        for ws in list(self._by_job.get(job_id, set())):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(job_id, ws)


_WS = _ConnectionRegistry()


@router.websocket("/ws/jobs/{job_id}")
async def ws_job(websocket: WebSocket, job_id: int):
    """Real-time AGUI: chat turns and canvas mutations are pushed as JSON messages.

    Protocol (client -> server):
      {"op":"chat","query":"..."}                         (runs BI chat turn)
      {"op":"insert","section":"...","block":{...}}       (insert a block)
      {"op":"move","block_id":"...","target_section":"...","target_position":n}
      {"op":"delete","block_id":"..."}

    Protocol (server -> client):
      {"event":"chat_turn", "turn": {...}}
      {"event":"canvas_update", "canvas": {...}}
    """
    await _WS.connect(job_id, websocket)
    try:
        while True:
            msg = await websocket.receive_json()
            op = msg.get("op")
            db = SessionLocal()
            try:
                if op == "chat":
                    job = _load_job_or_404(db, job_id)
                    analysis = db.query(Analysis).filter(Analysis.id == job.analysis_id).first()
                    dataset = db.query(Dataset).filter(Dataset.id == analysis.dataset_id).first() if analysis else None
                    if not analysis or not dataset:
                        await websocket.send_json({"event": "error", "detail": "missing analysis/dataset"})
                        continue
                    payload = resolve_semantic_analysis_payload(db, analysis.id) or {}
                    payload = enrich_payload_for_dashboard(db, analysis.id, payload)

                    def _load_df(_ds=dataset):
                        store = try_build_default_store() if _ds.object_key else None
                        return dataframe_for_uploaded_dataset(
                            dataset_storage_path=_ds.storage_path,
                            dataset_object_key=_ds.object_key,
                            filename=_ds.filename,
                            object_store=store,
                        )

                    turn = bi_chat.chat_query(
                        job_id=job.id, analysis_id=analysis.id,
                        query=msg.get("query") or "",
                        analysis_payload=payload, df_loader=_load_df,
                        ledger=ReflectionLedger(db), stm=STM(),
                    )
                    await _WS.broadcast(job_id, {"event": "chat_turn", "turn": turn.to_dict()})
                elif op == "insert":
                    body = InsertBlockIn(section=msg.get("section") or "bi_findings",
                                         block=msg.get("block") or {},
                                         position=msg.get("position"))
                    insert_block(job_id, body, db)
                    job = _load_job_or_404(db, job_id)
                    await _WS.broadcast(job_id, {"event": "canvas_update", "canvas": job.blocks_json})
                elif op == "move":
                    body = MoveBlockIn(block_id=msg.get("block_id") or "",
                                       target_section=msg.get("target_section") or "bi_findings",
                                       target_position=msg.get("target_position"))
                    move_block(job_id, body, db)
                    job = _load_job_or_404(db, job_id)
                    await _WS.broadcast(job_id, {"event": "canvas_update", "canvas": job.blocks_json})
                elif op == "delete":
                    bid = msg.get("block_id")
                    if bid:
                        delete_block(job_id, bid, db)
                        job = _load_job_or_404(db, job_id)
                        await _WS.broadcast(job_id, {"event": "canvas_update", "canvas": job.blocks_json})
                else:
                    await websocket.send_json({"event": "error", "detail": f"unknown op {op}"})
            finally:
                db.close()
    except WebSocketDisconnect:
        _WS.disconnect(job_id, websocket)
    except Exception as exc:
        logger.exception("ws error")
        try:
            await websocket.send_json({"event": "error", "detail": str(exc)})
        except Exception:
            pass
        _WS.disconnect(job_id, websocket)
