"""P1 gate tests: value-free template emission (template.ast / template.blueprint)."""
from __future__ import annotations

from report_builder.template_emit import (
    assert_value_free,
    build_value_free_blueprint,
    build_value_free_skeleton,
    clear_prefilled_slots,
)

# A minimal assembled AST carrying prose + values + a full-document physical-layout
# dump (raw OCR blocks, absolute geometry, 50 raw paragraphs) that MUST be stripped /
# compacted into the gold template shape.
_AST = {
    "metadata": {"documentId": "doc_test", "title": "PLFS Test", "version": "3.0"},
    "semanticAST": {"hierarchy": [
        {"nodeId": "c1", "title": "Worker Population Ratio", "children": [
            {"nodeId": "c1_1", "title": "By sector"},
            {"nodeId": "c1_2", "title": "By state"},
        ]},
        {"nodeId": "c2", "title": "Labour Force Participation"},
    ]},
    "contentAST": {
        "paragraphs": [
            {"id": "p1", "type": "paragraph", "content": "In 2023-24 the WPR was 53.4%."},
            {"id": "p2", "type": "heading", "content": "Worker Population Ratio"},
        ] + [{"id": f"raw_{i}", "type": "paragraph", "content": f"raw prose {i}"} for i in range(50)]
    },
    "tableAST": {"tables": [{"tableId": "t1", "columns": [{"header": "State"}], "rows": [{"State": "Kerala"}]}]},
    "chartAST": {"charts": [{"chartId": "ch1", "series": [{"label": "WPR", "points": [1, 2]}]}]},
    "figureAST": {"figures": [{"figureId": "f1", "caption": "WPR by sector, 2023-24"}]},
    "layoutAST": {"pages": [
        {"pageId": "page_001", "width": 1653, "height": 2339, "blocks": [
            {"blockId": f"b_{i}", "type": "text", "readingOrder": i, "bbox": [10, 20 * i, 80, 20 * i + 10]}
            for i in range(120)
        ]},
    ]},
    "geometryAST": {"nodes": [
        {"nodeId": f"b_{i}", "bbox": {"x": 10, "y": 20 * i, "width": 70, "height": 10}, "pageRef": "page_001"}
        for i in range(120)
    ]},
    "factGraph": {"facts": [{"statement": "WPR is 53.4%"}]},
    "extracted_assets": {"text_pages": [{"text": "raw pdf prose"}]},
    "blueprint": {
        "entities": [{"entityId": "e1", "name": "WPR", "entityType": "measure"}],
        "topics": [{"topicId": "tp1", "title": "WPR", "semanticRef": "c1", "questions": [
            {"questionId": "q1", "intent": "Compare WPR across sector.", "questionType": "comparison",
             "answerStructure": {"components": [
                {"componentId": "q1_c2", "kind": "chart", "refs": {"chartRef": "ch1", "figureRef": "f1"}},
             ]}},
        ]}],
        "tableStructures": [],
        "documentMap": {"title": "PLFS Test"},
        "glossary": [{"term": "WPR", "definition": "Worker Population Ratio"}],
        "palette": {"paletteId": "p", "categorical": ["#111", "#222"], "roles": {"delta_up": "#0f0"}},
        "entitiesRejected": [{"name": "col_5", "reason": "synthetic_placeholder"}],
    },
}


def test_skeleton_is_value_free():
    skeleton = build_value_free_skeleton(_AST)
    assert assert_value_free(skeleton, label="template.ast") == []
    blocks = skeleton["contentAST"]["blocks"]
    assert all(b["content"] == "" for b in blocks)
    assert skeleton["tableAST"]["tables"][0]["rows"] == []
    assert skeleton["chartAST"]["charts"][0]["series"] == []
    assert skeleton["figureAST"]["figures"][0]["caption"] == ""
    assert skeleton["metadata"]["valueFree"] is True


def test_skeleton_keeps_structural_labels():
    skeleton = build_value_free_skeleton(_AST)
    # Section titles and column headers are structure, not values — they must survive.
    assert skeleton["semanticAST"]["hierarchy"][0]["title"] == "Worker Population Ratio"
    assert skeleton["tableAST"]["tables"][0]["columns"][0]["header"] == "State"


def test_skeleton_excludes_value_laden_subtrees():
    skeleton = build_value_free_skeleton(_AST)
    assert "extracted_assets" not in skeleton
    assert skeleton.get("factGraph", {"facts": []})["facts"] == []


