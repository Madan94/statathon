"""Component registry for ReviewedPlan component palette.

The binder UI will eventually let officers add tables, charts, notes, formulas,
and other report components. This registry keeps those choices governed instead
of letting arbitrary component JSON leak into ReviewedPlan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ComponentDefinition:
    componentType: str
    label: str
    group: str
    allowedNodeTypes: tuple[str, ...] = ("topic", "subtopic", "subsubtopic", "question")
    requiredFields: tuple[str, ...] = ()
    requiresAnalyticsSpec: bool = False
    defaultSlotBehavior: str = "virtual"  # existing | virtual | none

    def to_dict(self) -> dict[str, Any]:
        return {
            "componentType": self.componentType,
            "label": self.label,
            "group": self.group,
            "allowedNodeTypes": list(self.allowedNodeTypes),
            "requiredFields": list(self.requiredFields),
            "requiresAnalyticsSpec": self.requiresAnalyticsSpec,
            "defaultSlotBehavior": self.defaultSlotBehavior,
        }


_COMPONENTS: dict[str, ComponentDefinition] = {
    "narrative": ComponentDefinition("narrative", "Narrative paragraph", "text"),
    "key_finding": ComponentDefinition("key_finding", "Key finding", "text"),
    "table": ComponentDefinition(
        "table", "Table", "data", requiredFields=("requiredEntities",), requiresAnalyticsSpec=True
    ),
    "chart": ComponentDefinition(
        "chart", "Chart", "visual", requiredFields=("requiredEntities",), requiresAnalyticsSpec=True
    ),
    "formula_metric": ComponentDefinition(
        "formula_metric", "Formula metric", "data", requiredFields=("formulaSpec",), requiresAnalyticsSpec=True
    ),
    "image_slot": ComponentDefinition("image_slot", "Image / infographic slot", "visual"),
    "source_note": ComponentDefinition("source_note", "Source note", "note", defaultSlotBehavior="none"),
    "footnote": ComponentDefinition("footnote", "Footnote", "note", defaultSlotBehavior="none"),
    "glossary": ComponentDefinition("glossary", "Glossary term", "note", defaultSlotBehavior="none"),
    "methodology_note": ComponentDefinition("methodology_note", "Methodology note", "note"),
    "caveat": ComponentDefinition("caveat", "Data caveat", "note"),
}


def list_component_definitions() -> list[dict[str, Any]]:
    return [definition.to_dict() for definition in _COMPONENTS.values()]


def get_component_definition(component_type: str) -> ComponentDefinition | None:
    return _COMPONENTS.get(component_type)


def normalize_component_type(component_type: str) -> str:
    aliases = {
        "paragraph": "narrative",
        "narrative_paragraph": "narrative",
        "metric": "formula_metric",
        "metric_card": "formula_metric",
        "data_table": "table",
        "figure": "image_slot",
        "infographic": "image_slot",
    }
    key = str(component_type or "").strip().lower()
    return aliases.get(key, key or "narrative")


def validate_component_payload(
    component_type: str,
    payload: dict[str, Any],
    *,
    node_type: str = "question",
) -> list[dict[str, Any]]:
    """Return warnings/errors for a component payload against the registry."""
    normalized = normalize_component_type(component_type)
    definition = get_component_definition(normalized)
    if definition is None:
        return [{
            "severity": "error",
            "code": "UNKNOWN_COMPONENT_TYPE",
            "message": f"Unknown component type: {component_type}",
        }]

    issues: list[dict[str, Any]] = []
    if node_type not in definition.allowedNodeTypes:
        issues.append({
            "severity": "error",
            "code": "COMPONENT_NODE_NOT_ALLOWED",
            "message": f"{normalized} cannot be attached to {node_type}",
        })
    for field_name in definition.requiredFields:
        if not payload.get(field_name):
            issues.append({
                "severity": "warn",
                "code": "COMPONENT_FIELD_MISSING",
                "message": f"{normalized} should define {field_name}",
            })
    if definition.requiresAnalyticsSpec and not payload.get("analyticsSpec"):
        issues.append({
            "severity": "warn",
            "code": "ANALYTICS_SPEC_MISSING",
            "message": f"{normalized} should define analyticsSpec before freeze",
        })
    return issues