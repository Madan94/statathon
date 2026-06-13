"""Report Orchestrator — Template + Dataset → Full verified report.

This is the Phase 3 entry point that connects:
  - Phase 2 output (template with topics/entities)
  - Template binding (entity→column resolution)
  - Agent pipeline (Planner→Analytics→Scribe→Verifier→Consensus)
  - LaTeX rendering (final output)

Supports topic-level parallelism with per-provider rate limiting.
Each question in a topic is processed through the full agent pipeline.
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from ast_core.schema import (
    TopicNode, QuestionNode, AnswerStructure, AnswerComponent,
    TemplateEntity,
)
from agents.consensus_engine import ConsensusEngine, ConsensuResult
from template_engine.binder.template_binder import (
    TemplateBinder, BindingResult, DatasetSchema, ColumnBinding,
)

logger = logging.getLogger(__name__)

# Maximum concurrent topics for parallel execution
MAX_PARALLEL_TOPICS = 4


@dataclass
class QuestionResult:
    """Result of processing a single question through the agent pipeline."""
    questionId: str
    intent: str
    narrative: str
    facts: dict[str, Any] = field(default_factory=dict)
    verdict: str = "pass"
    attempts: int = 1
    components: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "questionId": self.questionId,
            "intent": self.intent,
            "narrative": self.narrative,
            "verdict": self.verdict,
            "attempts": self.attempts,
            "components": self.components,
        }
        if self.citations:
            out["citations"] = self.citations
        if self.error:
            out["error"] = self.error
        return out


@dataclass
class TopicResult:
    """Result of processing all questions in a topic."""
    topicId: str
    title: str
    questions: list[QuestionResult] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "topicId": self.topicId,
            "title": self.title,
            "questions": [q.to_dict() for q in self.questions],
            "duration_ms": self.duration_ms,
        }


@dataclass
class ReportResult:
    """Complete report generation result."""
    reportId: str
    templateId: str
    datasetId: str
    topics: list[TopicResult] = field(default_factory=list)
    bindingResult: BindingResult | None = None
    totalDuration_ms: float = 0.0
    status: str = "complete"  # complete | partial | failed

    @property
    def total_questions(self) -> int:
        return sum(len(t.questions) for t in self.topics)

    @property
    def passed_questions(self) -> int:
        return sum(
            1 for t in self.topics for q in t.questions
            if q.verdict in ("pass", "warn")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "reportId": self.reportId,
            "templateId": self.templateId,
            "datasetId": self.datasetId,
            "topics": [t.to_dict() for t in self.topics],
            "totalDuration_ms": self.totalDuration_ms,
            "status": self.status,
            "totalQuestions": self.total_questions,
            "passedQuestions": self.passed_questions,
        }


class ReportOrchestrator:
    """Orchestrates full report generation from template + dataset.

    Pipeline per question:
      1. Resolve entity bindings → column names
      2. Extract facts from dataset using bound columns
      3. Generate narrative via ConsensusEngine (Scribe→Verifier loop)
      4. Collect citations from evidence
      5. Build component outputs (tables, charts, KPIs)
    """

    def __init__(
        self,
        *,
        consensus_engine: ConsensusEngine | None = None,
        binder: TemplateBinder | None = None,
        max_parallel: int = MAX_PARALLEL_TOPICS,
        progress_callback: Callable[[str, float], None] | None = None,
    ):
        self._consensus = consensus_engine or ConsensusEngine()
        self._binder = binder or TemplateBinder()
        self._max_parallel = max_parallel
        self._progress_cb = progress_callback

    def generate_report(
        self,
        *,
        report_id: str,
        topics: list[TopicNode],
        entities: list[TemplateEntity],
        df: pd.DataFrame,
        dataset_id: str = "default",
        template_id: str = "default",
        parallel: bool = True,
    ) -> ReportResult:
        """Generate a full report from template topics + dataset.

        Args:
            report_id: Unique report identifier.
            topics: Extracted topics with questions (Phase 2 output).
            entities: All extracted entities.
            df: Dataset as pandas DataFrame.
            dataset_id: Identifier for the dataset.
            template_id: Identifier for the template.
            parallel: Enable topic-level parallelism.

        Returns:
            ReportResult with all generated content.
        """
        start = time.time()
        result = ReportResult(
            reportId=report_id,
            templateId=template_id,
            datasetId=dataset_id,
        )

        # Step 1: Bind template entities to dataset columns
        self._emit_progress("binding", 0.05)
        schema = DatasetSchema.from_dataframe(dataset_id, df)
        binding = self._binder.bind(topics, entities, schema, template_id=template_id)
        result.bindingResult = binding

        if not binding.bindings and not binding.pending:
            logger.warning("No entities could be bound to dataset columns")
            result.status = "failed"
            return result

        # Auto-accept all pending for now (production would wait for UI)
        for pending in list(binding.pending):
            binding = self._binder.accept_pending(binding, pending.entityId)

        # Build binding lookup: entityId → column name
        binding_map = {b.entityId: b.effective_column for b in binding.bindings}

        # Step 2: Process topics
        self._emit_progress("generating", 0.10)
        total_topics = len(topics)

        if parallel and total_topics > 1:
            topic_results = self._process_topics_parallel(
                topics, binding_map, df, total_topics
            )
        else:
            topic_results = self._process_topics_sequential(
                topics, binding_map, df, total_topics
            )

        result.topics = topic_results
        result.totalDuration_ms = (time.time() - start) * 1000

        # Determine overall status
        if all(
            q.verdict in ("pass", "warn")
            for t in result.topics for q in t.questions
        ):
            result.status = "complete"
        elif any(q.error for t in result.topics for q in t.questions):
            result.status = "partial"

        self._emit_progress("complete", 1.0)
        logger.info(
            "Report %s: %d/%d questions passed in %.1fs",
            report_id, result.passed_questions, result.total_questions,
            result.totalDuration_ms / 1000,
        )
        return result

    def _process_topics_parallel(
        self,
        topics: list[TopicNode],
        binding_map: dict[str, str],
        df: pd.DataFrame,
        total: int,
    ) -> list[TopicResult]:
        """Process topics in parallel using thread pool."""
        results: list[TopicResult] = [None] * len(topics)  # type: ignore

        with ThreadPoolExecutor(max_workers=self._max_parallel) as executor:
            futures = {
                executor.submit(
                    self._process_topic, topic, binding_map, df
                ): idx
                for idx, topic in enumerate(topics)
            }
            completed = 0
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    logger.error("Topic %d failed: %s", idx, exc)
                    results[idx] = TopicResult(
                        topicId=topics[idx].topicId,
                        title=topics[idx].title,
                    )
                completed += 1
                self._emit_progress(
                    "generating",
                    0.10 + 0.85 * (completed / total),
                )

        return [r for r in results if r is not None]

    def _process_topics_sequential(
        self,
        topics: list[TopicNode],
        binding_map: dict[str, str],
        df: pd.DataFrame,
        total: int,
    ) -> list[TopicResult]:
        """Process topics sequentially."""
        results = []
        for idx, topic in enumerate(topics):
            try:
                tr = self._process_topic(topic, binding_map, df)
                results.append(tr)
            except Exception as exc:
                logger.error("Topic %s failed: %s", topic.topicId, exc)
                results.append(TopicResult(topicId=topic.topicId, title=topic.title))
            self._emit_progress("generating", 0.10 + 0.85 * ((idx + 1) / total))
        return results

    def _process_topic(
        self,
        topic: TopicNode,
        binding_map: dict[str, str],
        df: pd.DataFrame,
    ) -> TopicResult:
        """Process all questions in a single topic."""
        start = time.time()
        result = TopicResult(topicId=topic.topicId, title=topic.title)

        for question in topic.questions:
            qr = self._process_question(question, binding_map, df, topic.title)
            result.questions.append(qr)

        result.duration_ms = (time.time() - start) * 1000
        return result

    def _process_question(
        self,
        question: QuestionNode,
        binding_map: dict[str, str],
        df: pd.DataFrame,
        topic_title: str,
    ) -> QuestionResult:
        """Process a single question through the agent pipeline."""
        try:
            # 1. Resolve required columns from entity bindings
            bound_columns = []
            for binding in question.requiredEntities:
                col = binding_map.get(binding.entityId)
                if col and col in df.columns:
                    bound_columns.append(col)

            # 2. Extract facts from dataset
            facts = self._extract_facts(question, bound_columns, df)

            # 3. Build hints from answer structure
            hints = self._build_hints(question)

            # 4. Run consensus (Scribe → Verifier loop)
            consensus = self._consensus.run(
                block_id=question.questionId,
                block_title=question.intent or question.sourceHeading,
                block_section=topic_title,
                hints=hints,
                facts=facts,
                df=df if bound_columns else None,
                dataset_type="plfs",
            )

            # 5. Build component outputs
            components = self._build_components(
                question, bound_columns, df, facts
            )

            return QuestionResult(
                questionId=question.questionId,
                intent=question.intent,
                narrative=consensus.narrative,
                facts=facts,
                verdict=consensus.verdict.overall_status,
                attempts=consensus.attempts,
                components=components,
            )

        except Exception as exc:
            logger.error("Question %s failed: %s", question.questionId, exc)
            return QuestionResult(
                questionId=question.questionId,
                intent=question.intent,
                narrative="",
                error=str(exc),
                verdict="error",
            )

    def _extract_facts(
        self,
        question: QuestionNode,
        columns: list[str],
        df: pd.DataFrame,
    ) -> dict[str, Any]:
        """Extract numerical facts from dataset for the question."""
        facts: dict[str, Any] = {}
        if not columns:
            return facts

        for col in columns:
            if col not in df.columns:
                continue
            series = df[col]
            if pd.api.types.is_numeric_dtype(series):
                facts[f"{col}_mean"] = float(series.mean())
                facts[f"{col}_min"] = float(series.min())
                facts[f"{col}_max"] = float(series.max())
                facts[f"{col}_count"] = int(series.count())
                if series.count() > 0:
                    facts[f"{col}_latest"] = float(series.iloc[-1])
            else:
                facts[f"{col}_unique"] = int(series.nunique())
                facts[f"{col}_top"] = str(series.mode().iloc[0]) if len(series.mode()) > 0 else ""

        facts["_n_rows"] = len(df)
        facts["_n_columns"] = len(columns)
        return facts

    def _build_hints(self, question: QuestionNode) -> dict[str, Any]:
        """Build generation hints from answer structure."""
        hints: dict[str, Any] = {
            "question_type": question.questionType,
            "max_words": 250,
        }
        if question.answerStructure:
            for comp in question.answerStructure.components:
                constraints = comp.effective_constraints
                if comp.type == "narrative_paragraph":
                    hints["max_words"] = constraints.get("max_words", 250)
                    hints["style"] = constraints.get("style", "analytical")
                elif comp.type == "chart":
                    hints["chart_type"] = constraints.get("chart_type", "bar")
                elif comp.type == "kpi_card":
                    hints["precision"] = constraints.get("precision", 1)
                    hints["unit"] = constraints.get("unit", "")
        return hints

    def _build_components(
        self,
        question: QuestionNode,
        columns: list[str],
        df: pd.DataFrame,
        facts: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build rendered component data for each AnswerComponent."""
        components = []
        if not question.answerStructure:
            return components

        for comp in question.answerStructure.components:
            output: dict[str, Any] = {
                "componentId": comp.componentId,
                "type": comp.type,
                "renderOrder": comp.renderOrder,
            }

            if comp.type == "data_table" and columns:
                # Build table data from bound columns
                table_cols = columns[:5]  # limit for readability
                max_rows = comp.effective_constraints.get("table_max_rows", 20)
                subset = df[table_cols].head(max_rows)
                output["data"] = {
                    "headers": table_cols,
                    "rows": subset.values.tolist(),
                }

            elif comp.type == "kpi_card":
                # Find primary measure
                for col in columns:
                    key = f"{col}_latest"
                    if key in facts:
                        output["data"] = {
                            "value": facts[key],
                            "label": col,
                            "unit": comp.effective_constraints.get("unit", ""),
                        }
                        break

            elif comp.type == "chart":
                output["data"] = {
                    "chartType": comp.effective_constraints.get("chart_type", "bar"),
                    "columns": columns[:3],
                }

            elif comp.type == "narrative_paragraph":
                # Narrative is in QuestionResult.narrative — just reference it
                output["data"] = {"source": "narrative"}

            components.append(output)

        return components

    def _emit_progress(self, stage: str, fraction: float) -> None:
        """Emit progress update if callback is registered."""
        if self._progress_cb:
            try:
                self._progress_cb(stage, fraction)
            except Exception:
                pass


def generate_report(
    *,
    report_id: str,
    topics: list[TopicNode],
    entities: list[TemplateEntity],
    df: pd.DataFrame,
    dataset_id: str = "default",
    template_id: str = "default",
    progress_callback: Callable[[str, float], None] | None = None,
) -> ReportResult:
    """Module-level convenience function for report generation."""
    orchestrator = ReportOrchestrator(progress_callback=progress_callback)
    return orchestrator.generate_report(
        report_id=report_id,
        topics=topics,
        entities=entities,
        df=df,
        dataset_id=dataset_id,
        template_id=template_id,
    )
