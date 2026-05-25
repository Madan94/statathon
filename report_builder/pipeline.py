"""End-to-end orchestrator wiring Phases 0-6 for a single report job.

Flow:
  Phase 0:  Load AST (uploaded template OR builtin MoSPI default)
  Phase 1:  Build KG triples + export RDF/Turtle + push to Neo4j (best-effort)
  Phase 2:  Initialize STM session for this job; pull LTM reflections
  Phase 3:  Cache DataFrame in Arrow kernel; route each block to sql/python/static
  Phase 4:  Scribe -> narrative; Verifier -> recompute claims, attach verdict
  Phase 5:  Assemble BlockCanvas JSON
  Phase 6:  Render PDF + return content hash

All phases write into the ReportJob row at intermediate stages so the frontend
can show progress on every step.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from sqlalchemy.orm import Session

from . import blueprint as bp
from . import knowledge_graph as kg
from . import kernel as kx
from . import firewall as fw
from .agui import BlockCanvas, RenderedBlock
from .exporter import export_pdf
from .memory import STM, ReflectionLedger

logger = logging.getLogger(__name__)


# ---------------- Public entry ----------------

def generate_report(
    *,
    db: Session,
    job_id: int,
    analysis_id: int,
    dataset_id: int,
    analysis_payload: dict[str, Any],
    df_loader: Callable[[], pd.DataFrame],
    template_ast: dict[str, Any] | None,
    dataset_filename: str | None,
    out_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run all phases. Returns a small status dict; full canvas is persisted on the job."""
    out_root = Path(out_root or os.getenv("REPORT_STORAGE_PATH", "./storage/reports"))
    out_root.mkdir(parents=True, exist_ok=True)
    kg_dir = out_root / "kg"
    pdf_path = out_root / f"report_builder_{job_id}.pdf"

    _set_job(db, job_id, status="running", stage="phase0")
    # ----- Phase 0 — template AST -----
    ast = bp.template_from_ast_json(template_ast) if template_ast else bp.DEFAULT_MOSPI_TEMPLATE
    logger.info("[job %s] Phase 0 ok — %s blocks", job_id, len(ast.blocks))

    _set_job(db, job_id, stage="phase1")
    # ----- Phase 1 — KG export -----
    kg_result = kg.build_kg_from_state(
        dataset_id=dataset_id,
        analysis_id=analysis_id,
        analysis_payload=analysis_payload,
        out_dir=kg_dir,
    )
    logger.info(
        "[job %s] Phase 1 ok — %s triples (turtle=%s neo4j=%s)",
        job_id, kg_result.triples_count, bool(kg_result.turtle_path), kg_result.neo4j_pushed,
    )

    _set_job(db, job_id, stage="phase2")
    # ----- Phase 2 — memory -----
    stm = STM()
    ledger = ReflectionLedger(db)
    stm.put(job_id, "session_started", datetime.utcnow().isoformat())

    _set_job(db, job_id, stage="phase3")
    # ----- Phase 3 — Arrow kernel + router -----
    try:
        df = kx.ensure_loaded(analysis_id, df_loader)
    except Exception as exc:
        logger.warning("[job %s] Arrow kernel load failed: %s", job_id, exc)
        df = pd.DataFrame()
    facts = _collect_facts(analysis_payload, df)

    _set_job(db, job_id, stage="phase4_5")
    # ----- Phases 4 & 5 — Scribe + Verifier + AGUI assembly -----
    rendered_blocks: list[RenderedBlock] = []
    verifier_report: dict[str, Any] = {"blocks": []}

    for block in ast.blocks:
        route = kx.classify_intent(block.kind, block.hints or {})
        payload = _render_block_payload(block, analysis_payload, facts, df, kg_result, ledger)

        verifier_dict: dict[str, Any] | None = None
        if block.kind == "narrative" and payload.get("text"):
            verdict = fw.verify_block(
                block_id=block.block_id,
                narrative=payload["text"],
                df=df if not df.empty else None,
                expected_facts=facts,
            )
            verifier_dict = verdict.to_dict()
            verifier_report["blocks"].append(verifier_dict)

        rendered_blocks.append(RenderedBlock(
            block_id=block.block_id,
            kind=block.kind,
            title=block.title,
            section=block.section,
            payload=payload,
            verifier=verifier_dict,
            route={"engine": route.kind, "rationale": route.rationale},
        ))

    summary = _executive_summary_metrics(facts, kg_result)
    canvas = BlockCanvas(
        job_id=job_id,
        analysis_id=analysis_id,
        template_name=ast.name,
        blocks=rendered_blocks,
        summary=summary,
    )
    canvas_dict = canvas.to_dict()

    _set_job(
        db, job_id,
        stage="phase6",
        blocks_json=canvas_dict,
        verifier_report=verifier_report,
        kg_export_path=kg_result.turtle_path,
    )

    # ----- Phase 6 — Export PDF -----
    storage_path, digest = export_pdf(
        canvas_dict=canvas_dict, out_path=pdf_path, dataset_filename=dataset_filename,
    )
    logger.info("[job %s] Phase 6 ok — %s (%s)", job_id, storage_path, digest[:12])

    _set_job(
        db, job_id,
        status="exported",
        stage="done",
        final_pdf_path=storage_path,
        content_hash=digest,
    )
    return {
        "status": "exported",
        "job_id": job_id,
        "content_hash": digest,
        "final_pdf_path": storage_path,
        "triples": kg_result.triples_count,
        "blocks": len(rendered_blocks),
    }


