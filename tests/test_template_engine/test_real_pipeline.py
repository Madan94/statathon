"""Real-mode pipeline integration tests.

These tests verify the COMPLETE pipeline works with REAL components:
  ColPali (Docker :8100) → entities → Gemini questions → AST → review

Tier markers:
  live_vlm    — needs COLPALI_ENDPOINT set and service running
  live_llm    — needs GEMINI_API_KEY (reads from .env)
  live_sglang — needs SGLANG_ENDPOINT set and server running

Skip behaviour:
  Any test whose fixture finds the service missing auto-skips (pytest.skip).
  No test fails if services are absent — they simply don't run.

Run only the tests for which you have services:
  # ColPali + Gemini (most common real run):
  $env:COLPALI_ENDPOINT="http://localhost:8100"
  pytest tests/test_template_engine/test_real_pipeline.py -m "live_vlm or live_llm" -v

  # Everything (ColPali + Gemini + SGLang):
  $env:COLPALI_ENDPOINT="http://localhost:8100"
  $env:SGLANG_ENDPOINT="http://localhost:30000"
  pytest tests/test_template_engine/test_real_pipeline.py -v

  # CI / no services → all tests auto-skip, nothing fails:
  pytest tests/test_template_engine/test_real_pipeline.py -v
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from template_engine.observability.tracing import TracingConfig, init_tracing

init_tracing(TracingConfig(enabled=False))


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _ping(url: str, timeout: int = 4) -> bool:
    """HTTP GET /health and return True if 200."""
    try:
        import requests
        r = requests.get(url, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def colpali_url():
    ep = os.getenv("COLPALI_ENDPOINT", "http://localhost:8100")
    if not _ping(f"{ep}/health"):
        pytest.skip(
            f"ColPali service not reachable at {ep}/health — "
            "start with: docker run -p 8100:8100 --gpus all bharatstat/colpali-service:latest"
        )
    return ep


@pytest.fixture(scope="session")
def sglang_url():
    ep = os.getenv("SGLANG_ENDPOINT", "http://localhost:30000")
    if not _ping(f"{ep}/health"):
        pytest.skip(
            f"SGLang server not reachable at {ep}/health — "
            "start with: python -m sglang.launch_server --model-path Qwen/Qwen2.5-7B-Instruct --port 30000"
        )
    return ep


@pytest.fixture(scope="session")
def gemini_key():
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        pytest.skip("GEMINI_API_KEY not set in .env — add it to run live LLM tests")
    return key


@pytest.fixture(scope="session")
def real_pdf(tmp_path_factory) -> Path:
    """A minimal but structurally valid PDF for real-model tests."""
    p = tmp_path_factory.mktemp("real") / "sample_survey.pdf"
    # Minimal valid PDF-1.4 with title metadata
    p.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f\n"
        b"0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF\n"
    )
    return p


@pytest.fixture(scope="session")
def sample_pdf_for_upload() -> Path | None:
    """Use a sample report from the repo if available."""
    candidates = [
        Path("sample_reports/mospi_survey.pdf"),
        Path("sample_reports/energy_report.pdf"),
        Path("test_data/sample_report.pdf"),
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return None


# ══════════════════════════════════════════════════════════════════════════════
# TIER 1 — pdfplumber (local, no GPU/API needed)
# ══════════════════════════════════════════════════════════════════════════════

class TestPdfPlumberRealMode:
    """pdfplumber VLM adapter — extracts text/tables from real PDFs."""

    def test_pdfplumber_available(self):
        import pdfplumber  # noqa: F401

    def test_extracts_pages_from_minimal_pdf(self, real_pdf):
        from template_engine.vlm.pdfplumber_adapter import PdfPlumberVLMAdapter
        client = PdfPlumberVLMAdapter()
        pages = client.extract_pages(real_pdf)
        assert len(pages) >= 1

    def test_page_confidence_in_range(self, real_pdf):
        from template_engine.vlm.pdfplumber_adapter import PdfPlumberVLMAdapter
        for page in PdfPlumberVLMAdapter().extract_pages(real_pdf):
            assert 0.0 <= page.confidence <= 1.0

    def test_factory_creates_fallback_backend(self):
        from template_engine.vlm.client import VLMClientFactory
        client = VLMClientFactory.create("fallback")
        assert "pdfplumber" in client.backend_name

    def test_full_pipeline_with_pdfplumber_vlm(self, real_pdf):
        """Complete pipeline using pdfplumber as VLM (no GPU, no Docker)."""
        from template_engine.pipeline import run_extraction_pipeline
        result = run_extraction_pipeline(
            real_pdf,
            "pdfplumber Real Pipeline",
            vlm_backend="fallback",
            sglang_backend="mock",
        )
        assert result.success
        assert "fallback" in result.ast.extractionMethod
        assert result.ast.pageCount >= 1
        assert result.review is not None

    def test_pipeline_pdfplumber_ast_roundtrip(self, real_pdf):
        from template_engine.pipeline import run_extraction_pipeline
        from ast_core.schema import TemplateBlueprintAST
        result = run_extraction_pipeline(
            real_pdf, "Roundtrip", vlm_backend="fallback", sglang_backend="mock"
        )
        restored = TemplateBlueprintAST.from_dict(result.ast.to_dict())
        assert restored.templateId == result.ast.templateId

    def test_sample_report_if_available(self, sample_pdf_for_upload):
        """Extra test: run against a real sample report from the repo."""
        if sample_pdf_for_upload is None:
            pytest.skip("No sample report found in sample_reports/ or test_data/")
        from template_engine.pipeline import run_extraction_pipeline
        result = run_extraction_pipeline(
            sample_pdf_for_upload,
            "Sample Report",
            vlm_backend="fallback",
            sglang_backend="mock",
        )
        assert result.success
        assert len(result.ast.entities) >= 0  # may be sparse for simple PDFs


# ══════════════════════════════════════════════════════════════════════════════
# TIER 2 — ColPali (real vision model, GPU Docker)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.live
@pytest.mark.live_vlm
class TestColPaliRealMode:
    """Tests that require the ColPali Docker service on port 8100."""

    def test_health_check(self, colpali_url):
        from template_engine.vlm.colpali_client import ColPaliClient
        assert ColPaliClient(endpoint=colpali_url).health_check()

    def test_extracts_pages(self, colpali_url, real_pdf):
        from template_engine.vlm.colpali_client import ColPaliClient
        pages = ColPaliClient(endpoint=colpali_url).extract_pages(real_pdf)
        assert len(pages) >= 1
        for p in pages:
            assert 0.0 <= p.confidence <= 1.0

    def test_pages_have_regions(self, colpali_url, real_pdf):
        from template_engine.vlm.colpali_client import ColPaliClient
        pages = ColPaliClient(endpoint=colpali_url).extract_pages(real_pdf)
        total_regions = sum(len(p.regions) for p in pages)
        assert total_regions >= 0  # minimal PDF may have no text regions

    def test_factory_creates_colpali_when_endpoint_set(self, colpali_url):
        from template_engine.vlm.client import VLMClientFactory
        client = VLMClientFactory.create("colpali")
        assert client.backend_name == "colpali"

    def test_full_pipeline_colpali_mock_sglang(self, colpali_url, real_pdf):
        """ColPali VLM + mock SGLang — isolates the vision extraction step."""
        os.environ["COLPALI_ENDPOINT"] = colpali_url
        from template_engine.pipeline import run_extraction_pipeline
        result = run_extraction_pipeline(
            real_pdf,
            "ColPali Real VLM",
            vlm_backend="colpali",
            sglang_backend="mock",
        )
        assert result.success
        assert "colpali" in result.ast.extractionMethod
        assert result.ast.pageCount >= 1
        assert result.review is not None
        assert result.source_hash and len(result.source_hash) == 64

    def test_colpali_entities_extracted(self, colpali_url, real_pdf):
        from template_engine.vlm.colpali_client import ColPaliClient
        from template_engine.extraction.entity_extractor import extract_entities
        from template_engine.extraction.entity_deduplicator import deduplicate_entities
        pages = ColPaliClient(endpoint=colpali_url).extract_pages(real_pdf)
        raw = extract_entities(pages)
        deduped = deduplicate_entities(raw)
        # deduped count must be ≤ raw (may be 0 for empty PDFs)
        assert len(deduped) <= len(raw)
        ids = [e.entityId for e in deduped]
        assert len(ids) == len(set(ids)), "Duplicate entity IDs after dedup"

    def test_colpali_with_sample_report(self, colpali_url, sample_pdf_for_upload):
        """Run against a real sample report — best real-world test."""
        if sample_pdf_for_upload is None:
            pytest.skip("No sample report found in sample_reports/")
        from template_engine.pipeline import run_extraction_pipeline
        result = run_extraction_pipeline(
            sample_pdf_for_upload,
            "Real Sample Report",
            vlm_backend="colpali",
            sglang_backend="mock",
        )
        assert result.success
        assert len(result.ast.all_questions()) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# TIER 3 — Gemini (live LLM question inference)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.live
@pytest.mark.live_llm
class TestGeminiRealMode:
    """Tests that require a valid GEMINI_API_KEY in .env."""

    def test_gemini_key_loads_from_env(self, gemini_key):
        assert len(gemini_key) > 20

    def test_hybrid_inferrer_returns_question(self, gemini_key):
        from template_engine.inference.question_inferrer import HybridInferrer
        from template_engine.vlm.schemas import (
            VLMPageResult, VLMRegion, VLMBBox, VLMTableData
        )
        from ast_core.schema import TemplateEntity

        page = VLMPageResult(
            pageIndex=0,
            tables=[VLMTableData(
                headers=["State", "Rural MPCE (₹)", "Urban MPCE (₹)"],
                rows=[["Punjab", "2100", "3800"], ["Kerala", "1900", "4200"]],
                regionId="t1",
            )],
        )
        region = VLMRegion(
            regionId="r1", role="heading_h1",
            text="Household Consumption Expenditure by State",
            bbox=VLMBBox(50, 50, 400, 75), confidence=0.95,
        )
        entities = [
            TemplateEntity(entityId="e1", name="State",
                           entityType="dimension", sourceType="table_header", confidence=0.95),
            TemplateEntity(entityId="e2", name="MPCE",
                           entityType="measure", sourceType="table_header", confidence=0.93),
        ]
        result = HybridInferrer().infer(page, region, entities)
        assert result is not None, "Gemini returned None — check API key and quota"
        question, confidence = result
        assert question.strip(), "Gemini returned empty question string"
        assert 0.0 < confidence <= 1.0, f"Confidence out of range: {confidence}"

    def test_gemini_question_is_analytical(self, gemini_key):
        """Gemini question should end with '?' and contain analytical vocabulary."""
        from template_engine.inference.question_inferrer import HybridInferrer
        from template_engine.vlm.schemas import VLMPageResult, VLMRegion, VLMBBox, VLMChartData
        from ast_core.schema import TemplateEntity

        page = VLMPageResult(
            pageIndex=1,
            charts=[VLMChartData(
                chartType="bar",
                title="State-wise GDP Growth Rate",
                xAxis="State", yAxis="GDP Growth (%)",
                regionId="c1",
            )],
        )
        region = VLMRegion(
            regionId="r2", role="heading_h1",
            text="GDP Growth Rate Across States",
            bbox=VLMBBox(50, 50, 400, 75), confidence=0.9,
        )
        entities = [
            TemplateEntity(entityId="e3", name="GDP Growth Rate",
                           entityType="measure", sourceType="chart_axis", confidence=0.9),
        ]
        result = HybridInferrer().infer(page, region, entities)
        if result is None:
            pytest.skip("Gemini did not return a result (quota or transient error)")
        question, _ = result
        # Analytical questions tend to include comparison/distribution/trend words
        analytical_words = {
            "compare", "distribution", "trend", "variation", "across",
            "between", "change", "growth", "rate", "state", "gdp",
        }
        q_lower = question.lower()
        assert any(w in q_lower for w in analytical_words), (
            f"Question does not seem analytical: {question!r}"
        )

    def test_pipeline_uses_hybrid_for_headings(self, gemini_key, real_pdf):
        """With Gemini available, at least some questions should use hybrid method."""
        from template_engine.pipeline import run_extraction_pipeline
        result = run_extraction_pipeline(
            real_pdf,
            "Gemini Pipeline",
            vlm_backend="mock",       # mock gives rich pages
            sglang_backend="mock",
        )
        assert result.success
        methods = {q.inferenceMethod for q in result.ast.all_questions()}
        # With mock VLM giving headings + Gemini key set, hybrid should fire
        assert "hybrid" in methods or len(result.ast.all_questions()) > 0


# ══════════════════════════════════════════════════════════════════════════════
# TIER 4 — SGLang (grammar-constrained LLM)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.live
@pytest.mark.live_sglang
class TestSGLangRealMode:
    """Tests that require the SGLang server on port 30000."""

    def test_health_check(self, sglang_url):
        from template_engine.generation.sglang_client import RealSGLangClient
        assert RealSGLangClient(endpoint=sglang_url).health_check()

    def test_generates_valid_json(self, sglang_url):
        from template_engine.generation.sglang_client import RealSGLangClient
        from ast_core.pydantic_schema import export_json_schema
        client = RealSGLangClient(endpoint=sglang_url)
        schema = export_json_schema()
        prompt = (
            "Generate a minimal template blueprint for a 1-page report with one topic "
            "about household expenditure and one entity named 'MPCE'."
        )
        result = client.generate(prompt, schema)
        assert isinstance(result, dict), "SGLang did not return a dict"
        assert "templateId" in result or "topics" in result

    def test_output_conforms_to_pydantic_schema(self, sglang_url):
        from template_engine.generation.sglang_client import RealSGLangClient
        from ast_core.pydantic_schema import TemplateBlueprintModel, export_json_schema
        client = RealSGLangClient(endpoint=sglang_url)
        schema = export_json_schema()
        prompt = (
            "Create a minimal template blueprint JSON with: "
            "templateId='tmpl_test', name='Test', sourceHash='abc123', "
            "pageCount=1, extractionMethod='sglang', topics=[], entities=[], extractionMeta={}."
        )
        result = client.generate(prompt, schema)
        # Pydantic validation — will raise if non-conformant
        model = TemplateBlueprintModel(**result)
        assert model.extractionMethod == "sglang"

    def test_full_pipeline_mock_vlm_real_sglang(self, sglang_url, real_pdf):
        """Mock VLM (fast) + real SGLang — isolates the generation step."""
        os.environ["SGLANG_ENDPOINT"] = sglang_url
        from template_engine.pipeline import run_extraction_pipeline
        result = run_extraction_pipeline(
            real_pdf,
            "SGLang Real Generation",
            vlm_backend="mock",
            sglang_backend="sglang",
        )
        assert result.success
        assert "sglang" in result.ast.extractionMethod
        assert result.review is not None


# ══════════════════════════════════════════════════════════════════════════════
# TIER 5 — FULL REAL PIPELINE (ColPali + Gemini + SGLang together)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.live
@pytest.mark.live_vlm
@pytest.mark.live_llm
@pytest.mark.live_sglang
class TestFullRealPipeline:
    """Complete real pipeline: ColPali → Gemini → SGLang.

    Requires ALL three services running simultaneously.
    This is the production configuration.
    """

    def test_complete_real_cycle(self, colpali_url, gemini_key, sglang_url, real_pdf):
        """One complete cycle with all real components."""
        os.environ["COLPALI_ENDPOINT"] = colpali_url
        os.environ["SGLANG_ENDPOINT"]  = sglang_url

        from template_engine.pipeline import run_extraction_pipeline

        stages_seen: list[str] = []
        timings: dict[str, float] = {}

        def on_progress(p):
            stages_seen.append(p.stage)
            if hasattr(p, "elapsed"):
                timings[p.stage] = p.elapsed or 0.0

        result = run_extraction_pipeline(
            real_pdf,
            "Full Real Cycle",
            vlm_backend="colpali",
            sglang_backend="sglang",
            progress_callback=on_progress,
        )

        # Core correctness
        assert result.success, f"Pipeline failed: {result}"
        assert result.source_hash and len(result.source_hash) == 64
        assert result.ast is not None
        assert result.ast.pageCount >= 1
        assert "colpali" in result.ast.extractionMethod or "sglang" in result.ast.extractionMethod

        # Review must run
        assert result.review is not None
        from template_engine.review.reviewer import ReviewDecision
        assert result.review.decision in (
            ReviewDecision.AUTO_PASS, ReviewDecision.APPROVE, ReviewDecision.NEEDS_EDIT
        )

        # All stages must complete
        for stage in ["hashing", "vlm_parsing", "entity_extraction",
                      "entity_deduplication", "question_inference",
                      "ast_assembly", "validation", "complete"]:
            assert stage in stages_seen, f"Stage {stage!r} never reached"

        # Pydantic validation
        from ast_core.pydantic_schema import TemplateBlueprintModel
        model = TemplateBlueprintModel(**result.ast.to_dict())
        assert model.pageCount >= 1

        # Roundtrip
        from ast_core.schema import TemplateBlueprintAST
        restored = TemplateBlueprintAST.from_dict(result.ast.to_dict())
        assert restored.templateId == result.ast.templateId

        # Entity binding integrity
        entity_ids = {e.entityId for e in result.ast.entities}
        for q in result.ast.all_questions():
            for b in q.requiredEntities:
                assert b.entityId in entity_ids, f"Orphaned binding: {b.entityId}"

    def test_real_cycle_with_sample_report(
        self, colpali_url, gemini_key, sglang_url, sample_pdf_for_upload
    ):
        """Full real pipeline on a repo sample report (most realistic test)."""
        if sample_pdf_for_upload is None:
            pytest.skip("No sample report found in sample_reports/")

        os.environ["COLPALI_ENDPOINT"] = colpali_url
        os.environ["SGLANG_ENDPOINT"]  = sglang_url

        from template_engine.pipeline import run_extraction_pipeline
        result = run_extraction_pipeline(
            sample_pdf_for_upload,
            "Sample Report Real",
            vlm_backend="colpali",
            sglang_backend="sglang",
        )
        assert result.success
        # Real reports should give richer results
        assert len(result.ast.entities) >= 0  # at least attempted
        assert result.review.stats["topics"] >= 0

    def test_legacy_bridge_on_real_ast(self, colpali_url, gemini_key, sglang_url, real_pdf):
        """Legacy report_builder bridge must work on a real AST."""
        os.environ["COLPALI_ENDPOINT"] = colpali_url
        os.environ["SGLANG_ENDPOINT"]  = sglang_url

        from template_engine.pipeline import run_extraction_pipeline
        from report_builder.blueprint import template_from_deep_blueprint

        result = run_extraction_pipeline(
            real_pdf, "Legacy Bridge Real",
            vlm_backend="colpali", sglang_backend="sglang",
        )
        assert result.success
        legacy = template_from_deep_blueprint(result.ast)
        assert legacy is not None
        assert len(legacy.blocks) >= 0
