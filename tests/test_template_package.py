from __future__ import annotations

import json

from report_builder.slot_wiring import build_semantic_slot_graph, wire_template
from report_builder.template_package import (
    build_template_package_manifest,
    load_template_package,
    write_template_package,
)


def _sample_artifacts():
    skeleton = {
        "metadata": {"templateId": "tpl_test", "name": "Test Template", "version": "1.2.0", "valueFree": True},
        "contentAST": {"blocks": []},
        "tableAST": {"tables": []},
        "chartAST": {"charts": []},
        "figureAST": {"figures": []},
    }
    blueprint = {
        "templateMeta": {"templateId": "tpl_test", "name": "Test Template", "version": "1.2.0", "domain": "test", "valueFree": True},
        "entities": [{"entityId": "ent_lfpr", "canonicalName": "LFPR", "entityType": "measure"}],
        "topics": [{
            "topicId": "topic_labour",
            "title": "Labour",
            "questions": [{
                "questionId": "q_lfpr",
                "intent": "Summarize LFPR.",
                "answerStructure": {"components": [{"componentId": "comp_lfpr_text", "kind": "narrative"}]},
            }],
        }],
    }
    return skeleton, blueprint


def test_semantic_slot_graph_persists_component_wiring():
    skeleton, blueprint = _sample_artifacts()
    wiring = wire_template(skeleton, blueprint, auto_repair=True)
    graph = build_semantic_slot_graph(wiring.skeleton, blueprint, wiring)

    data = graph.to_dict()
    assert data["$schema"] == "bharatstat/semantic-slot-graph/v1"
    assert data["templateId"] == "tpl_test"
    assert data["counts"]["semanticSlots"] == 1
    slot = data["slots"][0]
    assert slot["topicId"] == "topic_labour"
    assert slot["questionId"] == "q_lfpr"
    assert slot["componentId"] == "comp_lfpr_text"
    assert slot["source"] == "auto_created"


def test_template_package_manifest_hashes_artifacts():
    skeleton, blueprint = _sample_artifacts()
    wiring = wire_template(skeleton, blueprint, auto_repair=True)
    graph = build_semantic_slot_graph(wiring.skeleton, blueprint, wiring).to_dict()
    manifest = build_template_package_manifest(
        template_ast=wiring.skeleton,
        template_blueprint=blueprint,
        semantic_slot_graph=graph,
        diagnostics={"status": "VALID", "binderReadinessScore": 0.91},
        runtime_trace={"totalCalls": 2, "fallbackCalls": 1},
    )
    data = manifest.to_dict()

    assert data["$schema"] == "bharatstat/template-package/v1"
    assert data["templateId"] == "tpl_test"
    assert data["status"] == "VALID"
    assert data["extractionScore"] == 0.91
    assert data["artifacts"]["templateAst"]["hash"]
    assert data["artifacts"]["templateBlueprint"]["hash"]
    assert data["artifacts"]["semanticSlotGraph"]["hash"]
    assert data["metadata"]["runtimeTrace"] == {"totalCalls": 2, "fallbackCalls": 1}


def test_template_package_write_load_roundtrip(tmp_path):
    skeleton, blueprint = _sample_artifacts()
    wiring = wire_template(skeleton, blueprint, auto_repair=True)
    graph = build_semantic_slot_graph(wiring.skeleton, blueprint, wiring).to_dict()

    manifest = write_template_package(
        tmp_path,
        template_ast=wiring.skeleton,
        template_blueprint=blueprint,
        semantic_slot_graph=graph,
        diagnostics={"status": "VALID", "binderReadinessScore": 0.88},
    )
    loaded = load_template_package(tmp_path)

    assert (tmp_path / "template.package.json").exists()
    assert manifest.templateId == loaded.manifest.templateId == "tpl_test"
    assert loaded.templateAst["metadata"]["templateId"] == "tpl_test"
    assert loaded.templateBlueprint["templateMeta"]["templateId"] == "tpl_test"
    assert loaded.semanticSlotGraph is not None
    assert loaded.diagnostics is not None
    assert json.dumps(loaded.manifest.to_dict())