# ---------------- Block rendering ----------------

def _render_block_payload(
    block,
    analysis_payload: dict[str, Any],
    facts: dict[str, Any],
    df: pd.DataFrame,
    kg_result,
    ledger: ReflectionLedger,
) -> dict[str, Any]:
    """Build the per-block payload that AGUI + exporter consume."""
    kind = block.kind
    hints = block.hints or {}
    title = block.title

    if kind == "narrative":
        reflections = ledger.retrieve_similar(block.block_id, title)
        text = fw.scribe_narrative(
            block_id=block.block_id,
            block_title=title,
            block_section=block.section,
            hints=hints,
            facts=facts,
            reflections=reflections,
        )
        return {"text": text}

    if kind == "metric":
        metrics_keys = hints.get("metrics") or []
        if not metrics_keys and hints.get("formats"):  # KG export block
            return {"metrics": {
                "rdf_turtle": kg_result.turtle_path or "(not generated)",
                "rdf_xml": kg_result.rdfxml_path or "(not generated)",
                "triples_count": kg_result.triples_count,
                "neo4j_projected": kg_result.neo4j_pushed,
            }}
        return {"metrics": {k: facts.get(k, "—") for k in metrics_keys}}

    if kind == "table":
        src = hints.get("source")
        if src == "semantic_mapping":
            rows = analysis_payload.get("semantic_mapping") or []
            if isinstance(rows, list):
                pruned = [
                    {
                        "column": r.get("column"),
                        "domain": r.get("domain") or r.get("semantic_domain"),
                        "confidence": r.get("confidence"),
                        "cluster_id": r.get("cluster_id"),
                    }
                    for r in rows if isinstance(r, dict)
                ]
                return {"columns": ["column", "domain", "confidence", "cluster_id"], "rows": pruned}
        if src == "phase3.anomaly_candidates":
            phase3 = analysis_payload.get("phase3") or {}
            cands = phase3.get("anomaly_candidates") or []
            rows = [
                {
                    "column": c.get("column"),
                    "row": c.get("row"),
                    "method": c.get("method"),
                    "severity": c.get("severity"),
                    "confidence": c.get("confidence"),
                }
                for c in cands if isinstance(c, dict)
            ][:200]
            return {"columns": ["column", "row", "method", "severity", "confidence"], "rows": rows}
        if src == "phase3.imputation_candidates":
            phase3 = analysis_payload.get("phase3") or {}
            cands = phase3.get("imputation_candidates") or []
            rows = [
                {
                    "column": c.get("column"),
                    "missing_count": c.get("missing_count"),
                    "recommended_method": c.get("recommended_method"),
                    "confidence": c.get("confidence"),
                    "confidence_band": c.get("confidence_band"),
                }
                for c in cands if isinstance(c, dict)
            ]
            return {"columns": ["column", "missing_count", "recommended_method",
                                 "confidence", "confidence_band"], "rows": rows}
        if src == "health_summary":
            health = (analysis_payload.get("health")
                      or (analysis_payload.get("profiling_summary") or {}).get("health") or {})
            if isinstance(health, dict) and health:
                rows = [{"metric": k, "value": str(v)} for k, v in health.items()]
                return {"columns": ["metric", "value"], "rows": rows}
        return {"columns": [], "rows": []}

    if kind == "chart":
        if hints.get("source") == "missing_per_column" and not df.empty:
            counts = kx.column_missing_counts(df)
            # top N missing columns
            top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:15]
            top = [(k, v) for k, v in top if v > 0]
            if top:
                return {
                    "chart_type": "bar",
                    "title": title,
                    "labels": [k for k, _ in top],
                    "values": [v for _, v in top],
                }
        if hints.get("chart_type") == "network":
            sg = analysis_payload.get("schema_graph") or {}
            edges = sg.get("edges") if isinstance(sg, dict) else []
            if edges:
                labels = []
                values = []
                seen: set[str] = set()
                for e in edges[:15]:
                    if not isinstance(e, dict):
                        continue
                    pair = f"{e.get('source')}->{e.get('target')}"
                    if pair in seen:
                        continue
                    seen.add(pair)
                    labels.append(pair)
                    values.append(float(e.get("weight") or 0.0))
                return {"chart_type": "bar", "title": "Top dependency weights",
                        "labels": labels, "values": values}
        return {"chart_type": hints.get("chart_type", "bar"), "labels": [], "values": []}

    return {}