def test_blueprint_is_value_free_and_has_envelope():
    blueprint = build_value_free_blueprint(_AST)
    assert assert_value_free(blueprint, label="template.blueprint") == []
    assert blueprint["templateMeta"]["valueFree"] is True
    assert blueprint["templateMeta"]["proseFree"] is True
    # Gold has NO entitiesRejected (diagnostic noise lives in a sidecar now).
    assert "entitiesRejected" not in blueprint
    assert len(blueprint["entities"]) == 1


def test_assert_value_free_flags_violations():
    bad = {
        "contentAST": {"paragraphs": [{"id": "p1", "content": "leaked prose"}]},
        "tableAST": {"tables": [{"tableId": "t1", "rows": [{"x": 1}]}]},
    }
    violations = assert_value_free(bad, label="bad")
    assert len(violations) == 2


def test_clear_prefilled_slots_idempotent():
    skeleton = build_value_free_skeleton(_AST)
    once = assert_value_free(clear_prefilled_slots(skeleton), label="t")
    assert once == []


# ── compaction → gold template shape (durable; runnable without GPU/real data) ──

def test_skeleton_compacted_to_gold_shape():
    """Compaction replaces the raw OCR-block + absolute-geometry dump with logical
    bbox-free regions and a relative flow (gold template.ast shape)."""
    skeleton = build_value_free_skeleton(_AST)
    geo = skeleton["geometryAST"]
    assert "flow" in geo and "nodes" not in geo          # relative, never absolute
    pages = skeleton["layoutAST"]["pages"]
    assert len(pages) == 1 and "blocks" not in pages[0]    # no 120 raw OCR blocks
    regions = pages[0]["regions"]
    assert regions and all(r["bbox"] is None for r in regions)
    headings = {r["bindsTo"] for r in regions if r["role"] == "heading"}
    assert headings == {"c1", "c2"}                       # top-level sections only
    assert geo["flow"] == [r["regionId"] for r in regions]


def test_content_slots_derived_from_questions():
    """contentAST carries one question-wired narrative slot, not the 50 raw paragraphs."""
    skeleton = build_value_free_skeleton(_AST)
    blocks = skeleton["contentAST"]["blocks"]
    assert len(blocks) == 1
    assert blocks[0]["biQuery"] == "q1"
    assert blocks[0]["content"] == ""
    assert blocks[0]["templateQuestion"] == "Compare WPR across sector."
    assert not any(b["blockId"].startswith("raw_") for b in blocks)


def test_blueprint_conforms_to_gold_shape():
    """conform: glossary→dict, palette→gold shape, renderProfile + figureTemplates."""
    bp = build_value_free_blueprint(_AST)
    assert isinstance(bp["glossary"], dict)
    assert bp["glossary"]["WPR"].startswith("Worker")
    assert sorted(bp["palette"].keys()) == ["categorical", "paletteId", "semantic", "sequential"]
    assert isinstance(bp["palette"]["categorical"], dict)
    assert set(bp["renderProfile"]) >= {"numberFormat", "percentFormat", "fontFamily", "pageSize"}
    assert len(bp["figureTemplates"]) == 1 and bp["figureTemplates"][0]["chartId"] == "ch1"


def test_compaction_and_conform_idempotent():
    """Re-applying compaction / conformance changes nothing (safe to run repeatedly)."""
    import copy

    from report_builder.template_emit import compact_skeleton_ast, conform_blueprint

    skeleton = build_value_free_skeleton(_AST)
    again = compact_skeleton_ast(copy.deepcopy(skeleton), _AST["blueprint"]["topics"])
    assert again["geometryAST"]["flow"] == skeleton["geometryAST"]["flow"]
    assert again["layoutAST"] == skeleton["layoutAST"]
    bp = build_value_free_blueprint(_AST)
    assert conform_blueprint(copy.deepcopy(bp)) == bp


# ── chart de-duplication + figure-template synthesis (test 7 regression) ──

def test_is_chart_kind_recognizes_specific_kinds():
    from report_builder.template_emit import _is_chart_kind

    for k in ("chart", "line_chart", "bar_chart", "grouped_bar_chart", "pie_chart",
              "scatter_plot", "geographic_map", "map"):
        assert _is_chart_kind(k), k
    for k in ("data_table", "metric_card", "narrative_paragraph", "", None):
        assert not _is_chart_kind(k), k


