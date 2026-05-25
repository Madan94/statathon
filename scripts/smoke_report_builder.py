"""End-to-end smoke test for the Report Builder.

Picks the most-recent complete analysis, runs all 6 phases via the orchestrator
without the FastAPI layer, and prints a summary.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Make repo root importable when run as a script.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "api"))

# Load .env so DATABASE_URL, GEMINI_API_KEY etc. are available.
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(_ROOT / ".env")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")

from database.database import SessionLocal  # noqa: E402
from database.models import Analysis, Dataset, ReportJob  # noqa: E402
from services.analysis_results_service import (  # noqa: E402
    enrich_payload_for_dashboard,
    resolve_semantic_analysis_payload,
)
from core.ingestion import dataframe_for_uploaded_dataset  # noqa: E402
from object_storage.object_store import try_build_default_store  # noqa: E402
from report_builder.pipeline import generate_report  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        analysis = (
            db.query(Analysis)
            .filter(Analysis.status == "complete")
            .order_by(Analysis.id.desc())
            .first()
        )
        if not analysis:
            print("No completed analyses in the database. Run one analysis first.")
            return 1

        dataset = db.query(Dataset).filter(Dataset.id == analysis.dataset_id).first()
        if not dataset:
            print(f"Dataset {analysis.dataset_id} missing")
            return 1

        print(f"Smoke test against analysis={analysis.id} dataset={dataset.id} file={dataset.filename}")

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

        # Persist a ReportJob row so the orchestrator can update it.
        job = ReportJob(
            analysis_id=analysis.id,
            template_id=None,
            status="pending",
            stage="queued",
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        result = generate_report(
            db=db,
            job_id=job.id,
            analysis_id=analysis.id,
            dataset_id=dataset.id,
            analysis_payload=payload,
            df_loader=_load_df,
            template_ast=None,
            dataset_filename=dataset.filename,
        )

        print("\n=== Result ===")
        for k, v in result.items():
            print(f"  {k}: {v}")
        print(f"\nJob row #{job.id} stored. Open /report-builder/{job.id} in the dashboard.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
