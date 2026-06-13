from __future__ import annotations


def test_slot_wiring_repairs_stale_fillfrom_and_missing_sibling_slot():
    from report_builder.slot_wiring import validate_wiring, wire_template

    skeleton = {
        "contentAST": {"blocks": []},
        "tableAST": {"tables": []},
        "chartAST": {
            "charts": [
                {
                    "chartId": "chart_sp03_q01",
                    "biQuery": "q_worker_population_ratio_gender",
                    "chartType": "grouped_bar",
                    "entityRefs": ["ent_wpr", "ent_gender"],
                    "measureEntityId": "ent_wpr",
                    "dimensionEntityId": "ent_gender",
                    "series": [],
                    "slot": {"fillFrom": "sp03_q01_c2", "status": "empty"},
                }
            ]
        },
        "figureAST": {"figures": []},
    }
    blueprint = {
        "templateMeta": {"templateId": "tpl_test"},
        "entities": [
            {"entityId": "ent_wpr", "canonicalName": "Worker Population Ratio", "entityType": "measure", "unit": "percent"},
            {"entityId": "ent_gender", "canonicalName": "Gender", "entityType": "dimension"},
        ],
        "topics": [
            {
                "topicId": "topic_wpr",
                "title": "Worker Population Ratio",
                "questions": [
                    {
                        "questionId": "q_worker_population_ratio_gender",
                        "intent": "Show Worker Population Ratio by Gender.",
                        "questionType": "comparison",
                        "requiredEntities": [
                            {"entityId": "ent_wpr", "role": "measure", "required": True},
                            {"entityId": "ent_gender", "role": "grouping", "required": True},
                        ],
                        "analyticsSpec": {
                            "operation": "group_aggregate",
                            "measure": {"entityRef": "ent_wpr"},
                            "groupBy": [{"entityRef": "ent_gender"}],
                        },
                        "answerStructure": {
                            "components": [
                                {"componentId": "q_worker_population_ratio_gender_c1", "kind": "narrative", "outputContract": {"type": "prose"}},
                                {"componentId": "q_worker_population_ratio_gender_c2", "kind": "chart", "outputContract": {"type": "chart"}},
                            ]
                        },
                    }
                ],
            }
        ],
    }

    before = validate_wiring(skeleton, blueprint)
    assert any(i.code == "BROKEN_FILLFROM" for i in before)

    result = wire_template(skeleton, blueprint, auto_repair=True)

    assert [i.to_dict() for i in result.issues if i.severity == "error"] == []
    chart = result.skeleton["chartAST"]["charts"][0]
    assert chart["slot"]["fillFrom"] == "q_worker_population_ratio_gender_c2"
    assert len(result.skeleton["chartAST"]["charts"]) == 1
    assert any(
        b.get("slot", {}).get("fillFrom") == "q_worker_population_ratio_gender_c1"
        for b in result.skeleton["contentAST"]["blocks"]
    )
    assert result.counts["crosswalkComponents"] == 2


def test_question_compiler_drops_chart_question_without_measure():
    from report_builder.question_compiler import compile_questions

    class Figure:
        figureTemplateId = "ft_wpr_gender"
        chartType = "bar"
        chartSubject = "Worker Population Ratio by Gender"
        measureRefs: list[str] = []
        dimensionRef = "ent_gender"
        categoryEntityRef = None

    result = compile_questions(
        figures=[Figure()],
        entities=[{"entityId": "ent_gender", "canonicalName": "Gender", "entityType": "dimension"}],
    )

    assert result.questions == []
    assert result.droppedQuestions
    assert result.droppedQuestions[0]["reason"] == "validation_error"
    assert set(result.droppedQuestions[0]["codes"]) == {"NO_MEASURE", "EMPTY_MEASURE_SPEC"}


def test_extraction_contract_strict_blocks_empty_measure_analytic_question():
    from report_builder.extraction_contracts import ExtractionMode, validate_extraction_contract

    blueprint = {
        "templateMeta": {"templateId": "tpl_test", "name": "PLFS", "domain": "labour_force"},
        "entities": [{"entityId": "ent_gender", "canonicalName": "Gender", "entityType": "dimension"}],
        "topics": [
            {
                "topicId": "topic_wpr",
                "title": "Worker Population Ratio",
                "questions": [
                    {
                        "questionId": "q_wpr_gender",
                        "intent": "Show Worker Population Ratio by Gender.",
                        "questionType": "comparison",
                        "requiredEntities": [{"entityId": "ent_gender", "role": "grouping", "required": True}],
                        "analyticsSpec": {
                            "operation": "group_aggregate",
                            "measure": {},
                            "measures": [{"entityRef": ""}],
                            "groupBy": [{"entityRef": "ent_gender"}],
                        },
                        "answerStructure": {"components": [{"componentId": "q_wpr_gender_c1", "kind": "narrative"}]},
                    }
                ],
            }
        ],
    }

    result = validate_extraction_contract(blueprint, mode=ExtractionMode.STRICT)

    assert result.status == "INVALID"
    assert {e.code for e in result.errors} >= {"MISSING_MEASURE_SPEC", "MISSING_MEASURE_ENTITY"}


