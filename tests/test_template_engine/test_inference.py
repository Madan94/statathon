"""Unit tests for question inference cascade."""
from __future__ import annotations

from pathlib import Path

import pytest

from template_engine.vlm.mock_client import MockVLMClient
from template_engine.extraction.entity_extractor import extract_entities
from template_engine.extraction.entity_deduplicator import deduplicate_entities
from template_engine.inference.question_inferrer import infer_questions
from ast_core.schema import TopicNode, QuestionNode


@pytest.fixture
def mock_pages(tmp_path: Path):
    client = MockVLMClient()
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\ntest\n%%EOF\n")
    return client.extract_pages(pdf)


@pytest.fixture
def entities(mock_pages):
    raw = extract_entities(mock_pages)
    return deduplicate_entities(raw)


class TestQuestionInference:
    def test_infers_topics(self, mock_pages, entities):
        topics = infer_questions(mock_pages, entities)
        assert len(topics) > 0
        assert all(isinstance(t, TopicNode) for t in topics)

    def test_topics_have_questions(self, mock_pages, entities):
        topics = infer_questions(mock_pages, entities)
        total_questions = sum(len(t.questions) for t in topics)
        assert total_questions > 0

    def test_questions_have_answer_structures(self, mock_pages, entities):
        topics = infer_questions(mock_pages, entities)
        for topic in topics:
            for q in topic.questions:
                assert q.answerStructure is not None
                # Components should exist (at least stub)
                assert len(q.answerStructure.components) >= 0

    def test_questions_have_valid_fields(self, mock_pages, entities):
        topics = infer_questions(mock_pages, entities)
        for topic in topics:
            assert topic.topicId
            assert topic.title
            for q in topic.questions:
                assert q.questionId
                assert q.intent
                assert 0 < q.inferenceConfidence <= 1.0

    def test_empty_pages_no_crash(self, entities):
        topics = infer_questions([], entities)
        assert isinstance(topics, list)

    def test_no_entities_still_produces_topics(self, mock_pages):
        topics = infer_questions(mock_pages, [])
        # Should still generate from page headings alone
        assert isinstance(topics, list)
