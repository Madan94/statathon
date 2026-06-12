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


# ─────────────────────────────────────────────────────────────────────────────
# Enterprise binder-contract schema fragments (P6 / Pass 3 question contracts)
# ─────────────────────────────────────────────────────────────────────────────

# Structured formula intent for a question. Value-free: shape + enums only.
FORMULA_SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["SHARE", "RATE", "RATIO", "GROWTH", "INDEX", "REPORTED_VALUE", "DESCRIPTIVE"],
        },
        "measureEntityIds": {"type": "array", "items": {"type": "string"}},
        "dimensionEntityIds": {"type": "array", "items": {"type": "string"}},
        "timeEntityIds": {"type": "array", "items": {"type": "string"}},
        "weightColumn": {"type": "string"},
        "multiplier": {"type": "number"},
        "readiness": {"type": "string", "enum": ["READY", "BLOCKED"]},
        "blockedReasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["type"],
}

# Provenance requirements attached to a question contract.
PROVENANCE_REQUIREMENTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "required": {"type": "boolean"},
        "lineageRef": {"type": "string"},
        "datasetSignature": {"type": "string"},
        "evidenceRefs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["required"],
}

# One answer component inside answerStructure.components[].
ANSWER_COMPONENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "componentId": {"type": "string"},
        "kind": {
            "type": "string",
            "enum": [
                "narrative",
                "formula_metric",
                "metric_card",
                "chart",
                "table",
                "provenance",
            ],
        },
        "order": {"type": "integer"},
    },
    "required": ["componentId", "kind"],
}

# Normalized evidence record threaded onto every binder-relevant entity.
ENTITY_EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "evidenceId": {"type": "string"},
        "sourceType": {"type": "string"},
        "page": {"type": "integer"},
        "confidence": {"type": "number"},
        "tableId": {"type": "string"},
        "figureId": {"type": "string"},
        "regionRef": {"type": "string"},
        "bbox": {"type": "array", "items": {"type": "number"}},
        "headerPath": {"type": "array", "items": {"type": "string"}},
        "physicalColumn": {"type": "string"},
    },
    "required": ["evidenceId", "sourceType", "confidence"],
}

# Full enterprise question contract.
ENTERPRISE_QUESTION_CONTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questionId": {"type": "string"},
        "questionText": {"type": "string"},
        "intent": {"type": "string"},
        "questionType": {
            "type": "string",
            "enum": ["comparison", "trend", "ranking", "distribution",
                     "composition", "correlation", "describe"],
        },
        "requiredEntities": {"type": "array", "items": {"type": "object"}},
        "formulaSpec": FORMULA_SPEC_SCHEMA,
        "binderContract": {"type": "object"},
        "qualityGates": {"type": "array", "items": {"type": "object"}},
        "provenanceRequirements": PROVENANCE_REQUIREMENTS_SCHEMA,
        "customization": {"type": "object"},
        "answerPlan": {"type": "object"},
        "answerStructure": {"type": "object"},
    },
    "required": ["questionId", "intent", "questionType", "formulaSpec"],
}
