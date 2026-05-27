"""End-to-end orchestrator — Phases 0-6 for a single report job.

Phase 0  — Template AST (template_engine)
Phase 1  — KG export (knowledge_graph)
Phase 2  — Memory init (STM/LTM)
Phase 3  — Arrow kernel + facts collection (kernel, report_semantics)
Phase 4/5 — Scribe → Verifier → Consensus (agents / firewall)
Phase 6  — PDF export (exporter)

New in v2:
  • report_semantics.DatasetSummary drives facts collection
  • report_semantics.ReportPlan can override template block order
  • agents.ConsensusEngine replaces single-pass scribe
  • template_engine.compile_template replaces blueprint.compile_template
  • exporter now produces government-grade MoSPI PDF
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from sqlalchemy.orm import Session

from report_builder import knowledge_graph as kg
from report_builder import kernel as kx
from report_builder import firewall as fw
from report_builder.agui import BlockCanvas, RenderedBlock
from report_builder.exporter import export_pdf
from report_builder.memory import STM, ReflectionLedger

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Template loading (template_engine preferred; fallback to blueprint)
# ---------------------------------------------------------------------------

def _load_template(template_ast: dict[str, Any] | None):
    """Returns a TemplateAST-compatible object."""
    if template_ast:
        try:
            from template_engine.ast.template_serializer import deserialize_template
            return deserialize_template(template_ast)
        except Exception as exc:
            logger.warning("template_engine deserialize failed: %s; falling back", exc)

    # blueprint fallback (backward-compat)
    from report_builder import blueprint as bp
    if template_ast:
        return bp.template_from_ast_json(template_ast)
    return bp.DEFAULT_MOSPI_TEMPLATE


# ---------------------------------------------------------------------------
# Facts collection (enhanced via report_semantics)
# ---------------------------------------------------------------------------

def _collect_facts(
    analysis_payload: dict[str, Any],
    df: pd.DataFrame,
) -> dict[str, Any]:
    """Build the canonical facts dict for Scribe + Verifier."""
    try:
        from report_semantics.summarizer.dataset_summarizer import compute_dataset_summary
        from report_semantics.metric_detector.detector import detect_key_metrics

        summary = compute_dataset_summary(analysis_payload, df if not df.empty else None)
        facts = detect_key_metrics(summary, analysis_payload, df if not df.empty else None)
        facts["_summary"] = summary.to_dict()
        return facts
    except Exception as exc:
        logger.warning("report_semantics facts failed: %s; using legacy", exc)
        return _collect_facts_legacy(analysis_payload, df)


def _collect_facts_legacy(
    payload: dict[str, Any], df: pd.DataFrame
) -> dict[str, Any]:
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


# ---------------------------------------------------------------------------
# Block payload renderers (table / chart / metric)
# ---------------------------------------------------------------------------

def _render_block_payload(
    block,
    analysis_payload: dict[str, Any],
    facts: dict[str, Any],
    df: pd.DataFrame,
    kg_result,
    ledger: ReflectionLedger,
) -> dict[str, Any]:
    kind = block.kind
    hints = block.hints or {}
    title = block.title
    dataset_type = str(facts.get("dataset_type") or "unknown")

    if kind == "narrative":
        reflections = ledger.retrieve_similar(block.block_id, title)
        text = fw.scribe_narrative(
            block_id=block.block_id,
            block_title=title,
            block_section=block.section,
            hints=hints,
            facts=facts,
            reflections=reflections,
            dataset_type=dataset_type,
        )
        return {"text": text}

    if kind == "metric":
        metrics_keys = hints.get("metrics") or []
        if hints.get("formats"):
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

        if src == "clusters":
            clusters = analysis_payload.get("clusters") or []
            rows = [
                {
                    "cluster_id": c.get("cluster_id"),
                    "domain": c.get("domain"),
                    "support_score": c.get("support_score"),
                    "columns": ", ".join(c.get("columns") or [])[:60] if c.get("columns") else "—",
                }
                for c in (clusters if isinstance(clusters, list) else [])
            ][:40]
            return {"columns": ["cluster_id", "domain", "support_score", "columns"], "rows": rows}

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
                }
                for c in cands if isinstance(c, dict)
            ]
            return {"columns": ["column", "missing_count", "recommended_method", "confidence"], "rows": rows}

        if src == "health_summary":
            health = (
                analysis_payload.get("health")
                or (analysis_payload.get("profiling_summary") or {}).get("health")
                or {}
            )
            if isinstance(health, dict) and health:
                rows = [{"metric": k, "value": str(v)} for k, v in health.items()]
                return {"columns": ["metric", "value"], "rows": rows}

        return {"columns": [], "rows": []}

    if kind == "chart":
        if hints.get("source") == "missing_per_column" and not df.empty:
            counts = kx.column_missing_counts(df)
            top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:20]
            top = [(k, v) for k, v in top if v > 0]
            if top:
                return {
                    "chart_type": "bar",
                    "title": title,
                    "labels": [k for k, _ in top],
                    "values": [v for _, v in top],
                }

        if hints.get("source") == "column_types" and not df.empty:
            import pandas as _pd
            types: dict[str, int] = {}
            for c in df.columns:
                dtype = df[c].dtype
                if _pd.api.types.is_numeric_dtype(dtype):
                    types["Numeric"] = types.get("Numeric", 0) + 1
                elif _pd.api.types.is_datetime64_any_dtype(dtype):
                    types["DateTime"] = types.get("DateTime", 0) + 1
                else:
                    types["Categorical"] = types.get("Categorical", 0) + 1
            if types:
                return {
                    "chart_type": "bar",
                    "title": "Column Types",
                    "labels": list(types.keys()),
                    "values": list(types.values()),
                }

        if hints.get("chart_type") == "network":
            sg = analysis_payload.get("schema_graph") or {}
            edges = sg.get("edges") if isinstance(sg, dict) else []
            if edges:
                labels, values, seen = [], [], set()
                for e in edges[:20]:
                    if not isinstance(e, dict):
                        continue
                    pair = f"{e.get('source')}→{e.get('target')}"
                    if pair in seen:
                        continue
                    seen.add(pair)
                    labels.append(pair)
                    values.append(float(e.get("weight") or 0.0))
                return {"chart_type": "bar", "title": "Top dependency weights",
                        "labels": labels, "values": values}

        return {"chart_type": hints.get("chart_type", "bar"), "labels": [], "values": []}

    return {}


def _executive_summary_metrics(facts: dict[str, Any], kg_result) -> dict[str, Any]:
    return {
        "Rows": facts.get("row_count", "—"),
        "Columns": facts.get("column_count", "—"),
        "Missing %": (
            f"{facts['missing_pct']:.2f}%"
            if isinstance(facts.get("missing_pct"), (int, float)) else "—"
        ),
        "Anomalies Flagged": facts.get("anomaly_count", 0),
        "Imputation Targets": facts.get("imputation_count", 0),
        "Semantic-Mapped Columns": facts.get("mapped_column_count", 0),
        "KG Triples": kg_result.triples_count,
        "KG Neo4j Pushed": kg_result.neo4j_pushed,
        "Dataset Type": facts.get("dataset_type", "—"),
        "Health Score": facts.get("health_score", "—"),
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _set_job(db: Session, job_id: int, **fields):
    from database.models import ReportJob

    row = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not row:
        return
    for k, v in fields.items():
        if hasattr(row, k):
            setattr(row, k, v)
    db.commit()


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

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
    """Run all phases. Returns status dict; full canvas persisted on the job."""
    out_root = Path(out_root or os.getenv("REPORT_STORAGE_PATH", "./storage/reports"))
    out_root.mkdir(parents=True, exist_ok=True)
    kg_dir = out_root / "kg"
    pdf_path = out_root / f"report_builder_{job_id}.pdf"

    _set_job(db, job_id, status="running", stage="phase0")

    # ----- Phase 0 — Template AST -----
    ast = _load_template(template_ast)
    logger.info("[job %s] Phase 0: template '%s' — %s blocks", job_id, ast.name, len(ast.blocks))

    _set_job(db, job_id, stage="phase1")

    # ----- Phase 1 — KG build + export -----
    kg_result = kg.build_kg_from_state(
        dataset_id=dataset_id,
        analysis_id=analysis_id,
        analysis_payload=analysis_payload,
        out_dir=kg_dir,
    )
    logger.info(
        "[job %s] Phase 1: %s triples (turtle=%s neo4j=%s)",
        job_id, kg_result.triples_count, bool(kg_result.turtle_path), kg_result.neo4j_pushed,
    )

    _set_job(db, job_id, stage="phase2")

    # ----- Phase 2 — Memory -----
    stm = STM()
    ledger = ReflectionLedger(db)
    stm.put(job_id, "session_started", datetime.utcnow().isoformat())

    _set_job(db, job_id, stage="phase3")

    # ----- Phase 3 — Arrow kernel + facts -----
    try:
        df = kx.ensure_loaded(analysis_id, df_loader)
    except Exception as exc:
        logger.warning("[job %s] Arrow kernel load failed: %s", job_id, exc)
        df = pd.DataFrame()

    facts = _collect_facts(analysis_payload, df)
    logger.info("[job %s] Phase 3: %s facts keys", job_id, len(facts))

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
        canvas_dict=canvas_dict,
        out_path=pdf_path,
        dataset_filename=dataset_filename,
        verifier_report=verifier_report,
    )
    logger.info("[job %s] Phase 6: PDF at %s (%s…)", job_id, storage_path, digest[:12])

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
