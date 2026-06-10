"""Template Compiler Wrapper (I0-I5).

Orchestrates E1-E12 compiler modules on existing extraction output to produce
improved binder-ready template artifacts.

Isolated from extraction_pipeline.py — can run standalone on saved outputs
for testing before pipeline integration (I6).

Usage:
    from report_builder.template_compiler import compile_template_artifacts
    result = compile_template_artifacts(raw_ast=ast, blueprint=bp)
    print(result["diagnostics"].binderReadinessScore)
"""
from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)


def compile_template_artifacts(
    *,
    raw_ast: dict[str, Any],
    blueprint: dict[str, Any],
    layout_pages: list[Any] | None = None,
    page_texts: list[str] | None = None,
    table_candidates: list[dict[str, Any]] | None = None,
    figure_candidates: list[dict[str, Any]] | None = None,
    document_map: dict[str, Any] | None = None,
    runtime_config: Any | None = None,
) -> dict[str, Any]:
    """Run the full compiler pipeline on existing extraction output.

    Steps (I1-I5):
    1. Entity hygiene + IDs + normalization + enrichment
    2. Table semantic compilation
    3. Chart semantic compilation
    4. Question compilation (deterministic)
    5. Slot wiring + value-free validation + contract + diagnostics

    Args:
        raw_ast: Existing template.ast.json dict.
        blueprint: Existing template.blueprint.json dict.
        table_candidates: Optional raw table dicts for E3.
        figure_candidates: Optional raw figure dicts for E11.
        page_texts: Optional per-page text for context extraction.
        document_map: Optional document structure for topic context.
        runtime_config: Optional RuntimeConfig for diagnostics.

    Returns:
        Dict with keys: template_ast, template_blueprint, diagnostics, intermediate
    """
    # Work on copies to avoid mutating input
    skeleton = copy.deepcopy(raw_ast)
    bp = copy.deepcopy(blueprint)

    intermediate: dict[str, Any] = {}

    # ═══════════════════════════════════════════════════════════════════════════
    # I1: Entity Compiler
    # ═══════════════════════════════════════════════════════════════════════════
    logger.info("[template-compiler] I1: Entity compilation")

    from report_builder.entity_hygiene import run_entity_hygiene
    from report_builder.entity_id_generator import generate_entity_id
    from report_builder.entity_normalizer import normalize_entities
    from report_builder.entity_enrichment import enrich_entities

    raw_entities = bp.get("entities") or []

    # E1: Hygiene
    hygiene_result = run_entity_hygiene(raw_entities)
    intermediate["hygiene"] = hygiene_result.to_dict()

    # E5: Assign semantic IDs
    for ent in hygiene_result.entities:
        ent.entityId = generate_entity_id(ent.canonicalName, ent.entityType)

    # E2: Normalize (merge year-suffixed, detect families)
    norm_result = normalize_entities(hygiene_result.entities)
    intermediate["normalization"] = norm_result.to_dict()

    # E6: Enrich (aliases, valueDomain, aggregation)
    enrichment_result = enrich_entities(
        norm_result.entities,
        measure_families=norm_result.measureFamilies,
        domain=bp.get("templateMeta", {}).get("domain") or "",
    )
    intermediate["enrichment"] = enrichment_result.to_dict()

    # Replace blueprint entities with enriched result
    bp["entities"] = [_entity_to_dict(e) for e in enrichment_result.entities]

    # Add measure families
    if norm_result.measureFamilies:
        bp["measureFamilies"] = [f.to_dict() for f in norm_result.measureFamilies]

    # Route topics from hygiene
    if hygiene_result.topics and not bp.get("topics"):
        bp["topics"] = [{"topicId": f"topic_{i}", "title": t["title"], "questions": []} for i, t in enumerate(hygiene_result.topics)]

    logger.info(
        "[template-compiler] I1 done: %d entities → %d clean (families=%d)",
        len(raw_entities), len(enrichment_result.entities), len(norm_result.measureFamilies),
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # I2: Table Compiler
    # ═══════════════════════════════════════════════════════════════════════════
    logger.info("[template-compiler] I2: Table compilation")

    from report_builder.table_semantic_compiler import compile_tables
    from report_builder.statistical_context_extractor import build_statistical_context

    # Use provided table candidates, or derive from existing tableTemplates/tableAST
    if table_candidates:
        table_result = compile_tables(table_candidates)
    else:
        # Derive minimal candidates from existing blueprint tableTemplates
        existing_tables = bp.get("tableTemplates") or bp.get("tableStructures") or []
        derived_candidates = []
        for tt in existing_tables:
            derived_candidates.append({
                "tableId": tt.get("tableId") or tt.get("tableTemplateId") or "",
                "title": tt.get("tableTitle") or tt.get("title") or "",
                "page": (tt.get("source") or {}).get("page") or tt.get("page") or 0,
                "row_count": 10,
                "col_count": len(tt.get("columns") or []) or 5,
                "filled_cells": 50,
                # Pass header info if available
                "header_rows": [],
            })
        table_result = compile_tables(derived_candidates) if derived_candidates else None

    intermediate["tables"] = table_result.to_dict() if table_result else {"tableCount": 0}

    # E4: Statistical context
    doc_info = {
        "sourceDocument": bp.get("templateMeta", {}).get("sourceDocument") or bp.get("templateMeta", {}).get("name") or "",
        "domain": bp.get("templateMeta", {}).get("domain") or "",
    }
    stat_ctx = build_statistical_context(
        doc_info,
        table_models=table_result.tables if table_result else None,
        page_texts=page_texts,
    )
    intermediate["context"] = stat_ctx.to_dict()

    # Add statistical context to blueprint if not present
    if not bp.get("statisticalContext"):
        bp["statisticalContext"] = {
            "sourceDocument": stat_ctx.sourceDocument,
            "domain": stat_ctx.domain,
        }

    logger.info("[template-compiler] I2 done: tables=%d context_units=%d",
                len(table_result.tables) if table_result else 0, len(stat_ctx.unitRegistry))

    # ═══════════════════════════════════════════════════════════════════════════
    # I3: Chart Compiler
    # ═══════════════════════════════════════════════════════════════════════════
    logger.info("[template-compiler] I3: Chart compilation")

    from report_builder.chart_semantic_compiler import compile_figure_semantics

    # Use provided figure candidates, or derive from existing
    if figure_candidates:
        chart_result = compile_figure_semantics(figure_candidates, entities=enrichment_result.entities)
    else:
        # Derive from existing figureTemplates or figureAST
        existing_figs = bp.get("figureTemplates") or []
        fig_candidates = []
        for ft in existing_figs:
            fig_candidates.append({
                "figureId": ft.get("figureTemplateId") or ft.get("figureId") or "",
                "caption": ft.get("chartSubject") or ft.get("captionTemplate") or "",
                "chartType": ft.get("chartType") or "",
                "page": ft.get("page"),
            })
        # Also check figureAST
        for fig in (skeleton.get("figureAST") or {}).get("figures") or []:
            fig_candidates.append({
                "figureId": fig.get("figureId") or "",
                "caption": fig.get("caption") or "",
                "page": fig.get("page"),
            })
        chart_result = compile_figure_semantics(fig_candidates, entities=enrichment_result.entities) if fig_candidates else None

    intermediate["charts"] = chart_result.to_dict() if chart_result else {"figureCount": 0}

    # Update figureTemplates if chart compiler produced better models
    if chart_result and chart_result.figures:
        bp["figureTemplates"] = [f.to_dict() for f in chart_result.figures]

    logger.info("[template-compiler] I3 done: charts=%d", len(chart_result.figures) if chart_result else 0)

    # ═══════════════════════════════════════════════════════════════════════════
    # I4: Question Compiler
    # ═══════════════════════════════════════════════════════════════════════════
    logger.info("[template-compiler] I4: Question compilation")

    from report_builder.question_compiler import compile_questions

    question_result = compile_questions(
        tables=table_result.tables if table_result else None,
        entities=enrichment_result.entities,
        measure_families=norm_result.measureFamilies,
        figures=chart_result.figures if chart_result else None,
    )
    intermediate["questions"] = question_result.to_dict()

    # Merge questions into blueprint topics
    if question_result.questions:
        compiled_q_dicts = [q.to_dict() for q in question_result.questions]

        # If topics exist, add to first topic; otherwise create one
        if bp.get("topics"):
            # Add compiled questions to first topic (or distribute later)
            existing_q_ids = set()
            for topic in bp["topics"]:
                for q in (topic.get("questions") or []):
                    existing_q_ids.add(q.get("questionId") or "")

            new_questions = [q for q in compiled_q_dicts if q.get("questionId") not in existing_q_ids]
            if new_questions:
                bp["topics"][0].setdefault("questions", []).extend(new_questions)
        else:
            bp["topics"] = [{"topicId": "topic_compiled", "title": "Compiled Questions", "questions": compiled_q_dicts}]

    logger.info("[template-compiler] I4 done: questions=%d", len(question_result.questions))

    # ═══════════════════════════════════════════════════════════════════════════
    # I5: Slot Wiring + Validation + Diagnostics
    # ═══════════════════════════════════════════════════════════════════════════
    logger.info("[template-compiler] I5: Wiring + validation + diagnostics")

    from report_builder.slot_wiring import wire_template
    from report_builder.value_free_validator import validate_value_free
    from report_builder.extraction_contracts import validate_extraction_contract, ExtractionMode
    from report_builder.extraction_diagnostics import build_extraction_diagnostics

    # Wire slots
    wiring_result = wire_template(skeleton, bp, auto_repair=True)
    skeleton = wiring_result.skeleton
    intermediate["wiring"] = wiring_result.to_dict()

    # Value-free validation
    vf_result = validate_value_free(skeleton, bp)

    # Contract validation
    contract_result = validate_extraction_contract(bp, mode=ExtractionMode.WARN)

    # Build diagnostics
    diagnostics = build_extraction_diagnostics(
        blueprint=bp,
        skeleton=skeleton,
        contract_result=contract_result,
        value_free_result=vf_result,
        hygiene_result=hygiene_result,
        normalization_result=norm_result,
        table_result=table_result,
        statistical_context=stat_ctx,
        enrichment_result=enrichment_result,
        chart_result=chart_result,
        question_result=question_result,
        wiring_result=wiring_result,
        runtime_config=runtime_config,
    )

    logger.info(
        "[template-compiler] I5 done: status=%s score=%.3f contract=%s valueFree=%s",
        diagnostics.status, diagnostics.binderReadinessScore,
        contract_result.status, vf_result.status,
    )

    return {
        "template_ast": skeleton,
        "template_blueprint": bp,
        "diagnostics": diagnostics,
        "intermediate": intermediate,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _entity_to_dict(entity: Any) -> dict[str, Any]:
    """Convert a SemanticEntity/NormalizedEntity to blueprint entity dict."""
    if hasattr(entity, "to_dict"):
        return entity.to_dict()
    if isinstance(entity, dict):
        return entity
    # Manual conversion for dataclass-like objects
    d: dict[str, Any] = {}
    for attr in ("entityId", "canonicalName", "entityType", "aliases", "unit", "format",
                 "valueDomain", "aggregation", "scope", "confidence", "isTotal", "isDerived",
                 "cardinalityHint", "familyRef", "normalizationHints"):
        val = getattr(entity, attr, None)
        if val is not None and val != "" and val != [] and val != {}:
            d[attr] = val
    return d
