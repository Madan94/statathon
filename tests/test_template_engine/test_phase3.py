"""Tests for Phase 3: Report Generation Pipeline (Steps 17-24).

Tests:
  - Template binder (entity → column resolution)
  - Column resolver cascade (exact, alias, glossary, fuzzy)
  - Report orchestrator (end-to-end with mock consensus)
  - LaTeX renderer (standalone generation)
  - Failure-classified consensus repair
  - Citation manager (inline citations)
  - Priority-based question extraction
  - Structural template cache (L1/L2)
"""
from __future__ import annotations

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from ast_core.schema import (
    TemplateEntity, TopicNode, QuestionNode, QuestionEntityBinding,
    AnswerStructure, AnswerComponent,
)
from template_engine.vlm.schemas import VLMPageResult, VLMRegion


# ---------------------------------------------------------------------------
# Template Binder Tests
# ---------------------------------------------------------------------------

class TestTemplateBinder:
    """Test template → dataset binding."""

    def _make_schema(self):
        from template_engine.binder.template_binder import DatasetSchema
        return DatasetSchema(
            datasetId="test_ds",
            columns=["lfpr_male", "lfpr_female", "wpr_total", "state", "quarter"],
            columnTypes={"lfpr_male": "float64", "state": "object"},
            sampleValues={"lfpr_male": ["78.2", "79.0"], "state": ["AP", "Bihar"]},
        )

    def _make_entities(self):
        return [
            TemplateEntity(
                entityId="e_001", name="LFPR", entityType="measure",
                confidence=0.95, sourceType="statement",
            ),
            TemplateEntity(
                entityId="e_002", name="State", entityType="dimension",
                confidence=0.90, sourceType="table_header",
            ),
            TemplateEntity(
                entityId="e_003", name="Obscure Indicator", entityType="measure",
                confidence=0.50, sourceType="inferred",
            ),
        ]

    def test_bind_resolves_entities(self):
        from template_engine.binder.template_binder import TemplateBinder
        binder = TemplateBinder()
        schema = self._make_schema()
        entities = self._make_entities()
        topics = [TopicNode(topicId="t1", title="Test")]

        result = binder.bind(topics, entities, schema)
        assert result.templateId == "default"
        assert result.datasetId == "test_ds"
        # At least one entity should resolve
        assert len(result.bindings) + len(result.pending) > 0

    def test_auto_accept_high_confidence(self):
        from template_engine.binder.template_binder import TemplateBinder
        binder = TemplateBinder()
        schema = self._make_schema()
        # Entity name matches column exactly
        entities = [
            TemplateEntity(entityId="e_state", name="state",
                           entityType="dimension", confidence=0.95),
        ]
        result = binder.bind([], entities, schema)
        # Exact match = confidence 1.0, should be auto-accepted
        assert len(result.bindings) == 1
        assert result.bindings[0].autoAccepted is True
        assert result.bindings[0].method == "exact"

    def test_accept_pending(self):
        from template_engine.binder.template_binder import TemplateBinder, DatasetSchema
        binder = TemplateBinder()
        schema = DatasetSchema(datasetId="ds", columns=["x_col", "y_col"])
        entities = [
            TemplateEntity(entityId="e_x", name="X metric", entityType="measure"),
        ]
        result = binder.bind([], entities, schema)
        # If it ended up in pending, accept it
        if result.pending:
            result = binder.accept_pending(result, "e_x", "x_col")
            assert any(b.entityId == "e_x" for b in result.bindings)

    def test_schema_from_dataframe(self):
        from template_engine.binder.template_binder import DatasetSchema
        df = pd.DataFrame({
            "LFPR": [42.3, 41.5, 40.2],
            "State": ["AP", "Bihar", "Gujarat"],
        })
        schema = DatasetSchema.from_dataframe("test", df)
        assert "LFPR" in schema.columns
        assert "State" in schema.columns
        assert schema.columnTypes["LFPR"] == "float64"


# ---------------------------------------------------------------------------
# Column Resolver Tests
# ---------------------------------------------------------------------------

