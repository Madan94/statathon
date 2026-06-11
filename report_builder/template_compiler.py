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
    # I4: Question Reconciliation + Compilation (QX1)
    # ═══════════════════════════════════════════════════════════════════════════
    logger.info("[template-compiler] I4: Question reconciliation + compilation")

    from report_builder.question_compiler import compile_questions

    # QX1: Build entity ref map (old → new) for question repair
    valid_entity_ids = {e.get("entityId") or "" for e in bp["entities"] if e.get("entityId")}
    ref_map = _build_entity_ref_map(raw_entities, bp["entities"])

    # QX1: Filter/repair existing old questions
    old_questions: list[dict[str, Any]] = []
    for topic in (bp.get("topics") or []):
        old_questions.extend(topic.get("questions") or [])

    kept_questions, dropped_questions, repair_log = _filter_or_repair_existing_questions(
        old_questions, ref_map, valid_entity_ids,
    )
    intermediate["question_reconciliation"] = {
        "old_count": len(old_questions),
        "kept": len(kept_questions),
        "dropped": len(dropped_questions),
        "repaired": sum(1 for r in repair_log if r.get("repaired")),
    }

    logger.info(
        "[template-compiler] QX1: %d old questions → %d kept, %d dropped, %d repaired",
        len(old_questions), len(kept_questions), len(dropped_questions),
        sum(1 for r in repair_log if r.get("repaired")),
    )

    # QX1: Replace old questions with kept/repaired only
    for topic in (bp.get("topics") or []):
        topic["questions"] = []
    if kept_questions and bp.get("topics"):
        bp["topics"][0]["questions"] = kept_questions

    # E7: Generate deterministic new questions
    # Detect doc_type from blueprint metadata or document_map
    _doc_type = "statistical_annual_report"
    _bp_meta = bp.get("templateMeta") or {}
    if _bp_meta.get("reportType") == "pib_press_release" or _bp_meta.get("domain") == "labour_force":
        _doc_type = "pib_press_release"
    elif document_map and document_map.get("doc_type"):
        _doc_type = document_map["doc_type"]

    # Collect section headings for PIB question matcher
    _section_headings: list[str] = []
    for topic in (bp.get("topics") or []):
        t = topic.get("title") or ""
        if t:
            _section_headings.append(t)

    question_result = compile_questions(
        tables=table_result.tables if table_result else None,
        entities=enrichment_result.entities,
        measure_families=norm_result.measureFamilies,
        figures=chart_result.figures if chart_result else None,
        doc_type=_doc_type,
        section_headings=_section_headings,
    )
    intermediate["questions"] = question_result.to_dict()

    # Merge: deterministic new questions + kept old questions (dedup)
    compiled_q_dicts = [q.to_dict() for q in question_result.questions]
    existing_q_ids = {q.get("questionId") or "" for q in kept_questions}
    new_questions = [q for q in compiled_q_dicts if q.get("questionId") not in existing_q_ids]

    # Assign all questions to topics
    all_final_questions = kept_questions + new_questions
    if bp.get("topics"):
        bp["topics"][0]["questions"] = all_final_questions
    else:
        bp["topics"] = [{"topicId": "topic_compiled", "title": "Compiled Questions", "questions": all_final_questions}]

    logger.info("[template-compiler] I4 done: %d final questions (%d kept + %d new)",
                len(all_final_questions), len(kept_questions), len(new_questions))

    # ═══════════════════════════════════════════════════════════════════════════
    # I5: Slot Wiring + Validation + Diagnostics
    # ═══════════════════════════════════════════════════════════════════════════
    logger.info("[template-compiler] I5: Wiring + validation + diagnostics")

    from report_builder.slot_wiring import wire_template, iter_questions as _iter_qs
    from report_builder.value_free_validator import validate_value_free
    from report_builder.extraction_contracts import validate_extraction_contract, ExtractionMode
    from report_builder.extraction_diagnostics import build_extraction_diagnostics

    # QX1 cleanup: Remove skeleton slots that reference dropped/non-existent questions
    final_question_ids = {q.get("questionId") or "" for q in _iter_qs(bp)}
    skeleton = _clean_orphan_slots(skeleton, final_question_ids)

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


def _clean_orphan_slots(skeleton: dict[str, Any], valid_question_ids: set[str]) -> dict[str, Any]:
    """Remove skeleton slots whose biQuery references non-existent questions.

    This fixes orphaned slots left over when old broken questions are dropped.
    """
    # Clean contentAST blocks
    content = skeleton.get("contentAST") or {}
    blocks = content.get("blocks") or content.get("paragraphs") or []
    content_key = "blocks" if "blocks" in content else "paragraphs"
    cleaned_blocks = [b for b in blocks if not b.get("biQuery") or b.get("biQuery") in valid_question_ids]
    if content_key in content:
        content[content_key] = cleaned_blocks

    # Clean tableAST tables
    table_ast = skeleton.get("tableAST") or {}
    tables = table_ast.get("tables") or []
    table_ast["tables"] = [t for t in tables if not t.get("biQuery") or t.get("biQuery") in valid_question_ids]

    # Clean chartAST charts
    chart_ast = skeleton.get("chartAST") or {}
    charts = chart_ast.get("charts") or []
    chart_ast["charts"] = [c for c in charts if not c.get("biQuery") or c.get("biQuery") in valid_question_ids]

    # Clean figureAST figures (keep figures without biQuery)
    figure_ast = skeleton.get("figureAST") or {}
    figures = figure_ast.get("figures") or []
    figure_ast["figures"] = [f for f in figures if not f.get("biQuery") or f.get("biQuery") in valid_question_ids]

    return skeleton


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