def test_dedupe_charts_collapses_speculative_bar_line_pairs():
    """A small VLM echoes bar+line per page (same title, empty series) — merge to one."""
    from report_builder.template_emit import dedupe_charts

    charts = [
        {"chartId": "c2_1", "chartType": "bar_chart", "title": "WPR sustained in 2025", "page": 2, "series": []},
        {"chartId": "c2_2", "chartType": "line_chart", "title": "WPR sustained in 2025", "page": 2, "series": []},
        {"chartId": "c3_1", "chartType": "bar_chart", "title": "Unemployment stable", "page": 3, "series": []},
        {"chartId": "c3_2", "chartType": "line_chart", "title": "Unemployment stable", "page": 3, "series": []},
    ]
    out = dedupe_charts(charts)
    assert len(out) == 2                                   # 4 → 2 (one per page/title)
    assert out[0]["chartTypes"] == ["bar_chart", "line_chart"]


def test_synthesize_figure_templates_matches_specific_chart_kind():
    """A ``line_chart`` component must yield a figure template (was dropped before)."""
    from report_builder.template_emit import synthesize_figure_templates

    bp = {"topics": [{"title": "WPR", "questions": [
        {"questionId": "q1", "intent": "Trend of WPR",
         "answerStructure": {"components": [
             {"componentId": "q1_c1", "kind": "line_chart", "refs": {}},
         ]}},
    ]}]}
    ft = synthesize_figure_templates(bp)
    assert len(ft) == 1 and ft[0]["chartId"] == "q1_c1"


def test_figure_templates_seeded_from_detected_charts():
    """Detected charts surface as figure templates even when no question wires them."""
    ast = {
        "metadata": {"documentId": "doc", "title": "T"},
        "chartAST": {"charts": [
            {"chartId": "ch_a", "chartType": "bar_chart", "title": "A", "page": 1},
            {"chartId": "ch_a2", "chartType": "line_chart", "title": "A", "page": 1},
            {"chartId": "ch_b", "chartType": "pie_chart", "title": "B", "page": 2},
        ]},
        "figureAST": {"figures": [
            {"figureId": "ch_a", "chartId": "ch_a", "type": "chart", "chartType": "bar_chart", "title": "A", "page": 1},
            {"figureId": "ch_a2", "chartId": "ch_a2", "type": "chart", "chartType": "line_chart", "title": "A", "page": 1},
            {"figureId": "ch_b", "chartId": "ch_b", "type": "chart", "chartType": "pie_chart", "title": "B", "page": 2},
        ]},
        "blueprint": {"entities": [], "topics": [], "tableStructures": [], "documentMap": {}},
    }
    bp = build_value_free_blueprint(ast)
    ft = bp["figureTemplates"]
    assert len(ft) == 2                                    # A (bar+line merged) + B
    assert {f["chartId"] for f in ft} == {"ch_a", "ch_b"}


def test_compaction_dedupes_chart_and_figure_asts():
    """Compaction collapses the mirrored bar+line figures so counts reflect reality."""
    import copy

    ast = copy.deepcopy(_AST)
    ast["chartAST"] = {"charts": [
        {"chartId": "c1", "chartType": "bar_chart", "title": "WPR", "page": 2, "series": [1]},
        {"chartId": "c2", "chartType": "line_chart", "title": "WPR", "page": 2, "series": [2]},
    ]}
    ast["figureAST"] = {"figures": [
        {"figureId": "c1", "chartId": "c1", "type": "chart", "chartType": "bar_chart", "title": "WPR", "page": 2},
        {"figureId": "c2", "chartId": "c2", "type": "chart", "chartType": "line_chart", "title": "WPR", "page": 2},
    ]}
    skeleton = build_value_free_skeleton(ast)
    assert len(skeleton["chartAST"]["charts"]) == 1        # 2 → 1
    assert len(skeleton["figureAST"]["figures"]) == 1
    assert skeleton["chartAST"]["charts"][0]["chartTypes"] == ["bar_chart", "line_chart"]


# ── full schema conformance vs gold (test 7 regression: tables/styles/entities/refs) ──

def test_ast_and_blueprint_carry_doc_provenance():
    """Both files must carry the gold top-level ``_doc`` string."""
    skeleton = build_value_free_skeleton(_AST)
    bp = build_value_free_blueprint(_AST)
    assert skeleton["_doc"].startswith("VALUE-FREE render skeleton")
    assert bp["_doc"].startswith("VALUE-FREE + PROSE-FREE")


def test_styleast_backfilled_when_empty():
    """An empty styleAST is backfilled so ``styleRef: s_body`` never dangles."""
    import copy

    ast = copy.deepcopy(_AST)
    ast["styleAST"] = {"styles": []}
    skeleton = build_value_free_skeleton(ast)
    style_ids = {s["styleId"] for s in skeleton["styleAST"]["styles"]}
    assert {"s_h1", "s_body", "s_table", "s_caption"} <= style_ids
    # The per-question content block references s_body — it must now resolve.
    assert skeleton["contentAST"]["blocks"][0]["styleRef"] == "s_body"


