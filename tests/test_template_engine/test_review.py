"""Tests for the review layer."""
from __future__ import annotations

from pathlib import Path

import pytest

from template_engine.pipeline import run_extraction_pipeline
from template_engine.review.reviewer import TemplateReviewer, ReviewDecision, ReviewResult
from ast_core.schema import TemplateBlueprintAST, TopicNode, QuestionNode, AnswerStructure, TemplateEntity


@pytest.fixture
def mock_ast(tmp_path: Path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\nreview test\n%%EOF\n")
    result = run_extraction_pipeline(
        pdf_path=pdf,
        template_name="Review Test",
        vlm_backend="mock",
        sglang_backend="mock",
    )
    assert result.success
    return result.ast


class TestTemplateReviewer:
    def test_review_mock_ast_passes(self, mock_ast):
        reviewer = TemplateReviewer()
        result = reviewer.review(mock_ast)
        assert isinstance(result, ReviewResult)
        assert result.decision in (ReviewDecision.APPROVE, ReviewDecision.AUTO_PASS)

    def test_review_has_stats(self, mock_ast):
        reviewer = TemplateReviewer()
        result = reviewer.review(mock_ast)
        assert "topics" in result.stats
        assert "questions" in result.stats
        assert "entities" in result.stats

    def test_empty_ast_gets_warnings(self):
        empty = TemplateBlueprintAST(
            templateId="tmpl_empty",
            name="Empty",
            sourceHash="",
            pageCount=0,
            topics=[],
            entities=[],
            extractionMeta={"avg_page_confidence": 0.2},
        )
        reviewer = TemplateReviewer()
        result = reviewer.review(empty)
        assert result.has_warnings or result.decision == ReviewDecision.NEEDS_EDIT

    def test_orphaned_binding_flagged(self):
        from ast_core.schema import QuestionEntityBinding, AnswerComponent, AnswerComponentRef
        ast = TemplateBlueprintAST(
            templateId="tmpl_orphan",
            name="Orphan Test",
            sourceHash="abc",
            pageCount=5,
            topics=[TopicNode(
                topicId="t1",
                title="Topic 1",
                questions=[QuestionNode(
                    questionId="q1",
                    intent="Test?",
                    requiredEntities=[
                        QuestionEntityBinding(entityId="nonexistent_entity", role="primary"),
                    ],
                    answerStructure=AnswerStructure(components=[
                        AnswerComponent(componentId="c1", type="narrative_paragraph",
                                        refs=AnswerComponentRef()),
                    ]),
                )],
            )],
            entities=[TemplateEntity(entityId="real_entity", name="Real", entityType="dimension",
                                     sourceType="table_header")],
            extractionMeta={"avg_page_confidence": 0.8},
        )
        reviewer = TemplateReviewer()
        result = reviewer.review(ast)
        error_msgs = [i.message for i in result.issues if i.severity == "error"]
        assert any("nonexistent_entity" in m for m in error_msgs)

    def test_confidence_score_range(self, mock_ast):
        reviewer = TemplateReviewer()
        result = reviewer.review(mock_ast)
        assert 0 <= result.confidence_score <= 1.0
