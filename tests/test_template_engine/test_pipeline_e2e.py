"""End-to-end test of the template engine pipeline with mock backends."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from template_engine.pipeline import run_extraction_pipeline, ExtractionResult


@pytest.fixture
def dummy_pdf(tmp_path: Path) -> Path:
    """Create a minimal dummy PDF file for hashing."""
    pdf = tmp_path / "test_report.pdf"
    # Minimal PDF structure (invalid for rendering, valid for hashing + mock VLM)
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    return pdf


class TestPipelineE2E:
    """Full pipeline tests using mock VLM + mock SGLang."""

    def test_mock_pipeline_produces_valid_ast(self, dummy_pdf: Path):
        """Pipeline with all mocks should produce a valid AST."""
        result = run_extraction_pipeline(
            pdf_path=dummy_pdf,
            template_name="Test MoSPI Report",
            vlm_backend="mock",
            sglang_backend="mock",
        )

        assert result.success
        assert result.ast is not None
        assert result.ast.name == "Test MoSPI Report"
        assert result.source_hash  # non-empty hash
        assert len(result.source_hash) == 64  # SHA-256 hex
        assert result.ast.pageCount > 0
        assert len(result.ast.topics) > 0
        assert len(result.ast.entities) > 0

    def test_mock_pipeline_has_questions(self, dummy_pdf: Path):
        """Pipeline should infer questions from mock VLM data."""
        result = run_extraction_pipeline(
            pdf_path=dummy_pdf,
            template_name="Questions Test",
            vlm_backend="mock",
            sglang_backend="mock",
        )

        assert result.success
        total_questions = sum(len(t.questions) for t in result.ast.topics)
        assert total_questions > 0

    def test_mock_pipeline_progress_tracking(self, dummy_pdf: Path):
        """Progress callback should receive stage updates."""
        stages_seen: list[str] = []

        def track(progress):
            stages_seen.append(progress.stage)

        result = run_extraction_pipeline(
            pdf_path=dummy_pdf,
            template_name="Progress Test",
            vlm_backend="mock",
            sglang_backend="mock",
            progress_callback=track,
        )

        assert result.success
        assert "hashing" in stages_seen
        assert "vlm_parsing" in stages_seen
        assert "entity_extraction" in stages_seen
        assert "complete" in stages_seen

    def test_pipeline_with_nonexistent_pdf(self, tmp_path: Path):
        """Pipeline should handle missing PDF gracefully."""
        fake_path = tmp_path / "does_not_exist.pdf"

        result = run_extraction_pipeline(
            pdf_path=fake_path,
            template_name="Missing PDF",
            vlm_backend="mock",
            sglang_backend="mock",
        )

        # Mock VLM doesn't actually read files, so pipeline may succeed
        # but source_hash should be empty
        assert result.source_hash == ""

    def test_pipeline_extraction_meta(self, dummy_pdf: Path):
        """ExtractionMeta should contain pipeline statistics."""
        result = run_extraction_pipeline(
            pdf_path=dummy_pdf,
            template_name="Meta Test",
            vlm_backend="mock",
            sglang_backend="mock",
        )

        assert result.success
        meta = result.ast.extractionMeta
        assert "total_pages" in meta
        assert "total_entities" in meta
        assert "total_topics" in meta
        assert "total_questions" in meta
        assert meta["total_pages"] > 0


class TestExtractionProgress:
    """Test progress tracking data structure."""

    def test_progress_to_dict(self):
        from template_engine.pipeline import ExtractionProgress
        p = ExtractionProgress(stage="vlm_parsing", progress_pct=30)
        d = p.to_dict()
        assert d["stage"] == "vlm_parsing"
        assert d["progress_pct"] == 30