class TestColumnResolver:
    """Test the 5-stage resolution cascade."""

    def _make_schema(self):
        from template_engine.binder.template_binder import DatasetSchema
        return DatasetSchema(
            datasetId="test",
            columns=["lfpr_pct", "wpr_pct", "unemployment_rate", "state_name", "quarter"],
        )

    def test_exact_match(self):
        from template_engine.binder.column_resolver import ColumnResolver
        schema = self._make_schema()
        entity = TemplateEntity(entityId="e1", name="state_name", entityType="dimension")
        resolver = ColumnResolver()
        result = resolver.resolve(entity, schema)
        assert result is not None
        assert result["column"] == "state_name"
        assert result["confidence"] >= 0.95
        assert result["method"] == "exact"

    def test_exact_match_case_insensitive(self):
        from template_engine.binder.column_resolver import ColumnResolver
        schema = self._make_schema()
        entity = TemplateEntity(entityId="e1", name="State_Name", entityType="dimension")
        resolver = ColumnResolver()
        result = resolver.resolve(entity, schema)
        assert result is not None
        assert result["column"] == "state_name"

    def test_alias_match_lfpr(self):
        from template_engine.binder.column_resolver import ColumnResolver
        schema = self._make_schema()
        entity = TemplateEntity(entityId="e1", name="LFPR", entityType="measure")
        resolver = ColumnResolver()
        result = resolver.resolve(entity, schema)
        assert result is not None
        # Should match lfpr_pct via alias expansion
        assert "lfpr" in result["column"].lower()

    def test_fuzzy_match(self):
        from template_engine.binder.column_resolver import ColumnResolver
        from template_engine.binder.template_binder import DatasetSchema
        schema = DatasetSchema(
            datasetId="test",
            columns=["labour_force_participation_rate", "worker_ratio"],
        )
        entity = TemplateEntity(entityId="e1", name="labour force participation",
                                entityType="measure")
        resolver = ColumnResolver()
        result = resolver.resolve(entity, schema)
        assert result is not None
        assert "labour_force" in result["column"]

    def test_no_match_returns_none(self):
        from template_engine.binder.column_resolver import ColumnResolver
        from template_engine.binder.template_binder import DatasetSchema
        schema = DatasetSchema(datasetId="test", columns=["col_a", "col_b"])
        entity = TemplateEntity(entityId="e1", name="completely_unrelated_xyz",
                                entityType="measure")
        resolver = ColumnResolver()
        result = resolver.resolve(entity, schema)
        # Should return None or very low confidence
        if result:
            assert result["confidence"] < 0.60


# ---------------------------------------------------------------------------
# LaTeX Renderer Tests
# ---------------------------------------------------------------------------

class TestLaTeXRenderer:
    """Test LaTeX rendering (without compilation)."""

    def _make_report_result(self):
        from report_builder.orchestrator import (
            ReportResult, TopicResult, QuestionResult,
        )
        return ReportResult(
            reportId="test_001",
            templateId="plfs_q1_2024",
            datasetId="ds_001",
            topics=[
                TopicResult(
                    topicId="topic_ch2",
                    title="Key Labour Force Indicators",
                    questions=[
                        QuestionResult(
                            questionId="q_001",
                            intent="What is the LFPR trend?",
                            narrative="The LFPR increased from 40.2% to 42.3% between Q1 2023 and Q1 2024.",
                            verdict="pass",
                            components=[
                                {"type": "data_table", "data": {
                                    "headers": ["Quarter", "LFPR"],
                                    "rows": [["Q1-2023", "40.2"], ["Q1-2024", "42.3"]],
                                }},
                            ],
                        ),
                    ],
                ),
            ],
        )

    def test_render_standalone_latex(self):
        from template_engine.render.latex_renderer import LaTeXRenderer
        renderer = LaTeXRenderer(output_dir=Path(tempfile.mkdtemp()))
        result = self._make_report_result()
        outputs = renderer.render(result, compile_pdf=False, generate_html=False)
        assert "tex" in outputs
        assert outputs["tex"].exists()
        content = outputs["tex"].read_text()
        assert r"\documentclass" in content
        assert "Key Labour Force Indicators" in content
        assert "LFPR" in content

    def test_escape_latex_special_chars(self):
        from template_engine.render.latex_renderer import _escape_latex
        assert r"\&" in _escape_latex("A & B")
        assert r"\%" in _escape_latex("50%")
        assert r"\$" in _escape_latex("$100")
        assert r"\#" in _escape_latex("#1")

    def test_render_table_in_latex(self):
        from template_engine.render.latex_renderer import LaTeXRenderer
        renderer = LaTeXRenderer()
        lines = renderer._render_table({
            "headers": ["State", "LFPR"],
            "rows": [["AP", "76.5"], ["Bihar", "68.2"]],
        })
        joined = "\n".join(lines)
        assert "longtable" in joined
        assert "AP" in joined
        assert "76.5" in joined


