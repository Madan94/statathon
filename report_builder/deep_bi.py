"""DeepBI — Public entry point for the DeepAgent BI chat system.

Replaces the simple semantic-router bi_chat.py with the full DeepAgent
orchestration pipeline:

  PlannerAgent → RetrievalAgent → AnalyticsAgent → Scribe+Verifier → Canvas

Backward-compatible: still returns the same `ChatTurn`-shaped dict so
existing route handlers need no changes.  The new `deep_chat` function
extends this with the full DeepAgentTurn payload.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import pandas as pd

logger = logging.getLogger(__name__)


def deep_chat(
    *,
    job_id: int,
    analysis_id: int,
    query: str,
    analysis_payload: dict[str, Any],
    df_loader: Callable[[], pd.DataFrame],
    db=None,
    stm=None,
    ledger=None,
) -> dict[str, Any]:
    """
    Run the full DeepAgent pipeline for one user turn.

    Returns a dict with shape:
    {
        "role": "assistant",
        "text": <primary narrative or summary>,
        "blocks": [RenderedBlock, ...],   # drag into report canvas
        "plan": {...},                    # ExecutionPlan
        "analytics": {...},               # AnalyticsResult
        "context_used": {...},            # provenance
        "verifier": {...} | null,
        "route": {"engine": "deep_agent", ...},
        "turn_id": "...",
        "created_at": "...",
    }
    """
    from agents.deep_agent import DeepAgent

    agent = DeepAgent(db=db)
    turn = agent.run(
        query=query,
        analysis_id=analysis_id,
        analysis_payload=analysis_payload,
        df_loader=df_loader,
        stm=stm,
        ledger=ledger,
    )

    # Primary text = narrative block text or analytics hints
    primary_text = ""
    verifier_out = None
    for block in turn.blocks:
        if block.get("kind") == "narrative":
            primary_text = (block.get("payload") or {}).get("text", "")
            verifier_out = block.get("verifier")
            break
    if not primary_text:
        primary_text = turn.narrative_hints or f"Analysis complete: {turn.analytics.get('mode', '')}"

    return {
        "role": "assistant",
        "text": primary_text,
        "block": turn.blocks[0] if turn.blocks else None,
        "blocks": turn.blocks,
        "plan": turn.plan,
        "analytics": turn.analytics,
        "context_used": turn.context_used,
        "verifier": verifier_out,
        "route": {"engine": "deep_agent", "rationale": f"intent={turn.plan.get('intent','')}"},
        "turn_id": turn.turn_id,
        "error": turn.error,
        "created_at": turn.created_at,
    }


def get_context_status(
    *,
    analysis_id: int,
    analysis_payload: dict[str, Any],
    df_loader: Callable[[], pd.DataFrame],
    db=None,
) -> dict[str, Any]:
    """
    Return a snapshot of what data sources are available for this job.
    Shown in the Context Panel of the DeepAgent BI UI.
    """
    status: dict[str, Any] = {}

    # Dataset
    try:
        from report_builder import kernel as kx
        df = kx.ensure_loaded(analysis_id, df_loader)
        status["dataset"] = {
            "loaded": True,
            "rows": len(df),
            "columns": len(df.columns),
            "col_sample": list(df.columns)[:8],
        }
    except Exception as exc:
        status["dataset"] = {"loaded": False, "error": str(exc)}

    # KG
    try:
        from graph.query_api import neo4j_enabled, make_graph_client
        if neo4j_enabled():
            gc = make_graph_client(analysis_id, payload_fallback=analysis_payload)
            status["knowledge_graph"] = {
                "backend": "neo4j",
                "available": True,
            }
        else:
            status["knowledge_graph"] = {
                "backend": "payload_fallback",
                "available": True,
                "note": "Set NEO4J_ENABLED=true for full graph traversal",
            }
    except Exception:
        status["knowledge_graph"] = {"available": False}

    # STM
    try:
        from report_builder.memory import STM
        import os
        stm = STM()
        status["stm"] = {
            "backend": "redis" if os.getenv("REDIS_URL") else "in_memory",
            "available": True,
        }
    except Exception:
        status["stm"] = {"available": False}

    # LTM / Qdrant
    try:
        from report_builder.memory import _qdrant_client
        qc = _qdrant_client()
        status["ltm"] = {
            "backend": "qdrant",
            "available": qc is not None,
        }
    except Exception:
        status["ltm"] = {"available": False}

    # Rulebooks
    try:
        from pathlib import Path
        rule_path = Path(__file__).resolve().parents[1] / "model" / "config" / "validation_rule_library.json"
        status["rulebooks"] = {
            "available": rule_path.exists(),
            "path": str(rule_path),
        }
    except Exception:
        status["rulebooks"] = {"available": False}

    # Analysis payload summary
    sm = analysis_payload.get("semantic_mapping") or []
    clusters = analysis_payload.get("clusters") or []
    phase3 = analysis_payload.get("phase3") or {}
    status["analysis"] = {
        "semantic_mapped_columns": len(sm),
        "clusters": len(clusters),
        "anomaly_candidates": len(phase3.get("anomaly_candidates") or []),
        "imputation_candidates": len(phase3.get("imputation_candidates") or []),
        "has_schema_graph": bool(analysis_payload.get("schema_graph")),
        "has_kg": bool(analysis_payload.get("kg_export_path") or analysis_payload.get("schema_graph")),
    }

    # Domain distribution
    domains: dict[str, int] = {}
    for row in sm:
        if isinstance(row, dict):
            d = row.get("domain") or "unknown"
            domains[str(d)] = domains.get(str(d), 0) + 1
    status["domains"] = domains

    return status
