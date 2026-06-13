import json

from report_builder.template_traversal import (
    iter_components,
    iter_question_contexts,
    iter_questions,
    walk_outline_nodes,
)
from report_builder.enterprise_template_contract import (
    enrich_enterprise_ast,
    enrich_enterprise_blueprint,
    enrich_entities,
    enrich_questions,
    infer_domain,
)
from report_builder.slot_wiring import build_semantic_slot_graph, validate_wiring
from report_builder.template_emit import build_value_free_skeleton
from report_builder.template_emit import emit_templates
from report_builder.extraction_diagnostics import build_extraction_diagnostics
from report_builder.extraction_pipeline import (
    _extract_numbered_sections,
    _is_footnote_like_heading,
    _is_promotable_heading,
    _is_sentence_like_heading,
)
from report_builder.llm_router import summarize_provider_call_ledger
from report_builder.llm_schemas import (
    ANSWER_COMPONENT_SCHEMA,
    ENTERPRISE_QUESTION_CONTRACT_SCHEMA,
    ENTITY_EVIDENCE_SCHEMA,
    FORMULA_SPEC_SCHEMA,
    PAGE_ENTITY_STRUCTURE_SCHEMA,
    PROVENANCE_REQUIREMENTS_SCHEMA,
)
from report_builder.binding.blueprint_qa import validate_blueprint_qa


