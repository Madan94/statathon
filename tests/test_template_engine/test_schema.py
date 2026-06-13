"""Schema tests — validates ast_core/schema.py and pydantic_schema.py."""
from __future__ import annotations

import json

import pytest

from ast_core.schema import (
    TemplateBlueprintAST,
    TopicNode,
    QuestionNode,
    AnswerStructure,
    AnswerComponent,
    AnswerComponentRef,
    TemplateEntity,
    QuestionEntityBinding,
    COMPONENT_TYPES,
    ENTITY_TYPES,
    ENTITY_SOURCE_TYPES,
)
from ast_core.pydantic_schema import (
    TemplateBlueprintModel,
    TopicNodeModel,
    QuestionNodeModel,
    export_json_schema,
    blueprint_model_to_dataclass,
    ComponentType,
    EntityType,
)


class TestSchemaDataclasses:
    def test_blueprint_to_dict(self):
        ast = TemplateBlueprintAST(
            templateId="tmpl_test",
            name="Test",
            sourceHash="abc123",
            pageCount=5,
            topics=[],
            entities=[],
        )
        d = ast.to_dict()
        assert d["templateId"] == "tmpl_test"
        assert d["pageCount"] == 5

    def test_blueprint_from_dict_roundtrip(self):
        original = TemplateBlueprintAST(
            templateId="tmpl_rt",
            name="Roundtrip",
            sourceHash="hash123",
            pageCount=10,
            topics=[TopicNode(
                topicId="t1",
                title="Topic 1",
                questions=[QuestionNode(
                    questionId="q1",
                    intent="What is X?",
                    answerStructure=AnswerStructure(components=[
                        AnswerComponent(
                            componentId="c1",
                            type="data_table",
                            refs=AnswerComponentRef(entityRefs=["e1"]),
                        ),
                    ]),
                    requiredEntities=[
                        QuestionEntityBinding(entityId="e1", role="primary"),
                    ],
                )],
            )],
            entities=[TemplateEntity(
                entityId="e1",
                name="GDP",
                entityType="measure",
                sourceType="table_header",
                confidence=0.9,
            )],
        )
        d = original.to_dict()
        restored = TemplateBlueprintAST.from_dict(d)
        assert restored.templateId == original.templateId
        assert len(restored.topics) == 1
        assert len(restored.entities) == 1
        assert restored.topics[0].questions[0].intent == "What is X?"

    def test_all_questions_flattens(self):
        ast = TemplateBlueprintAST(
            templateId="t",
            name="N",
            topics=[
                TopicNode(topicId="t1", title="T1", questions=[
                    QuestionNode(questionId="q1", intent="Q1", answerStructure=AnswerStructure()),
                    QuestionNode(questionId="q2", intent="Q2", answerStructure=AnswerStructure()),
                ]),
                TopicNode(topicId="t2", title="T2", questions=[
                    QuestionNode(questionId="q3", intent="Q3", answerStructure=AnswerStructure()),
                ]),
            ],
        )
        assert len(ast.all_questions()) == 3

    def test_entity_by_id(self):
        ast = TemplateBlueprintAST(
            templateId="t",
            name="N",
            entities=[
                TemplateEntity(entityId="e1", name="A", entityType="measure", sourceType="heading"),
                TemplateEntity(entityId="e2", name="B", entityType="dimension", sourceType="table_header"),
            ],
        )
        assert ast.entity_by_id("e1").name == "A"
        assert ast.entity_by_id("e2").name == "B"
        assert ast.entity_by_id("nonexistent") is None


class TestPydanticSchema:
    def test_export_json_schema(self):
        schema = export_json_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema or "$defs" in schema

    def test_json_schema_is_valid_json(self):
        schema = export_json_schema()
        dumped = json.dumps(schema)
        assert len(dumped) > 100

    def test_component_type_enum(self):
        assert "data_table" in [ct.value for ct in ComponentType]
        assert "grouped_bar_chart" in [ct.value for ct in ComponentType]

    def test_entity_type_enum(self):
        assert "measure" in [et.value for et in EntityType]
        assert "dimension" in [et.value for et in EntityType]

    def test_constants_match_enums(self):
        for ct in COMPONENT_TYPES:
            assert ct in [e.value for e in ComponentType]
        for et in ENTITY_TYPES:
            assert et in [e.value for e in EntityType]
