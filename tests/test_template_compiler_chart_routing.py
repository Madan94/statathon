from __future__ import annotations

from report_builder.template_compiler import compile_template_artifacts


def test_chart_ast_drives_semantics_and_topic_routing():
    ast = {
        "metadata": {"documentId": "tpl_test", "title": "PLFS Press"},
        "contentAST": {"blocks": []},
        "tableAST": {"tables": []},
        "chartAST": {"charts": [
            {"chartId": "chart_lfpr", "chartType": "bar_chart", "title": "Fig. 1(a): LFPR (%) in rural areas"},
            {"chartId": "chart_ur", "chartType": "line_chart", "title": "Fig. 2(a): Unemployment Rate (%) in urban areas"},
        ]},
        "figureAST": {"figures": []},
        "layoutAST": {"pages": []},
        "geometryAST": {"flow": []},
    }
    blueprint = {
        "templateMeta": {"templateId": "tpl_test", "name": "PLFS Press", "domain": "labour_force", "reportType": "pib_press_release"},
        "entities": [
            {"entityId": "ent_lfpr_old", "canonicalName": "Labour Force Participation Rate", "entityType": "measure", "aliases": ["LFPR"], "unit": "percent"},
            {"entityId": "ent_ur_old", "canonicalName": "Unemployment Rate", "entityType": "measure", "aliases": ["UR"], "unit": "percent"},
            {"entityId": "ent_sector_old", "canonicalName": "Sector", "entityType": "dimension", "aliases": ["rural", "urban"]},
        ],
        "topics": [
            {"topicId": "topic_lfpr", "title": "Stable Labour Force Participation Rate", "questions": []},
            {"topicId": "topic_ur", "title": "Unemployment Rate", "questions": []},
        ],
    }

    result = compile_template_artifacts(raw_ast=ast, blueprint=blueprint)
    compiled_ast = result["template_ast"]
    compiled_bp = result["template_blueprint"]

    charts = compiled_ast["chartAST"]["charts"]
    assert any(c.get("entityRefs") for c in charts), charts
    assert any(c.get("measureEntityId") for c in charts), charts

    topics = {t["topicId"]: t for t in compiled_bp["topics"]}
    assert len(topics["topic_lfpr"].get("questions", [])) >= 1
    assert len(topics["topic_ur"].get("questions", [])) >= 1

    all_questions = [q for t in compiled_bp["topics"] for q in t.get("questions", [])]
    assert all(q.get("measureEntityId") for q in all_questions if q.get("requiredEntities"))
    assert compiled_bp.get("chartPanelGroups")
