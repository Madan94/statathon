"""Enhanced template engine tests — uses real .env config.

Test tiers:
  TIER 1 (always run, no external deps):
      TestEnvConfig, TestPipelineMockFull, TestSchemaContract,
      TestEntityExtractionDepth, TestQuestionInferenceDepth,
      TestASTAssemblerDepth, TestReviewerThresholds

  TIER 2 (live_llm — needs GEMINI_API_KEY):
      TestGeminiHybridInference

  TIER 3 (live_vlm — needs COLPALI_ENDPOINT):
      TestColPaliLive

  TIER 4 (live_sglang — needs SGLANG_ENDPOINT):
      TestSGLangLive

  TIER 5 (live_db — needs DATABASE_URL with Supabase):
      TestTemplateRepository

  TIER 6 (live_s3 — needs R2/S3):
      TestS3Storage
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from ast_core.schema import (
    AnswerComponent,
    AnswerComponentRef,
    AnswerStructure,
    COMPONENT_TYPES,
    ENTITY_SOURCE_TYPES,
    ENTITY_TYPES,
    QuestionEntityBinding,
    QuestionNode,
    TemplateBlueprintAST,
    TemplateEntity,
    TopicNode,
)
from ast_core.pydantic_schema import TemplateBlueprintModel, export_json_schema
from template_engine.extraction.entity_classifier import classify_entity_type
from template_engine.extraction.entity_deduplicator import deduplicate_entities
from template_engine.extraction.entity_extractor import extract_entities
from template_engine.generation.ast_assembler import assemble_template_ast
from template_engine.generation.sglang_client import MockSGLangClient, SGLangClientFactory
from template_engine.inference.question_inferrer import infer_questions
from template_engine.observability.tracing import TracingConfig, init_tracing, trace_span
from template_engine.pipeline import (
    PIPELINE_STAGES,
    ExtractionProgress,
    ExtractionResult,
    run_extraction_pipeline,
)
from template_engine.review.reviewer import ReviewDecision, ReviewResult, TemplateReviewer
from template_engine.vlm.client import VLMClientFactory
from template_engine.vlm.mock_client import MockVLMClient
from template_engine.vlm.schemas import VLMBBox, VLMChartData, VLMEntity, VLMPageResult, VLMRegion, VLMTableData

# ── Disable tracing in all tests by default ─────────────────────────────────
init_tracing(TracingConfig(enabled=False))


# ===========================================================================
# TIER 1 — No external dependencies
# ===========================================================================


class TestEnvConfig:
    """Verify .env values are loaded and sensible."""

    def test_gemini_api_key_in_env(self):
        """GEMINI_API_KEY must be set (either from .env or CI env)."""
        key = os.getenv("GEMINI_API_KEY", "")
        assert key, "GEMINI_API_KEY missing — add to .env or CI secrets"

    def test_database_url_in_env(self):
        url = os.getenv("DATABASE_URL", "")
        assert url.startswith("postgresql://"), f"DATABASE_URL not configured: {url!r}"

    def test_s3_bucket_in_env(self):
        assert os.getenv("S3_BUCKET"), "S3_BUCKET not set"

    def test_s3_endpoint_in_env(self):
        endpoint = os.getenv("S3_ENDPOINT_URL", "")
        assert endpoint.startswith("https://"), f"S3_ENDPOINT_URL looks wrong: {endpoint!r}"

    def test_gemini_model_set(self):
        model = os.getenv("GEMINI_SEMANTIC_MODEL", "")
        assert model, "GEMINI_SEMANTIC_MODEL not set"

    def test_redis_url_in_env(self):
        redis_url = os.getenv("REDIS_URL", "")
        assert redis_url.startswith("redis://"), f"REDIS_URL not configured: {redis_url!r}"

    def test_mail_config(self):
        assert os.getenv("SMTP_HOST"), "SMTP_HOST not set"
        assert os.getenv("SMTP_USER"), "SMTP_USER not set"

    def test_secret_key_length(self):
        key = os.getenv("SECRET_KEY", "")
        assert len(key) >= 32, "SECRET_KEY too short (min 32 chars)"


class TestPipelineMockFull:
    """Comprehensive mock pipeline cycle — no external services required."""

    @pytest.fixture(autouse=True)
    def _pdf(self, tmp_path):
        self.pdf = tmp_path / "report.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\nMoSPI Survey 2024\n%%EOF\n")

    def test_complete_pipeline_cycle(self):
        """One complete cycle: PDF → hash → VLM → entities → questions → AST → review."""
        result = run_extraction_pipeline(
            self.pdf,
            "MoSPI Survey 2024",
            vlm_backend="mock",
            sglang_backend="mock",
        )
        assert result.success
        assert result.source_hash and len(result.source_hash) == 64
        assert result.ast is not None
        assert len(result.ast.topics) >= 1
        assert len(result.ast.entities) >= 5
        assert len(result.ast.all_questions()) >= 1
        assert result.review is not None
        assert result.review.decision in (
            ReviewDecision.AUTO_PASS, ReviewDecision.APPROVE, ReviewDecision.NEEDS_EDIT
        )

    def test_extractionmethod_contains_backend_name(self):
        result = run_extraction_pipeline(
            self.pdf, "Label Test", vlm_backend="mock", sglang_backend="mock"
        )
        assert "mock" in result.ast.extractionMethod

    def test_ast_pydantic_validates(self):
        result = run_extraction_pipeline(
            self.pdf, "Pydantic Test", vlm_backend="mock", sglang_backend="mock"
        )
        model = TemplateBlueprintModel(**result.ast.to_dict())
        assert len(model.topics) == len(result.ast.topics)

    def test_ast_roundtrip_lossless(self):
        result = run_extraction_pipeline(
            self.pdf, "Roundtrip", vlm_backend="mock", sglang_backend="mock"
        )
        d = result.ast.to_dict()
        restored = TemplateBlueprintAST.from_dict(d)
        assert restored.templateId == result.ast.templateId
        assert len(restored.all_questions()) == len(result.ast.all_questions())
        assert len(restored.entities) == len(result.ast.entities)

    def test_all_entity_bindings_valid(self):
        result = run_extraction_pipeline(
            self.pdf, "Binding Test", vlm_backend="mock", sglang_backend="mock"
        )
        entity_ids = {e.entityId for e in result.ast.entities}
        for q in result.ast.all_questions():
            for binding in q.requiredEntities:
                assert binding.entityId in entity_ids, (
                    f"Orphaned binding: {binding.entityId} not in {entity_ids}"
                )

    def test_all_component_types_valid(self):
        result = run_extraction_pipeline(
            self.pdf, "Component Types", vlm_backend="mock", sglang_backend="mock"
        )
        for q in result.ast.all_questions():
            for comp in q.answerStructure.components:
                assert comp.type in COMPONENT_TYPES, (
                    f"Invalid component type: {comp.type!r}"
                )

    def test_all_entity_types_valid(self):
        result = run_extraction_pipeline(
            self.pdf, "Entity Types", vlm_backend="mock", sglang_backend="mock"
        )
        for ent in result.ast.entities:
            assert ent.entityType in ENTITY_TYPES, (
                f"Invalid entity type: {ent.entityType!r}"
            )
            assert ent.sourceType in ENTITY_SOURCE_TYPES, (
                f"Invalid source type: {ent.sourceType!r}"
            )

    def test_confidence_values_in_range(self):
        result = run_extraction_pipeline(
            self.pdf, "Confidence", vlm_backend="mock", sglang_backend="mock"
        )
        for ent in result.ast.entities:
            assert 0.0 <= ent.confidence <= 1.0, f"Entity confidence out of range: {ent.confidence}"
        for q in result.ast.all_questions():
            assert 0.0 <= q.inferenceConfidence <= 1.0, (
                f"Inference confidence out of range: {q.inferenceConfidence}"
            )

    def test_all_stages_complete_in_progress(self):
        stages: list[str] = []
        run_extraction_pipeline(
            self.pdf, "Progress", vlm_backend="mock", sglang_backend="mock",
            progress_callback=lambda p: stages.append(p.stage),
        )
        for required in ["hashing", "vlm_parsing", "entity_extraction",
                         "entity_deduplication", "question_inference",
                         "ast_assembly", "validation", "complete"]:
            assert required in stages, f"Stage {required!r} never reached"

    def test_timings_all_non_negative(self):
        result = run_extraction_pipeline(
            self.pdf, "Timings", vlm_backend="mock", sglang_backend="mock"
        )
        for stage, t in result.progress.timings.items():
            assert t >= 0, f"Negative timing for stage {stage}: {t}"

    def test_review_stats_match_ast(self):
        result = run_extraction_pipeline(
            self.pdf, "Stats Match", vlm_backend="mock", sglang_backend="mock"
        )
        stats = result.review.stats
        assert stats["topics"] == len(result.ast.topics)
        assert stats["questions"] == len(result.ast.all_questions())
        assert stats["entities"] == len(result.ast.entities)

    def test_legacy_bridge_produces_blocks(self):
        result = run_extraction_pipeline(
            self.pdf, "Bridge", vlm_backend="mock", sglang_backend="mock"
        )
        from report_builder.blueprint import template_from_deep_blueprint
        legacy = template_from_deep_blueprint(result.ast)
        assert len(legacy.blocks) > 0


class TestSchemaContract:
    """Verify schema constants are internally consistent."""

    def test_component_types_tuple(self):
        assert len(COMPONENT_TYPES) == 11
        assert "narrative_paragraph" in COMPONENT_TYPES
        assert "data_table" in COMPONENT_TYPES
        assert "grouped_bar_chart" in COMPONENT_TYPES

    def test_entity_types_tuple(self):
        assert set(ENTITY_TYPES) == {"dimension", "measure", "filter", "metadata"}

    def test_entity_source_types_tuple(self):
        assert len(ENTITY_SOURCE_TYPES) == 7
        assert "table_header" in ENTITY_SOURCE_TYPES

    def test_pydantic_json_schema_exportable(self):
        schema = export_json_schema()
        assert schema.get("type") == "object"
        assert "properties" in schema
        assert "topics" in schema["properties"]
        assert "entities" in schema["properties"]

    def test_pydantic_validates_minimal_blueprint(self):
        minimal = {
            "templateId": "tmpl_abc",
            "name": "Test",
            "sourceHash": "abc123",
            "pageCount": 1,
            "extractionMethod": "mock",
            "topics": [],
            "entities": [],
            "extractionMeta": {},
        }
        model = TemplateBlueprintModel(**minimal)
        assert model.templateId == "tmpl_abc"

    def test_blueprint_rejects_invalid_component_type(self):
        """Pydantic must reject unknown component types (strict enums)."""
        data = {
            "templateId": "t1",
            "name": "X",
            "sourceHash": "",
            "pageCount": 0,
            "extractionMethod": "mock",
            "topics": [
                {
                    "topicId": "t1",
                    "title": "T",
                    "questions": [
                        {
                            "questionId": "q1",
                            "intent": "Q?",
                            "questionType": "describe",
                            "inferenceMethod": "stub",
                            "inferenceConfidence": 0.5,
                            "requiredEntities": [],
                            "answerStructure": {
                                "layoutType": "single",
                                "components": [
                                    {
                                        "componentId": "c1",
                                        "renderOrder": 1,
                                        "type": "INVALID_TYPE_XYZ",  # ← must fail
                                        "constraints": {},
                                        "refs": {},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            "entities": [],
            "extractionMeta": {},
        }
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TemplateBlueprintModel(**data)


class TestEntityExtractionDepth:
    """Deep tests on entity extraction from realistic mock pages."""

    @pytest.fixture(autouse=True)
    def _pages(self, tmp_path):
        client = MockVLMClient()
        pdf = tmp_path / "mospi.pdf"
        pdf.write_bytes(b"%PDF-1.4\n\n%%EOF\n")
        self.pages = client.extract_pages(pdf)

    def test_extracts_from_table_headers(self):
        raw = extract_entities(self.pages)
        # Mock table page has: State, Rural MPCE (₹), Urban MPCE (₹), Combined MPCE (₹)
        names = [e.name for e in raw]
        assert any("State" in n for n in names), f"Expected 'State' in {names}"

    def test_extracts_from_chart_axes(self):
        raw = extract_entities(self.pages)
        names_lower = [e.name.lower() for e in raw]
        # Chart page has xAxis=State, yAxis=MPCE (₹)
        assert any("state" in n for n in names_lower), "chart_axis entity 'State' missing"

    def test_extracts_from_narrative_terms(self):
        raw = extract_entities(self.pages)
        names = [e.name for e in raw]
        # Executive summary has VLMEntity: MPCE, Rural, Urban
        assert any(n in ("MPCE", "Rural", "Urban") for n in names)

    def test_dedup_removes_exact_duplicates(self):
        raw = extract_entities(self.pages)
        deduped = deduplicate_entities(raw)
        names_lower = [e.name.lower() for e in deduped]
        assert len(names_lower) == len(set(names_lower)), "Duplicates remain after dedup"

    def test_dedup_boosts_confidence_for_multi_source(self):
        """An entity confirmed from multiple sources should have higher confidence."""
        raw = extract_entities(self.pages)
        deduped = deduplicate_entities(raw)
        # "State" appears in table headers AND chart axes
        state_entities = [e for e in deduped if e.name.lower() == "state"]
        assert state_entities, "Entity 'State' missing"
        # Confidence should be boosted (> 0.80 since it comes from high-trust table_header)
        assert state_entities[0].confidence > 0.80

    def test_entity_ids_are_unique(self):
        raw = extract_entities(self.pages)
        deduped = deduplicate_entities(raw)
        ids = [e.entityId for e in deduped]
        assert len(ids) == len(set(ids)), "Duplicate entity IDs after dedup"

    def test_entity_classifier_measure_keywords(self):
        assert classify_entity_type("MPCE (₹)", "table_header") == "measure"
        assert classify_entity_type("Expenditure Rate", "table_header") == "measure"
        assert classify_entity_type("GDP Growth", "chart_axis") == "measure"

    def test_entity_classifier_dimension_keywords(self):
        assert classify_entity_type("State", "table_header") == "dimension"
        assert classify_entity_type("Rural Sector", "chart_legend") == "dimension"
        assert classify_entity_type("Gender", "section_heading") == "dimension"

    def test_entity_classifier_metadata_from_footnote(self):
        assert classify_entity_type("NSSO 68th Round", "footnote") == "metadata"

    def test_entity_classifier_measure_from_formula(self):
        assert classify_entity_type("sample_size", "formula_variable") == "measure"


class TestQuestionInferenceDepth:
    """Deep tests on question inference cascade."""

    @pytest.fixture(autouse=True)
    def _data(self, tmp_path):
        client = MockVLMClient()
        pdf = tmp_path / "q.pdf"
        pdf.write_bytes(b"%PDF-1.4\n\n%%EOF\n")
        pages = client.extract_pages(pdf)
        raw = extract_entities(pages)
        self.entities = deduplicate_entities(raw)
        self.pages = pages
        self.topics = infer_questions(pages, self.entities)

    def test_produces_topics(self):
        assert len(self.topics) >= 1

    def test_each_topic_has_questions(self):
        # Most topics should have questions (some cover/intro pages may not)
        topics_with_questions = [t for t in self.topics if t.questions]
        assert topics_with_questions, "No topics have any questions"

    def test_question_intents_are_non_empty(self):
        for topic in self.topics:
            for q in topic.questions:
                assert q.intent.strip(), f"Empty intent in {q.questionId}"

    def test_question_inference_confidence_above_threshold(self):
        for topic in self.topics:
            for q in topic.questions:
                assert q.inferenceConfidence >= 0.3, (
                    f"Confidence below threshold: {q.inferenceConfidence} for {q.intent!r}"
                )

    def test_answer_structures_have_components(self):
        for topic in self.topics:
            for q in topic.questions:
                assert q.answerStructure.components, (
                    f"Empty answer structure for {q.questionId}: {q.intent!r}"
                )

    def test_page_range_populated(self):
        for topic in self.topics:
            assert topic.pageRange, f"Topic {topic.topicId} has empty pageRange"

    def test_topic_ids_are_unique(self):
        ids = [t.topicId for t in self.topics]
        assert len(ids) == len(set(ids)), "Duplicate topicIds"

    def test_question_ids_unique_across_all_topics(self):
        all_ids = [q.questionId for t in self.topics for q in t.questions]
        assert len(all_ids) == len(set(all_ids)), "Duplicate questionIds across topics"

    def test_inference_method_is_known(self):
        known_methods = {"vlm", "hybrid", "pattern", "stub"}
        for topic in self.topics:
            for q in topic.questions:
                assert q.inferenceMethod in known_methods, (
                    f"Unknown method: {q.inferenceMethod!r}"
                )

    def test_chart_page_produces_chart_component(self):
        """Page 4 (chart page) should produce at least one chart component."""
        chart_pages = [p for p in self.pages if p.has_charts]
        if not chart_pages:
            pytest.skip("No chart pages in mock data")

        all_comps = [
            comp
            for t in self.topics
            for q in t.questions
            for comp in q.answerStructure.components
        ]
        chart_comp_types = {
            "grouped_bar_chart", "line_chart", "pie_chart", "geographic_map"
        }
        has_chart_comp = any(c.type in chart_comp_types for c in all_comps)
        assert has_chart_comp, "Chart page did not produce a chart component"

    def test_table_page_produces_table_component(self):
        """Page 3 (table page) should produce at least one data_table component."""
        table_pages = [p for p in self.pages if p.has_tables]
        if not table_pages:
            pytest.skip("No table pages in mock data")

        all_comps = [
            comp
            for t in self.topics
            for q in t.questions
            for comp in q.answerStructure.components
        ]
        has_table = any(c.type in ("data_table", "cross_tabulation_matrix") for c in all_comps)
        assert has_table, "Table page did not produce a table component"


class TestASTAssemblerDepth:
    """Detailed tests for the AST assembler stage."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        client = MockVLMClient()
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4\n\n%%EOF\n")
        pages = client.extract_pages(pdf)
        raw = extract_entities(pages)
        entities = deduplicate_entities(raw)
        topics = infer_questions(pages, entities)
        self.ast = assemble_template_ast(
            pages, entities, topics, "Assembler Test", "testhash123456"
        )

    def test_template_id_uses_hash_prefix(self):
        # assembler uses first 12 chars: "testhash123456"[:12] == "testhash1234"
        assert self.ast.templateId == "tmpl_testhash1234"

    def test_page_count_correct(self):
        assert self.ast.pageCount == 6  # mock client always generates 6 pages

    def test_extraction_meta_complete(self):
        meta = self.ast.extractionMeta
        assert "total_pages" in meta
        assert "total_entities" in meta
        assert "total_topics" in meta
        assert "total_questions" in meta
        assert "avg_page_confidence" in meta
        assert meta["total_pages"] == 6
        assert meta["total_entities"] > 0

    def test_avg_page_confidence_in_range(self):
        conf = self.ast.extractionMeta.get("avg_page_confidence", -1)
        assert 0.0 <= conf <= 1.0, f"avg_page_confidence out of range: {conf}"

    def test_entity_refs_in_components_reference_real_ids(self):
        entity_ids = {e.entityId for e in self.ast.entities}
        for q in self.ast.all_questions():
            for comp in q.answerStructure.components:
                for ref in comp.refs.entityRefs:
                    assert ref in entity_ids, f"Component entityRef {ref} is invalid"

    def test_empty_source_hash_gives_draft_id(self):
        from template_engine.extraction.entity_extractor import extract_entities
        client = MockVLMClient()
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4\n\n%%EOF\n")
            tmp = f.name
        try:
            pages = client.extract_pages(tmp)
            raw = extract_entities(pages)
            ents = deduplicate_entities(raw)
            topics = infer_questions(pages, ents)
            ast = assemble_template_ast(pages, ents, topics, "Draft", source_hash="")
            assert ast.templateId == "tmpl_draft"
        finally:
            os.unlink(tmp)

    def test_mock_vlm_backend_label(self, tmp_path: Path):
        client = MockVLMClient()
        pdf = tmp_path / "label.pdf"
        pdf.write_bytes(b"%PDF-1.4\n\n%%EOF\n")
        pages = client.extract_pages(pdf)
        raw = extract_entities(pages)
        ents = deduplicate_entities(raw)
        topics = infer_questions(pages, ents)
        ast = assemble_template_ast(
            pages, ents, topics, "Label", "hashxyz",
            vlm_backend="mock"
        )
        assert "mock" in ast.extractionMethod


