"""Unit tests for VLM clients (mock, pdfplumber adapter)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from template_engine.vlm.schemas import VLMPageResult, VLMRegion, VLMEntity
from template_engine.vlm.client import VLMClientFactory, VLMExtractionError
from template_engine.vlm.mock_client import MockVLMClient


class TestMockVLMClient:
    def test_extract_returns_pages(self, tmp_path: Path):
        client = MockVLMClient()
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\ntest content\n%%EOF\n")

        pages = client.extract_pages(pdf)
        assert len(pages) > 0
        assert all(isinstance(p, VLMPageResult) for p in pages)

    def test_pages_have_regions(self, tmp_path: Path):
        client = MockVLMClient()
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\ntest\n%%EOF\n")

        pages = client.extract_pages(pdf)
        total_regions = sum(len(p.regions) for p in pages)
        assert total_regions > 0

    def test_pages_have_entities(self, tmp_path: Path):
        client = MockVLMClient()
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\ntest\n%%EOF\n")

        pages = client.extract_pages(pdf)
        total_entities = sum(len(p.entities) for p in pages)
        assert total_entities > 0

    def test_health_check(self):
        client = MockVLMClient()
        assert client.health_check() is True

    def test_page_properties(self, tmp_path: Path):
        client = MockVLMClient()
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\ntest\n%%EOF\n")

        pages = client.extract_pages(pdf)
        for page in pages:
            assert 0 <= page.confidence <= 1.0
            assert page.pageIndex >= 0
            assert isinstance(page.headings, list)
            assert isinstance(page.has_tables, bool)
            assert isinstance(page.has_charts, bool)


class TestVLMClientFactory:
    def test_mock_backend(self):
        client = VLMClientFactory.create("mock")
        assert isinstance(client, MockVLMClient)

    def test_invalid_backend_raises(self):
        with pytest.raises(ValueError):
            VLMClientFactory.create("nonexistent_backend")