# ---------------- Facts collection ----------------

def _collect_facts(payload: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    """Produce the canonical 'facts' dict consumed by Scribe + Verifier."""
    facts: dict[str, Any] = {}
    health = (
        payload.get("health")
        or (payload.get("profiling_summary") or {}).get("health")
        or {}
    )
    if isinstance(health, dict):
        for k in ("row_count", "column_count", "missing_pct", "duplicate_rows"):
            if k in health:
                facts[k] = health[k]

    if df is not None and not df.empty:
        facts.setdefault("row_count", int(len(df)))
        facts.setdefault("column_count", int(len(df.columns)))
        total = float(df.size) or 1.0
        facts.setdefault("missing_pct", float(df.isna().sum().sum()) / total * 100.0)

    phase3 = payload.get("phase3") or {}
    if isinstance(phase3, dict):
        anomalies = phase3.get("anomaly_candidates") or []
        if isinstance(anomalies, list):
            facts["anomaly_count"] = len(anomalies)
        imputations = phase3.get("imputation_candidates") or []
        if isinstance(imputations, list):
            facts["imputation_count"] = len(imputations)

    ctx = payload.get("dataset_context") or {}
    if isinstance(ctx, dict) and ctx.get("dataset_type"):
        facts["dataset_type"] = ctx["dataset_type"]

    mapping = payload.get("semantic_mapping") or []
    if isinstance(mapping, list):
        facts["mapped_column_count"] = sum(
            1 for r in mapping if isinstance(r, dict) and r.get("domain")
        )

    return facts


def _executive_summary_metrics(facts: dict[str, Any], kg_result) -> dict[str, Any]:
    return {
        "rows": facts.get("row_count", "—"),
        "columns": facts.get("column_count", "—"),
        "missing_pct": (
            f"{facts['missing_pct']:.2f}%"
            if isinstance(facts.get("missing_pct"), (int, float)) else "—"
        ),
        "anomalies_flagged": facts.get("anomaly_count", 0),
        "imputation_targets": facts.get("imputation_count", 0),
        "semantic_mapped_columns": facts.get("mapped_column_count", 0),
        "kg_triples": kg_result.triples_count,
        "kg_neo4j_pushed": kg_result.neo4j_pushed,
        "dataset_type": facts.get("dataset_type", "—"),
    }


# ---------------- DB helpers ----------------

def _set_job(db: Session, job_id: int, **fields):
    from database.models import ReportJob

    row = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not row:
        return
    for k, v in fields.items():
        if hasattr(row, k):
            setattr(row, k, v)
    db.commit()