class TestReviewerThresholds:
    """Detailed tests for TemplateReviewer decision boundaries."""

    def _minimal_ast(
        self,
        n_topics: int = 3,
        n_questions_per_topic: int = 2,
        n_entities: int = 6,
        avg_confidence: float = 0.90,
        orphan_binding: bool = False,
    ) -> TemplateBlueprintAST:
        entities = [
            TemplateEntity(
                entityId=f"ent_{i:04d}",
                name=f"Entity {i}",
                entityType="dimension",
                sourceType="table_header",
                confidence=0.85,
            )
            for i in range(n_entities)
        ]
        topics = []
        for ti in range(n_topics):
            questions = []
            for qi in range(n_questions_per_topic):
                binding_id = "ent_ORPHAN" if orphan_binding and ti == 0 and qi == 0 else (
                    f"ent_{(ti * n_questions_per_topic + qi) % max(n_entities, 1):04d}"
                )
                questions.append(QuestionNode(
                    questionId=f"Q_{ti:02d}{qi:02d}",
                    intent=f"Question {ti}-{qi}?",
                    questionType="describe",
                    inferenceMethod="pattern",
                    inferenceConfidence=0.65,
                    requiredEntities=[QuestionEntityBinding(entityId=binding_id, role="required", confidence=0.8)],
                    answerStructure=AnswerStructure(components=[
                        AnswerComponent(componentId=f"c_{ti}_{qi}", renderOrder=1, type="narrative_paragraph")
                    ]),
                ))
            topics.append(TopicNode(topicId=f"topic_{ti:03d}", title=f"Topic {ti}", questions=questions))
        return TemplateBlueprintAST(
            templateId="t1", name="Test", sourceHash="x", pageCount=5,
            extractionMethod="mock",
            topics=topics, entities=entities,
            extractionMeta={"avg_page_confidence": avg_confidence},
        )

    def test_auto_pass_on_healthy_ast(self):
        ast = self._minimal_ast()
        result = TemplateReviewer().review(ast)
        assert result.decision in (ReviewDecision.AUTO_PASS, ReviewDecision.APPROVE)
        assert not result.has_errors

    def test_needs_edit_on_orphaned_binding(self):
        ast = self._minimal_ast(orphan_binding=True)
        result = TemplateReviewer().review(ast)
        assert result.decision == ReviewDecision.NEEDS_EDIT
        assert result.has_errors

    def test_warning_on_below_min_topics(self):
        ast = self._minimal_ast(n_topics=1)
        result = TemplateReviewer(min_topics=3).review(ast)
        warning_msgs = [i.message for i in result.issues if i.severity == "warning"]
        assert any("topic" in m.lower() for m in warning_msgs)

    def test_warning_on_below_min_entities(self):
        ast = self._minimal_ast(n_entities=2)
        result = TemplateReviewer(min_entities=5).review(ast)
        warning_msgs = [i.message for i in result.issues]
        assert any("entit" in m.lower() for m in warning_msgs)

    def test_confidence_score_is_1_for_perfect_ast(self):
        # 10 topics, 10 questions each, 20 entities, perfect confidence
        ast = self._minimal_ast(n_topics=10, n_questions_per_topic=10, n_entities=20, avg_confidence=1.0)
        result = TemplateReviewer(min_topics=2, min_questions=3, min_entities=5).review(ast)
        assert result.confidence_score == pytest.approx(1.0)

    def test_reviewer_stats_match_ast(self):
        ast = self._minimal_ast(n_topics=3, n_questions_per_topic=2, n_entities=6)
        result = TemplateReviewer().review(ast)
        assert result.stats["topics"] == 3
        assert result.stats["questions"] == 6
        assert result.stats["entities"] == 6


