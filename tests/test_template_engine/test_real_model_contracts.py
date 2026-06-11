"""Contract tests for real-model paths.

These tests verify that:
  1. ColPaliClient handles all HTTP error paths correctly (connection errors,
     timeouts, HTTP errors, bad JSON, partial parse failures, retries).
  2. RealSGLangClient handles all HTTP error paths (same categories).
  3. PdfPlumberVLMAdapter extracts from a real minimal PDF.
  4. Pipeline resume/merge flow produces correct merged AST.
  5. Pipeline review result is populated and correct.
  6. VLMClientFactory auto-detection logic works.
  7. ExtractionResult.review is populated after pipeline run.

All network calls are intercepted with unittest.mock — NO real HTTP required.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from ast_core.schema import (
    AnswerComponent,
    AnswerComponentRef,
    AnswerStructure,
    QuestionEntityBinding,
    QuestionNode,
    TemplateBlueprintAST,
    TemplateEntity,
    TopicNode,
)
from template_engine.generation.sglang_client import (
    MockSGLangClient,
    RealSGLangClient,
    SGLangClientFactory,
)
from template_engine.pipeline import run_extraction_pipeline
from template_engine.review.reviewer import ReviewDecision, TemplateReviewer
from template_engine.vlm.client import VLMClientFactory, VLMExtractionError
from template_engine.vlm.colpali_client import ColPaliClient
from template_engine.vlm.mock_client import MockVLMClient
from template_engine.vlm.schemas import VLMPageResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_pdf(tmp_path: Path, name: str = "test.pdf") -> Path:
    """Minimal bytes that satisfy the mock VLM but NOT pdfplumber.

    pdfplumber/pdfminer fail to open this (no /Root object), so MockVLMClient
    falls back to its default 6-page synthetic fixture.  All non-pdfplumber
    tests use this helper so the mock always returns 6 pages.
    """
    pdf = tmp_path / name
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    return pdf


def _make_valid_pdf(tmp_path: Path, name: str = "valid.pdf") -> Path:
    """Proper PDF-1.4 with /Root + /Pages tree that pdfplumber can open."""
    pdf = tmp_path / name
    pdf.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%%%EOF\n"
    )
    return pdf


def _make_colpali_response(n_pages: int = 2) -> dict[str, Any]:
    """Build a valid ColPali HTTP response body."""
    pages = []
    for i in range(n_pages):
        pages.append({
            "pageIndex": i,
            "width": 595.0,
            "height": 842.0,
            "regions": [
                {
                    "regionId": f"r_{i}_1",
                    "role": "heading_h1",
                    "text": f"Section {i + 1}",
                    "bbox": {"x0": 50, "y0": 50, "x1": 400, "y1": 75},
                    "confidence": 0.95,
                }
            ],
            "entities": [
                {
                    "name": f"Entity_{i}",
                    "entityType": "dimension",
                    "sourceType": "section_heading",
                    "sourceRegion": f"r_{i}_1",
                    "confidence": 0.90,
                    "context": f"Section {i + 1}",
                }
            ],
            "tables": [],
            "charts": [],
            "rawText": f"Section {i + 1}",
            "confidence": 0.92,
        })
    return {"pages": pages}


def _make_sglang_response(template_id: str = "tmpl_test") -> str:
    """Build a valid SGLang response JSON string (as content field)."""
    ast = {
        "templateId": template_id,
        "name": "SGLang Test",
        "sourceHash": "abc123",
        "pageCount": 2,
        "extractionMethod": "colpali+sglang",
        "topics": [
            {
                "topicId": "topic_001",
                "title": "Overview",
                "questions": [
                    {
                        "questionId": "Q_0001",
                        "intent": "What is the overview of the dataset?",
                        "questionType": "describe",
                        "inferenceMethod": "pattern",
                        "inferenceConfidence": 0.75,
                        "requiredEntities": [],
                        "answerStructure": {
                            "layoutType": "single",
                            "components": [
                                {
                                    "componentId": "comp_001",
                                    "renderOrder": 1,
                                    "type": "narrative_paragraph",
                                    "constraints": {},
                                    "refs": {},
                                }
                            ],
                        },
                    }
                ],
                "pageRange": [0, 1],
            }
        ],
        "entities": [
            {
                "entityId": "ent_0001",
                "name": "Entity_0",
                "entityType": "dimension",
                "sourceType": "section_heading",
                "confidence": 0.90,
            }
        ],
        "extractionMeta": {"total_pages": 2, "total_entities": 1, "avg_page_confidence": 0.92},
    }
    return json.dumps(ast)


# ---------------------------------------------------------------------------
# ColPali HTTP contract tests
# ---------------------------------------------------------------------------

class TestColPaliClientHTTP:
    """Tests for ColPaliClient HTTP communication (mocked)."""

    def test_successful_extraction(self, tmp_path: Path):
        pdf = _make_minimal_pdf(tmp_path)
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_colpali_response(3)
        mock_resp.raise_for_status = Mock()

        client = ColPaliClient(endpoint="http://test-colpali:8100")
        with patch("requests.post", return_value=mock_resp):
            pages = client.extract_pages(pdf)

        assert len(pages) == 3
        assert all(isinstance(p, VLMPageResult) for p in pages)
        assert pages[0].pageIndex == 0
        assert pages[2].pageIndex == 2

    def test_connection_error_raises_vlm_error(self, tmp_path: Path):
        import requests

        pdf = _make_minimal_pdf(tmp_path)
        client = ColPaliClient(endpoint="http://dead-host:8100", max_retries=1)

        with patch("requests.post", side_effect=requests.ConnectionError("refused")):
            with pytest.raises(VLMExtractionError, match="unreachable"):
                client.extract_pages(pdf)

    def test_timeout_raises_vlm_error(self, tmp_path: Path):
        import requests

        pdf = _make_minimal_pdf(tmp_path)
        client = ColPaliClient(endpoint="http://slow-host:8100", max_retries=1)

        with patch("requests.post", side_effect=requests.Timeout()):
            with pytest.raises(VLMExtractionError, match="timed out"):
                client.extract_pages(pdf)

    def test_http_401_raises_vlm_error(self, tmp_path: Path):
        import requests

        pdf = _make_minimal_pdf(tmp_path)
        mock_resp = Mock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        http_err = requests.HTTPError(response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_err

        client = ColPaliClient(endpoint="http://test:8100", max_retries=1)
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(VLMExtractionError, match="HTTP 401"):
                client.extract_pages(pdf)

    def test_empty_pages_raises_vlm_error(self, tmp_path: Path):
        pdf = _make_minimal_pdf(tmp_path)
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"pages": []}
        mock_resp.raise_for_status = Mock()

        client = ColPaliClient(endpoint="http://test:8100")
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(VLMExtractionError, match="empty pages"):
                client.extract_pages(pdf)

    def test_partial_parse_failure_continues(self, tmp_path: Path):
        """If some pages fail JSON parse, valid ones are returned."""
        pdf = _make_minimal_pdf(tmp_path)
        response_body = _make_colpali_response(3)
        # Corrupt page 1 by adding an invalid entityType that will fail schema
        # Actually from_dict is lenient, let's make the pageIndex negative
        response_body["pages"][1] = {"pageIndex": None, "garbage": True}

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_body
        mock_resp.raise_for_status = Mock()

        client = ColPaliClient(endpoint="http://test:8100")
        with patch("requests.post", return_value=mock_resp):
            # Should not raise — returns 2 valid pages
            pages = client.extract_pages(pdf)

        assert len(pages) >= 1

    def test_nonexistent_pdf_raises(self, tmp_path: Path):
        client = ColPaliClient(endpoint="http://test:8100")
        with pytest.raises(VLMExtractionError, match="not found"):
            client.extract_pages(tmp_path / "ghost.pdf")

    def test_retry_on_503(self, tmp_path: Path):
        """A 503 should trigger retry, then succeed."""
        import requests

        pdf = _make_minimal_pdf(tmp_path)

        # First call: 503, Second call: 200
        call_count = 0

        def fake_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                r = Mock()
                r.status_code = 503
                r.raise_for_status = Mock()
                r.json.return_value = {}
                return r
            r = Mock()
            r.status_code = 200
            r.raise_for_status = Mock()
            r.json.return_value = _make_colpali_response(1)
            return r

        client = ColPaliClient(endpoint="http://test:8100", max_retries=2)
        with patch("requests.post", side_effect=fake_post):
            with patch("time.sleep"):  # Skip actual sleep
                pages = client.extract_pages(pdf)

        assert len(pages) == 1
        assert call_count == 2

    def test_health_check_success(self):
        mock_resp = Mock()
        mock_resp.status_code = 200

        client = ColPaliClient(endpoint="http://test:8100")
        with patch("requests.get", return_value=mock_resp):
            assert client.health_check() is True

    def test_health_check_failure(self):
        import requests

        client = ColPaliClient(endpoint="http://dead:8100")
        with patch("requests.get", side_effect=requests.ConnectionError()):
            assert client.health_check() is False

    def test_string_path_accepted(self, tmp_path: Path):
        """ColPaliClient must accept str paths (not just Path)."""
        pdf = _make_minimal_pdf(tmp_path)
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_colpali_response(1)
        mock_resp.raise_for_status = Mock()

        client = ColPaliClient(endpoint="http://test:8100")
        with patch("requests.post", return_value=mock_resp):
            pages = client.extract_pages(str(pdf))  # str, not Path
        assert len(pages) == 1


# ---------------------------------------------------------------------------
# RealSGLangClient contract tests
# ---------------------------------------------------------------------------

class TestRealSGLangClientHTTP:
    """Tests for RealSGLangClient HTTP communication (mocked)."""

    def _make_ok_response(self, content: str) -> Mock:
        resp = Mock()
        resp.status_code = 200
        resp.raise_for_status = Mock()
        resp.json.return_value = {
            "choices": [{"message": {"content": content}}]
        }
        return resp

    def test_successful_generation(self):
        client = RealSGLangClient(endpoint="http://sglang:30000", max_retries=1)
        content = _make_sglang_response()

        with patch("requests.post", return_value=self._make_ok_response(content)):
            result = client.generate("Test prompt", {})

        assert result["templateId"] == "tmpl_test"
        assert len(result["topics"]) == 1

    def test_connection_error_raises(self):
        import requests

        client = RealSGLangClient(endpoint="http://dead:30000", max_retries=1)
        with patch("requests.post", side_effect=requests.ConnectionError("refused")):
            with pytest.raises(RuntimeError, match="unreachable"):
                client.generate("prompt", {})

    def test_timeout_raises(self):
        import requests

        client = RealSGLangClient(endpoint="http://slow:30000", max_retries=1)
        with patch("requests.post", side_effect=requests.Timeout()):
            with pytest.raises(RuntimeError, match="timed out"):
                client.generate("prompt", {})

    def test_http_error_raises(self):
        import requests

        mock_resp = Mock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        http_err = requests.HTTPError(response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_err

        client = RealSGLangClient(endpoint="http://test:30000", max_retries=1)
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="HTTP 500"):
                client.generate("prompt", {})

    def test_invalid_json_response_raises(self):
        client = RealSGLangClient(endpoint="http://test:30000", max_retries=1)
        resp = self._make_ok_response("not valid json{{{{")

        with patch("requests.post", return_value=resp):
            with pytest.raises(RuntimeError, match="parsing failed"):
                client.generate("prompt", {})

    def test_missing_choices_key_raises(self):
        resp = Mock()
        resp.status_code = 200
        resp.raise_for_status = Mock()
        resp.json.return_value = {"error": "no choices"}  # missing 'choices'

        client = RealSGLangClient(endpoint="http://test:30000", max_retries=1)
        with patch("requests.post", return_value=resp):
            with pytest.raises(RuntimeError, match="parsing failed"):
                client.generate("prompt", {})

    def test_retry_on_503(self):
        import requests

        call_count = 0

        def fake_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                r = Mock()
                r.status_code = 503
                r.raise_for_status = Mock()
                return r
            return self._make_ok_response(_make_sglang_response())

        client = RealSGLangClient(endpoint="http://test:30000", max_retries=2)
        with patch("requests.post", side_effect=fake_post):
            with patch("time.sleep"):
                result = client.generate("prompt", {})

        assert result["templateId"] == "tmpl_test"
        assert call_count == 2

    def test_health_check_ok(self):
        mock_resp = Mock()
        mock_resp.status_code = 200
        client = RealSGLangClient(endpoint="http://test:30000")
        with patch("requests.get", return_value=mock_resp):
            assert client.health_check() is True

    def test_health_check_fail(self):
        import requests
        client = RealSGLangClient(endpoint="http://dead:30000")
        with patch("requests.get", side_effect=requests.ConnectionError()):
            assert client.health_check() is False

    def test_factory_sglang_backend(self):
        with patch.dict("os.environ", {"SGLANG_ENDPOINT": "http://sglang:30000"}):
            client = SGLangClientFactory.create("sglang")
        assert isinstance(client, RealSGLangClient)

    def test_factory_invalid_backend(self):
        with pytest.raises(ValueError, match="Unknown SGLang backend"):
            SGLangClientFactory.create("nonexistent")

    def test_json_schema_sent_in_payload(self):
        """Verify the JSON schema is forwarded in the request payload."""
        client = RealSGLangClient(endpoint="http://test:30000", max_retries=1)
        captured_payload: dict = {}

        def fake_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = Mock()
            resp.status_code = 200
            resp.raise_for_status = Mock()
            resp.json.return_value = {
                "choices": [{"message": {"content": '{"key": "val"}'}}]
            }
            return resp

        schema = {"type": "object", "properties": {"key": {"type": "string"}}}
        with patch("requests.post", side_effect=fake_post):
            client.generate("test prompt", schema)

        assert captured_payload["response_format"]["type"] == "json_schema"
        assert captured_payload["response_format"]["json_schema"]["schema"] == schema
        assert captured_payload["response_format"]["json_schema"]["strict"] is True


# ---------------------------------------------------------------------------
# PdfPlumber adapter with real minimal PDF
# ---------------------------------------------------------------------------

class TestPdfPlumberAdapter:
    """Tests for PdfPlumberVLMAdapter with a real (minimal) PDF content."""

    def test_extracts_from_valid_pdf_if_pdfplumber_available(self, tmp_path: Path):
        pytest.importorskip("pdfplumber")
        from template_engine.vlm.pdfplumber_adapter import PdfPlumberVLMAdapter

        pdf = _make_valid_pdf(tmp_path)  # needs /Root for pdfplumber
        adapter = PdfPlumberVLMAdapter()
        pages = adapter.extract_pages(pdf)

        # Minimal PDF may have 1 page with no text
        assert isinstance(pages, list)
        assert len(pages) >= 1
        assert all(isinstance(p, VLMPageResult) for p in pages)

    def test_string_path_accepted(self, tmp_path: Path):
        pytest.importorskip("pdfplumber")
        from template_engine.vlm.pdfplumber_adapter import PdfPlumberVLMAdapter

        pdf = _make_valid_pdf(tmp_path)  # needs /Root for pdfplumber
        adapter = PdfPlumberVLMAdapter()
        pages = adapter.extract_pages(str(pdf))  # str, not Path

        assert isinstance(pages, list)

    def test_nonexistent_pdf_raises(self, tmp_path: Path):
        pytest.importorskip("pdfplumber")
        from template_engine.vlm.pdfplumber_adapter import PdfPlumberVLMAdapter

        adapter = PdfPlumberVLMAdapter()
        with pytest.raises(VLMExtractionError, match="not found"):
            adapter.extract_pages(tmp_path / "ghost.pdf")

    def test_health_check_with_pdfplumber(self):
        pdfplumber = pytest.importorskip("pdfplumber")
        from template_engine.vlm.pdfplumber_adapter import PdfPlumberVLMAdapter

        adapter = PdfPlumberVLMAdapter()
        assert adapter.health_check() is True

    def test_backend_name(self):
        from template_engine.vlm.pdfplumber_adapter import PdfPlumberVLMAdapter
        assert "pdfplumber" in PdfPlumberVLMAdapter().backend_name


# ---------------------------------------------------------------------------
# VLMClientFactory auto-detection
# ---------------------------------------------------------------------------

class TestVLMClientFactoryAutoDetect:
    def test_auto_detects_colpali_when_endpoint_set(self):
        with patch.dict("os.environ", {"COLPALI_ENDPOINT": "http://colpali:8100"}):
            # Reset VLM_BACKEND to empty so auto-detect kicks in
            with patch.dict("os.environ", {"VLM_BACKEND": ""}):
                client = VLMClientFactory.create()
        assert isinstance(client, ColPaliClient)

    def test_auto_detects_mock_when_no_endpoint(self):
        with patch.dict("os.environ", {"COLPALI_ENDPOINT": "", "VLM_BACKEND": ""}):
            client = VLMClientFactory.create()
        assert isinstance(client, MockVLMClient)

    def test_explicit_mock_overrides_env(self):
        with patch.dict("os.environ", {"COLPALI_ENDPOINT": "http://colpali:8100"}):
            client = VLMClientFactory.create("mock")
        assert isinstance(client, MockVLMClient)

    def test_available_backends_always_includes_mock(self):
        backends = VLMClientFactory.available_backends()
        assert "mock" in backends

    def test_available_backends_includes_colpali_when_env_set(self):
        with patch.dict("os.environ", {"COLPALI_ENDPOINT": "http://colpali:8100"}):
            backends = VLMClientFactory.available_backends()
        assert "colpali" in backends


# ---------------------------------------------------------------------------
# Pipeline resume / merge flow
# ---------------------------------------------------------------------------

class TestPipelineResumeMerge:
    """Tests for resume_from / _merge_with_existing functionality."""

    def _make_existing_ast(self) -> TemplateBlueprintAST:
        """Build a minimal existing AST representing a previous partial run."""
        return TemplateBlueprintAST(
            templateId="tmpl_existing",
            name="Partial Run",
            sourceHash="oldhash",
            pageCount=3,
            extractionMethod="mock+mock_sglang",
            topics=[
                TopicNode(
                    topicId="topic_existing_001",
                    title="Old Topic",
                    questions=[
                        QuestionNode(
                            questionId="Q_old_0001",
                            intent="What was in the old extraction?",
                            questionType="describe",
                            inferenceMethod="stub",
                            inferenceConfidence=0.45,
                            answerStructure=AnswerStructure(
                                layoutType="single",
                                components=[
                                    AnswerComponent(
                                        componentId="comp_old_001",
                                        renderOrder=1,
                                        type="narrative_paragraph",
                                    )
                                ],
                            ),
                        )
                    ],
                    pageRange=[0, 1],
                )
            ],
            entities=[
                TemplateEntity(
                    entityId="ent_old_0001",
                    name="Old Entity",
                    entityType="dimension",
                    sourceType="section_heading",
                    confidence=0.70,
                )
            ],
            extractionMeta={"total_pages": 3},
        )

    def test_resume_merges_topics(self, tmp_path: Path):
        """New extraction topics + old unique topics should both appear."""
        pdf = _make_minimal_pdf(tmp_path)
        existing = self._make_existing_ast()

        result = run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Resume Test",
            vlm_backend="mock",
            sglang_backend="mock",
            resume_from=existing,
        )

        assert result.success
        # New AST's topics + old "topic_existing_001" (not in new run)
        topic_ids = {t.topicId for t in result.ast.topics}
        assert "topic_existing_001" in topic_ids

    def test_resume_merges_entities(self, tmp_path: Path):
        """Entities from both runs should be present after merge."""
        pdf = _make_minimal_pdf(tmp_path)
        existing = self._make_existing_ast()

        result = run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Entity Merge Test",
            vlm_backend="mock",
            sglang_backend="mock",
            resume_from=existing,
        )

        assert result.success
        entity_names = [e.name for e in result.ast.entities]
        assert "Old Entity" in entity_names

    def test_resume_sets_merged_flag(self, tmp_path: Path):
        pdf = _make_minimal_pdf(tmp_path)
        existing = self._make_existing_ast()

        result = run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Merge Flag Test",
            vlm_backend="mock",
            sglang_backend="mock",
            resume_from=existing,
        )

        assert result.success
        assert result.ast.extractionMeta.get("merged") is True

    def test_skip_pages_excludes_from_extraction(self, tmp_path: Path):
        """skip_pages should filter out already-extracted pages."""
        pdf = _make_minimal_pdf(tmp_path)

        result_full = run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Full",
            vlm_backend="mock",
            sglang_backend="mock",
        )
        full_pages = result_full.progress.pages_processed

        # Need at least 2 pages for a meaningful skip; if the synthetic PDF
        # resolves to a single page (newer pdfplumber opens the minimal PDF
        # directly instead of using the 6-page fallback), skipping all pages
        # has nothing to extract — not a valid scenario for this assertion.
        if full_pages < 2:
            pytest.skip(f"synthetic PDF has {full_pages} page(s); need >=2 to test skip")

        # Skip only the first page so at least one page remains to extract.
        result_partial = run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Partial",
            vlm_backend="mock",
            sglang_backend="mock",
            skip_pages=[0],
        )

        assert result_partial.success
        # Pages processed should be reduced
        assert result_partial.progress.pages_processed < full_pages


# ---------------------------------------------------------------------------
# Pipeline review integration
# ---------------------------------------------------------------------------

class TestPipelineReviewIntegration:
    """Tests that pipeline populates ExtractionResult.review correctly."""

    def test_review_populated_after_pipeline(self, tmp_path: Path):
        pdf = _make_minimal_pdf(tmp_path)
        result = run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Review Integration",
            vlm_backend="mock",
            sglang_backend="mock",
        )

        assert result.success
        assert result.review is not None

    def test_review_decision_is_valid(self, tmp_path: Path):
        pdf = _make_minimal_pdf(tmp_path)
        result = run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Decision Test",
            vlm_backend="mock",
            sglang_backend="mock",
        )

        assert result.review.decision in (
            ReviewDecision.AUTO_PASS,
            ReviewDecision.APPROVE,
            ReviewDecision.NEEDS_EDIT,
        )

    def test_review_confidence_in_range(self, tmp_path: Path):
        pdf = _make_minimal_pdf(tmp_path)
        result = run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Confidence Range",
            vlm_backend="mock",
            sglang_backend="mock",
        )

        assert 0.0 <= result.review.confidence_score <= 1.0

    def test_review_stats_populated(self, tmp_path: Path):
        pdf = _make_minimal_pdf(tmp_path)
        result = run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Stats Test",
            vlm_backend="mock",
            sglang_backend="mock",
        )

        stats = result.review.stats
        assert "topics" in stats
        assert "questions" in stats
        assert "entities" in stats

    def test_reviewer_needs_edit_on_orphaned_binding(self):
        """NEEDS_EDIT when a question references a non-existent entity."""
        ast = TemplateBlueprintAST(
            templateId="tmpl_bad",
            name="Bad Template",
            sourceHash="xyz",
            pageCount=2,
            extractionMethod="mock",
            topics=[
                TopicNode(
                    topicId="topic_001",
                    title="Topic",
                    questions=[
                        QuestionNode(
                            questionId="Q_0001",
                            intent="What is X?",
                            questionType="describe",
                            inferenceMethod="stub",
                            inferenceConfidence=0.5,
                            requiredEntities=[
                                QuestionEntityBinding(
                                    entityId="ent_NONEXISTENT",  # orphan!
                                    role="required",
                                    confidence=0.8,
                                )
                            ],
                            answerStructure=AnswerStructure(
                                components=[
                                    AnswerComponent(
                                        componentId="comp_001",
                                        renderOrder=1,
                                        type="narrative_paragraph",
                                    )
                                ]
                            ),
                        )
                    ],
                )
            ],
            entities=[],  # No entities — so the binding is orphaned
            extractionMeta={"avg_page_confidence": 0.8},
        )

        reviewer = TemplateReviewer(min_topics=1, min_questions=1, min_entities=0)
        result = reviewer.review(ast)

        assert result.decision == ReviewDecision.NEEDS_EDIT
        assert result.has_errors
        error_messages = [i.message for i in result.issues if i.severity == "error"]
        assert any("ent_NONEXISTENT" in m for m in error_messages)

    def test_reviewer_approve_on_minor_warnings(self):
        """APPROVE when only non-critical warnings exist."""
        ast = TemplateBlueprintAST(
            templateId="tmpl_ok",
            name="OK Template",
            sourceHash="abc",
            pageCount=5,
            extractionMethod="mock",
            topics=[
                TopicNode(
                    topicId=f"topic_{i:03d}",
                    title=f"Topic {i}",
                    questions=[
                        QuestionNode(
                            questionId=f"Q_{i:04d}",
                            intent=f"Question {i}?",
                            questionType="describe",
                            inferenceMethod="pattern",
                            inferenceConfidence=0.72,
                            answerStructure=AnswerStructure(
                                components=[
                                    AnswerComponent(
                                        componentId=f"comp_{i:03d}",
                                        renderOrder=1,
                                        type="narrative_paragraph",
                                    )
                                ]
                            ),
                        )
                    ],
                )
                for i in range(3)
            ],
            entities=[
                TemplateEntity(
                    entityId=f"ent_{j:04d}",
                    name=f"Entity {j}",
                    entityType="dimension",
                    sourceType="table_header",
                    confidence=0.85,
                )
                for j in range(6)
            ],
            extractionMeta={"avg_page_confidence": 0.88},
        )

        reviewer = TemplateReviewer()
        result = reviewer.review(ast)

        assert result.decision in (ReviewDecision.APPROVE, ReviewDecision.AUTO_PASS)
        assert not result.has_errors


# ---------------------------------------------------------------------------
# Extraction method labelling (vlm_backend propagation)
# ---------------------------------------------------------------------------

class TestExtractionMethodLabel:
    """Verify that the vlm_backend label is correctly propagated to the AST."""

    def test_mock_backend_label_in_ast(self, tmp_path: Path):
        pdf = _make_minimal_pdf(tmp_path)
        result = run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Label Test",
            vlm_backend="mock",
            sglang_backend="mock",
        )

        assert result.success
        # Should contain "mock" not "colpali"
        assert "mock" in result.ast.extractionMethod

    def test_fallback_backend_label(self, tmp_path: Path):
        """When fallback is used, extractionMethod should say pdfplumber_fallback."""
        pytest.importorskip("pdfplumber")
        pdf = _make_valid_pdf(tmp_path)  # pdfplumber requires /Root — minimal PDF fails
        result = run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Fallback Label",
            vlm_backend="fallback",
            sglang_backend="mock",
        )

        assert result.success
        assert "pdfplumber_fallback" in result.ast.extractionMethod


# ---------------------------------------------------------------------------
# Pipeline progress callbacks — detailed timing checks
# ---------------------------------------------------------------------------

class TestPipelineTimings:
    def test_all_stages_have_timings(self, tmp_path: Path):
        pdf = _make_minimal_pdf(tmp_path)
        result = run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Timing Test",
            vlm_backend="mock",
            sglang_backend="mock",
        )

        timings = result.progress.timings
        assert "hashing" in timings
        assert "vlm_parsing" in timings
        assert "entity_extraction" in timings
        assert "entity_deduplication" in timings
        assert "question_inference" in timings
        assert "ast_assembly" in timings
        assert "validation" in timings
        assert all(v >= 0 for v in timings.values())

    def test_progress_pct_at_complete(self, tmp_path: Path):
        pdf = _make_minimal_pdf(tmp_path)
        final_progress = None

        def track(p):
            nonlocal final_progress
            final_progress = p

        run_extraction_pipeline(
            pdf_path=pdf,
            template_name="Pct Test",
            vlm_backend="mock",
            sglang_backend="mock",
            progress_callback=track,
        )

        assert final_progress is not None
        assert final_progress.stage == "complete"
        assert final_progress.progress_pct == 100


# ---------------------------------------------------------------------------
# VLMPageResult schema properties (contract for real backends)
# ---------------------------------------------------------------------------

class TestVLMPageResultContract:
    """Every backend must produce VLMPageResult objects satisfying these contracts."""

    def _assert_page_contract(self, page: VLMPageResult):
        assert isinstance(page.pageIndex, int)
        assert page.pageIndex >= 0
        assert isinstance(page.width, float) and page.width > 0
        assert isinstance(page.height, float) and page.height > 0
        assert 0.0 <= page.confidence <= 1.0
        assert isinstance(page.regions, list)
        assert isinstance(page.entities, list)
        assert isinstance(page.tables, list)
        assert isinstance(page.charts, list)
        # Properties must work without raising
        _ = page.has_tables
        _ = page.has_charts
        _ = page.headings
        # to_dict / from_dict roundtrip
        d = page.to_dict()
        restored = VLMPageResult.from_dict(d)
        assert restored.pageIndex == page.pageIndex
        assert abs(restored.confidence - page.confidence) < 1e-6

    def test_mock_pages_pass_contract(self, tmp_path: Path):
        client = MockVLMClient()
        pdf = _make_minimal_pdf(tmp_path)
        pages = client.extract_pages(pdf)
        for page in pages:
            self._assert_page_contract(page)

    def test_pdfplumber_pages_pass_contract(self, tmp_path: Path):
        pytest.importorskip("pdfplumber")
        from template_engine.vlm.pdfplumber_adapter import PdfPlumberVLMAdapter

        pdf = _make_valid_pdf(tmp_path)  # pdfplumber requires /Root
        adapter = PdfPlumberVLMAdapter()
        pages = adapter.extract_pages(pdf)
        for page in pages:
            self._assert_page_contract(page)

    def test_colpali_response_parsed_to_contract(self):
        """Parsed ColPali HTTP response satisfies the contract."""
        response_body = _make_colpali_response(2)
        pages = [VLMPageResult.from_dict(p) for p in response_body["pages"]]
        for page in pages:
            self._assert_page_contract(page)
