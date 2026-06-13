"""Unit tests for SGLang client and AST assembler."""
from __future__ import annotations

from pathlib import Path

import pytest

from template_engine.generation.sglang_client import (
    SGLangClient,
    MockSGLangClient,
    SGLangClientFactory,
)
from template_engine.generation.ast_assembler import assemble_template_ast
from template_engine.vlm.mock_client import MockVLMClient
from template_engine.extraction.entity_extractor import extract_entities
from template_engine.extraction.entity_deduplicator import deduplicate_entities
from template_engine.inference.question_inferrer import infer_questions
from ast_core.schema import TemplateBlueprintAST


@pytest.fixture
def mock_pages(tmp_path: Path):
    client = MockVLMClient()
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\ntest\n%%EOF\n")
    return client.extract_pages(pdf)


@pytest.fixture
def pipeline_data(mock_pages):
    raw_entities = extract_entities(mock_pages)
    entities = deduplicate_entities(raw_entities)
    topics = infer_questions(mock_pages, entities)
    return mock_pages, entities, topics


class TestMockSGLangClient:
    def test_health_check(self):
        client = MockSGLangClient()
        assert client.health_check() is True

    def test_backend_name(self):
        client = MockSGLangClient()
        assert client.backend_name == "mock_sglang"

    def test_generate_with_json_block(self):
        client = MockSGLangClient()
        payload = '{"key": "value"}'
        prompt = f"Context\n```json\n{payload}\n```\nEnd"
        result = client.generate(prompt, {})
        assert result == {"key": "value"}

    def test_generate_without_json_block(self):
        client = MockSGLangClient()
        result = client.generate("No JSON here", {})
        assert "templateId" in result
        assert "topics" in result

    def test_factory_mock(self):
        client = SGLangClientFactory.create("mock")
        assert isinstance(client, MockSGLangClient)


class TestASTAssembler:
    def test_assembles_valid_ast(self, pipeline_data):
        pages, entities, topics = pipeline_data
        ast = assemble_template_ast(
            pages=pages,
            entities=entities,
            topics=topics,
            template_name="Test Assembly",
            source_hash="abc123def456",
        )
        assert isinstance(ast, TemplateBlueprintAST)
        assert ast.name == "Test Assembly"
        assert ast.templateId.startswith("tmpl_")
        assert len(ast.topics) > 0
        assert len(ast.entities) > 0

    def test_assembler_with_sglang_mock(self, pipeline_data):
        pages, entities, topics = pipeline_data
        client = MockSGLangClient()
        ast = assemble_template_ast(
            pages=pages,
            entities=entities,
            topics=topics,
            template_name="With SGLang",
            source_hash="feedbeef1234",
            sglang_client=client,
        )
        assert ast is not None
        assert ast.pageCount == len(pages)

    def test_assembler_extraction_meta(self, pipeline_data):
        pages, entities, topics = pipeline_data
        ast = assemble_template_ast(
            pages=pages,
            entities=entities,
            topics=topics,
            template_name="Meta Test",
            source_hash="meta123",
        )
        meta = ast.extractionMeta
        assert "total_pages" in meta
        assert "total_entities" in meta
        assert "total_topics" in meta
        assert "total_questions" in meta
        assert "avg_page_confidence" in meta

    def test_assembler_cross_links(self, pipeline_data):
        pages, entities, topics = pipeline_data
        ast = assemble_template_ast(
            pages=pages,
            entities=entities,
            topics=topics,
            template_name="CrossLink Test",
            source_hash="xlink123",
        )
        # All entity bindings should reference valid entities
        entity_ids = {e.entityId for e in ast.entities}
        for q in ast.all_questions():
            for binding in q.requiredEntities:
                assert binding.entityId in entity_ids

    def test_to_dict_roundtrip(self, pipeline_data):
        pages, entities, topics = pipeline_data
        ast = assemble_template_ast(
            pages=pages,
            entities=entities,
            topics=topics,
            template_name="Roundtrip",
            source_hash="round123",
        )
        d = ast.to_dict()
        reconstructed = TemplateBlueprintAST.from_dict(d)
        assert reconstructed.name == ast.name
        assert reconstructed.sourceHash == ast.sourceHash
        assert len(reconstructed.topics) == len(ast.topics)
        assert len(reconstructed.entities) == len(ast.entities)
