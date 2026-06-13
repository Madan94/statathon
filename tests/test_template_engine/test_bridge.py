"""Tests for the report_builder bridge (deep pipeline → legacy TemplateAST)."""
from __future__ import annotations

from pathlib import Path

import pytest

from template_engine.pipeline import run_extraction_pipeline
from report_builder.blueprint import (
    template_from_deep_blueprint,
    TemplateAST,
    BlockSpec,
    _infer_block_kind,
)


@pytest.fixture
def deep_ast(tmp_path: Path):
    """Generate a deep AST via mock pipeline."""
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\nbridge test\n%%EOF\n")
    result = run_extraction_pipeline(
        pdf_path=pdf,
        template_name="Bridge Test Report",
        vlm_backend="mock",
        sglang_backend="mock",
    )
    assert result.success
    return result.ast


class TestDeepToLegacyBridge:
    def test_converts_to_template_ast(self, deep_ast):
        legacy = template_from_deep_blueprint(deep_ast)
        assert isinstance(legacy, TemplateAST)
        assert legacy.name == "Bridge Test Report"
        assert legacy.source_hash == deep_ast.sourceHash
        assert legacy.page_count == deep_ast.pageCount
        assert len(legacy.blocks) > 0

    def test_topics_become_headings(self, deep_ast):
        legacy = template_from_deep_blueprint(deep_ast)
        heading_blocks = [b for b in legacy.blocks if b.kind == "heading"]
        assert len(heading_blocks) == len(deep_ast.topics)

    def test_questions_become_blocks(self, deep_ast):
        legacy = template_from_deep_blueprint(deep_ast)
        total_questions = sum(len(t.questions) for t in deep_ast.topics)
        non_heading_blocks = [b for b in legacy.blocks if b.kind != "heading"]
        assert len(non_heading_blocks) == total_questions

    def test_block_hints_contain_metadata(self, deep_ast):
        legacy = template_from_deep_blueprint(deep_ast)
        question_blocks = [b for b in legacy.blocks if b.kind != "heading"]
        for block in question_blocks:
            assert "question_id" in block.hints
            assert "confidence" in block.hints

    def test_extraction_method_preserved(self, deep_ast):
        legacy = template_from_deep_blueprint(deep_ast)
        assert legacy.extraction_method != ""

    def test_to_dict_works(self, deep_ast):
        legacy = template_from_deep_blueprint(deep_ast)
        d = legacy.to_dict()
        assert "blocks" in d
        assert "name" in d
        assert d["name"] == "Bridge Test Report"


class TestBlockKindInference:
    def test_table_component(self):
        from ast_core.schema import QuestionNode, AnswerStructure, AnswerComponent, AnswerComponentRef
        q = QuestionNode(
            questionId="q1",
            intent="Test",
            answerStructure=AnswerStructure(components=[
                AnswerComponent(
                    componentId="c1",
                    type="data_table",
                    refs=AnswerComponentRef(),
                ),
            ]),
        )
        assert _infer_block_kind(q) == "table"

    def test_chart_component(self):
        from ast_core.schema import QuestionNode, AnswerStructure, AnswerComponent, AnswerComponentRef
        q = QuestionNode(
            questionId="q1",
            intent="Test",
            answerStructure=AnswerStructure(components=[
                AnswerComponent(
                    componentId="c1",
                    type="grouped_bar_chart",
                    refs=AnswerComponentRef(),
                ),
            ]),
        )
        assert _infer_block_kind(q) == "chart"

    def test_narrative_default(self):
        from ast_core.schema import QuestionNode, AnswerStructure, AnswerComponent, AnswerComponentRef
        q = QuestionNode(
            questionId="q1",
            intent="Test",
            answerStructure=AnswerStructure(components=[
                AnswerComponent(
                    componentId="c1",
                    type="narrative_paragraph",
                    refs=AnswerComponentRef(),
                ),
            ]),
        )
        assert _infer_block_kind(q) == "narrative"