def test_entity_source_refs_survive_hygiene_normalization_and_dedupe():
    from report_builder.entity_hygiene import run_entity_hygiene
    from report_builder.entity_normalizer import normalize_entities
    from report_builder.extraction_pipeline import _deduplicate_entities

    source_ref = {
        "sourceType": "table_header",
        "page": 2,
        "regionRef": "p003_r004",
        "physicalColumn": "Worker Population Ratio (%)",
        "bbox": [10, 20, 110, 60],
        "confidence": 0.91,
    }
    hygiene = run_entity_hygiene([
        {
            "name": "Worker Population Ratio (%)",
            "source": "table_header",
            "page": 2,
            "sourceRefs": [source_ref],
        }
    ])
    assert hygiene.entities
    assert hygiene.entities[0].sourceRefs[0].to_dict()["regionRef"] == "p003_r004"

    normalized = normalize_entities(hygiene.entities)
    [entity_dict] = [e.to_dict() for e in normalized.entities]
    assert entity_dict["sourceRefs"][0]["regionRef"] == "p003_r004"
    assert entity_dict["sourceRefs"][0]["bbox"] == [10, 20, 110, 60]

    deduped = _deduplicate_entities([
        {"name": "Worker Population Ratio", "sourceRefs": [source_ref], "pages": [2]},
        {
            "name": "worker population ratio",
            "sourceRefs": [{"sourceType": "vlm_entity", "page": 2, "confidence": 0.8}],
            "pages": [2],
        },
    ])
    assert len(deduped) == 1
    assert {ref["sourceType"] for ref in deduped[0]["sourceRefs"]} == {"table_header", "vlm_entity"}


def test_template_semantic_graph_indexes_typed_entities_and_evidence():
    from report_builder.extraction_pipeline import _build_template_semantic_graph

    graph = _build_template_semantic_graph({
        "title": "PLFS",
        "page_count": 2,
        "all_entities": [
            {
                "entityId": "ent_wpr",
                "name": "Worker Population Ratio",
                "entityType_hint": "measure",
                "unit": "percent",
                "pages": [0],
                "sourceRefs": [
                    {"sourceType": "table_header", "page": 0, "physicalColumn": "WPR", "confidence": 0.95}
                ],
            }
        ],
        "chapters": [{"chapterId": "ch_01", "title": "WPR", "level": 1, "pageRange": [0, 1]}],
        "table_structures": [{"tableId": "tbl_1", "page": 0, "columns": ["Gender", "WPR"], "dimensions": ["Gender"], "measures": ["WPR"]}],
        "entity_relationships": [{"from": "ent_gender", "to": "ent_wpr", "relation": "dimension_of"}],
    })

    assert graph["$schema"] == "bharatstat/template-semantic-graph/v1"
    assert graph["diagnostics"]["entitiesWithSourceRefs"] == 1
    assert graph["evidenceIndex"][0]["evidenceId"] == "ev_0001"
    assert graph["entities"][0]["entityType"] == "measure"
    assert graph["entities"][0]["evidenceRefs"] == ["ev_0001"]


def test_template_semantic_graph_keeps_distinct_bbox_evidence_refs():
    from report_builder.extraction_pipeline import _build_template_semantic_graph

    graph = _build_template_semantic_graph({
        "title": "PLFS",
        "all_entities": [
            {
                "entityId": "ent_wpr",
                "name": "Worker Population Ratio",
                "entityType_hint": "measure",
                "sourceRefs": [
                    {"sourceType": "table_header", "page": 0, "physicalColumn": "WPR", "bbox": [0, 0, 10, 10]},
                    {"sourceType": "table_header", "page": 0, "physicalColumn": "WPR", "bbox": [20, 0, 30, 10]},
                ],
            }
        ],
    })

    assert [row["evidenceId"] for row in graph["evidenceIndex"]] == ["ev_0001", "ev_0002"]
    assert graph["entities"][0]["evidenceRefs"] == ["ev_0001", "ev_0002"]


