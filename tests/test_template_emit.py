"""P1 gate tests: value-free template emission (template.ast / template.blueprint)."""
from __future__ import annotations

from report_builder.template_emit import (
    assert_value_free,
    build_value_free_blueprint,
    build_value_free_skeleton,
    clear_prefilled_slots,
)

# A minimal assembled AST carrying prose + values that MUST be stripped from the skeleton.
_AST = {
    "metadata": {"documentId": "doc_test", "title": "PLFS Test", "version": "3.0"},
    "semanticAST": {"hierarchy": [{"nodeId": "c1", "title": "Worker Population Ratio"}]},
    "contentAST": {
        "paragraphs": [
            {"id": "p1", "type": "paragraph", "content": "In 2023-24 the WPR was 53.4%."},
            {"id": "p2", "type": "heading", "content": "Worker Population Ratio"},
        ]
    },
    "tableAST": {"tables": [{"tableId": "t1", "columns": [{"header": "State"}], "rows": [{"State": "Kerala"}]}]},
    "chartAST": {"charts": [{"chartId": "ch1", "series": [{"label": "WPR", "points": [1, 2]}]}]},
    "figureAST": {"figures": [{"figureId": "f1", "caption": "WPR by sector, 2023-24"}]},
    "factGraph": {"facts": [{"statement": "WPR is 53.4%"}]},
    "extracted_assets": {"text_pages": [{"text": "raw pdf prose"}]},
    "blueprint": {
        "entities": [{"entityId": "e1", "name": "WPR", "entityType": "measure"}],
        "topics": [{"topicId": "tp1", "title": "WPR", "questions": []}],
        "tableStructures": [],
        "documentMap": {"title": "PLFS Test"},
    },
}


def test_skeleton_is_value_free():
    skeleton = build_value_free_skeleton(_AST)
    assert assert_value_free(skeleton, label="template.ast") == []
    paras = skeleton["contentAST"]["paragraphs"]
    assert all(p["content"] == "" for p in paras)
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
    assert "entitiesRejected" in blueprint
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