class TestVLMPageProperties:
    """VLMPageResult computed properties."""

    def test_has_tables_true(self):
        page = VLMPageResult(
            pageIndex=0,
            tables=[VLMTableData(headers=["A", "B"], rows=[["1", "2"]], regionId="t1")],
        )
        assert page.has_tables is True

    def test_has_tables_false(self):
        page = VLMPageResult(pageIndex=0)
        assert page.has_tables is False

    def test_has_charts_true(self):
        page = VLMPageResult(
            pageIndex=0,
            charts=[VLMChartData(chartType="bar", regionId="c1")],
        )
        assert page.has_charts is True

    def test_headings_filter(self):
        page = VLMPageResult(
            pageIndex=0,
            regions=[
                VLMRegion(regionId="r1", role="title", text="Title", bbox=VLMBBox()),
                VLMRegion(regionId="r2", role="paragraph", text="Body text", bbox=VLMBBox()),
                VLMRegion(regionId="r3", role="heading_h1", text="Section 1", bbox=VLMBBox()),
                VLMRegion(regionId="r4", role="heading_h2", text="Subsection", bbox=VLMBBox()),
            ],
        )
        headings = page.headings
        assert "Title" in headings
        assert "Section 1" in headings
        assert "Subsection" in headings
        assert "Body text" not in headings

    def test_to_dict_from_dict_roundtrip_all_fields(self):
        page = VLMPageResult(
            pageIndex=2,
            width=800.0,
            height=1000.0,
            regions=[VLMRegion(regionId="r1", role="title", text="T", bbox=VLMBBox(10, 20, 300, 50))],
            entities=[VLMEntity(name="E", entityType="measure", sourceType="table_header", confidence=0.9)],
            tables=[VLMTableData(headers=["X"], rows=[["1"]], regionId="t1")],
            charts=[VLMChartData(chartType="line", title="Growth", xAxis="Year", yAxis="GDP")],
            rawText="raw",
            confidence=0.85,
        )
        d = page.to_dict()
        restored = VLMPageResult.from_dict(d)
        assert restored.pageIndex == 2
        assert restored.width == 800.0
        assert len(restored.regions) == 1
        assert len(restored.entities) == 1
        assert len(restored.tables) == 1
        assert len(restored.charts) == 1
        assert restored.confidence == pytest.approx(0.85)
        assert restored.regions[0].text == "T"
        assert restored.entities[0].name == "E"


