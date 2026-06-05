"""Unit tests for entity extraction, classification, and deduplication."""
from __future__ import annotations

from pathlib import Path

import pytest

from template_engine.vlm.mock_client import MockVLMClient
from template_engine.extraction.entity_extractor import extract_entities
from template_engine.extraction.entity_classifier import classify_entity_type
from template_engine.extraction.entity_deduplicator import deduplicate_entities
from ast_core.schema import TemplateEntity


@pytest.fixture
def mock_pages(tmp_path: Path):
    client = MockVLMClient()
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\ntest\n%%EOF\n")
    return client.extract_pages(pdf)


class TestEntityExtraction:
    def test_extracts_entities_from_mock(self, mock_pages):
        entities = extract_entities(mock_pages)
        assert len(entities) > 0
        assert all(isinstance(e, TemplateEntity) for e in entities)

    def test_entities_have_valid_fields(self, mock_pages):
        entities = extract_entities(mock_pages)
        for e in entities:
            assert e.entityId
            assert e.name
            assert e.sourceType
            assert 0 < e.confidence <= 1.0

    def test_empty_pages_yield_no_entities(self):
        entities = extract_entities([])
        assert entities == []


class TestEntityClassifier:
    def test_measure_detection(self):
        assert classify_entity_type("GDP Growth Rate", "table_header") == "measure"
        assert classify_entity_type("Revenue", "table_header") == "measure"
        assert classify_entity_type("Total Expenditure", "heading") == "measure"

    def test_dimension_detection(self):
        assert classify_entity_type("State", "table_header") == "dimension"
        assert classify_entity_type("District Name", "heading") == "dimension"
        assert classify_entity_type("Year", "table_header") == "dimension"

    def test_filter_detection(self):
        assert classify_entity_type("Rural/Urban", "table_header") in ("filter", "dimension")
        assert classify_entity_type("Above 50000", "table_header") == "filter"

    def test_metadata_detection(self):
        assert classify_entity_type("Source: NSSO", "footnote") == "metadata"
        assert classify_entity_type("Note: Provisional", "footnote") == "metadata"


class TestEntityDeduplication:
    def test_dedup_removes_exact_duplicates(self, mock_pages):
        entities = extract_entities(mock_pages)
        # Duplicate them
        doubled = entities + entities
        deduped = deduplicate_entities(doubled)
        # Should be fewer than doubled
        assert len(deduped) < len(doubled)

    def test_dedup_boosts_confidence(self, mock_pages):
        entities = extract_entities(mock_pages)
        if len(entities) >= 2:
            # Create a known duplicate
            dup = TemplateEntity(
                entityId="test_dup",
                name=entities[0].name,
                entityType=entities[0].entityType,
                sourceType=entities[0].sourceType,
                confidence=0.5,
                pageIndex=99,
            )
            combined = entities + [dup]
            deduped = deduplicate_entities(combined)
            # The merged entity should have higher confidence
            merged = next((e for e in deduped if e.name == entities[0].name), None)
            assert merged is not None
            assert merged.confidence >= entities[0].confidence

    def test_dedup_empty_list(self):
        result = deduplicate_entities([])
        assert result == []