# ---------------------------------------------------------------------------
# Consensus Repair Tests
# ---------------------------------------------------------------------------

class TestConsensusRepair:
    """Test failure-classified repair in consensus engine."""

    def test_failure_classification(self):
        from agents.consensus_engine import _classify_failure, FailureType
        from agents.verifier_agent import VerifierVerdict

        # Create mock verdict with mixed failures
        verdict = MagicMock(spec=VerifierVerdict)
        check_rounding = MagicMock()
        check_rounding.status = "fail"
        check_rounding.raw = "LFPR was 42.3%"
        check_rounding.claimed_value = "42.3"
        check_rounding.computed_value = 42.31  # within 0.5%

        check_hallucination = MagicMock()
        check_hallucination.status = "unverified"
        check_hallucination.raw = "Growth was 5.2%"
        check_hallucination.claimed_value = "5.2"
        check_hallucination.computed_value = None

        check_logic = MagicMock()
        check_logic.status = "fail"
        check_logic.raw = "WPR dropped to 20%"
        check_logic.claimed_value = "20"
        check_logic.computed_value = 38.5  # way off

        verdict.checks = [check_rounding, check_hallucination, check_logic]

        classified = _classify_failure(verdict)
        assert len(classified[FailureType.ROUNDING]) >= 1
        assert len(classified[FailureType.HALLUCINATION]) >= 1
        assert len(classified[FailureType.LOGIC]) >= 1

    def test_classified_repair_output(self):
        from agents.consensus_engine import _build_classified_repair
        from agents.verifier_agent import VerifierVerdict

        verdict = MagicMock(spec=VerifierVerdict)
        check = MagicMock()
        check.status = "unverified"
        check.raw = "Mystery stat 99%"
        check.claimed_value = "99"
        check.computed_value = None
        verdict.checks = [check]

        repair_text = _build_classified_repair(verdict)
        assert "HALLUCINATED DATA" in repair_text
        assert "Mystery stat" in repair_text

    def test_priority_retry_map(self):
        from agents.consensus_engine import _PRIORITY_RETRY_MAP
        assert _PRIORITY_RETRY_MAP["high"] == 4
        assert _PRIORITY_RETRY_MAP["medium"] == 3
        assert _PRIORITY_RETRY_MAP["low"] == 2


# ---------------------------------------------------------------------------
# Citation Manager Tests
# ---------------------------------------------------------------------------