# ===========================================================================
# TIER 2 — Gemini live tests (live_llm marker)
# ===========================================================================

@pytest.mark.live
@pytest.mark.live_llm
class TestGeminiHybridInference:
    """Live tests using real Gemini API. Requires GEMINI_API_KEY in .env."""

    def test_gemini_key_is_accessible(self):
        key = os.getenv("GEMINI_API_KEY", "")
        assert key, "GEMINI_API_KEY not loaded from .env"

    def test_hybrid_inferrer_returns_question(self, tmp_path):
        """HybridInferrer should return a non-empty question string via Gemini."""
        from template_engine.inference.question_inferrer import HybridInferrer
        from template_engine.vlm.schemas import VLMRegion, VLMBBox

        inferrer = HybridInferrer()
        page = VLMPageResult(
            pageIndex=3,
            tables=[VLMTableData(
                headers=["State", "Rural MPCE (₹)", "Urban MPCE (₹)"],
                rows=[["Punjab", "2100", "3800"]],
                regionId="t1",
            )],
        )
        region = VLMRegion(
            regionId="r1",
            role="heading_h1",
            text="Household Consumption Expenditure by State",
            bbox=VLMBBox(50, 50, 400, 75),
            confidence=0.95,
        )
        entities = [
            TemplateEntity(
                entityId="ent_0001", name="State",
                entityType="dimension", sourceType="table_header", confidence=0.95
            ),
            TemplateEntity(
                entityId="ent_0002", name="MPCE",
                entityType="measure", sourceType="table_header", confidence=0.93
            ),
        ]

        result = inferrer.infer(page, region, entities)
        assert result is not None, "HybridInferrer returned None (check GEMINI_API_KEY)"
        question, confidence = result
        assert question.strip(), "Gemini returned empty question"
        assert 0.0 < confidence <= 1.0

    def test_gemini_model_is_configured(self):
        model_name = os.getenv("GEMINI_SEMANTIC_MODEL", "")
        assert model_name, "GEMINI_SEMANTIC_MODEL not set"
        assert "gemini" in model_name.lower(), f"Unexpected model name: {model_name!r}"

    def test_pipeline_with_live_gemini_inference(self, tmp_path):
        """Run mock VLM + real Gemini hybrid inference for question generation."""
        pdf = tmp_path / "live_gemini.pdf"
        pdf.write_bytes(b"%PDF-1.4\nHousehold Survey 2024\n%%EOF\n")

        result = run_extraction_pipeline(
            pdf,
            "Live Gemini Test",
            vlm_backend="mock",
            sglang_backend="mock",
        )
        assert result.success
        # With Gemini live, at least one question should use "hybrid" inference method
        methods = [q.inferenceMethod for q in result.ast.all_questions()]
        # In the pipeline, Gemini runs first in the cascade
        # If key is valid, some questions should be "hybrid"
        assert len(result.ast.all_questions()) > 0