def _nested_blueprint():
    return {
        "topics": [
            {
                "topicId": "topic_energy",
                "title": "Energy statistics",
                "questions": [{"questionId": "q_legacy_topic", "answerStructure": {"components": []}}],
                "chapters": [
                    {
                        "chapterId": "chapter_reserves",
                        "title": "Energy reserves",
                        "sections": [
                            {
                                "sectionId": "section_coal",
                                "title": "Coal reserves",
                                "questions": [
                                    {
                                        "questionId": "q_nested_coal",
                                        "answerStructure": {
                                            "components": [
                                                {"componentId": "q_nested_coal__narrative", "kind": "narrative"}
                                            ]
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "questions": [{"questionId": "q_top_level", "answerStructure": {"components": []}}],
    }


def test_recursive_question_traversal_supports_nested_and_legacy_shapes():
    blueprint = _nested_blueprint()

    question_ids = [q["questionId"] for q in iter_questions(blueprint)]
    contexts = {ctx["question"]["questionId"]: ctx for ctx in iter_question_contexts(blueprint)}
    outline_ids = [ctx["nodeId"] for ctx in walk_outline_nodes(blueprint)]

    assert question_ids == ["q_legacy_topic", "q_nested_coal", "q_top_level"]
    assert contexts["q_top_level"]["topicId"] is None
    assert contexts["q_legacy_topic"]["topicId"] == "topic_energy"
    assert contexts["q_nested_coal"]["topicId"] == "topic_energy"
    assert contexts["q_nested_coal"]["chapterId"] == "chapter_reserves"
    assert contexts["q_nested_coal"]["sectionId"] == "section_coal"
    assert "topic_energy" in outline_ids
    assert "chapter_reserves" in outline_ids
    assert "section_coal" in outline_ids


def test_iter_components_reads_answer_structure_and_legacy_output_contract():
    assert iter_components({"answerStructure": {"components": [{"componentId": "c1"}]}}) == [{"componentId": "c1"}]
    assert iter_components({"answerComponents": [{"componentId": "legacy_c1"}]}) == [{"componentId": "legacy_c1"}]
    assert iter_components({"outputContract": {"components": [{"componentId": "c2"}]}}) == [{"componentId": "c2"}]
    assert iter_components({"answerStructure": {"components": [None, {"componentId": "c3"}]}}) == [{"componentId": "c3"}]


def test_blueprint_qa_accepts_formula_spec_and_legacy_answer_components():
    blueprint = {
        "entities": [
            {"entityId": "ent_total", "name": "Total workers", "entityType": "measure"},
            {"entityId": "ent_self", "name": "Self-employed", "entityType": "measure"},
        ],
        "topics": [
            {
                "topicId": "topic_work",
                "title": "Workforce",
                "questions": [
                    {
                        "questionId": "q_share",
                        "intent": "What is the share of self-employed workers?",
                        "questionType": "composition",
                        "requiredEntities": [
                            {"entityId": "ent_self", "role": "numerator"},
                            {"entityId": "ent_total", "role": "denominator"},
                        ],
                        "formulaSpec": {
                            "type": "SHARE",
                            "numeratorEntityId": "ent_self",
                            "denominatorEntityId": "ent_total",
                            "multiplier": 100,
                        },
                        "answerComponents": [
                            {"componentId": "q_share__metric", "kind": "formula_metric"}
                        ],
                    }
                ],
            }
        ],
    }

    qa = validate_blueprint_qa(blueprint)

    assert qa.status == "VALID"
    assert not [w for w in qa.warnings if w["code"] in {"MISSING_ANALYTICS_SPEC", "MISSING_OUTPUT_CONTRACT"}]


def test_energy_blueprint_gets_enterprise_contracts_without_plfs_concepts():
    blueprint = {
        "templateMeta": {"name": "Energy Statistics Annual", "domain": "energy"},
        "entities": [
            {"entityId": "ent_coal", "name": "Coal reserves", "entityType": "measure"},
            {"entityId": "ent_gas", "name": "Natural gas", "entityType": "measure"},
        ],
        "topics": [
            {"topicId": "topic_energy", "title": "Energy", "questions": [{"questionId": "q1", "intent": "What is the coal reserve composition?"}]}
        ],
    }

    enriched = enrich_enterprise_blueprint(blueprint)
    required = {
        "officerCustomization",
        "dataContract",
        "binderDeliverableContract",
        "publicationContract",
        "formulaCatalog",
        "qualityGateProfile",
        "officerWorkbench",
    }
    text = str(enriched).lower()

    assert infer_domain(blueprint) == "energy"
    assert required.issubset(enriched)
    assert "coal" in text
    assert "natural_gas" in text
    assert "lfpr" not in text
    assert "wpr" not in text
    assert "unemployment" not in text


def test_entity_enrichment_adds_evidence_and_flags_missing_source_refs():
    blueprint = {
        "entities": [
            {
                "entityId": "ent_coal_reserves",
                "name": "Coal reserves",
                "entityType": "measure",
                "sourceRefs": [{"sourceType": "table_header", "page": 2, "confidence": 0.91, "tableId": "tbl_2"}],
            },
            {"entityId": "ent_period", "name": "Period", "entityType": "time"},
        ]
    }

    enrich_entities(blueprint, "energy")
    with_refs, missing_refs = blueprint["entities"]

    assert with_refs["evidence"][0]["evidenceId"] == "ev_ent_coal_reserves_1"
    assert with_refs["evidence"][0]["page"] == 2
    assert with_refs["evidence"][0]["tableId"] == "tbl_2"
    assert with_refs["aggregationPolicy"]["method"] == "sum"
    assert "missing_source_refs" not in with_refs["riskFlags"]
    assert missing_refs["sourceRefs"] == []
    assert missing_refs["evidence"] == []
    assert "missing_source_refs" in missing_refs["riskFlags"]
    assert missing_refs["officerReview"]["status"] == "needs_review"


def test_question_enrichment_adds_binder_fields_and_provenance_component():
    blueprint = {
        "entities": [
            {"entityId": "ent_coal", "name": "Coal reserves", "entityType": "measure"},
            {"entityId": "ent_state", "name": "State", "entityType": "dimension"},
        ],
        "topics": [
            {
                "topicId": "topic_energy",
                "questions": [
                    {
                        "questionId": "q_share",
                        "intent": "What is the share of coal reserves by state?",
                        "questionType": "comparison",
                        "requiredEntities": [
                            {"entityId": "ent_coal", "role": "measure"},
                            {"entityId": "ent_state", "role": "dimension"},
                        ],
                        "answerStructure": {"components": [{"kind": "chart", "componentId": "q_share__chart"}]},
                    }
                ],
            }
        ],
    }

    enrich_questions(blueprint, "energy")
    q = iter_questions(blueprint)[0]
    kinds = {component["kind"] for component in q["answerStructure"]["components"]}

    assert q["questionText"] == q["intent"]
    assert q["formulaSpec"]["type"] == "SHARE"
    assert q["formulaSpec"]["measureEntityIds"] == ["ent_coal"]
    assert q["formulaSpec"]["dimensionEntityIds"] == ["ent_state"]
    assert q["binderContract"]["readiness"] == "READY"
    assert q["qualityGates"]
    assert q["provenanceRequirements"]["required"] is True
    assert q["customization"]["lockedFields"] == ["questionId", "formulaSpec.type"]
    assert {"narrative", "formula_metric", "chart", "provenance"} <= kinds


def test_slot_graph_uses_component_fillfrom_and_nested_lineage():
    blueprint = {
        "topics": [
            {
                "topicId": "topic_energy",
                "chapters": [
                    {
                        "chapterId": "chapter_reserves",
                        "sections": [
                            {
                                "sectionId": "section_coal",
                                "questions": [
                                    {
                                        "questionId": "q_coal",
                                        "answerStructure": {
                                            "components": [{"componentId": "q_coal__narrative", "kind": "narrative"}]
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    skeleton = {
        "contentAST": {
            "blocks": [
                {
                    "blockId": "p_q_coal",
                    "biQuery": "q_coal",
                    "slot": {"fillFrom": "q_coal__narrative", "status": "empty"},
                }
            ]
        }
    }

    graph = build_semantic_slot_graph(skeleton, blueprint).to_dict()
    slot = graph["slots"][0]
    broken = {
        "contentAST": {
            "blocks": [
                {"blockId": "bad", "biQuery": "q_coal", "slot": {"fillFrom": "q_coal", "status": "empty"}}
            ]
        }
    }
    issues = validate_wiring(broken, blueprint)

    assert slot["topicId"] == "topic_energy"
    assert slot["chapterId"] == "chapter_reserves"
    assert slot["sectionId"] == "section_coal"
    assert slot["componentId"] == "q_coal__narrative"
    assert slot["fillFrom"] == "q_coal__narrative"
    assert slot["lineageRequired"] is True
    assert slot["slotPolicies"]["fillFromMustReference"] == "componentId"
    assert any(issue.code == "BROKEN_FILLFROM" and issue.severity == "error" for issue in issues)


def test_enterprise_ast_overlays_and_multiple_pages():
    blueprint = enrich_enterprise_blueprint({
        "templateMeta": {"name": "Energy Annual", "domain": "energy"},
        "entities": [{"entityId": "ent_coal", "name": "Coal reserves", "entityType": "measure"}],
        "topics": [
            {
                "topicId": "topic_energy",
                "chapters": [
                    {
                        "chapterId": "chapter_reserves",
                        "sections": [
                            {"sectionId": "section_coal", "questions": [{"questionId": "q1", "intent": "Describe coal reserves"}]},
                            {"sectionId": "section_gas", "questions": [{"questionId": "q2", "intent": "Describe gas reserves"}]},
                        ],
                    }
                ],
            }
        ],
    })
    ast = build_value_free_skeleton({"metadata": {"title": "Energy Annual"}, "blueprint": blueprint})
    overlaid = enrich_enterprise_ast({"layoutAST": {"pages": []}}, blueprint)

    assert "customizationAST" in ast
    assert "publicationAST" in ast
    assert "officerGuideAST" in ast
    assert len(ast["layoutAST"]["pages"]) > 1
    assert overlaid["publicationAST"]["questionCount"] == 2


def test_enterprise_diagnostics_block_broken_fillfrom_and_missing_contracts():
    weak_blueprint = {
        "templateMeta": {"templateId": "weak", "enterpriseReady": True},
        "entities": [{"entityId": "ent_measure", "name": "Reserve", "entityType": "measure"}],
        "topics": [{"topicId": "topic", "questions": [{"questionId": "q1", "intent": "What is reserve?"}]}],
    }
    weak_skeleton = {
        "metadata": {"templateId": "weak"},
        "contentAST": {"blocks": [{"blockId": "p_q1", "biQuery": "q1", "slot": {"fillFrom": "q1"}}]},
    }
    issues = validate_wiring(weak_skeleton, weak_blueprint)
    diagnostics = build_extraction_diagnostics(blueprint=weak_blueprint, skeleton=weak_skeleton, wiring_result=type("W", (), {"issues": issues, "counts": {}})())
    codes = {issue.code for issue in diagnostics.blockingErrors}

    assert diagnostics.status == "INVALID"
    assert diagnostics.binderReadinessScore <= 0.59
    assert "BROKEN_FILLFROM" in codes
    assert "ENTERPRISE_CONTRACTS_MISSING" in codes
    assert "ENTITY_MISSING_SOURCE_REFS" in codes
    assert "QUESTION_ENTERPRISE_FIELDS_MISSING" in codes
    assert "QUESTION_PROVENANCE_COMPONENT_MISSING" in codes
    assert "ENTERPRISE_AST_OVERLAYS_MISSING" in codes


def test_heading_hygiene_rejects_footnotes_sentences_and_keeps_chapters():
    assert _is_footnote_like_heading("2 Total may not tally due to rounding off")
    assert _is_sentence_like_heading("As of 01-04-2025 there were several reserves reported in the document.")
    assert not _is_promotable_heading("2 Total may not tally due to rounding off", numbered=True, layout_backed=True)
    assert not _is_promotable_heading("As of 01-04-2025 there were several reserves reported in the document.", numbered=True, layout_backed=False)
    assert _is_promotable_heading("Chapter 1: Energy Reserves and Potential", numbered=False, layout_backed=True)

    sections = _extract_numbered_sections([
        {
            "raw_text": "\n".join([
                "1. Coal Reserves and Potential",
                "2 Total may not tally due to rounding off",
                "3. As of 01-04-2025 there were several reserves reported in the document.",
            ])
        }
    ])

    assert [s["title"] for s in sections] == ["Coal Reserves and Potential"]


def test_enterprise_schema_fragments_and_provider_trace_summary():
    assert FORMULA_SPEC_SCHEMA["properties"]["type"]["enum"] == ["SHARE", "RATE", "RATIO", "GROWTH", "INDEX", "REPORTED_VALUE", "DESCRIPTIVE"]
    assert "provenance" in ANSWER_COMPONENT_SCHEMA["properties"]["kind"]["enum"]
    assert PROVENANCE_REQUIREMENTS_SCHEMA["properties"]["required"]["type"] == "boolean"
    assert ENTITY_EVIDENCE_SCHEMA["required"] == ["evidenceId", "sourceType", "confidence"]
    assert "formulaSpec" in ENTERPRISE_QUESTION_CONTRACT_SCHEMA["required"]
    entity_schema = PAGE_ENTITY_STRUCTURE_SCHEMA["properties"]["entities"]["items"]["properties"]
    assert {"name", "entityType", "sourceType", "headerPath", "confidence"} <= set(entity_schema)

    summary = summarize_provider_call_ledger([
        {"status": "success", "task": "entity_binding", "actualProvider": "azure", "schemaRequired": True, "schemaEnforced": False},
        {"status": "success", "task": "entity_binding", "actualProvider": "qwen", "schemaRequired": True, "schemaEnforced": True},
        {"status": "success", "task": "question_generation", "actualProvider": "azure", "schemaRequired": False, "schemaEnforced": False},
    ])

    assert summary["schemaRequiredCalls"] == 2
    assert summary["schemaEnforcedCalls"] == 1
    assert summary["providerCounts"] == {"azure": 2, "qwen": 1}


def test_emit_enriched_energy_package_end_to_end(tmp_path):
    ast = {
        "metadata": {"title": "Energy Annual", "domain": "energy"},
        "blueprint": {
            "templateMeta": {"name": "Energy Annual", "domain": "energy", "templateId": "energy_annual"},
            "entities": [
                {
                    "entityId": "ent_coal",
                    "name": "Coal reserves",
                    "entityType": "measure",
                    "sourceRefs": [{"sourceType": "table_header", "page": 1, "confidence": 0.9, "tableId": "tbl_1"}],
                },
                {
                    "entityId": "ent_state",
                    "name": "State",
                    "entityType": "dimension",
                    "sourceRefs": [{"sourceType": "table_header", "page": 1, "confidence": 0.9, "tableId": "tbl_1"}],
                },
            ],
            "topics": [
                {
                    "topicId": "topic_energy",
                    "chapters": [
                        {
                            "chapterId": "chapter_reserves",
                            "sections": [
                                {
                                    "sectionId": "section_coal",
                                    "questions": [
                                        {
                                            "questionId": "q_coal_share",
                                            "intent": "What is the share of coal reserves by state?",
                                            "questionType": "comparison",
                                            "requiredEntities": [
                                                {"entityId": "ent_coal", "role": "measure"},
                                                {"entityId": "ent_state", "role": "dimension"},
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
        "contentAST": {"blocks": []},
        "tableAST": {"tables": []},
        "chartAST": {"charts": []},
        "figureAST": {"figures": []},
    }

    result = emit_templates(ast, tmp_path)
    blueprint = json.loads((tmp_path / "template.blueprint.json").read_text(encoding="utf-8"))
    skeleton = json.loads((tmp_path / "template.ast.json").read_text(encoding="utf-8"))
    graph = json.loads((tmp_path / "semantic_slot_graph.json").read_text(encoding="utf-8"))
    q = iter_questions(blueprint)[0]
    issue_codes = {issue.get("code") for issue in graph.get("issues", []) if issue.get("severity") == "error"}

    assert not result["violations"]
    assert {"officerCustomization", "dataContract", "binderDeliverableContract", "publicationContract", "formulaCatalog", "qualityGateProfile", "officerWorkbench"} <= set(blueprint)
    assert blueprint["entities"][0]["evidence"][0]["tableId"] == "tbl_1"
    assert q["formulaSpec"]["type"] == "SHARE"
    assert any(c["kind"] == "provenance" for c in q["answerStructure"]["components"])
    assert {"customizationAST", "publicationAST", "officerGuideAST"} <= set(skeleton)
    assert graph["counts"]["questions"] == 1
    assert graph["counts"]["components"] >= 3
    assert graph["slots"]
    assert "BROKEN_FILLFROM" not in issue_codes


def test_template_package_payload_embeds_compiler_artifacts(monkeypatch):
    from api.report_builder_api import routes as rb_routes

    def fake_compile_template_artifacts(**kwargs):
        return {
            "template_ast": {"contentAST": {"blocks": []}, "tableAST": {"tables": [{"tableId": "tbl_1"}]}},
            "template_blueprint": kwargs["blueprint"],
            "semantic_slot_graph": {"slots": [{"slotId": "slot_1"}]},
            "template_package_manifest": {"packageSchema": "binding.templatePackage.v1", "sha256": "abc"},
            "diagnostics": type("D", (), {"to_dict": lambda self: {"status": "VALID", "binderReadinessScore": 0.91}})(),
        }

    monkeypatch.setattr(
        "report_builder.template_compiler.compile_template_artifacts",
        fake_compile_template_artifacts,
    )

    payload = rb_routes._build_template_package_payload(
        ast_payload={
            "contentAST": {"blocks": []},
            "blueprint": {
                "templateMeta": {"templateId": "tpl_test"},
                "entities": [{"entityId": "ent_1", "name": "Measure", "entityType": "measure"}],
                "topics": [],
            },
        },
        diagnostics={"stages": {"stage": "ok"}},
    )

    assert payload["schema_version"] == "binding.templatePackage.v1"
    assert payload["blueprint"]["templateMeta"]["templateId"] == "tpl_test"
    assert payload["semantic_slot_graph"]["slots"][0]["slotId"] == "slot_1"
    assert payload["template_manifest"]["packageSchema"] == "binding.templatePackage.v1"
    assert payload["extraction_diagnostics"]["status"] == "VALID"
    assert payload["ast_json"]["blueprint"]["templateMeta"]["templateId"] == "tpl_test"
    assert payload["ast_json"]["template_ast"]["tableAST"]["tables"][0]["tableId"] == "tbl_1"
