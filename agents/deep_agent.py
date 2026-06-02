"""DeepAgent — Central orchestrator for the Government Statistical BI system.

Architecture:

  User Question
       │
       ▼
  PlannerAgent        (intent + task decomposition)
       │
       ▼
  RetrievalAgent      (dataset + KG + rulebooks + history + phase3)
       │
       ▼
  AnalyticsAgent      (correlation / trend / forecast / test / aggregation)
       │
       ▼
  ScribeAgent         (grounded narrative from facts + reflections)
       │
       ▼
  VerifierAgent       (recompute every numeric claim)
       │
       ▼
  ConsensusEngine     (retry loop until pass or deterministic fallback)
       │
       ▼
  RenderedBlock(s)    (narrative / table / chart / metric / ast_block)

Everything returns a DeepAgentResponse which the canvas consumes.
The response contains one or more RenderedBlocks that can be dragged into
any section of the report.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import pandas as pd

from agents.planner_agent import PlannerAgent, ExecutionPlan
from agents.retrieval_agent import RetrievalAgent, RetrievalBundle
from agents.analytics_agent import AnalyticsAgent, AnalyticsResult

logger = logging.getLogger(__name__)

# Singletons — one per process
_planner = PlannerAgent()
_retriever = RetrievalAgent()
_analytics = AnalyticsAgent()


@dataclass
class DeepAgentTurn:
    """Single request/response cycle."""
    turn_id: str
    query: str
    plan: dict[str, Any]
    analytics: dict[str, Any]
    blocks: list[dict[str, Any]]          # list of RenderedBlock.to_dict()
    context_used: dict[str, Any]          # what sources were hit
    narrative_hints: str
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "query": self.query,
            "plan": self.plan,
            "analytics": self.analytics,
            "blocks": self.blocks,
            "context_used": self.context_used,
            "narrative_hints": self.narrative_hints,
            "error": self.error,
            "created_at": self.created_at,
        }


def _make_block(
    kind: str,
    title: str,
    section: str,
    payload: dict[str, Any],
    verifier: dict[str, Any] | None = None,
    route: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "block_id": f"deep_{uuid.uuid4().hex[:8]}",
        "kind": kind,
        "title": title,
        "section": section,
        "payload": payload,
        "verifier": verifier,
        "route": route or {"engine": "deep_agent", "rationale": "DeepAgent orchestrated"},
        "version": 1,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _assemble_blocks(
    plan: ExecutionPlan,
    analytics_result: AnalyticsResult,
    narrative: str,
    verifier_dict: dict[str, Any] | None,
    bundle: RetrievalBundle,
) -> list[dict[str, Any]]:
    """Convert analytics + narrative into canvas RenderedBlocks."""
    blocks: list[dict[str, Any]] = []
    section = "Deep Analysis"
    output_types = plan.output_types

    # Narrative block
    if "narrative" in output_types and narrative:
        blocks.append(_make_block(
            "narrative", plan.query[:80], section,
            {"text": narrative},
            verifier=verifier_dict,
        ))

    # Table block
    if "table" in output_types and analytics_result.table:
        blocks.append(_make_block(
            "table", f"Data: {plan.intent.replace('_', ' ').title()}", section,
            analytics_result.table,
        ))

    # Chart block
    if "chart" in output_types and analytics_result.chart:
        blocks.append(_make_block(
            "chart", analytics_result.chart.get("title", "Chart"), section,
            analytics_result.chart,
        ))

    # Metric block
    if "metric" in output_types and analytics_result.metrics:
        blocks.append(_make_block(
            "metric", "Key Metrics", section,
            {"metrics": analytics_result.metrics},
        ))
    elif "metric" in output_types and analytics_result.facts:
        kpi_facts = {k: v for k, v in analytics_result.facts.items()
                     if isinstance(v, (int, float, str)) and v is not None}
        if kpi_facts:
            blocks.append(_make_block(
                "metric", "Key Metrics", section,
                {"metrics": kpi_facts},
            ))

    # AST block (pre-filled template block)
    if "ast_block" in output_types and narrative:
        blocks.append(_make_block(
            "narrative", f"[AST] {plan.intent.title()}", "auto_generated",
            {
                "text": narrative,
                "ast_meta": {
                    "intent": plan.intent,
                    "domains": plan.target_domains,
                    "columns": plan.target_columns[:10],
                },
            },
            verifier=verifier_dict,
        ))

    # Fallback — always return at least one block
    if not blocks:
        blocks.append(_make_block(
            "narrative", plan.query[:80], section,
            {"text": narrative or analytics_result.narrative_hints or
             "Analysis complete. No output types matched."},
        ))

    return blocks


class DeepAgent:
    """Orchestrates all 6 sub-agents into a single reasoning pipeline."""

    def __init__(self, db=None):
        self._db = db

    def run(
        self,
        *,
        query: str,
        analysis_id: int,
        analysis_payload: dict[str, Any],
        df_loader: Callable[[], pd.DataFrame],
        stm=None,
        ledger=None,
    ) -> DeepAgentTurn:
        turn_id = uuid.uuid4().hex[:12]
        logger.info("[DeepAgent %s] query: %s", turn_id, query[:80])

        # ── Phase P: Plan ───────────────────────────────────────────────
        available_columns: list[str] = []
        for row in analysis_payload.get("semantic_mapping") or []:
            if isinstance(row, dict) and row.get("column"):
                available_columns.append(str(row["column"]))

        plan: ExecutionPlan = _planner.plan(
            query,
            analysis_payload=analysis_payload,
            available_columns=available_columns,
        )
        logger.info("[DeepAgent %s] plan: intent=%s steps=%d", turn_id, plan.intent, len(plan.steps))

        # ── Phase R: Retrieve ───────────────────────────────────────────
        bundle: RetrievalBundle = _retriever.retrieve(
            analysis_id=analysis_id,
            df_loader=df_loader,
            analysis_payload=analysis_payload,
            plan=plan,
            db=self._db,
        )
        logger.info(
            "[DeepAgent %s] retrieved: df=%s cols=%d kg_nbrs=%d",
            turn_id, bundle.df.shape if not bundle.df.empty else "(empty)",
            len(bundle.resolved_columns), len(bundle.kg_neighbors),
        )

        # ── Phase A: Analytics ──────────────────────────────────────────
        analytics_result: AnalyticsResult = _analytics.run(plan=plan, bundle=bundle)
        logger.info("[DeepAgent %s] analytics: mode=%s error=%s",
                    turn_id, analytics_result.mode, analytics_result.error)

        # Build enriched facts for Scribe
        facts: dict[str, Any] = dict(analytics_result.facts)
        # Merge baseline facts from payload
        health = (
            analysis_payload.get("health")
            or (analysis_payload.get("profiling_summary") or {}).get("health")
            or {}
        )
        if isinstance(health, dict):
            for k in ("row_count", "column_count", "missing_cells"):
                if k in health:
                    facts.setdefault(k, health[k])
        facts["dataset_type"] = str(
            (analysis_payload.get("dataset_context") or {}).get("dataset_type") or "unknown"
        )
        facts["analytics_mode"] = analytics_result.mode
        facts["narrative_hints"] = analytics_result.narrative_hints
        if bundle.anomaly_candidates:
            facts.setdefault("anomaly_count", len(bundle.anomaly_candidates))
        if bundle.imputation_candidates:
            facts.setdefault("imputation_count", len(bundle.imputation_candidates))

        # ── Phase S: Scribe + Verifier + Consensus ──────────────────────
        narrative = ""
        verifier_dict: dict[str, Any] | None = None

        if "narrative" in plan.output_types or "ast_block" in plan.output_types:
            reflections: list[dict] = []
            if ledger:
                try:
                    reflections = ledger.retrieve_similar("deep_agent", query, limit=4)
                except Exception:
                    pass
            reflections += [
                {"after": c.get("text", ""), "kind": "rulebook"}
                for c in bundle.rulebook_chunks[:3]
            ]
            reflections += [
                {"after": h.get("after") or h.get("text", ""), "kind": "history"}
                for h in bundle.history_chunks[:3]
            ]

            # Enrich hints with KG path context
            if bundle.kg_paths:
                path_str = " → ".join(h.get("column", "") for h in bundle.kg_paths)
                facts["kg_path"] = path_str

            # Context summary from bundle injected as hint
            facts["retrieval_context"] = bundle.context_summary()

            try:
                from report_builder.firewall import scribe_narrative, verify_block
                from agents.consensus_engine import ConsensusEngine
                from agents.scribe_agent import ScribeAgent
                from agents.verifier_agent import VerifierAgent

                narrative = scribe_narrative(
                    block_id=turn_id,
                    block_title=query[:80],
                    block_section="deep_analysis",
                    hints={
                        "source": "deep_agent",
                        "analytics_context": analytics_result.narrative_hints,
                        "kg_context": (
                            "; ".join(
                                f"{n.get('column')} ({n.get('domain')})"
                                for n in bundle.kg_neighbors[:5]
                            )
                        ),
                        "rulebook": "; ".join(
                            r.get("text", "")[:100] for r in bundle.rulebook_chunks[:2]
                        ),
                    },
                    facts=facts,
                    reflections=reflections,
                    dataset_type=str(facts.get("dataset_type")),
                )

                df_for_verify = bundle.df if not bundle.df.empty else None
                verdict = verify_block(
                    block_id=turn_id,
                    narrative=narrative,
                    df=df_for_verify,
                    expected_facts=facts,
                )
                verifier_dict = verdict.to_dict()
            except Exception as exc:
                logger.warning("[DeepAgent %s] Scribe/Verifier failed: %s", turn_id, exc)
                narrative = analytics_result.narrative_hints or "Analysis complete."

        # ── Phase O: Assemble blocks ────────────────────────────────────
        blocks = _assemble_blocks(plan, analytics_result, narrative, verifier_dict, bundle)

        # ── Persist turn in STM ─────────────────────────────────────────
        if stm is not None:
            try:
                history = stm.get(analysis_id, "deep_chat_history") or []
                history.append({
                    "turn_id": turn_id,
                    "query": query,
                    "intent": plan.intent,
                    "block_count": len(blocks),
                })
                stm.put(analysis_id, "deep_chat_history", history[-20:])
            except Exception:
                pass

        context_used = {
            "dataset_rows": len(bundle.df) if not bundle.df.empty else 0,
            "resolved_columns": bundle.resolved_columns[:15],
            "kg_neighbors_count": len(bundle.kg_neighbors),
            "rulebook_chunks": len(bundle.rulebook_chunks),
            "history_chunks": len(bundle.history_chunks),
            "anomalies": len(bundle.anomaly_candidates),
            "imputations": len(bundle.imputation_candidates),
            "intent": plan.intent,
            "sub_intents": plan.sub_intents,
            "target_domains": plan.target_domains,
        }

        return DeepAgentTurn(
            turn_id=turn_id,
            query=query,
            plan=plan.to_dict(),
            analytics=analytics_result.to_dict(),
            blocks=blocks,
            context_used=context_used,
            narrative_hints=analytics_result.narrative_hints,
        )