# ─────────────────────────────────────────────────────────────────────────────
# QX1: Question Reconciliation Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _build_entity_ref_map(old_entities: list[dict[str, Any]], new_entities: list[dict[str, Any]]) -> dict[str, str]:
    """Map old entity IDs to new semantic IDs using name/alias matching.

    Returns: {old_id: new_id} for entities that can be mapped.
    """
    import re

    ref_map: dict[str, str] = {}

    # Build new entity lookup by name/alias
    new_by_name: dict[str, str] = {}
    new_by_alias: dict[str, str] = {}
    for ne in new_entities:
        nid = ne.get("entityId") or ""
        nname = (ne.get("canonicalName") or "").lower().strip()
        if nname and nid:
            new_by_name[nname] = nid
        for alias in (ne.get("aliases") or []):
            if alias:
                new_by_alias[alias.lower().strip()] = nid

    # Try to map each old entity
    for old_ent in old_entities:
        old_id = old_ent.get("entityId") or ""
        if not old_id:
            continue
        old_name = (old_ent.get("canonicalName") or "").lower().strip()

        # Already semantic (not ent_0XX)? Skip mapping
        if not re.match(r'^ent_\d{2,}$', old_id):
            if old_id in {ne.get("entityId") for ne in new_entities}:
                ref_map[old_id] = old_id
            continue

        # Try exact name match
        if old_name in new_by_name:
            ref_map[old_id] = new_by_name[old_name]
            continue

        # Try normalized name (remove year, normalize spaces)
        norm_name = re.sub(r'\s*(19|20)\d{2}(-\d{2,4})?\s*', '', old_name).strip()
        norm_name = re.sub(r'\s+', ' ', norm_name).strip()
        if norm_name in new_by_name:
            ref_map[old_id] = new_by_name[norm_name]
            continue

        # Try alias match
        if old_name in new_by_alias:
            ref_map[old_id] = new_by_alias[old_name]
            continue

        # Try first word match for short entities
        first_word = old_name.split()[0] if old_name.split() else ""
        if first_word and len(first_word) >= 4:
            for nname, nid in new_by_name.items():
                if nname.startswith(first_word) or first_word in nname:
                    ref_map[old_id] = nid
                    break

    return ref_map


def _repair_question_entity_refs(
    question: dict[str, Any],
    ref_map: dict[str, str],
    valid_entity_ids: set[str],
) -> tuple[dict[str, Any], bool, list[str]]:
    """Rewrite entity references in a question using ref_map.

    Returns (repaired_question, was_repaired, still_broken_refs).
    """
    import copy
    q = copy.deepcopy(question)
    repaired = False
    broken: list[str] = []

    # Repair requiredEntities
    for req in (q.get("requiredEntities") or []):
        eid = req.get("entityId") or req.get("entityRef") or ""
        if eid and eid not in valid_entity_ids:
            if eid in ref_map:
                req["entityId"] = ref_map[eid]
                if "entityRef" in req:
                    req["entityRef"] = ref_map[eid]
                repaired = True
            else:
                broken.append(eid)

    # Repair analyticsSpec refs
    spec = q.get("analyticsSpec") or {}
    _repair_spec_refs(spec, ref_map, valid_entity_ids, broken)
    if spec:
        q["analyticsSpec"] = spec

    return q, repaired, broken


def _repair_spec_refs(spec: dict[str, Any], ref_map: dict[str, str], valid: set[str], broken: list[str]):
    """In-place repair of entity refs in analyticsSpec."""
    # measure.entityRef
    measure = spec.get("measure")
    if isinstance(measure, dict) and measure.get("entityRef"):
        ref = measure["entityRef"]
        if ref not in valid:
            if ref in ref_map:
                measure["entityRef"] = ref_map[ref]
            else:
                broken.append(ref)

    # measures[].entityRef
    for m in (spec.get("measures") or []):
        if isinstance(m, dict) and m.get("entityRef"):
            ref = m["entityRef"]
            if ref not in valid:
                if ref in ref_map:
                    m["entityRef"] = ref_map[ref]
                else:
                    broken.append(ref)

    # groupBy[].entityRef
    for g in (spec.get("groupBy") or []):
        if isinstance(g, dict) and g.get("entityRef"):
            ref = g["entityRef"]
            if ref not in valid:
                if ref in ref_map:
                    g["entityRef"] = ref_map[ref]
                else:
                    broken.append(ref)

    # filters[].entityRef
    for f in (spec.get("filters") or []):
        if isinstance(f, dict) and f.get("entityRef"):
            ref = f["entityRef"]
            if ref not in valid:
                if ref in ref_map:
                    f["entityRef"] = ref_map[ref]
                else:
                    broken.append(ref)


def _filter_or_repair_existing_questions(
    questions: list[dict[str, Any]],
    ref_map: dict[str, str],
    valid_entity_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Filter or repair existing questions. Drop those with unresolvable refs.

    Returns (kept, dropped, repair_log).
    """
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    repair_log: list[dict[str, Any]] = []

    for q in questions:
        qid = q.get("questionId") or ""

        # Try repair
        repaired_q, was_repaired, still_broken = _repair_question_entity_refs(q, ref_map, valid_entity_ids)

        if still_broken:
            # Cannot fix — drop
            dropped.append({"questionId": qid, "reason": f"broken_refs: {still_broken[:3]}", "broken_count": len(still_broken)})
            repair_log.append({"questionId": qid, "repaired": False, "broken": still_broken[:3]})
        else:
            # All refs resolved (either already valid or remapped)
            kept.append(repaired_q)
            repair_log.append({"questionId": qid, "repaired": was_repaired})

    return kept, dropped, repair_log