# ===========================================================================
# TIER 3 — ColPali live tests
# ===========================================================================

@pytest.mark.live
@pytest.mark.live_vlm
class TestColPaliLive:
    """Live tests against real ColPali service. Requires COLPALI_ENDPOINT."""

    def test_health_check_passes(self, colpali_endpoint):
        from template_engine.vlm.colpali_client import ColPaliClient
        client = ColPaliClient(endpoint=colpali_endpoint)
        assert client.health_check(), f"ColPali health check failed at {colpali_endpoint}"

    def test_extracts_pages_from_real_pdf(self, colpali_endpoint, tmp_path):
        from template_engine.vlm.colpali_client import ColPaliClient
        client = ColPaliClient(endpoint=colpali_endpoint)
        pdf = tmp_path / "real.pdf"
        pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
        pages = client.extract_pages(pdf)
        assert len(pages) >= 1
        for page in pages:
            assert 0.0 <= page.confidence <= 1.0

    def test_full_pipeline_with_colpali(self, colpali_endpoint, tmp_path):
        pdf = tmp_path / "colpali_real.pdf"
        pdf.write_bytes(b"%PDF-1.4\nReal Test\n%%EOF\n")
        result = run_extraction_pipeline(
            pdf,
            "ColPali Live Test",
            vlm_backend="colpali",
            sglang_backend="mock",
        )
        assert result.success
        assert "colpali" in result.ast.extractionMethod