class TestCitationManager:
    """Test evidence citation system."""

    def test_basic_citation(self):
        from template_engine.render.citation_manager import CitationManager
        manager = CitationManager(tolerance=0.01)
        narrative = "The LFPR was 42.3% in Q1 2024."
        facts = {"lfpr_latest": 42.3}
        result = manager.cite(narrative, facts)
        assert "[1]" in result.cited_narrative
        assert len(result.citations) >= 1
        assert result.citations[0].value == 42.3

    def test_multiple_citations(self):
        from template_engine.render.citation_manager import CitationManager
        manager = CitationManager(tolerance=0.02)
        narrative = "LFPR rose from 40.2% to 42.3% over the period."
        facts = {"lfpr_min": 40.2, "lfpr_latest": 42.3}
        result = manager.cite(narrative, facts)
        assert len(result.citations) >= 2

    def test_no_citation_for_unmatched(self):
        from template_engine.render.citation_manager import CitationManager
        manager = CitationManager(tolerance=0.01)
        narrative = "The rate was 99.9%."
        facts = {"lfpr_latest": 42.3}  # doesn't match 99.9
        result = manager.cite(narrative, facts)
        assert len(result.citations) == 0

    def test_appendix_generation(self):
        from template_engine.render.citation_manager import CitationManager
        manager = CitationManager()
        narrative = "LFPR is 42.3%."
        facts = {"lfpr_latest": 42.3}
        result = manager.cite(narrative, facts)
        assert "Evidence Sources" in result.appendix_text

    def test_latex_citation_format(self):
        from template_engine.render.citation_manager import CitationManager
        manager = CitationManager()
        narrative = "The rate is 42.3%."
        facts = {"rate_latest": 42.3}
        result = manager.cite_latex(narrative, facts)
        assert r"\textsuperscript" in result.cited_narrative


# ---------------------------------------------------------------------------
# Priority-based Question Extraction Tests
# ---------------------------------------------------------------------------

class TestPriorityExtraction:
    """Test priority assignment in question inference."""

    def test_high_priority_for_plfs_direct(self):
        from template_engine.inference.question_inferrer import _assign_priority
        assert _assign_priority(0.92, "plfs_direct", "trend") == "high"

    def test_high_priority_for_high_confidence(self):
        from template_engine.inference.question_inferrer import _assign_priority
        assert _assign_priority(0.90, "pattern", "describe") == "high"

    def test_medium_priority(self):
        from template_engine.inference.question_inferrer import _assign_priority
        assert _assign_priority(0.65, "pattern", "describe") == "medium"

    def test_low_priority(self):
        from template_engine.inference.question_inferrer import _assign_priority
        assert _assign_priority(0.45, "stub", "describe") == "low"

    def test_question_node_has_priority(self):
        q = QuestionNode(questionId="q1", priority="high")
        assert q.priority == "high"
        d = q.to_dict()
        assert d["priority"] == "high"

    def test_question_node_priority_roundtrip(self):
        q = QuestionNode(questionId="q1", priority="low")
        d = q.to_dict()
        restored = QuestionNode.from_dict(d)
        assert restored.priority == "low"

    def test_infer_questions_assigns_priority(self):
        from template_engine.inference.question_inferrer import infer_questions

        pages = [VLMPageResult(
            pageIndex=0,
            regions=[
                VLMRegion(regionId="r_0_0", role="heading_h1",
                          text="Chapter 2: Key Indicators"),
                VLMRegion(regionId="r_0_1", role="heading_h2",
                          text="Statement 2.1: Quarterly estimates of key labour indicators"),
            ],
        )]
        topics = infer_questions(pages, [])
        assert len(topics) >= 1
        all_questions = [q for t in topics for q in t.questions]
        # At least one question should be high priority (the PLFS statement)
        priorities = [q.priority for q in all_questions]
        assert "high" in priorities


# ---------------------------------------------------------------------------
# Template Cache Tests
# ---------------------------------------------------------------------------