def test_question_local_evidence_rejects_out_of_section_measure():
    from report_builder.extraction_pipeline import _question_local_evidence

    entities = [
        {"entityId": "ent_wpr", "name": "Worker Population Ratio", "entityType_hint": "measure", "aliases": ["WPR"], "pages": [1]},
        {"entityId": "ent_ur", "name": "Unemployment Rate", "entityType_hint": "measure", "aliases": ["UR"], "pages": [5]},
    ]
    chapters = [
        {"chapterId": "ch_wpr", "title": "WPR", "pageRange": [1, 2]},
        {"chapterId": "ch_ur", "title": "UR", "pageRange": [5, 6]},
    ]

    ok, evidence = _question_local_evidence(
        {"intent": "What is the unemployment rate by gender?", "questionType": "comparison", "page": 1},
        entities,
        chapters,
    )

    assert ok is False
    assert evidence["reason"] == "out_of_section_measure"


def test_question_local_evidence_accepts_section_measure():
    from report_builder.extraction_pipeline import _question_local_evidence

    ok, evidence = _question_local_evidence(
        {"intent": "What is the worker population ratio by gender?", "questionType": "comparison", "page": 1},
        [{"entityId": "ent_wpr", "name": "Worker Population Ratio", "entityType_hint": "measure", "aliases": ["WPR"], "pages": [1]}],
        [{"chapterId": "ch_wpr", "title": "WPR", "pageRange": [1, 2]}],
    )

    assert ok is True
    assert evidence["reason"] == "local_measure_evidence"


def test_s35_gate_blocks_semantic_graph_entities_without_source_refs():
    from report_builder.extraction_diagnostics import build_extraction_diagnostics

    blueprint = {
        "templateMeta": {"templateId": "tpl_test", "name": "PLFS", "domain": "labour_force"},
        "templateSemanticGraph": {
            "$schema": "bharatstat/template-semantic-graph/v1",
            "diagnostics": {"entityCount": 1, "evidenceCount": 0},
        },
        "entities": [{"entityId": "ent_wpr", "canonicalName": "Worker Population Ratio", "entityType": "measure", "unit": "percent"}],
        "topics": [{
            "topicId": "topic_wpr",
            "questions": [{
                "questionId": "q_wpr",
                "intent": "What is the worker population ratio by gender?",
                "questionType": "comparison",
                "requiredEntities": [{"entityId": "ent_wpr", "role": "measure"}],
                "analyticsSpec": {"operation": "group_aggregate", "measure": {"entityRef": "ent_wpr"}},
                "answerStructure": {"components": [{"componentId": "q_wpr_c1", "kind": "narrative"}]},
            }],
        }],
    }

    diag = build_extraction_diagnostics(
        blueprint=blueprint,
        skeleton={"metadata": {"templateId": "tpl_test"}},
        runtime_trace={"statusCounts": {}, "schemaRequiredCalls": 0, "schemaEnforcedCalls": 0},
    )

    assert diag.status == "INVALID"
    assert {e.code for e in diag.blockingErrors} >= {"ENTITY_MISSING_SOURCE_REFS", "SEMANTIC_GRAPH_WITHOUT_EVIDENCE"}
    assert diag.binderCompatibility.recommendation == "invalid"


def test_s35_gate_blocks_non_executable_analytic_question_when_graph_present():
    from report_builder.extraction_diagnostics import build_extraction_diagnostics

    blueprint = {
        "templateMeta": {"templateId": "tpl_test", "name": "PLFS", "domain": "labour_force"},
        "templateSemanticGraph": {
            "$schema": "bharatstat/template-semantic-graph/v1",
            "diagnostics": {"entityCount": 1, "evidenceCount": 1},
            "evidenceIndex": [{"evidenceId": "ev_0001", "sourceType": "table_header", "page": 0}],
        },
        "entities": [{
            "entityId": "ent_gender",
            "canonicalName": "Gender",
            "entityType": "dimension",
            "sourceRefs": [{"sourceType": "table_header", "page": 0}],
        }],
        "topics": [{
            "topicId": "topic_wpr",
            "questions": [{
                "questionId": "q_wpr",
                "intent": "What is the worker population ratio by gender?",
                "questionType": "comparison",
                "requiredEntities": [{"entityId": "ent_gender", "role": "grouping"}],
                "analyticsSpec": {"operation": "group_aggregate", "measure": {}},
                "answerStructure": {"components": [{"componentId": "q_wpr_c1", "kind": "narrative"}]},
            }],
        }],
    }

    diag = build_extraction_diagnostics(blueprint=blueprint, skeleton={"metadata": {"templateId": "tpl_test"}})

    assert diag.status == "INVALID"
    assert "ANALYTIC_QUESTION_NOT_EXECUTABLE" in {e.code for e in diag.blockingErrors}


