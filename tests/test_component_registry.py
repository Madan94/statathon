from __future__ import annotations

from report_builder.binding.component_registry import (
    get_component_definition,
    list_component_definitions,
    normalize_component_type,
    validate_component_payload,
)


def test_component_registry_contains_mospi_palette():
    types = {item["componentType"] for item in list_component_definitions()}
    assert {"narrative", "table", "chart", "formula_metric", "source_note", "caveat"} <= types


def test_component_type_aliases_normalize():
    assert normalize_component_type("data_table") == "table"
    assert normalize_component_type("metric_card") == "formula_metric"
    assert normalize_component_type("paragraph") == "narrative"


def test_component_payload_validation_warns_for_missing_specs():
    issues = validate_component_payload("table", {}, node_type="question")
    codes = {issue["code"] for issue in issues}
    assert "COMPONENT_FIELD_MISSING" in codes
    assert "ANALYTICS_SPEC_MISSING" in codes


def test_component_lookup_unknown():
    assert get_component_definition("table") is not None
    assert validate_component_payload("not_real", {})[0]["code"] == "UNKNOWN_COMPONENT_TYPE"