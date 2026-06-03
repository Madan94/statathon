"""Response Builder — the full DeepBI orchestrator.

End-to-end: query -> intent -> reasoning -> plan -> execute -> evidence ->
verify -> confidence -> response.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from .intent_parser import IntentParser, ParsedIntent
from .column_synonym_kg import ColumnSynonymKG
from .reasoning_engine import ReasoningEngine, ReasoningPath
from .analytics_planner import AnalyticsPlanner, AnalyticsPlan
from .analytics_executor import AnalyticsExecutor, AnalyticsExecution
from .evidence_ledger import EvidenceLedger
from .confidence_scorer import ConfidenceScorer, ConfidenceReport

logger = logging.getLogger(__name__)


@dataclass
class DeepBIResponse:
    query: str
    intent: ParsedIntent
    reasoning: ReasoningPath
    plan: AnalyticsPlan
    execution: AnalyticsExecution
    evidence: list[dict[str, Any]] = field(default_factory=list)
    sentence_evidence_map: list[dict[str, Any]] = field(default_factory=list)
    confidence: ConfidenceReport | None = None
    narrative: str = ""
    final_table: dict[str, Any] | None = None
    final_chart: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "intent": self.intent.to_dict(),
            "reasoning": self.reasoning.to_dict(),
            "plan": self.plan.to_dict(),
            "execution": self.execution.to_dict(),
            "evidence": self.evidence,
            "sentence_evidence_map": self.sentence_evidence_map,
            "confidence": self.confidence.to_dict() if self.confidence else None,
            "narrative": self.narrative,
            "final_table": self.final_table,
            "final_chart": self.final_chart,
        }


class ResponseBuilder:

    def __init__(self, *, schema_graph: dict[str, Any] | None = None,
                  column_domains: dict[str, str] | None = None,
                  bert_embedder=None):
        self._schema_graph = schema_graph or {}
        self._column_domains = column_domains or {}
        self._embedder = bert_embedder
        self._intent_parser = IntentParser()

    def answer(self, *, query: str, df: pd.DataFrame,
                semantic_archetype: str | None = None,
                narrate: Callable[[str, list[dict[str, Any]]], str] | None = None,
                ) -> DeepBIResponse:
        columns = [str(c) for c in df.columns]
        kg = ColumnSynonymKG(columns=columns,
                              column_domains=self._column_domains,
                              bert_embedder=self._embedder)

        # 1. Intent
        intent = self._intent_parser.parse(
            query, columns=columns, dataset_archetype=semantic_archetype,
        )

        # 2. Reasoning path
        engine = ReasoningEngine(schema_graph=self._schema_graph, column_kg=kg)
        reasoning = engine.build_path(intent.concepts)

        # 3. Analytics plan
        planner = AnalyticsPlanner(column_kg=kg)
        numeric_cols = [c for c in df.columns
                          if pd.api.types.is_numeric_dtype(df[c])]
        plan = planner.plan(intent, columns=columns, numeric_columns=numeric_cols)

        # 4. Execute
        executor = AnalyticsExecutor()
        execution = executor.execute(plan, df)

        # 5. Evidence ledger
        ledger = EvidenceLedger()
        records = ledger.import_execution(execution)

        # 6. Build narrative — caller-provided LLM hook or deterministic fallback
        narrative = self._narrate(query, intent, plan, execution, records,
                                    narrate=narrate)

        # 7. Sentence-evidence map
        sent_map = ledger.attach_to_narrative(narrative)

        # 8. Mark records that have at least one matching sentence as verified
        verifiable_ids: set[str] = set()
        for entry in sent_map:
            for eid in entry["evidence_ids"]:
                verifiable_ids.add(eid)
        for r in records:
            if r.evidence_id in verifiable_ids:
                r.verified = True
                r.confidence = max(r.confidence, 0.92)

        # 9. Confidence rollup
        scorer = ConfidenceScorer()
        confidence = scorer.score(
            intent_confidence=intent.confidence,
            reasoning_total_weight=reasoning.total_weight,
            evidence_records=records,
            verifier_verdict={"overall_status":
                                "pass" if all(r.verified for r in records) else "warn"},
        )

        return DeepBIResponse(
            query=query, intent=intent, reasoning=reasoning, plan=plan,
            execution=execution, evidence=[r.to_dict() for r in records],
            sentence_evidence_map=sent_map, confidence=confidence,
            narrative=narrative, final_table=execution.final_table,
            final_chart=execution.final_chart,
        )

    # ---------------- Narrative ----------------

    def _narrate(self, query: str, intent: ParsedIntent, plan: AnalyticsPlan,
                  execution: AnalyticsExecution, records,
                  *, narrate: Callable | None = None) -> str:
        if narrate is not None:
            try:
                return narrate(query, [r.to_dict() for r in records])
            except Exception:
                pass
        return self._deterministic_narrative(query, intent, plan, execution, records)

    @staticmethod
    def _deterministic_narrative(query, intent, plan, execution, records) -> str:
        bits: list[str] = []
        bits.append(f"Question type: {intent.question_type}.")
        if intent.concepts:
            bits.append(f"Concepts considered: {', '.join(intent.concepts[:6])}.")
        if plan.target_columns:
            bits.append(f"Primary columns: {', '.join(plan.target_columns[:5])}.")

        # Surface up to 3 evidence values
        shown = 0
        for r in records:
            if shown >= 3:
                break
            if isinstance(r.value, dict):
                # Skip large dicts in narrative; mention summary
                if len(r.value) <= 8:
                    pairs = ", ".join(f"{k}={v}" for k, v in list(r.value.items())[:6])
                    bits.append(f"{r.claim}: {pairs}.")
                    shown += 1
            elif isinstance(r.value, list):
                if r.value and isinstance(r.value[0], dict):
                    top = r.value[0]
                    pairs = ", ".join(f"{k}={v}" for k, v in list(top.items())[:6])
                    bits.append(f"{r.claim} - leading entry: {pairs}.")
                    shown += 1
                elif r.value:
                    bits.append(f"{r.claim}: {len(r.value)} entries.")
                    shown += 1
            elif isinstance(r.value, (int, float, str)):
                bits.append(f"{r.claim}: {r.value}.")
                shown += 1
        if shown == 0:
            bits.append("No concrete numeric evidence was produced.")
        return " ".join(bits)
