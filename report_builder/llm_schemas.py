"""Reusable JSON schemas for vLLM ``guided_json`` constrained decoding (P6 / Q20).

These schemas are passed as the ``schema=`` argument to ``llm_text_call`` /
``llm_vision_call``. They force the 3B Qwen model to emit well-formed, enum-valid
JSON, which is the single biggest quality lever for a small model. All schemas are
value-free (they constrain shape + enums only, never specific data values).
"""
from __future__ import annotations

from typing import Any

# Question generation (Pass 3, Loop 1): array of question stubs.
QUESTION_LIST_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "questionId": {"type": "string"},
            "intent": {"type": "string", "minLength": 12},
            "questionType": {
                "type": "string",
                "enum": ["comparison", "trend", "ranking", "distribution",
                         "composition", "correlation", "describe"],
            },
            "sourceHeading": {"type": "string"},
        },
        "required": ["intent", "questionType"],
    },
}

# Entity binding (Pass 3, Loop 2): roles + answer structure for one question.
ENTITY_BINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "requiredEntities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entityRef": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": ["measure", "groupBy", "grouping", "dimension",
                                 "filter", "breakdown", "time"],
                    },
                },
                "required": ["entityRef", "role"],
            },
        },
        "answerStructure": {
            "type": "object",
            "properties": {
                "layoutType": {"type": "string", "enum": ["single", "split"]},
                "components": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["narrative_paragraph", "data_table",
                                         "grouped_bar_chart", "line_chart",
                                         "pie_chart", "metric_card"],
                            },
                            "renderOrder": {"type": "integer"},
                        },
                        "required": ["type"],
                    },
                },
            },
        },
        "confidence": {"type": "number"},
    },
}

# Entity type classification (Pass 2.6): array of {name, type}.
ENTITY_CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "type": {
                "type": "string",
                "enum": ["dimension", "measure", "filter", "metadata"],
            },
        },
        "required": ["name", "type"],
    },
}
