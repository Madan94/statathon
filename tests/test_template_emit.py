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
