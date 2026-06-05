"""Full end-to-end pipeline verification — one pytest test per stage.

Runs the 10-stage verification of the entire template engine pipeline
using only mock backends (no external services required).

Previously lived as tests/verify_full.py (bare script).
Moved here and converted to proper pytest so it is discovered
automatically and failures surface clearly per stage.
"""
from __future__ import annotations

import json
import tempfile
import os
from pathlib import Path

import pytest

from template_engine.observability.tracing import TracingConfig, init_tracing, trace_span

init_tracing(TracingConfig(enabled=False))


@pytest.fixture(scope="module")
def pipeline_pdf(tmp_path_factory) -> str:
    """Minimal PDF written to a temp file (string path — verifies str/Path fix)."""
    p = tmp_path_factory.mktemp("verify") / "full_verify.pdf"
    p.write_bytes(b"%PDF-1.4\nfull verification\n%%EOF\n")
    return str(p)


@pytest.fixture(scope="module")
def pipeline_artifacts(pipeline_pdf):
    """Run all pipeline stages once; share results across tests in this module."""
    from template_engine.vlm.mock_client import MockVLMClient
    from template_engine.extraction.entity_extractor import extract_entities
    from template_engine.extraction.entity_deduplicator import deduplicate_entities
    from template_engine.inference.question_inferrer import infer_questions
    from template_engine.generation.ast_assembler import assemble_template_ast
    from template_engine.review.reviewer import TemplateReviewer
    from template_engine.pipeline import run_extraction_pipeline

    with trace_span("vlm_test") as s:
        pages = MockVLMClient().extract_pages(pipeline_pdf)
        s["page_count"] = len(pages)

    raw = extract_entities(pages)
    entities = deduplicate_entities(raw)
    topics = infer_questions(pages, entities)
    ast = assemble_template_ast(pages, entities, topics, "Full Verify", "hash_abc123")
    review = TemplateReviewer().review(ast)
    pipeline_result = run_extraction_pipeline(
        pipeline_pdf, "Pipeline Entry", vlm_backend="mock", sglang_backend="mock"
    )

    return {
        "pages": pages,
        "raw_entities": raw,
        "entities": entities,
        "topics": topics,
        "ast": ast,
        "review": review,
        "pipeline_result": pipeline_result,
    }


# ── Stage 1: VLM ─────────────────────────────────────────────────────────────

def test_vlm_produces_6_pages(pipeline_artifacts):
    pages = pipeline_artifacts["pages"]
    assert len(pages) == 6, f"Expected 6 pages, got {len(pages)}"


def test_vlm_page_confidence_in_range(pipeline_artifacts):
    for p in pipeline_artifacts["pages"]:
        assert 0.0 <= p.confidence <= 1.0, f"Page {p.pageIndex} confidence out of range"


# ── Stage 2: Entity extraction ───────────────────────────────────────────────

def test_raw_entity_count(pipeline_artifacts):
    assert len(pipeline_artifacts["raw_entities"]) >= 5


def test_deduped_entity_count_less_than_raw(pipeline_artifacts):
    assert len(pipeline_artifacts["entities"]) <= len(pipeline_artifacts["raw_entities"])


def test_deduped_entity_ids_unique(pipeline_artifacts):
    ids = [e.entityId for e in pipeline_artifacts["entities"]]
    assert len(ids) == len(set(ids))


# ── Stage 3: Question inference ──────────────────────────────────────────────

def test_topics_produced(pipeline_artifacts):
    assert len(pipeline_artifacts["topics"]) >= 1


def test_every_topic_has_required_fields(pipeline_artifacts):
    for t in pipeline_artifacts["topics"]:
        assert t.topicId, "topicId is empty"
        assert t.title, "title is empty"


def test_every_question_has_required_fields(pipeline_artifacts):
    for t in pipeline_artifacts["topics"]:
        for q in t.questions:
            assert q.questionId, "questionId empty"
            assert q.intent, "intent empty"
            assert q.inferenceConfidence > 0
            assert q.answerStructure.components, "no components"


# ── Stage 4: AST assembly ────────────────────────────────────────────────────

def test_ast_template_id(pipeline_artifacts):
    ast = pipeline_artifacts["ast"]
    assert ast.templateId == "tmpl_hash_abc123"


def test_ast_topic_and_entity_counts(pipeline_artifacts):
    ast = pipeline_artifacts["ast"]
    assert len(ast.topics) >= 1
    assert len(ast.entities) >= 5


# ── Stage 5: Pydantic validation ─────────────────────────────────────────────

def test_pydantic_validates_ast(pipeline_artifacts):
    from ast_core.pydantic_schema import TemplateBlueprintModel
    model = TemplateBlueprintModel(**pipeline_artifacts["ast"].to_dict())
    assert model.templateId == pipeline_artifacts["ast"].templateId


# ── Stage 6: JSON schema ─────────────────────────────────────────────────────

def test_json_schema_is_valid_json(pipeline_artifacts):
    from ast_core.pydantic_schema import export_json_schema
    schema_str = json.dumps(export_json_schema())
    assert len(schema_str) > 100
    reparsed = json.loads(schema_str)
    assert "properties" in reparsed


# ── Stage 7: Review ───────────────────────────────────────────────────────────

def test_review_decision_is_set(pipeline_artifacts):
    from template_engine.review.reviewer import ReviewDecision
    assert pipeline_artifacts["review"].decision in (
        ReviewDecision.AUTO_PASS, ReviewDecision.APPROVE, ReviewDecision.NEEDS_EDIT
    )


def test_review_confidence_in_range(pipeline_artifacts):
    assert 0.0 <= pipeline_artifacts["review"].confidence_score <= 1.0


# ── Stage 8: AST roundtrip ───────────────────────────────────────────────────

def test_ast_roundtrip_lossless(pipeline_artifacts):
    from ast_core.schema import TemplateBlueprintAST
    ast = pipeline_artifacts["ast"]
    d = ast.to_dict()
    restored = TemplateBlueprintAST.from_dict(d)
    assert restored.templateId == ast.templateId
    assert len(restored.all_questions()) == len(ast.all_questions())
    assert len(json.dumps(d)) > 0


# ── Stage 9: Legacy bridge ───────────────────────────────────────────────────

def test_legacy_bridge_produces_blocks(pipeline_artifacts):
    from report_builder.blueprint import template_from_deep_blueprint
    legacy = template_from_deep_blueprint(pipeline_artifacts["ast"])
    assert len(legacy.blocks) > 0


# ── Stage 10: Pipeline entry point ───────────────────────────────────────────

def test_pipeline_entry_success(pipeline_artifacts):
    r = pipeline_artifacts["pipeline_result"]
    assert r.success
    assert r.ast is not None


def test_pipeline_entry_produces_topics(pipeline_artifacts):
    r = pipeline_artifacts["pipeline_result"]
    assert len(r.ast.topics) >= 1