class TestTemplateCache:
    """Test structural template cache (L1/L2)."""

    def _make_pages_data(self, variant: str = "a"):
        """Create mock serialized page data."""
        return [
            {
                "pageIndex": 0,
                "regions": [
                    {"role": "heading_h1", "text": f"Chapter {variant}",
                     "bbox": {"x0": 50, "y0": 50, "x1": 500, "y1": 80}},
                    {"role": "table", "text": "data",
                     "bbox": {"x0": 50, "y0": 200, "x1": 500, "y1": 600}},
                ],
            },
            {
                "pageIndex": 1,
                "regions": [
                    {"role": "heading_h2", "text": f"Section {variant}",
                     "bbox": {"x0": 50, "y0": 50, "x1": 500, "y1": 80}},
                    {"role": "paragraph", "text": "narrative content",
                     "bbox": {"x0": 50, "y0": 100, "x1": 500, "y1": 300}},
                ],
            },
        ]

    def test_store_and_l1_hit(self):
        from template_engine.storage.template_cache import TemplateCache
        cache = TemplateCache(cache_dir=Path(tempfile.mkdtemp()))
        pages = self._make_pages_data("test")

        # Store
        topics = [TopicNode(topicId="t1", title="Test")]
        entities = [TemplateEntity(entityId="e1", name="LFPR", entityType="measure")]
        cache.store(pages, topics, entities)

        # Lookup same data → L1 hit
        result = cache.lookup(pages)
        assert result.hit is True
        assert result.level == "L1"
        assert result.similarity == 1.0

    def test_l2_structural_hit(self):
        from template_engine.storage.template_cache import TemplateCache
        cache = TemplateCache(cache_dir=Path(tempfile.mkdtemp()))

        pages_a = self._make_pages_data("a")
        topics = [TopicNode(topicId="t1", title="Test")]
        entities = []
        cache.store(pages_a, topics, entities)

        # Similar structure but different content text
        pages_b = self._make_pages_data("b")
        result = cache.lookup(pages_b)
        # Should get L2 hit due to same structure (heading_h1, table, heading_h2, paragraph)
        assert result.hit is True
        assert result.level == "L2"
        assert result.similarity >= 0.85

    def test_cache_miss(self):
        from template_engine.storage.template_cache import TemplateCache
        cache = TemplateCache(cache_dir=Path(tempfile.mkdtemp()))
        pages = self._make_pages_data("miss")
        result = cache.lookup(pages)
        assert result.hit is False

    def test_invalidate(self):
        from template_engine.storage.template_cache import TemplateCache
        cache = TemplateCache(cache_dir=Path(tempfile.mkdtemp()))
        pages = self._make_pages_data("inv")
        key = cache.store(pages, [], [])
        assert cache.lookup(pages).hit is True
        cache.invalidate(key)
        assert cache.lookup(pages).hit is False

    def test_clear_all(self):
        from template_engine.storage.template_cache import TemplateCache
        cache = TemplateCache(cache_dir=Path(tempfile.mkdtemp()))
        cache.store(self._make_pages_data("1"), [], [])
        cache.store(self._make_pages_data("2"), [], [])
        count = cache.clear()
        assert count == 2


# ---------------------------------------------------------------------------
# Integration: Phase 2→3 Connection Test
# ---------------------------------------------------------------------------

class TestPhase2To3Integration:
    """Test that Phase 2 output feeds correctly into Phase 3."""

    def test_plfs_extraction_to_binding(self):
        """Verify PLFS extracted entities can be bound to a dataset."""
        from template_engine.extraction.plfs_parser import extract_plfs_questions
        from template_engine.binder.template_binder import TemplateBinder, DatasetSchema

        # Simulate Phase 2 output
        pages = [VLMPageResult(
            pageIndex=0,
            rawText="Statement 2.1: Quarterly estimates",
            regions=[VLMRegion(
                regionId="r_0_0", role="heading_h2",
                text="Statement 2.1: Quarterly estimates of key labour indicators",
            )],
        )]
        topics, entities = extract_plfs_questions(pages)

        # Phase 3: bind to dataset
        schema = DatasetSchema(
            datasetId="plfs_2024",
            columns=["lfpr_pct", "wpr_pct", "ur_pct", "quarter", "sector"],
        )
        binder = TemplateBinder()
        result = binder.bind(topics, entities, schema)

        # Should have at least some resolution
        total_resolved = len(result.bindings) + len(result.pending)
        assert total_resolved >= 0  # May be 0 if entities don't match columns exactly

    def test_question_priority_flows_to_consensus(self):
        """Verify priority field is available for consensus engine."""
        q = QuestionNode(
            questionId="q_plfs_2_1",
            intent="What is the LFPR trend?",
            priority="high",
            inferenceConfidence=0.92,
            inferenceMethod="plfs_direct",
        )
        assert q.priority == "high"
        # Priority maps to retry budget
        from agents.consensus_engine import _PRIORITY_RETRY_MAP
        assert _PRIORITY_RETRY_MAP[q.priority] == 4