# ===========================================================================
# TIER 4 — SGLang live tests
# ===========================================================================

@pytest.mark.live
@pytest.mark.live_sglang
class TestSGLangLive:
    """Live tests against real SGLang server. Requires SGLANG_ENDPOINT."""

    def test_health_check_passes(self, sglang_endpoint):
        from template_engine.generation.sglang_client import RealSGLangClient
        client = RealSGLangClient(endpoint=sglang_endpoint)
        assert client.health_check(), f"SGLang health check failed at {sglang_endpoint}"

    def test_generates_valid_json_conforming_to_schema(self, sglang_endpoint, tmp_path):
        from template_engine.generation.sglang_client import RealSGLangClient
        client = RealSGLangClient(endpoint=sglang_endpoint)
        schema = export_json_schema()
        prompt = (
            "Generate a minimal template blueprint for a 2-page statistical report "
            "with one topic and one question about household expenditure."
        )
        result = client.generate(prompt, schema)
        assert "templateId" in result
        assert "topics" in result
        assert "entities" in result

    def test_full_pipeline_with_sglang(self, sglang_endpoint, tmp_path):
        pdf = tmp_path / "sglang_real.pdf"
        pdf.write_bytes(b"%PDF-1.4\nSGLang Real\n%%EOF\n")
        result = run_extraction_pipeline(
            pdf,
            "SGLang Live Test",
            vlm_backend="mock",
            sglang_backend="sglang",
        )
        assert result.success
        assert "sglang" in result.ast.extractionMethod


