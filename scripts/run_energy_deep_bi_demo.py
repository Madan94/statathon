#!/usr/bin/env python3
"""Seed energy reserves dataset + AST template, run analysis, generate report, test Deep BI.

Usage (from repo root):
  $env:PYTHONPATH = "$PWD"
  .\\.venv\\Scripts\\python.exe scripts/run_energy_deep_bi_demo.py

Prints dashboard URLs when done.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "api"))
sys.path.insert(1, str(REPO))

from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import Analysis, Dataset, ReportJob, ReportTemplate, User
from report_builder.energy_ast_converter import document_ast_to_report_blocks
from report_builder.deep_bi import deep_chat
from services.analysis_runner import execute_registered_analysis_job
from services.analysis_results_service import enrich_payload_for_dashboard, resolve_semantic_analysis_payload
from services.dataset_profiler import profile_dataset
from repositories.dataset_repository import DatasetRepository
from services.dataset_profile_service import DatasetProfileService
from report_builder_api.template_validation import validate_ast_payload

CSV_PATH = REPO / "test_data" / "unified_energy_reserves_dataset.csv"
AST_PATH = REPO / "test_data" / "ast.json.txt"
UPLOAD_DIR = REPO / "api" / "storage" / "uploads"


def _load_df(dataset: Dataset):
    from core.ingestion import dataframe_for_uploaded_dataset

    return dataframe_for_uploaded_dataset(
        dataset.storage_path,
        dataset.object_key,
        dataset.filename,
        None,
    )


def ensure_energy_dataset(db: Session, user_id: int) -> Dataset:
    existing = (
        db.query(Dataset)
        .filter(Dataset.user_id == user_id, Dataset.filename == CSV_PATH.name)
        .order_by(Dataset.id.desc())
        .first()
    )
    if existing and existing.storage_path and Path(existing.storage_path).is_file():
        print(f"Reusing dataset #{existing.id} ({existing.filename})")
        return existing

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = CSV_PATH.suffix
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    shutil.copy2(CSV_PATH, dest)
    profile = profile_dataset(str(dest), filename=CSV_PATH.name)
    file_bytes = dest.read_bytes()

    ds = Dataset(
        user_id=user_id,
        filename=CSV_PATH.name,
        storage_path=str(dest),
        storage_provider="local",
        file_size=dest.stat().st_size,
        row_count=profile["row_count"],
        column_count=profile["column_count"],
        health_summary=profile["health_summary"],
        upload_status="UPLOADED",
        status="ingested",
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    DatasetProfileService(db).persist_from_profiler(ds.id, profile, source_bytes=file_bytes)
    db.commit()
    print(f"Created dataset #{ds.id} — {ds.row_count} rows × {ds.column_count} cols")
    return ds


def run_analysis(db: Session, dataset_id: int) -> Analysis:
    complete = (
        db.query(Analysis)
        .filter(Analysis.dataset_id == dataset_id, Analysis.status == "complete")
        .order_by(Analysis.id.desc())
        .first()
    )
    if complete:
        print(f"Reusing completed analysis #{complete.id}")
        return complete

    an = Analysis(dataset_id=dataset_id, status="pending")
    db.add(an)
    db.commit()
    db.refresh(an)
    print(f"Running analysis #{an.id} (this may take 10–20 min on first run)…")
    execute_registered_analysis_job(dataset_id, an.id)
    db.refresh(an)
    if an.status != "complete":
        raise RuntimeError(f"Analysis #{an.id} ended with status={an.status}: {an.error_message}")
    print(f"Analysis #{an.id} complete")
    return an


def ensure_energy_template(db: Session, user_id: int) -> ReportTemplate:
    name = "Energy Reserves and Potential (AST)"
    existing = (
        db.query(ReportTemplate)
        .filter(ReportTemplate.user_id == user_id, ReportTemplate.name == name)
        .first()
    )
    if existing:
        print(f"Reusing template #{existing.id}")
        return existing

    raw = json.loads(AST_PATH.read_text(encoding="utf-8"))
    ast_payload = validate_ast_payload(document_ast_to_report_blocks(raw))
    row = ReportTemplate(
        user_id=user_id,
        name=name,
        description="Imported from test_data/ast.json.txt",
        ast_json=ast_payload,
        extraction_method=ast_payload.get("extraction_method"),
        page_count=ast_payload.get("page_count"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    print(f"Created template #{row.id} with {len(ast_payload['blocks'])} blocks")
    return row


def generate_report_job(db: Session, analysis_id: int, template_id: int) -> ReportJob:
    from core.ingestion import dataframe_for_uploaded_dataset
    from object_storage.object_store import try_build_default_store
    from report_builder.pipeline import generate_report

    existing = (
        db.query(ReportJob)
        .filter(ReportJob.analysis_id == analysis_id, ReportJob.template_id == template_id)
        .order_by(ReportJob.id.desc())
        .first()
    )
    if existing and existing.status in ("exported", "verified") and existing.final_pdf_path:
        print(f"Reusing report job #{existing.id} ({existing.status})")
        return existing

    job = ReportJob(
        analysis_id=analysis_id,
        template_id=template_id,
        status="pending",
        stage="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    print(f"Generating report job #{job.id}…")

    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    dataset = db.query(Dataset).filter(Dataset.id == analysis.dataset_id).first()
    payload = resolve_semantic_analysis_payload(db, analysis.id) or {}
    payload = enrich_payload_for_dashboard(db, analysis.id, payload)
    template = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()

    def _load_df():
        store = try_build_default_store() if dataset.object_key else None
        return dataframe_for_uploaded_dataset(
            dataset.storage_path,
            dataset.object_key,
            dataset.filename,
            store,
        )

    generate_report(
        db=db,
        job_id=job.id,
        analysis_id=analysis.id,
        dataset_id=dataset.id,
        analysis_payload=payload,
        df_loader=_load_df,
        template_ast=template.ast_json if template else None,
        dataset_filename=dataset.filename,
        filter_config=job.filter_config,
    )
    db.refresh(job)
    if job.status == "failed":
        raise RuntimeError(f"Report job failed: {job.error_message}")
    print(f"Report job #{job.id} status={job.status}")
    return job


def test_deep_bi(db: Session, job: ReportJob, analysis: Analysis, dataset: Dataset) -> None:
    payload = resolve_semantic_analysis_payload(db, analysis.id) or {}
    payload = enrich_payload_for_dashboard(db, analysis.id, payload)
    queries = [
        "What are total coal reserves by state in Jharkhand?",
        "Compare proved vs inferred reserves across resource categories.",
        "Which states have the highest total reserves?",
    ]
    for q in queries:
        print(f"\nDeep BI Q: {q}")
        turn = deep_chat(
            job_id=job.id,
            analysis_id=analysis.id,
            query=q,
            analysis_payload=payload,
            df_loader=lambda: _load_df(dataset),
            db=db,
        )
        print(f"  -> {turn.get('text', '')[:200]}...")
        print(f"  blocks: {len(turn.get('blocks') or [])} intent={turn.get('plan', {}).get('intent')}")


def main() -> None:
    if not CSV_PATH.is_file():
        raise SystemExit(f"Missing dataset: {CSV_PATH}")
    if not AST_PATH.is_file():
        raise SystemExit(f"Missing AST: {AST_PATH}")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "officer@example.com").first()
        if not user:
            user = db.query(User).first()
        if not user:
            raise SystemExit("No user in DB — log in once via dashboard first.")

        dataset = ensure_energy_dataset(db, user.id)
        analysis = run_analysis(db, dataset.id)
        template = ensure_energy_template(db, user.id)
        job = generate_report_job(db, analysis.id, template.id)
        test_deep_bi(db, job, analysis, dataset)

        pdf = job.final_pdf_path or ""
        print("\n" + "=" * 60)
        print("ENERGY DEEP BI DEMO — READY")
        print("=" * 60)
        print(f"Dataset:   #{dataset.id}  {dataset.filename}")
        print(f"Analysis:  #{analysis.id}  (status={analysis.status})")
        print(f"Template:  #{template.id}  {template.name}")
        print(f"Report:    job #{job.id}  status={job.status}")
        if pdf:
            print(f"PDF:       {pdf}")
        print("\nOpen in browser:")
        print(f"  Report canvas + Deep BI:  http://localhost:3000/report-builder/{job.id}")
        print(f"  PDF download:             http://localhost:3000/api/backend/report-builder/jobs/{job.id}/pdf")
        print(f"  New report wizard:        http://localhost:3000/report-builder/new")
        print("=" * 60)
    finally:
        db.close()


if __name__ == "__main__":
    main()
