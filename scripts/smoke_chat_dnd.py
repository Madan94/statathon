"""Smoke test for the BI Chat + drag-and-drop + re-export flow."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "api"))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(_ROOT / ".env")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")

import pandas as pd  # noqa: E402

from database.database import SessionLocal  # noqa: E402
from database.models import Analysis, Dataset, ReportJob  # noqa: E402
from services.analysis_results_service import (  # noqa: E402
    enrich_payload_for_dashboard,
    resolve_semantic_analysis_payload,
)
from report_builder import bi_chat  # noqa: E402
from report_builder.exporter import export_pdf  # noqa: E402
from report_builder.memory import ReflectionLedger, STM  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        # Pick the most recent report job (we created #1 earlier).
        job = db.query(ReportJob).order_by(ReportJob.id.desc()).first()
        if not job:
            print("No ReportJob row yet — run smoke_report_builder.py first.")
            return 1
        analysis = db.query(Analysis).filter(Analysis.id == job.analysis_id).first()
        dataset = db.query(Dataset).filter(Dataset.id == analysis.dataset_id).first()

        payload = resolve_semantic_analysis_payload(db, analysis.id) or {}
        payload = enrich_payload_for_dashboard(db, analysis.id, payload)

        def _load_df():
            # World population is .xls; fall back to a tiny synthetic frame so the kernel branch fires.
            return pd.DataFrame({
                "row": list(range(10)),
                "value": [1.0, 2.0, 3.0, 4.0, 100.0, 5.0, 6.0, 7.0, 8.0, 9.0],
                "region": ["A", "A", "B", "B", "A", "C", "C", "B", "A", "B"],
            })

        queries = [
            "show missing values per column",
            "find outliers with z-score",
            "count of row by region",
            "summarise the dataset",
        ]
        for q in queries:
            print(f"\n>>> {q}")
            turn = bi_chat.chat_query(
                job_id=job.id, analysis_id=analysis.id, query=q,
                analysis_payload=payload, df_loader=_load_df,
                ledger=ReflectionLedger(db), stm=STM(),
            )
            print(f"    route={turn.route} verifier={turn.verifier and turn.verifier.get('overall_status')}")
            print(f"    block.kind={turn.block and turn.block.get('kind')} title={turn.block and turn.block.get('title')}")

        # Simulate a drop: insert the last turn's block into bi_findings.
        canvas = dict(job.blocks_json or {})
        sections = canvas.setdefault("sections", [])
        bi = next((s for s in sections if s.get("section") == "bi_findings"), None)
        if not bi:
            bi = {"section": "bi_findings", "blocks": []}
            sections.append(bi)
        if turn.block:
            bi["blocks"].append(turn.block)
        job.blocks_json = canvas
        db.commit()
        print(f"\nDropped 1 chat block into bi_findings (total {len(bi['blocks'])}).")

        # Re-export PDF.
        out_path = Path("storage/reports") / f"report_builder_{job.id}.pdf"
        storage_path, digest = export_pdf(
            canvas_dict=job.blocks_json, out_path=out_path,
            dataset_filename=dataset.filename if dataset else None,
        )
        job.final_pdf_path = storage_path
        job.content_hash = digest
        db.commit()
        print(f"\nRe-exported PDF -> {storage_path} hash={digest[:12]}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