def test_pass_dump_entity_preserves_binder_evidence_and_runtime_refs():
    from report_builder.extraction_pipeline import _pass_dump_entity

    dumped = _pass_dump_entity({
        "entityId": "ent_wpr",
        "name": "Worker Population Ratio",
        "entityType_hint": "measure",
        "unit": "percent",
        "valueDomain": {"kind": "ratio"},
        "pages": [2],
        "sourceRefs": [{
            "sourceType": "table_header",
            "page": 2,
            "tableId": "tbl_2",
            "regionRef": "p003_r004",
            "physicalColumn": "WPR",
            "confidence": 0.94,
        }],
        "runtimeTraceRefs": [{"task": "entity_extraction", "callId": "call_1"}],
    })

    assert dumped["entityId"] == "ent_wpr"
    assert dumped["sourceRefs"][0]["regionRef"] == "p003_r004"
    assert dumped["sourceRefs"][0]["physicalColumn"] == "WPR"
    assert dumped["runtimeTraceRefs"] == [{"task": "entity_extraction", "callId": "call_1"}]
    assert dumped["valueDomain"] == {"kind": "ratio"}


def test_s35_gate_blocks_partial_semantic_graph_evidence_gap():
    from report_builder.extraction_diagnostics import build_extraction_diagnostics

    blueprint = {
        "templateMeta": {"templateId": "tpl_test", "name": "PLFS", "domain": "labour_force"},
        "templateSemanticGraph": {
            "$schema": "bharatstat/template-semantic-graph/v1",
            "diagnostics": {"entityCount": 2, "evidenceCount": 1},
            "evidenceIndex": [{"evidenceId": "ev_0001", "sourceType": "table_header", "page": 0}],
            "entities": [
                {"entityId": "ent_wpr", "name": "Worker Population Ratio", "entityType": "measure", "evidenceRefs": ["ev_0001"]},
                {"entityId": "ent_gender", "name": "Gender", "entityType": "dimension", "evidenceRefs": []},
            ],
        },
        "entities": [
            {
                "entityId": "ent_wpr",
                "canonicalName": "Worker Population Ratio",
                "entityType": "measure",
                "sourceRefs": [{"sourceType": "table_header", "page": 0}],
            },
            {
                "entityId": "ent_gender",
                "canonicalName": "Gender",
                "entityType": "dimension",
                "sourceRefs": [{"sourceType": "table_header", "page": 0}],
            },
        ],
        "topics": [{
            "topicId": "topic_wpr",
            "questions": [{
                "questionId": "q_wpr",
                "intent": "What is the worker population ratio by gender?",
                "questionType": "comparison",
                "requiredEntities": [{"entityId": "ent_wpr", "role": "measure"}],
                "analyticsSpec": {"operation": "group_aggregate", "measure": {"entityRef": "ent_wpr"}},
                "answerStructure": {"components": [{"componentId": "q_wpr_c1", "kind": "narrative"}]},
            }],
        }],
    }

    diag = build_extraction_diagnostics(blueprint=blueprint, skeleton={"metadata": {"templateId": "tpl_test"}})

    assert diag.status == "INVALID"
    assert "SEMANTIC_GRAPH_ENTITY_EVIDENCE_GAP" in {e.code for e in diag.blockingErrors}


def test_s35_gate_warns_about_unbound_render_only_chart_panels():
    from report_builder.extraction_diagnostics import build_extraction_diagnostics

    blueprint = {
        "templateMeta": {"templateId": "tpl_test", "name": "PLFS", "domain": "labour_force"},
        "templateSemanticGraph": {
            "$schema": "bharatstat/template-semantic-graph/v1",
            "diagnostics": {"entityCount": 1, "evidenceCount": 1},
            "evidenceIndex": [{"evidenceId": "ev_0001", "sourceType": "figure_detection", "page": 0}],
            "entities": [{"entityId": "ent_wpr", "name": "Worker Population Ratio", "entityType": "measure", "evidenceRefs": ["ev_0001"]}],
        },
        "entities": [{
            "entityId": "ent_wpr",
            "canonicalName": "Worker Population Ratio",
            "entityType": "measure",
            "sourceRefs": [{"sourceType": "figure_detection", "page": 0}],
        }],
        "topics": [{
            "topicId": "topic_wpr",
            "questions": [{
                "questionId": "q_wpr",
                "intent": "What is the worker population ratio?",
                "questionType": "metric",
                "requiredEntities": [{"entityId": "ent_wpr", "role": "measure"}],
                "analyticsSpec": {"operation": "group_aggregate", "measure": {"entityRef": "ent_wpr"}},
                "answerStructure": {"components": [{"componentId": "q_wpr_c1", "kind": "narrative"}]},
            }],
        }],
    }
    skeleton = {
        "metadata": {"templateId": "tpl_test"},
        "chartAST": {"charts": [{"chartId": "chart_ungrouped", "series": [], "slot": {"status": "empty"}}]},
    }

    diag = build_extraction_diagnostics(blueprint=blueprint, skeleton=skeleton)

    assert "CHART_GROUP_MISSING_MEASURE" not in {e.code for e in diag.blockingErrors}
    assert "UNBOUND_CHART_PANELS" in {w.code for w in diag.warnings}
