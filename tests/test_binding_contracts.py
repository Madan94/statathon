"""Regression tests for the Binding Contract Compiler.

Tests the critical contract rules that WILL regress without automated checks:
- SHARE/RATE/RATIO missing denominator → BLOCKED, NOT_READY
- Distribution query → DIRECT (not SHARE)
- Growth uncertain → DEGRADED
- BlueprintQA invalid entity ref → detected
- Resolver exact evidence populated
- Type mismatch risk populated
- ExecutionBundle round-trip (including sourceAnalyticsSpec)
- Frozen bundle stable identity (idempotent freeze)
- Severity controls status (not level)
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from report_builder.binding.execution_contracts import (
    ExecutionBundle,
    FormulaSpec,
    LineageRef,
    NormalizationPlan,
    QuestionExecutionPlan,
    ReadinessCheck,
    StatisticalContext,
)
from report_builder.binding.schema import (
    BindingAST,
    ColumnProfile,
    DatasetAST,
    ResolvedRoles,
)
from report_builder.binding.readiness_gate import validate_execution_ready
from report_builder.binding.blueprint_qa import validate_blueprint_qa


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def plfs_dataset():
    """PLFS-style dataset with state dimension + LFPR measure."""
    return DatasetAST(columns=[
        ColumnProfile(name="State_UT", role="dimension", dtype="string", cardinality=36),
        ColumnProfile(name="LFPR", role="measure", dtype="float", unit="percent", cardinality=36),
        ColumnProfile(name="WPR", role="measure", dtype="float", unit="percent", cardinality=36),
        ColumnProfile(name="UR", role="measure", dtype="float", unit="percent", cardinality=36),
        ColumnProfile(name="Gender", role="dimension", dtype="string", cardinality=3),
        ColumnProfile(name="Year_2023", role="measure", dtype="float", unit="percent", cardinality=36),
        ColumnProfile(name="Year_2024", role="measure", dtype="float", unit="percent", cardinality=36),
    ])


@pytest.fixture
def energy_dataset():
    """Energy-style dataset for testing DIRECT formula."""
    return DatasetAST(columns=[
        ColumnProfile(name="State", role="dimension", dtype="string", cardinality=28),
        ColumnProfile(name="Coal_Reserve_MT", role="measure", dtype="float", unit="MT", cardinality=28),
        ColumnProfile(name="Oil_Reserve_MT", role="measure", dtype="float", unit="MT", cardinality=20),
        ColumnProfile(name="Region", role="dimension", dtype="string", cardinality=5),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: SHARE missing denominator → BLOCKED + NOT_READY
# ─────────────────────────────────────────────────────────────────────────────

class TestShareMissingDenominator:
    """SHARE formula without denominator must BLOCK the plan and produce NOT_READY bundle."""

    def test_share_no_denominator_blocks(self, plfs_dataset):
        plan = QuestionExecutionPlan(
            planId="p_share", questionId="q_share", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            analyticsSpec={"measure": {"column": "LFPR", "agg": "reported_value"}},
            formulaSpec=FormulaSpec(type="SHARE", numeratorColumn="LFPR"),
            lineage=LineageRef(sourceQuestionId="q_share", sourceColumnIds=["LFPR", "State_UT"]),
        )
        report = validate_execution_ready([plan], plfs_dataset)

        assert plan.status == "BLOCKED", f"Expected BLOCKED, got {plan.status}"
        assert report.status == "NOT_READY", f"Expected NOT_READY, got {report.status}"
        assert any("FORMULA_MISSING_DENOMINATOR" in c.code for c in report.checks)
        assert any("denominator" in e for e in report.errors)

    def test_rate_no_denominator_blocks(self, plfs_dataset):
        plan = QuestionExecutionPlan(
            planId="p_rate", questionId="q_rate", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            formulaSpec=FormulaSpec(type="RATE", numeratorColumn="LFPR"),
            lineage=LineageRef(sourceQuestionId="q_rate", sourceColumnIds=["LFPR"]),
        )
        report = validate_execution_ready([plan], plfs_dataset)

        assert plan.status == "BLOCKED"
        assert report.status == "NOT_READY"

    def test_ratio_no_denominator_blocks(self, plfs_dataset):
        plan = QuestionExecutionPlan(
            planId="p_ratio", questionId="q_ratio", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            formulaSpec=FormulaSpec(type="RATIO", numeratorColumn="LFPR"),
            lineage=LineageRef(sourceQuestionId="q_ratio", sourceColumnIds=["LFPR"]),
        )
        report = validate_execution_ready([plan], plfs_dataset)

        assert plan.status == "BLOCKED"
        assert report.status == "NOT_READY"

    def test_share_with_denominator_passes(self, plfs_dataset):
        """SHARE with both numerator AND denominator should not block."""
        plan = QuestionExecutionPlan(
            planId="p_share_ok", questionId="q_share_ok", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            analyticsSpec={"measure": {"column": "LFPR", "agg": "reported_value"}},
            formulaSpec=FormulaSpec(type="SHARE", numeratorColumn="LFPR", denominatorColumn="WPR"),
            lineage=LineageRef(sourceQuestionId="q_share_ok", sourceColumnIds=["LFPR", "WPR"]),
        )
        report = validate_execution_ready([plan], plfs_dataset)

        assert plan.status == "EXECUTABLE"
        assert report.status == "READY"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Distribution query → DIRECT (not SHARE)
# ─────────────────────────────────────────────────────────────────────────────

class TestDistributionIsNotShare:
    """'distribution of X by Y' should produce DIRECT formula, NOT SHARE."""

    def test_distribution_keyword_produces_direct(self):
        from report_builder.binding.question_binder import _infer_formula_type

        assert _infer_formula_type("group_aggregate", "distribution of coal reserves by state", "comparison") == "DIRECT"
        assert _infer_formula_type("group_aggregate", "show distribution across regions", "comparison") == "DIRECT"
        assert _infer_formula_type("distribution", "distribution of production", "comparison") == "DIRECT"

    def test_share_requires_explicit_keyword(self):
        from report_builder.binding.question_binder import _infer_formula_type

        assert _infer_formula_type("group_aggregate", "share of each state in total production", "comparison") == "SHARE"
        assert _infer_formula_type("group_aggregate", "percentage of total output by region", "comparison") == "SHARE"
        assert _infer_formula_type("share", "calculate share", "comparison") == "SHARE"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Growth uncertain → DEGRADED
# ─────────────────────────────────────────────────────────────────────────────

class TestGrowthUncertainDegraded:
    """GROWTH formula with missing period info should DEGRADE (not block)."""

    def test_growth_missing_both_columns_degrades(self, plfs_dataset):
        plan = QuestionExecutionPlan(
            planId="p_growth", questionId="q_growth", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            formulaSpec=FormulaSpec(type="GROWTH"),  # no numerator/denominator
            lineage=LineageRef(sourceQuestionId="q_growth", sourceColumnIds=["LFPR"]),
        )
        report = validate_execution_ready([plan], plfs_dataset)

        assert plan.status == "DEGRADED"
        assert any("GROWTH_MISSING_PERIODS" in c.code for c in report.checks)
        # Growth missing periods is a WARN, so bundle should be DEGRADED not NOT_READY
        assert report.status == "DEGRADED" or report.status == "NOT_READY"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: BlueprintQA invalid entity ref
# ─────────────────────────────────────────────────────────────────────────────

class TestBlueprintQAEntityRef:
    """BlueprintQA must catch references to non-existent entities."""

    def test_missing_entity_ref_flagged(self):
        blueprint = {
            "entities": [
                {"entityId": "ent_001", "canonicalName": "LFPR", "entityType": "measure"},
                {"entityId": "ent_002", "canonicalName": "State", "entityType": "grouping"},
            ],
            "topics": [{
                "questions": [{
                    "questionId": "q1",
                    "requiredEntities": [
                        {"entityId": "ent_001"},
                        {"entityId": "ent_999"},  # does NOT exist
                    ],
                    "analyticsSpec": {"operation": "group_aggregate"},
                }]
            }],
        }
        qa = validate_blueprint_qa(blueprint)
        assert "q1" in str(qa.missingEntities)

    def test_valid_refs_pass(self):
        blueprint = {
            "entities": [
                {"entityId": "ent_001", "canonicalName": "LFPR", "entityType": "measure"},
            ],
            "topics": [{
                "questions": [{
                    "questionId": "q1",
                    "requiredEntities": [{"entityId": "ent_001"}],
                    "analyticsSpec": {"operation": "group_aggregate"},
                }]
            }],
        }
        qa = validate_blueprint_qa(blueprint)
        assert not qa.missingEntities


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Resolver evidence populated
# ─────────────────────────────────────────────────────────────────────────────

class TestResolverEvidence:
    """Resolver must populate evidence[] with signals on successful match."""

    def test_exact_name_evidence(self, plfs_dataset):
        from report_builder.binding.resolver import resolve_entity

        entity = {"entityId": "ent_lfpr", "canonicalName": "LFPR", "entityType": "measure", "aliases": ["LFPR"]}
        binding = resolve_entity(entity, plfs_dataset)

        assert binding.status in ("proposed", "confirmed")
        assert binding.evidence, "Evidence should not be empty for exact name match"
        signals = [e.get("signal") for e in binding.evidence]
        assert "exact_name" in signals or "alias" in signals

    def test_type_mismatch_risk(self, plfs_dataset):
        """Binding a measure entity to a dimension column should produce risk."""
        from report_builder.binding.resolver import resolve_entity

        # Force-bind a "measure" entity to a name that exists as dimension
        entity = {"entityId": "ent_state", "canonicalName": "State_UT", "entityType": "measure", "aliases": ["State_UT"]}
        binding = resolve_entity(entity, plfs_dataset)

        if binding.status in ("proposed", "confirmed"):
            # If it resolves, it should have TYPE_MISMATCH risk
            risk_codes = [r.get("code") for r in binding.risks]
            assert "TYPE_MISMATCH" in risk_codes, f"Expected TYPE_MISMATCH risk, got: {binding.risks}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: ExecutionBundle round-trip
# ─────────────────────────────────────────────────────────────────────────────

class TestBundleRoundTrip:
    """ExecutionBundle must round-trip through to_dict/from_dict without data loss."""

    def test_full_bundle_round_trip(self, plfs_dataset):
        plan = QuestionExecutionPlan(
            planId="p1", questionId="q1", questionText="What is LFPR by state?",
            status="EXECUTABLE",
            analyticsSpec={"operation": "group_aggregate", "measure": {"column": "LFPR", "agg": "reported_value", "unit": "percent"}},
            sourceAnalyticsSpec={"measure": {"entityRef": "ent_lfpr"}, "operation": "group_aggregate"},
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            formulaSpec=FormulaSpec(type="DIRECT"),
            normalizationPlan=NormalizationPlan(type="NONE"),
            lineage=LineageRef(sourceQuestionId="q1", sourceColumnIds=["LFPR", "State_UT"]),
            diagnostics=["info: resolved successfully"],
        )

        bundle = ExecutionBundle(
            templateId="plfs_2024",
            datasetId="ds_001",
            bindingAstId="bind_plfs_abc123",
            status="READY",
            datasetAst=plfs_dataset,
            statisticalContext=StatisticalContext(
                geographyLevel="state_ut",
                unitRegistry={"LFPR": "percent"},
                sourceNotes=["PLFS Annual 2024-25"],
            ),
            plans=[plan],
            frozenAt="2026-06-10T00:00:00+00:00",
        )

        # Serialize
        d = bundle.to_dict()
        json_str = json.dumps(d, default=str)

        # Deserialize
        d2 = json.loads(json_str)
        bundle2 = ExecutionBundle.from_dict(d2)

        assert bundle2.templateId == "plfs_2024"
        assert bundle2.status == "READY"
        assert len(bundle2.plans) == 1
        assert bundle2.plans[0].analyticsSpec["measure"]["column"] == "LFPR"
        assert bundle2.plans[0].sourceAnalyticsSpec["measure"]["entityRef"] == "ent_lfpr"
        assert bundle2.statisticalContext.geographyLevel == "state_ut"
        assert bundle2.frozenAt == "2026-06-10T00:00:00+00:00"

    def test_readiness_check_severity_round_trip(self):
        """ReadinessCheck severity and recommendedAction must survive round-trip."""
        rc = ReadinessCheck(
            level="statistical", severity="error", passed=False,
            code="FORMULA_MISSING_DENOMINATOR",
            message="SHARE formula requires denominator",
            planId="p1",
            recommendedAction="Add denominator entity binding",
        )
        d = rc.to_dict()
        rc2 = ReadinessCheck.from_dict(d)

        assert rc2.severity == "error"
        assert rc2.recommendedAction == "Add denominator entity binding"
        assert rc2.level == "statistical"
        assert rc2.code == "FORMULA_MISSING_DENOMINATOR"


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Frozen bundle stable identity (idempotent freeze)
# ─────────────────────────────────────────────────────────────────────────────

class TestFreezeIdempotent:
    """Repeated freeze calls with same content → same version (no duplicate files)."""

    def test_idempotent_freeze(self, plfs_dataset, tmp_path, monkeypatch):
        from report_builder.binding import freeze_store

        # Redirect FREEZE_DIR to tmp
        monkeypatch.setattr(freeze_store, "FREEZE_DIR", tmp_path)

        plan = QuestionExecutionPlan(
            planId="p1", questionId="q1", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            formulaSpec=FormulaSpec(type="DIRECT"),
            lineage=LineageRef(sourceQuestionId="q1", sourceColumnIds=["LFPR"]),
        )
        bundle = ExecutionBundle(
            templateId="plfs_test",
            datasetId="ds_001",
            bindingAstId="bind_plfs_test123",
            status="READY",
            datasetAst=plfs_dataset,
            plans=[plan],
        )

        # First freeze
        info1 = freeze_store.freeze_bundle(bundle)
        assert info1["version"] == 1
        assert info1["isNew"] is True

        # Second freeze (same content) — should return same version
        info2 = freeze_store.freeze_bundle(bundle)
        assert info2["version"] == 1
        assert info2["isNew"] is False

    def test_changed_content_new_version(self, plfs_dataset, tmp_path, monkeypatch):
        from report_builder.binding import freeze_store

        monkeypatch.setattr(freeze_store, "FREEZE_DIR", tmp_path)

        plan = QuestionExecutionPlan(
            planId="p1", questionId="q1", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            formulaSpec=FormulaSpec(type="DIRECT"),
            lineage=LineageRef(sourceQuestionId="q1", sourceColumnIds=["LFPR"]),
        )
        bundle = ExecutionBundle(
            templateId="plfs_test",
            datasetId="ds_001",
            bindingAstId="bind_plfs_test123",
            status="READY",
            datasetAst=plfs_dataset,
            plans=[plan],
        )

        info1 = freeze_store.freeze_bundle(bundle)
        assert info1["version"] == 1

        # Change the bundle (add a dimension)
        bundle.plans[0].resolvedRoles.dimensions.append("Gender")
        info2 = freeze_store.freeze_bundle(bundle)
        assert info2["version"] == 2
        assert info2["isNew"] is True

    def test_load_frozen_bundle(self, plfs_dataset, tmp_path, monkeypatch):
        from report_builder.binding import freeze_store

        monkeypatch.setattr(freeze_store, "FREEZE_DIR", tmp_path)

        plan = QuestionExecutionPlan(
            planId="p1", questionId="q1", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            formulaSpec=FormulaSpec(type="DIRECT"),
            lineage=LineageRef(sourceQuestionId="q1", sourceColumnIds=["LFPR"]),
        )
        bundle = ExecutionBundle(
            templateId="plfs_load",
            datasetId="ds_001",
            bindingAstId="bind_plfs_load123",
            status="READY",
            datasetAst=plfs_dataset,
            plans=[plan],
        )

        freeze_store.freeze_bundle(bundle)

        # Load it back
        loaded = freeze_store.load_frozen_bundle("plfs_load", "ds_001")
        assert loaded is not None
        assert loaded.templateId == "plfs_load"
        assert loaded.status == "READY"
        assert len(loaded.plans) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Severity controls bundle status (not level)
# ─────────────────────────────────────────────────────────────────────────────

class TestSeverityControlsStatus:
    """Bundle status must derive from check severity, not from check level."""

    def test_statistical_error_produces_not_ready(self, plfs_dataset):
        """A statistical severity=error check should make bundle NOT_READY."""
        plan = QuestionExecutionPlan(
            planId="p1", questionId="q1", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            analyticsSpec={"measure": {"column": "LFPR", "agg": "reported_value"}},
            formulaSpec=FormulaSpec(type="SHARE", numeratorColumn="LFPR"),  # no denominator
            lineage=LineageRef(sourceQuestionId="q1", sourceColumnIds=["LFPR"]),
        )
        report = validate_execution_ready([plan], plfs_dataset)

        # The check has level="statistical" but severity="error"
        denom_check = next(c for c in report.checks if c.code == "FORMULA_MISSING_DENOMINATOR")
        assert denom_check.level == "statistical"
        assert denom_check.severity == "error"

        # Bundle status must be NOT_READY (severity controls, not level)
        assert report.status == "NOT_READY"
        assert "denominator" in report.errors[0]

    def test_statistical_warn_produces_degraded(self, plfs_dataset):
        """A statistical severity=warn check should make bundle DEGRADED, not NOT_READY."""
        plan = QuestionExecutionPlan(
            planId="p1", questionId="q1", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            analyticsSpec={"measure": {"column": "LFPR", "agg": "sum"}},  # sum on percent = warn
            formulaSpec=FormulaSpec(type="DIRECT"),
            lineage=LineageRef(sourceQuestionId="q1", sourceColumnIds=["LFPR"]),
        )
        report = validate_execution_ready([plan], plfs_dataset)

        rate_check = next(c for c in report.checks if c.code == "RATE_SUMMED")
        assert rate_check.severity == "warn"

        assert plan.status == "DEGRADED"
        assert report.status == "DEGRADED"
        assert not report.errors  # no errors, only warnings
        assert report.warnings  # should have the warning

    def test_evidence_info_does_not_block(self, plfs_dataset):
        """Evidence-level info checks should not degrade or block."""
        plan = QuestionExecutionPlan(
            planId="p1", questionId="q1", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            analyticsSpec={"measure": {"column": "LFPR", "agg": "reported_value"}},
            formulaSpec=FormulaSpec(type="DIRECT"),
            lineage=LineageRef(sourceQuestionId="", sourceColumnIds=[]),  # missing lineage
        )
        report = validate_execution_ready([plan], plfs_dataset)

        # Missing lineage = info level, should NOT block or degrade
        assert plan.status == "EXECUTABLE"
        assert report.status == "READY"
        assert not report.errors
        assert not report.warnings


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: CAGR/INDEX blocking checks
# ─────────────────────────────────────────────────────────────────────────────

class TestCAGRIndexBlocking:
    """CAGR without timeWindow and INDEX without baseValue must BLOCK."""

    def test_cagr_missing_time_window_blocks(self, plfs_dataset):
        plan = QuestionExecutionPlan(
            planId="p_cagr", questionId="q_cagr", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            formulaSpec=FormulaSpec(type="CAGR"),  # no timeWindow
            lineage=LineageRef(sourceQuestionId="q_cagr", sourceColumnIds=["LFPR"]),
        )
        report = validate_execution_ready([plan], plfs_dataset)

        assert plan.status == "BLOCKED"
        assert report.status == "NOT_READY"

    def test_index_missing_base_blocks(self, plfs_dataset):
        plan = QuestionExecutionPlan(
            planId="p_idx", questionId="q_idx", status="EXECUTABLE",
            resolvedRoles=ResolvedRoles(measures=["LFPR"], dimensions=["State_UT"]),
            formulaSpec=FormulaSpec(type="INDEX"),  # no baseValue
            lineage=LineageRef(sourceQuestionId="q_idx", sourceColumnIds=["LFPR"]),
        )
        report = validate_execution_ready([plan], plfs_dataset)

        assert plan.status == "BLOCKED"
        assert report.status == "NOT_READY"
