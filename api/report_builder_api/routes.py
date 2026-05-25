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
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile,
    WebSocket, WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import Analysis, Dataset, ReportCorrection, ReportJob, ReportTemplate
from services.analysis_results_service import resolve_semantic_analysis_payload, enrich_payload_for_dashboard
from core.ingestion import dataframe_for_uploaded_dataset
from object_storage.object_store import try_build_default_store

from report_builder import bi_chat
from report_builder import blueprint as bp
from report_builder import firewall as fw
from report_builder.memory import ReflectionLedger, STM
from report_builder.pipeline import generate_report

from .schemas import (
    ChatIn, CorrectionIn, GenerateRequest, InsertBlockIn, JobOut, MoveBlockIn,
    TemplateCreateOut, TemplateOut,
)

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
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


def _job_to_out(row: ReportJob) -> JobOut:
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
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


# ---------------- Templates ----------------

@router.post("/templates/upload", response_model=TemplateCreateOut)
async def upload_template(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
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
def list_templates(db: Session = Depends(get_db)):
    rows = db.query(ReportTemplate).order_by(ReportTemplate.id.desc()).all()
    return [_template_to_out(r) for r in rows]


@router.get("/templates/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db)):
    row = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
    if not row:
        raise HTTPException(404, "Template not found")
    return {
        **_template_to_out(row).model_dump(),
        "ast": row.ast_json,
    }


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    row = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
    if not row:
        raise HTTPException(404, "Template not found")
    db.delete(row)
    db.commit()
    return {"deleted": template_id}


@router.get("/templates/default/preview")
def default_template_preview():
    """Returns the builtin MoSPI default AST (no DB row)."""
    return bp.DEFAULT_MOSPI_TEMPLATE.to_dict()


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

        generate_report(
            db=db,
            job_id=job.id,
            analysis_id=analysis.id,
            dataset_id=dataset.id,
            analysis_payload=payload,
            df_loader=_load_df,
            template_ast=template_ast,
            dataset_filename=dataset.filename,
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


@router.post("/generate", response_model=JobOut)
def generate(req: GenerateRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    analysis = db.query(Analysis).filter(Analysis.id == req.analysis_id).first()
    if not analysis:
        raise HTTPException(404, "Analysis not found")
    if analysis.status != "complete":
        raise HTTPException(409, f"Analysis status is '{analysis.status}', must be 'complete'")
    if req.template_id is not None:
        tpl = db.query(ReportTemplate).filter(ReportTemplate.id == req.template_id).first()
        if not tpl:
            raise HTTPException(404, "Template not found")

    job = ReportJob(
        analysis_id=req.analysis_id,
        template_id=req.template_id,
        status="pending",
        stage="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background.add_task(_run_job, job.id)
    return _job_to_out(job)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(analysis_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(ReportJob).order_by(ReportJob.id.desc())
    if analysis_id is not None:
        q = q.filter(ReportJob.analysis_id == analysis_id)
    return [_job_to_out(r) for r in q.limit(100).all()]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    row = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not row:
        raise HTTPException(404, "Job not found")
    return _job_to_out(row)


@router.get("/jobs/{job_id}/canvas")
def get_canvas(job_id: int, db: Session = Depends(get_db)):
    row = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not row:
        raise HTTPException(404, "Job not found")
    return {
        **_job_to_out(row).model_dump(),
        "canvas": row.blocks_json or None,
        "verifier_report": row.verifier_report or None,
    }


@router.get("/jobs/{job_id}/download")
def download_job_pdf(job_id: int, db: Session = Depends(get_db)):
    row = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not row:
        raise HTTPException(404, "Job not found")
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
def regenerate_block(job_id: int, block_id: str, db: Session = Depends(get_db)):
    job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not job or not job.blocks_json:
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
    job_id: int, block_id: str, body: CorrectionIn, db: Session = Depends(get_db)
):
    job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
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


def _load_job_or_404(db: Session, job_id: int) -> ReportJob:
    job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return job


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
def insert_block(job_id: int, body: InsertBlockIn, db: Session = Depends(get_db)):
    """Insert a chat-proposed (or freshly drafted) block into the canvas."""
    job = _load_job_or_404(db, job_id)
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
def move_block(job_id: int, body: MoveBlockIn, db: Session = Depends(get_db)):
    job = _load_job_or_404(db, job_id)
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
def delete_block(job_id: int, block_id: str, db: Session = Depends(get_db)):
    job = _load_job_or_404(db, job_id)
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
def re_export(job_id: int, db: Session = Depends(get_db)):
    """Re-render the PDF from the current canvas after edits / inserts."""
    from report_builder.exporter import export_pdf

    job = _load_job_or_404(db, job_id)
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


# ---------------- BI Chat ----------------


@router.get("/jobs/{job_id}/chat/history")
def chat_history(job_id: int, db: Session = Depends(get_db)):
    _load_job_or_404(db, job_id)
    return {"turns": bi_chat.get_history(job_id)}


@router.post("/jobs/{job_id}/chat")
def chat(job_id: int, body: ChatIn, db: Session = Depends(get_db)):
    """One BI chat turn — runs through Phases 1-5 and returns a draggable block."""
    job = _load_job_or_404(db, job_id)
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
