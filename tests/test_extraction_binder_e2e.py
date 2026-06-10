"""E13 — Extraction→Binder E2E Integration Tests.

Proves that extraction artifacts can flow into the binder and produce
an ExecutionBundle. Tests in two stages:

E13A: Energy gold blueprint → Binder → ExecutionBundle
E13B: Current generated output → diagnostics baseline comparison
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

GOLD_DIR = Path(__file__).parent.parent / "report_builder" / "gold_standard"
TEST_DATA = Path(__file__).parent.parent / "test_data"
OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "syl_payaluga"


@pytest.fixture
def energy_blueprint():
    return json.loads((GOLD_DIR / "energy.template.blueprint.json").read_text(encoding="utf-8"))


@pytest.fixture
def energy_ast():
    return json.loads((GOLD_DIR / "energy.template.ast.json").read_text(encoding="utf-8"))


@pytest.fixture
def energy_dataframe():
    csv_path = TEST_DATA / "unified_energy_reserves_dataset.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path)
    # Fallback: minimal synthetic dataframe matching gold entities
    return pd.DataFrame({
        "State": ["Jharkhand", "Odisha", "Chhattisgarh", "West Bengal", "Madhya Pradesh"],
        "Proved_Reserves": [671, 520, 430, 310, 290],
        "Indicated_Reserves": [329, 210, 180, 150, 130],
        "Inferred_Reserves": [98, 70, 55, 40, 35],
        "Total_Reserves": [1098, 800, 665, 500, 455],
        "Distribution_Percent": [26.5, 19.3, 16.0, 12.1, 11.0],
        "Wind_Power_MW": [0, 0, 0, 0, 2931],
        "Solar_Energy_MW": [18180, 25000, 18270, 6260, 61660],
    })


@pytest.fixture
def dataset_ast(energy_dataframe):
    """Profile the energy dataframe into a DatasetAST."""
    from report_builder.binding.schema import DatasetAST, ColumnProfile

    df = energy_dataframe
    columns = []
    for col_name in df.columns:
        dtype = "float" if df[col_name].dtype in ("int64", "float64") else "string"
        role = "dimension" if dtype == "string" else "measure"
        if col_name.lower() in ("site_id", "id"):
            role = "id"
        cardinality = int(df[col_name].nunique())

        # Detect unit from column name
        unit = None
        col_low = col_name.lower()
        if "percent" in col_low or "distribution" in col_low:
            unit = "percent"
        elif "mw" in col_low or "power" in col_low or "energy" in col_low or "potential" in col_low:
            unit = "MW"
        elif "reserve" in col_low or "total" in col_low:
            unit = "million_tonnes"

        columns.append(ColumnProfile(
            name=col_name,
            role=role,
            dtype=dtype,
            cardinality=cardinality,
            unit=unit,
        ))

    return DatasetAST(columns=columns)


# ═══════════════════════════════════════════════════════════════════════════════
# E13A: Gold → Binder → ExecutionBundle
# ═══════════════════════════════════════════════════════════════════════════════


class TestEnergyGoldBinderQA:
    """Gold blueprint passes binder BlueprintQA."""

    def test_blueprint_qa_not_invalid(self, energy_blueprint):
        from report_builder.binding.blueprint_qa import validate_blueprint_qa
        qa = validate_blueprint_qa(energy_blueprint)
        assert qa.status != "INVALID", f"BlueprintQA failed: {qa.errors}"


class TestEnergyGoldEntityResolution:
    """Gold entities can be resolved against the energy dataset."""

    def test_resolver_proposes_bindings(self, energy_blueprint, dataset_ast):
        from report_builder.binding.resolver import resolve_entities

        entities = energy_blueprint.get("entities", [])
        bindings = resolve_entities(entities, dataset_ast)

        assert len(bindings) > 0, "No bindings produced"

        # Count proposed (at least some should match)
        proposed = [b for b in bindings if b.status in ("proposed", "confirmed")]
        print(f"  Bindings: {len(bindings)} total, {len(proposed)} proposed")

        # Core entities should bind
        bound_ids = {b.entityId for b in proposed}
        # At least State and some reserve measures should bind
        assert any("state" in eid.lower() or "State" in (b.entityName or "") for b, eid in zip(bindings, [b.entityId for b in bindings]) if b.status == "proposed"), \
            "State/UT entity should bind"

        for b in proposed[:5]:
            print(f"    {b.entityId}: {b.column_names} conf={b.confidence:.2f}")

    def test_resolver_has_evidence(self, energy_blueprint, dataset_ast):
        from report_builder.binding.resolver import resolve_entities

        entities = energy_blueprint.get("entities", [])
        bindings = resolve_entities(entities, dataset_ast)
        proposed = [b for b in bindings if b.status == "proposed"]

        # At least some should have evidence
        with_evidence = [b for b in proposed if b.evidence]
        assert len(with_evidence) > 0, "No bindings have evidence"


class TestEnergyGoldQuestionBinding:
    """Gold questions can be bound using resolved entities."""

    def test_questions_bind(self, energy_blueprint, dataset_ast):
        from report_builder.binding.resolver import resolve_entities
        from report_builder.binding.question_binder import bind_questions

        entities = energy_blueprint.get("entities", [])
        bindings = resolve_entities(entities, dataset_ast)

        # Auto-confirm all proposed for test
        for b in bindings:
            if b.status == "proposed":
                b.status = "confirmed"

        question_bindings = bind_questions(energy_blueprint, bindings, dataset_ast)

        assert len(question_bindings) > 0, "No question bindings produced"

        executable = [qb for qb in question_bindings if qb.status == "executable"]
        degraded = [qb for qb in question_bindings if qb.status == "degraded"]
        blocked = [qb for qb in question_bindings if qb.status == "blocked"]

        print(f"  Questions: {len(question_bindings)} total")
        print(f"    executable={len(executable)} degraded={len(degraded)} blocked={len(blocked)}")

        # At least some should be executable or degraded
        assert len(executable) + len(degraded) > 0, \
            f"All questions blocked: {[qb.questionId for qb in blocked]}"


class TestEnergyGoldPlanCompilation:
    """Gold questions compile into QuestionExecutionPlans."""

    def test_plans_compile(self, energy_blueprint, dataset_ast):
        from report_builder.binding.resolver import resolve_entities
        from report_builder.binding.question_binder import bind_questions, compile_execution_plans

        entities = energy_blueprint.get("entities", [])
        bindings = resolve_entities(entities, dataset_ast)
        for b in bindings:
            if b.status == "proposed":
                b.status = "confirmed"

        question_bindings = bind_questions(energy_blueprint, bindings, dataset_ast)
        plans = compile_execution_plans(energy_blueprint, question_bindings, dataset_ast)

        assert len(plans) > 0, "No execution plans produced"

        for plan in plans[:3]:
            print(f"    plan={plan.planId} status={plan.status} spec={list(plan.analyticsSpec.keys())}")
            assert plan.analyticsSpec.get("operation"), f"Plan {plan.planId} missing operation"
            assert plan.lineage.sourceQuestionId, f"Plan {plan.planId} missing lineage"


class TestEnergyGoldReadinessGate:
    """Readiness gate runs on compiled plans."""

    def test_readiness_report(self, energy_blueprint, dataset_ast):
        from report_builder.binding.resolver import resolve_entities
        from report_builder.binding.question_binder import bind_questions, compile_execution_plans
        from report_builder.binding.readiness_gate import validate_execution_ready

        entities = energy_blueprint.get("entities", [])
        bindings = resolve_entities(entities, dataset_ast)
        for b in bindings:
            if b.status == "proposed":
                b.status = "confirmed"

        question_bindings = bind_questions(energy_blueprint, bindings, dataset_ast)
        plans = compile_execution_plans(energy_blueprint, question_bindings, dataset_ast)
        report = validate_execution_ready(plans, dataset_ast)

        print(f"  Readiness: exec={report.executableCount} degraded={report.degradedCount} blocked={report.blockedCount}")
        print(f"  Status: {report.status}")
        print(f"  Errors: {len(report.errors)} Warnings: {len(report.warnings)}")

        # Not all should be blocked
        assert report.executableCount + report.degradedCount > 0, \
            f"All plans blocked. Errors: {report.errors}"


class TestEnergyGoldExecutionBundle:
    """Full ExecutionBundle can be produced from gold."""

    def test_bundle_produced(self, energy_blueprint, dataset_ast, energy_dataframe):
        from report_builder.binding.resolver import resolve_entities
        from report_builder.binding.question_binder import bind_questions, compile_execution_plans
        from report_builder.binding.readiness_gate import validate_execution_ready
        from report_builder.binding.execution_contracts import ExecutionBundle, StatisticalContext

        entities = energy_blueprint.get("entities", [])
        bindings = resolve_entities(entities, dataset_ast)
        for b in bindings:
            if b.status == "proposed":
                b.status = "confirmed"

        question_bindings = bind_questions(energy_blueprint, bindings, dataset_ast)
        plans = compile_execution_plans(energy_blueprint, question_bindings, dataset_ast)
        readiness = validate_execution_ready(plans, dataset_ast)

        # Build a minimal bundle
        bundle = ExecutionBundle(
            templateId="tpl_energy_statistics_ch1_v1",
            datasetId="unified_energy_reserves",
            bindingAstId="bind_test_energy",
            status=readiness.status if readiness.status != "NOT_READY" else "DEGRADED",
            datasetAst=dataset_ast,
            plans=plans,
            readinessReport=readiness,
            statisticalContext=StatisticalContext(
                geographyLevel="state_ut",
                sourceNotes=["Energy Statistics India 2025"],
            ),
        )

        assert bundle.templateId == "tpl_energy_statistics_ch1_v1"
        assert len(bundle.plans) > 0
        assert bundle.readinessReport is not None

        # Serialize test
        d = bundle.to_dict()
        assert "plans" in d
        assert len(d["plans"]) > 0

        print(f"  Bundle: status={bundle.status} plans={len(bundle.plans)}")
        print(f"  Executable: {bundle.readinessReport.executableCount}")
        print(f"  Degraded: {bundle.readinessReport.degradedCount}")
        print(f"  Blocked: {bundle.readinessReport.blockedCount}")


# ═══════════════════════════════════════════════════════════════════════════════
# E13B: Current Generated Output Baseline
# ═══════════════════════════════════════════════════════════════════════════════


class TestCurrentGeneratedBaseline:
    """Measure current generated output against gold standard."""

    @pytest.fixture
    def generated_blueprint(self):
        path = OUTPUTS_DIR / "template.blueprint.json"
        if not path.exists():
            pytest.skip("No generated output at outputs/syl_payaluga/")
        return json.loads(path.read_text(encoding="utf-8"))

    @pytest.fixture
    def generated_ast(self):
        path = OUTPUTS_DIR / "template.ast.json"
        if not path.exists():
            pytest.skip("No generated AST at outputs/syl_payaluga/")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_generated_diagnostics(self, generated_blueprint, generated_ast):
        """Generate diagnostics for current output and compare to gold."""
        from report_builder.extraction_contracts import validate_extraction_contract, ExtractionMode
        from report_builder.value_free_validator import validate_value_free
        from report_builder.extraction_diagnostics import build_extraction_diagnostics

        contract = validate_extraction_contract(generated_blueprint, mode=ExtractionMode.WARN)
        vf = validate_value_free(generated_ast, generated_blueprint)

        diag = build_extraction_diagnostics(
            blueprint=generated_blueprint,
            skeleton=generated_ast,
            contract_result=contract,
            value_free_result=vf,
        )

        print(f"\n  Generated output diagnostics:")
        print(f"    Status: {diag.status}")
        print(f"    Score: {diag.binderReadinessScore:.3f}")
        print(f"    Recommendation: {diag.binderCompatibility.recommendation}")
        print(f"    Categories: {', '.join(f'{k}={v:.2f}' for k, v in diag.categoryScores.items())}")

        # Gold score should be higher
        gold_score = 0.92  # From energy.diagnostics.json
        print(f"    Gold score: {gold_score}")
        print(f"    Gap: {gold_score - diag.binderReadinessScore:.3f}")

        assert diag.binderReadinessScore < gold_score, \
            "Generated should score lower than gold (if equal, gold is too easy)"

    def test_generated_contract(self, generated_blueprint):
        """Contract validation produces actionable diagnostics."""
        from report_builder.extraction_contracts import validate_extraction_contract, ExtractionMode

        result = validate_extraction_contract(generated_blueprint, mode=ExtractionMode.WARN)

        print(f"\n  Contract: {result.status}")
        print(f"    Errors: {len(result.errors)}")
        print(f"    Warnings: {len(result.warnings)}")
        if result.warnings:
            for w in result.warnings[:5]:
                print(f"      [{w.code}] {w.message[:60]}")

        # Should produce useful output (not crash)
        assert result.status in ("VALID", "VALID_WITH_WARNINGS", "INVALID")

    def test_generated_value_free(self, generated_ast, generated_blueprint):
        """Value-free validation on generated output."""
        from report_builder.value_free_validator import validate_value_free

        result = validate_value_free(generated_ast, generated_blueprint)
        print(f"\n  Value-free: {result.status} (leakages={len(result.leakages)})")

        # Current template_emit.py already clears values, so should pass
        assert result.status == "VALID", f"Leakages: {[l.code for l in result.leakages]}"
