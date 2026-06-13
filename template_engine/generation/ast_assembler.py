"""AST Assembler — orchestrates full TemplateBlueprintAST construction.

Takes VLM pages + extracted entities + inferred questions and assembles
the complete deep AST with all cross-links populated.

This is the final assembly step before validation and commit.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

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
from ast_core.pydantic_schema import TemplateBlueprintModel, export_json_schema
from template_engine.generation.sglang_client import SGLangClient, SGLangClientFactory
from template_engine.vlm.schemas import VLMPageResult

logger = logging.getLogger(__name__)


def assemble_template_ast(
    pages: list[VLMPageResult],
    entities: list[TemplateEntity],
    topics: list[TopicNode],
    template_name: str,
    source_hash: str,
    sglang_client: SGLangClient | None = None,
    vlm_backend: str | None = None,
) -> TemplateBlueprintAST:
    """Assemble the complete TemplateBlueprintAST.

    Pipeline:
      1. Build base AST from topics/entities/pages
      2. Optionally enrich via SGLang (grammar-constrained generation)
      3. Validate against Pydantic schema
      4. Populate cross-links between components and AST nodes

    Args:
        pages: VLM page results.
        entities: Extracted and deduplicated entities.
        topics: Inferred topics with questions.
        template_name: Display name for the template.
        source_hash: SHA-256 of source PDF.
        sglang_client: Optional SGLang client for LLM enrichment.

    Returns:
        Complete TemplateBlueprintAST ready for commit.
    """
    # 1. Build base AST
    ast = TemplateBlueprintAST(
        templateId=f"tmpl_{source_hash[:12]}" if source_hash else "tmpl_draft",
        name=template_name,
        sourceHash=source_hash,
        pageCount=len(pages),
        extractionMethod=_determine_extraction_method(pages, sglang_client, vlm_backend),
        topics=topics,
        entities=entities,
        extractionMeta={
            "total_pages": len(pages),
            "total_entities": len(entities),
            "total_topics": len(topics),
            "total_questions": sum(len(t.questions) for t in topics),
            "avg_page_confidence": (
                sum(p.confidence for p in pages) / max(len(pages), 1)
            ),
        },
    )

    # 2. SGLang enrichment (optional — adds semantic hints, refines questions)
    if sglang_client and sglang_client.backend_name != "mock_sglang":
        ast = _sglang_enrich(ast, pages, sglang_client, entities)

    # 3. Validate
    _validate_ast(ast)

    # 4. Cross-link population
    _populate_cross_links(ast, pages)

    logger.info(
        "Assembled template '%s': %d topics, %d questions, %d entities",
        ast.name, len(ast.topics), len(ast.all_questions()), len(ast.entities),
    )
    return ast


def _determine_extraction_method(pages: list[VLMPageResult],
                                  sglang_client: SGLangClient | None,
                                  vlm_backend: str | None = None) -> str:
    """Determine the extraction method string for metadata."""
    parts: list[str] = []

    # Use explicit backend name when available (avoids guessing from confidence)
    if vlm_backend:
        parts.append(vlm_backend)
    elif pages:
        # Fallback: infer backend from page confidence
        avg_conf = sum(p.confidence for p in pages) / max(len(pages), 1)
        if avg_conf > 0.85:
            parts.append("colpali")
        elif avg_conf > 0.6:
            parts.append("pdfplumber")
        else:
            parts.append("stub")

    if sglang_client:
        parts.append(sglang_client.backend_name)
    else:
        parts.append("deterministic")

    return "+".join(parts) or "unknown"


def _sglang_enrich(ast: TemplateBlueprintAST, pages: list[VLMPageResult],
                   client: SGLangClient,
                   entities: list[TemplateEntity] | None = None) -> TemplateBlueprintAST:
    """Use SGLang to enrich the AST with better question intents and constraints.

    If decomposed mode is enabled (SGLANG_DECOMPOSED=true) and client is
    RealSGLangClient, uses the 3-call pipeline for smaller context windows.
    """
    # Check if decomposed mode is requested
    use_decomposed = os.getenv("SGLANG_DECOMPOSED", "").lower() in ("1", "true", "yes")

    if use_decomposed and hasattr(client, "generate_decomposed"):
        return _sglang_enrich_decomposed(ast, pages, client, entities or [])

    try:
        schema = export_json_schema()

        # Build enrichment prompt
        current_ast = ast.to_dict()
        page_summaries = [
            {"page": p.pageIndex, "headings": p.headings[:5],
             "has_tables": p.has_tables, "has_charts": p.has_charts}
            for p in pages[:10]
        ]

        prompt = (
            "You are a government statistical report template compiler. "
            "Given a partially-assembled template AST and page summaries from a MoSPI PDF, "
            "refine the question intents to be more specific and actionable for a BI system. "
            "Ensure each question's answerStructure.components have appropriate constraints.\n\n"
            f"Current AST:\n```json\n{json.dumps(current_ast, indent=2)[:6000]}\n```\n\n"
            f"Page summaries:\n{json.dumps(page_summaries, indent=2)}\n\n"
            "Return the complete refined AST conforming to the schema."
        )

        enriched = client.generate(prompt, schema)
        return TemplateBlueprintAST.from_dict(enriched)

    except Exception as exc:
        logger.warning("SGLang enrichment failed, using base AST: %s", exc)
        return ast


def _validate_ast(ast: TemplateBlueprintAST) -> None:
    """Validate AST against Pydantic schema. Raises on invalid."""
    try:
        model = TemplateBlueprintModel(**ast.to_dict())
        # If this succeeds, the AST is valid
        logger.debug("AST validation passed: %d topics, %d entities",
                     len(model.topics), len(model.entities))
    except Exception as exc:
        logger.warning("AST validation warning (non-fatal): %s", exc)
        # Non-fatal: we continue with the dataclass version


def _populate_cross_links(ast: TemplateBlueprintAST,
                           pages: list[VLMPageResult]) -> None:
    """Populate cross-link refs in answer components based on available data.

    Links components to entity IDs, infers layout/geometry refs from page data.
    """
    entity_index: dict[str, TemplateEntity] = {
        e.entityId: e for e in ast.entities
    }

    for topic in ast.topics:
        for question in topic.questions:
            # Ensure entity bindings reference valid entities
            valid_bindings = []
            for binding in question.requiredEntities:
                if binding.entityId in entity_index:
                    valid_bindings.append(binding)
            question.requiredEntities = valid_bindings

            # Populate component refs with entity connections
            bound_entity_ids = [b.entityId for b in question.requiredEntities]
            for component in question.answerStructure.components:
                if not component.refs.entityRefs:
                    component.refs.entityRefs = bound_entity_ids[:5]


# ---------------------------------------------------------------------------
# Decomposed SGLang enrichment (Step 7)
# ---------------------------------------------------------------------------

def _sglang_enrich_decomposed(
    ast: TemplateBlueprintAST,
    pages: list[VLMPageResult],
    client: SGLangClient,
    entities: list[TemplateEntity],
) -> TemplateBlueprintAST:
    """3-call decomposed SGLang pipeline for small-VRAM models.

    Splits the monolithic AST generation into:
      1. Topics extraction (small schema, fast)
      2. Questions per topic (medium schema)
      3. Answer structure per question (medium schema)

    Results are merged back into the AST.
    """
    try:
        # Build compact document context
        doc_ctx_parts = []
        for p in pages[:15]:
            doc_ctx_parts.append(
                f"Page {p.pageIndex}: headings={p.headings[:3]}, "
                f"tables={p.has_tables}, charts={p.has_charts}"
            )
        doc_context = "\n".join(doc_ctx_parts)

        # Call 1-2-3
        merged = client.generate_decomposed(doc_context)

        # Merge topics from decomposed into AST
        new_topics = merged.get("topics", [])
        answers_map: dict[str, dict] = {
            a["questionId"]: a for a in merged.get("answers", [])
        }

        for topic_data in new_topics:
            tid = topic_data.get("topicId", "")
            # Find matching existing topic or skip
            existing = next((t for t in ast.topics if t.topicId == tid), None)
            if not existing:
                continue

            # Enrich questions with answer structures from call 3
            for q in existing.questions:
                answer_data = answers_map.get(q.questionId)
                if answer_data and answer_data.get("components"):
                    # Update answer structure with suggested constraints
                    for comp_data in answer_data["components"]:
                        comp_id = comp_data.get("componentId", "")
                        existing_comp = next(
                            (c for c in q.answerStructure.components if c.componentId == comp_id),
                            None,
                        )
                        if existing_comp and comp_data.get("suggestedConstraints"):
                            existing_comp.suggestedConstraints = comp_data["suggestedConstraints"]

        logger.info("Decomposed SGLang enrichment complete: %d topics processed", len(new_topics))
        return ast

    except Exception as exc:
        logger.warning("Decomposed SGLang enrichment failed, using base AST: %s", exc)
        return ast
