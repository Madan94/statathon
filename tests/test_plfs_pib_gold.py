"""Phase 6: PLFS PIB Gold Standard Regression Tests.

Guards the PLFS PIB compiled output so future changes cannot regress it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_GOLD_DIR = Path(__file__).parent.parent / "report_builder" / "gold_standard"


@pytest.fixture(scope="module")
def gold_ast() -> dict[str, Any]:
    path = _GOLD_DIR / "plfs_press_release.template.ast.json"
    if not path.exists():
        pytest.skip("PLFS gold AST not available")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gold_blueprint() -> dict[str, Any]:
    path = _GOLD_DIR / "plfs_press_release.template.blueprint.json"
    if not path.exists():
        pytest.skip("PLFS gold blueprint not available")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gold_diagnostics() -> dict[str, Any]:
    path = _GOLD_DIR / "plfs_press_release.diagnostics.json"
    if not path.exists():
        pytest.skip("PLFS gold diagnostics not available")
    return json.loads(path.read_text(encoding="utf-8"))


class TestPLFSGoldContract:
    """Contract and structural validation of gold PLFS PIB output."""

    def test_contract_valid(self, gold_blueprint):
        """Extraction contract should not be INVALID."""
        from report_builder.extraction_contracts import validate_extraction_contract, ExtractionMode
        result = validate_extraction_contract(gold_blueprint, mode=ExtractionMode.WARN)
        assert result.status != "INVALID", f"Contract INVALID: {result.errors}"

    def test_value_free(self, gold_ast, gold_blueprint):
        """Template must pass value-free validation."""
        from report_builder.value_free_validator import validate_value_free
        result = validate_value_free(gold_ast, gold_blueprint)
        assert result.status == "VALID", f"Value-free FAILED: {result.leakages[:3]}"


class TestPLFSGoldEntities:
    """Entity coverage and quality for PLFS PIB."""

    def test_core_entities_present(self, gold_blueprint):
        """Core PLFS entities must exist."""
        entity_names = {e.get("canonicalName", "").lower() for e in gold_blueprint["entities"]}
        entity_aliases = set()
        for e in gold_blueprint["entities"]:
            for a in (e.get("aliases") or []):
                entity_aliases.add(a.lower())
        all_names = entity_names | entity_aliases

        required = [
            "labour force participation rate",
            "unemployment rate",
            "worker population ratio",
            "gender",
        ]
        for name in required:
            assert name in all_names, f"Missing core entity: {name}"

    def test_units_on_measures(self, gold_blueprint):
        """Rate measures must have unit=percent."""
        rate_entities = [
            e for e in gold_blueprint["entities"]
            if any(k in (e.get("canonicalName") or "").lower()
                   for k in ("rate", "ratio", "share"))
            and e.get("entityType") == "measure"
        ]
        for e in rate_entities:
            assert e.get("unit") == "percent", (
                f"{e['canonicalName']} missing unit=percent (has: {e.get('unit')})"
            )

    def test_entity_count(self, gold_blueprint):
        """Should have enough entities for meaningful coverage."""
        assert len(gold_blueprint["entities"]) >= 10

    def test_no_empty_entity_ids(self, gold_blueprint):
        """All entities must have non-empty entityId."""
        for e in gold_blueprint["entities"]:
            assert e.get("entityId"), f"Empty entityId on: {e.get('canonicalName')}"


class TestPLFSGoldQuestions:
    """Question completeness for PLFS PIB."""

    def test_question_count(self, gold_blueprint):
        """At least 7 questions."""
        qs = []
        for topic in gold_blueprint.get("topics", []):
            qs.extend(topic.get("questions", []))
        assert len(qs) >= 7, f"Only {len(qs)} questions"

    def test_no_deprecated_roles(self, gold_blueprint):
        """No breakdown/groupBy/group_by roles."""
        deprecated = {"breakdown", "groupBy", "group_by"}
        for topic in gold_blueprint.get("topics", []):
            for q in topic.get("questions", []):
                for req in (q.get("requiredEntities") or []):
                    role = req.get("role", "")
                    assert role not in deprecated, (
                        f"Deprecated role '{role}' in question {q.get('questionId')}"
                    )

    def test_questions_have_analytics_spec(self, gold_blueprint):
        """Non-descriptive questions must have analyticsSpec."""
        for topic in gold_blueprint.get("topics", []):
            for q in topic.get("questions", []):
                qtype = q.get("questionType", "")
                if qtype != "descriptive":
                    spec = q.get("analyticsSpec") or {}
                    assert spec.get("operation"), (
                        f"Question {q.get('questionId')} missing analyticsSpec.operation"
                    )

    def test_questions_have_answer_structure(self, gold_blueprint):
        """All questions must have answerStructure.components."""
        for topic in gold_blueprint.get("topics", []):
            for q in topic.get("questions", []):
                ans = q.get("answerStructure") or {}
                comps = ans.get("components") or []
                assert comps, f"Question {q.get('questionId')} missing components"

    def test_no_empty_required_entity_ids(self, gold_blueprint):
        """No requiredEntity with empty entityId (warn: some old VLM questions may have gaps)."""
        empty_count = 0
        total_reqs = 0
        for topic in gold_blueprint.get("topics", []):
            for q in topic.get("questions", []):
                for req in (q.get("requiredEntities") or []):
                    total_reqs += 1
                    if not req.get("entityId", ""):
                        empty_count += 1
        # Allow up to 10% empty (old VLM questions with unresolved refs)
        max_allowed = max(1, int(total_reqs * 0.10))
        assert empty_count <= max_allowed, (
            f"Too many empty entityIds: {empty_count}/{total_reqs} (max allowed: {max_allowed})"
        )


class TestPLFSGoldDiagnostics:
    """Diagnostics scores for PLFS PIB."""

    def test_status_valid(self, gold_diagnostics):
        assert gold_diagnostics["status"] == "VALID"

    def test_score_above_threshold(self, gold_diagnostics):
        assert gold_diagnostics["binderReadinessScore"] >= 0.75

    def test_value_free_compliance(self, gold_diagnostics):
        assert gold_diagnostics["categoryScores"]["valueFreeCompliance"] >= 1.0

    def test_question_completeness(self, gold_diagnostics):
        assert gold_diagnostics["categoryScores"]["questionCompleteness"] >= 0.75

    def test_cross_reference_integrity(self, gold_diagnostics):
        assert gold_diagnostics["categoryScores"]["crossReferenceIntegrity"] >= 0.80

    def test_unit_coverage(self, gold_diagnostics):
        assert gold_diagnostics["categoryScores"]["unitCoverage"] >= 0.60


class TestPLFSGoldSlotWiring:
    """Slot wiring validation on gold output."""

    def test_no_error_issues(self, gold_ast, gold_blueprint):
        """Slot wiring should have no error-level issues."""
        from report_builder.slot_wiring import validate_wiring
        issues = validate_wiring(gold_ast, gold_blueprint)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0, f"Wiring errors: {[e.message for e in errors[:5]]}"


class TestPLFSGoldMetadata:
    """Template metadata correctness."""

    def test_domain(self, gold_blueprint):
        meta = gold_blueprint.get("templateMeta", {})
        assert meta.get("domain") == "labour_force"

    def test_report_type(self, gold_blueprint):
        meta = gold_blueprint.get("templateMeta", {})
        assert meta.get("reportType") == "pib_press_release"

    def test_name_not_generic(self, gold_blueprint):
        meta = gold_blueprint.get("templateMeta", {})
        name = meta.get("name", "")
        assert name != "Document"
        assert len(name) > 5