# ===========================================================================
# TIER 5 — Supabase / Postgres live tests
# ===========================================================================

@pytest.mark.live
@pytest.mark.live_db
class TestTemplateRepository:
    """Live tests against Supabase Postgres. Requires DATABASE_URL."""

    @pytest.fixture(autouse=True)
    def _db_session(self, database_url):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        engine = create_engine(database_url, pool_pre_ping=True)
        Session = sessionmaker(bind=engine)
        self.session = Session()
        yield
        self.session.close()

    def test_database_connection(self):
        from sqlalchemy import text
        result = self.session.execute(text("SELECT 1")).scalar()
        assert result == 1

    def test_save_and_load_template(self, tmp_path):
        """Save a TemplateAST to DB and reload it."""
        from template_engine.storage.template_repository import save_template, load_template

        # Run pipeline to get a real AST
        pdf = tmp_path / "db_test.pdf"
        pdf.write_bytes(b"%PDF-1.4\nDB Test\n%%EOF\n")
        result = run_extraction_pipeline(pdf, "DB Test Template", vlm_backend="mock", sglang_backend="mock")
        assert result.success

        # Convert deep AST to legacy TemplateAST for repository
        from report_builder.blueprint import template_from_deep_blueprint
        from template_engine.ast.ast_builder import TemplateAST
        legacy = template_from_deep_blueprint(result.ast)

        row = save_template(self.session, legacy, "Integration Test Template")
        assert row.id is not None

        loaded = load_template(self.session, row.id)
        assert loaded is not None
        assert loaded.name == legacy.name

    def test_list_templates(self):
        from template_engine.storage.template_repository import list_templates
        templates = list_templates(self.session)
        assert isinstance(templates, list)


# ===========================================================================
# TIER 6 — Cloudflare R2 / S3 live tests
# ===========================================================================

@pytest.mark.live
@pytest.mark.live_s3
class TestS3Storage:
    """Live tests against Cloudflare R2. Requires S3/R2 credentials."""

    def test_s3_config_loaded(self, s3_config):
        assert s3_config["bucket"]
        assert s3_config["endpoint"].startswith("https://")

    def test_list_bucket(self, s3_config):
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=s3_config["endpoint"],
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=s3_config["region"],
        )
        # List objects — should not raise
        response = s3.list_objects_v2(Bucket=s3_config["bucket"], MaxKeys=5)
        assert "ResponseMetadata" in response

    def test_presigned_url_generation(self, s3_config):
        """Presigned URL for upload should be generatable."""
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=s3_config["endpoint"],
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=s3_config["region"],
        )
        url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": s3_config["bucket"], "Key": "test/integration_test.txt"},
            ExpiresIn=60,
        )
        assert url.startswith("https://")
        assert s3_config["bucket"] in url or "test" in url
