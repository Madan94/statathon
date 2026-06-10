"""Regression tests for Energy Gold Standard.

Validates that gold files pass all extraction validators:
- Extraction contract (E0)
- Value-free validator (E12)
- Slot wiring (E8)
- Diagnostics scoring (E9)
- Binder BlueprintQA compatibility
"""
import json
import re
from pathlib import Path

import pytest

GOLD_DIR = Path(__file__).parent.parent / "report_builder" / "gold_standard"


@pytest.fixture
def energy_blueprint():
    return json.loads((GOLD_DIR / "energy.template.blueprint.json").read_text(encoding="utf-8"))


@pytest.fixture
def energy_ast():
    return json.loads((GOLD_DIR / "energy.template.ast.json").read_text(encoding="utf-8"))


@pytest.fixture
def energy_diagnostics():
    return json.loads((GOLD_DIR / "energy.diagnostics.json").read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# E0: Extraction Contract
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractionContract:
    def test_contract_not_invalid(self, energy_blueprint):
        from report_builder.extraction_contracts import validate_extraction_contract, ExtractionMode
        result = validate_extraction_contract(energy_blueprint, mode=ExtractionMode.STRICT)
        assert result.status != "INVALID", f"Contract errors: {[e.code for e in result.errors]}"

    def test_no_sequential_ids(self, energy_blueprint):
        for ent in energy_blueprint["entities"]:
            eid = ent["entityId"]
            assert not re.match(r"^ent_\d{2,}$", eid), f"Sequential ID: {eid}"

    def test_entities_have_type(self, energy_blueprint):
        valid_types = {"measure", "dimension", "time", "filter", "metadata"}
        for ent in energy_blueprint["entities"]:
            assert ent["entityType"] in valid_types, f"{ent['entityId']} has invalid type"


# ─────────────────────────────────────────────────────────────────────────────
# E12: Value-Free
# ─────────────────────────────────────────────────────────────────────────────

class TestValueFree:
    def test_skeleton_value_free(self, energy_ast, energy_blueprint):
        from report_builder.value_free_validator import validate_value_free
        result = validate_value_free(energy_ast, energy_blueprint)
        assert result.status == "VALID", f"Leakages: {[l.code for l in result.leakages]}"

    def test_no_table_rows(self, energy_ast):
        for table in energy_ast.get("tableAST", {}).get("tables", []):
            assert table.get("rows") == [], f"Table {table.get('tableId')} has rows"

    def test_no_chart_series(self, energy_ast):
        for chart in energy_ast.get("chartAST", {}).get("charts", []):
            assert chart.get("series") == [], f"Chart {chart.get('chartId')} has series"

    def test_content_blocks_empty(self, energy_ast):
        for block in energy_ast.get("contentAST", {}).get("blocks", []):
            assert block.get("content") == "", f"Block {block.get('blockId')} has content"


# ─────────────────────────────────────────────────────────────────────────────
# Entity Quality
# ─────────────────────────────────────────────────────────────────────────────

class TestEntityQuality:
    def test_semantic_ids(self, energy_blueprint):
        for ent in energy_blueprint["entities"]:
            assert not re.match(r"^ent_\d+$", ent["entityId"])
            assert ent["entityId"].startswith("ent_")

    def test_measures_have_aliases(self, energy_blueprint):
        measures = [e for e in energy_blueprint["entities"] if e["entityType"] == "measure"]
        for m in measures:
            assert len(m.get("aliases", [])) >= 2, f"{m['entityId']} has < 2 aliases"

    def test_measures_have_units(self, energy_blueprint):
        measures = [e for e in energy_blueprint["entities"] if e["entityType"] == "measure"]
        for m in measures:
            assert m.get("unit"), f"{m['entityId']} missing unit"

    def test_period_entity_exists(self, energy_blueprint):
        ids = {e["entityId"] for e in energy_blueprint["entities"]}
        assert "ent_period" in ids

    def test_period_has_members(self, energy_blueprint):
        period = next(e for e in energy_blueprint["entities"] if e["entityId"] == "ent_period")
        members = period.get("valueDomain", {}).get("members", [])
        assert "2024" in members and "2025" in members

    def test_measure_families_present(self, energy_blueprint):
        families = energy_blueprint.get("measureFamilies", [])
        assert len(families) >= 2
        family_ids = {f["familyId"] for f in families}
        assert "mf_reserves_by_category" in family_ids
        assert "mf_renewable_potential_by_source" in family_ids

    def test_total_marked(self, energy_blueprint):
        total = next((e for e in energy_blueprint["entities"] if e["entityId"] == "ent_total_reserves"), None)
        assert total is not None
        assert total.get("isTotal") is True

    def test_distribution_marked_derived(self, energy_blueprint):
        dist = next((e for e in energy_blueprint["entities"] if e["entityId"] == "ent_distribution_percent"), None)
        assert dist is not None
        assert dist.get("isDerived") is True
        assert dist.get("aggregation") == "reported_value"


# ─────────────────────────────────────────────────────────────────────────────
# Table Templates
# ─────────────────────────────────────────────────────────────────────────────

class TestTableTemplates:
    def test_table_templates_exist(self, energy_blueprint):
        templates = energy_blueprint.get("tableTemplates", [])
        assert len(templates) >= 3

    def test_coal_table_has_column_groups(self, energy_blueprint):
        coal = next(t for t in energy_blueprint["tableTemplates"] if t["tableId"] == "tt_coal_reserves_state")
        assert len(coal.get("columnGroups", [])) >= 4

    def test_measure_columns_have_header_path(self, energy_blueprint):
        for template in energy_blueprint["tableTemplates"]:
            for col in template.get("columns", []):
                if col.get("role") == "measure":
                    assert col.get("headerPath"), f"Column {col.get('columnId')} missing headerPath"

    def test_coal_table_has_periods(self, energy_blueprint):
        coal = next(t for t in energy_blueprint["tableTemplates"] if t["tableId"] == "tt_coal_reserves_state")
        all_periods = []
        for g in coal.get("columnGroups", []):
            all_periods.extend(g.get("periods", []))
        assert "2024" in all_periods and "2025" in all_periods

    def test_normalization_advice(self, energy_blueprint):
        coal = next(t for t in energy_blueprint["tableTemplates"] if t["tableId"] == "tt_coal_reserves_state")
        assert coal.get("normalizationAdvice") == "WIDE_TO_LONG"


# ─────────────────────────────────────────────────────────────────────────────
# Questions
# ─────────────────────────────────────────────────────────────────────────────

class TestQuestions:
    def _all_questions(self, bp):
        qs = []
        for topic in bp.get("topics", []):
            qs.extend(topic.get("questions", []))
        return qs

    def test_questions_exist(self, energy_blueprint):
        assert len(self._all_questions(energy_blueprint)) >= 5

    def test_questions_have_analytics_spec(self, energy_blueprint):
        for q in self._all_questions(energy_blueprint):
            assert q.get("analyticsSpec", {}).get("operation"), f"{q['questionId']} missing operation"

    def test_questions_have_answer_structure(self, energy_blueprint):
        for q in self._all_questions(energy_blueprint):
            components = q.get("answerStructure", {}).get("components", [])
            assert components, f"{q['questionId']} has no components"

    def test_required_entities_resolve(self, energy_blueprint):
        entity_ids = {e["entityId"] for e in energy_blueprint["entities"]}
        for q in self._all_questions(energy_blueprint):
            for req in q.get("requiredEntities", []):
                eid = req.get("entityId", "")
                assert eid in entity_ids, f"{q['questionId']} references missing entity {eid}"

    def test_questions_have_formula_intent(self, energy_blueprint):
        for q in self._all_questions(energy_blueprint):
            assert q.get("formulaIntent"), f"{q['questionId']} missing formulaIntent"


# ─────────────────────────────────────────────────────────────────────────────
# Slot Wiring
# ─────────────────────────────────────────────────────────────────────────────

class TestSlotWiring:
    def test_wiring_validates(self, energy_ast, energy_blueprint):
        from report_builder.slot_wiring import validate_wiring
        issues = validate_wiring(energy_ast, energy_blueprint)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0, f"Wiring errors: {[(e.code, e.message) for e in errors]}"


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ─────────────────────────────────────────────────────────────────────────────

class TestDiagnostics:
    def test_diagnostics_valid(self, energy_diagnostics):
        assert energy_diagnostics["status"] == "VALID"

    def test_binder_readiness_high(self, energy_diagnostics):
        assert energy_diagnostics["binderReadinessScore"] >= 0.85

    def test_recommendation_proceed(self, energy_diagnostics):
        assert energy_diagnostics["binderCompatibility"]["recommendation"] == "proceed"

    def test_value_free_compliance(self, energy_diagnostics):
        assert energy_diagnostics["categoryScores"]["valueFreeCompliance"] == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Binder BlueprintQA Compatibility
# ─────────────────────────────────────────────────────────────────────────────

class TestBinderCompatibility:
    def test_blueprint_qa_not_invalid(self, energy_blueprint):
        from report_builder.extraction_contracts import validate_extraction_contract, ExtractionMode
        result = validate_extraction_contract(energy_blueprint, mode=ExtractionMode.WARN)
        assert result.status != "INVALID", f"Errors: {[e.code for e in result.errors]}"