def test_semanticast_strips_internal_diagnostics():
    """Internal ``_quality`` diagnostics are not part of the template."""
    import copy

    ast = copy.deepcopy(_AST)
    ast["semanticAST"]["_quality"] = {"score": 0.4, "notes": "noisy"}
    skeleton = build_value_free_skeleton(ast)
    assert "_quality" not in skeleton["semanticAST"]
    assert "hierarchy" in skeleton["semanticAST"]


def test_documentmap_conforms_to_gold_order():
    """Legacy ``{title, chapters}`` documentMap → gold ``{order, frontMatter, backMatter}``."""
    bp = build_value_free_blueprint(_AST)
    dm = bp["documentMap"]
    assert sorted(dm.keys()) == ["backMatter", "frontMatter", "order"]
    assert dm["order"] == ["tp1"]
    assert dm["frontMatter"] == ["title_page", "toc"]


def test_entities_drop_unreferenced_noise_and_backfill_name():
    """``metadata`` scaffolding entities are pruned unless a question needs them."""
    import copy

    ast = copy.deepcopy(_AST)
    ast["blueprint"]["entities"] = [
        {"entityId": "e1", "name": "WPR", "entityType": "measure"},
        {"entityId": "noise_pg", "name": "page 4", "entityType": "metadata"},
        {"entityId": "src_ctx", "name": "source", "entityType": "metadata"},
    ]
    bp = build_value_free_blueprint(ast)
    ids = {e["entityId"] for e in bp["entities"]}
    assert ids == {"e1"}                                   # both metadata noise dropped
    assert all(e.get("canonicalName") for e in bp["entities"])


def test_metadata_entity_kept_when_referenced():
    """A metadata entity referenced by a question must NOT be pruned (no dangling ref)."""
    import copy

    ast = copy.deepcopy(_AST)
    ast["blueprint"]["entities"] = [
        {"entityId": "e1", "name": "WPR", "entityType": "measure"},
        {"entityId": "meta_period", "name": "round", "entityType": "metadata"},
    ]
    ast["blueprint"]["topics"][0]["questions"][0]["requiredEntities"] = [
        {"entityId": "meta_period", "role": "time"},
    ]
    bp = build_value_free_blueprint(ast)
    assert {"e1", "meta_period"} <= {e["entityId"] for e in bp["entities"]}


def test_components_normalized_to_gold_kind_and_refs_wired():
    """Legacy ``{type, renderOrder, constraints, refs:{}}`` → gold ``{kind, order, refs}``."""
    import copy

    ast = copy.deepcopy(_AST)
    ast["blueprint"]["topics"][0]["questions"][0]["answerStructure"]["components"] = [
        {"componentId": "q1_c1", "type": "narrative_paragraph", "renderOrder": 1, "constraints": {}, "refs": {}},
        {"componentId": "q1_c2", "type": "line_chart", "renderOrder": 2, "constraints": {}, "refs": {}},
        {"componentId": "q1_c3", "type": "data_table", "renderOrder": 3, "constraints": {}, "refs": {}},
    ]
    bp = build_value_free_blueprint(ast)
    comps = bp["topics"][0]["questions"][0]["answerStructure"]["components"]
    by_id = {c["componentId"]: c for c in comps}
    # generic kind + specific preserved; legacy keys gone
    assert by_id["q1_c1"]["kind"] == "narrative" and by_id["q1_c1"]["componentKind"] == "narrative_paragraph"
    assert by_id["q1_c2"]["kind"] == "chart"
    assert by_id["q1_c3"]["kind"] == "table"
    assert all("type" not in c and "renderOrder" not in c and "constraints" not in c for c in comps)
    assert all("order" in c and "outputContract" in c for c in comps)
    # deterministic ref wiring
    assert by_id["q1_c1"]["refs"]["contentRef"] == "p_q1"
    assert by_id["q1_c2"]["refs"]["chartRef"] and by_id["q1_c2"]["refs"]["figureRef"]


def test_content_slot_fillfrom_points_at_first_component():
    """Each content block's slot.fillFrom names the question's first component."""
    import copy

    ast = copy.deepcopy(_AST)
    ast["blueprint"]["topics"][0]["questions"][0]["answerStructure"]["components"] = [
        {"componentId": "q1_c1", "type": "narrative_paragraph", "renderOrder": 1, "refs": {}},
    ]
    skeleton = build_value_free_skeleton(ast)
    block = skeleton["contentAST"]["blocks"][0]
    assert block["slot"]["fillFrom"] == "q1_c1"
    assert block["slot"]["status"] == "empty"

