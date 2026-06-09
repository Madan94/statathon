"""Phase 1 thin fixtures — validate ExecutionBundle contract shape.

Two MoSPI-representative scenarios:
1. PLFS-simple: Rural/Urban, Male/Female, rate measures
2. Energy-wide: Proved_2024/2025, wide-to-long normalization needed
"""
from report_builder.binding.execution_contracts import (
    CONTRACT_VERSION,
    ExecutionBundle,
    ExecutionReadinessReport,
    FormulaSpec,
    LineageRef,
    NormalizationPlan,
    QuestionExecutionPlan,
    StatisticalContext,
)
from report_builder.binding.schema import (
    BindingAST,
    ColumnProfile,
    DatasetAST,
    EntityBinding,
    BoundColumn,
    QuestionBinding,
    ResolvedFilter,
    ResolvedRoles,
    ResolvedTime,
)


def fixture_plfs_simple() -> ExecutionBundle:
    """PLFS-style: LFPR by sector (Rural/Urban) — direct rate, no normalization."""

    dataset = DatasetAST(
        datasetId="ds_plfs_2025",
        sourceFile="plfs_annual_2024_25.csv",
        rowCount=36,
        archetype="labour_force",
        columns=[
            ColumnProfile(name="State_UT", dtype="string", role="dimension", cardinality=36, sampleValues=["Andhra Pradesh", "Bihar", "Delhi"]),
            ColumnProfile(name="Sector", dtype="string", role="dimension", cardinality=2, sampleValues=["Rural", "Urban"]),
            ColumnProfile(name="Gender", dtype="string", role="dimension", cardinality=3, sampleValues=["Male", "Female", "Person"]),
            ColumnProfile(name="LFPR_ps_ss", dtype="float", role="measure", cardinality=36, unit="percent", minValue=20.1, maxValue=85.3),
            ColumnProfile(name="WPR_ps_ss", dtype="float", role="measure", cardinality=36, unit="percent", minValue=18.5, maxValue=82.1),
            ColumnProfile(name="UR_ps_ss", dtype="float", role="measure", cardinality=36, unit="percent", minValue=0.5, maxValue=12.8),
        ],
    )

    binding = BindingAST(
        templateId="tpl_plfs_annual_v1",
        datasetId="ds_plfs_2025",
        datasetSignature="abc123def456",
        entityBindings=[
            EntityBinding(entityId="ent_lfpr", entityName="LFPR", entityType="measure",
                         columns=[BoundColumn(column="LFPR_ps_ss")], confidence=0.95, method="exact", status="confirmed"),
            EntityBinding(entityId="ent_sector", entityName="Sector", entityType="dimension",
                         columns=[BoundColumn(column="Sector")], confidence=0.98, method="exact", status="confirmed"),
            EntityBinding(entityId="ent_gender", entityName="Gender", entityType="dimension",
                         columns=[BoundColumn(column="Gender")], confidence=0.98, method="exact", status="confirmed"),
        ],
    )

    plan = QuestionExecutionPlan(
        planId="plan_q_lfpr_sector",
        questionId="q_lfpr_01",
        questionText="Compare LFPR across Rural and Urban sectors",
        status="EXECUTABLE",
        analyticsSpec={
            "operation": "group_aggregate",
            "measure": {"column": "LFPR_ps_ss", "agg": "weighted_ratio"},
            "groupBy": [{"column": "Sector"}],
            "filters": [],
            "sort": {"by": "measure", "order": "desc"},
        },
        resolvedRoles=ResolvedRoles(
            measures=["LFPR_ps_ss"],
            dimensions=["Sector"],
            filters=[],
            time=ResolvedTime(timeResolved=False),
        ),
        normalizationPlan=NormalizationPlan(type="NONE"),
        formulaSpec=FormulaSpec(type="DIRECT"),
        outputContract={
            "components": [
                {"kind": "narrative", "maxWords": 90},
                {"kind": "chart", "chartType": "grouped_bar", "xAxis": "Sector", "yAxis": "LFPR_ps_ss"},
            ]
        },
        lineage=LineageRef(
            sourceQuestionId="q_lfpr_01",
            sourceEntityIds=["ent_lfpr", "ent_sector"],
            sourceColumnIds=["LFPR_ps_ss", "Sector"],
        ),
    )

    readiness = ExecutionReadinessReport(executableCount=1, degradedCount=0, blockedCount=0)

    return ExecutionBundle(
        templateId="tpl_plfs_annual_v1",
        datasetId="ds_plfs_2025",
        bindingAstId="bind_plfs_001",
        status="READY",
        datasetAst=dataset,
        bindingAst=binding,
        statisticalContext=StatisticalContext(
            geographyLevel="state_ut",
            timeCoverage=["2024-25"],
            unitRegistry={"LFPR_ps_ss": "percent", "WPR_ps_ss": "percent", "UR_ps_ss": "percent"},
            sourceNotes=["PLFS Annual Report 2024-25"],
            surveyRound="PLFS Annual 2024-25",
        ),
        plans=[plan],
        readinessReport=readiness,
        dataframeRef={"type": "csv", "path": "storage/uploads/plfs_annual_2024_25.csv"},
        frozenAt="2025-06-10T00:00:00Z",
    )


def fixture_energy_wide() -> ExecutionBundle:
    """Energy Statistics-style: wide year columns needing WIDE_TO_LONG normalization."""

    dataset = DatasetAST(
        datasetId="ds_energy_2025",
        sourceFile="energy_ch1_reserves.csv",
        rowCount=30,
        archetype="energy",
        columns=[
            ColumnProfile(name="State_UT", dtype="string", role="dimension", cardinality=30, sampleValues=["Jharkhand", "Odisha", "Chhattisgarh"]),
            ColumnProfile(name="Proved_2024", dtype="float", role="measure", cardinality=28, unit="MT"),
            ColumnProfile(name="Proved_2025", dtype="float", role="measure", cardinality=28, unit="MT"),
            ColumnProfile(name="Indicated_2024", dtype="float", role="measure", cardinality=25, unit="MT"),
            ColumnProfile(name="Indicated_2025", dtype="float", role="measure", cardinality=25, unit="MT"),
            ColumnProfile(name="Inferred_2024", dtype="float", role="measure", cardinality=20, unit="MT"),
            ColumnProfile(name="Inferred_2025", dtype="float", role="measure", cardinality=20, unit="MT"),
        ],
    )

    binding = BindingAST(
        templateId="tpl_energy_ch1",
        datasetId="ds_energy_2025",
        datasetSignature="energy_hash_789",
        entityBindings=[
            EntityBinding(entityId="ent_state", entityName="State/UT", entityType="dimension",
                         columns=[BoundColumn(column="State_UT")], confidence=0.95, method="alias", status="confirmed"),
            EntityBinding(entityId="ent_proved", entityName="Proved Reserves", entityType="measure",
                         cardinality="timeSeries",
                         columns=[BoundColumn(column="Proved_2024", period="2024"), BoundColumn(column="Proved_2025", period="2025")],
                         confidence=0.88, method="synonym", status="confirmed"),
        ],
    )

    # This question REQUIRES normalization: wide year columns → long
    plan = QuestionExecutionPlan(
        planId="plan_q_coal_distribution",
        questionId="q_coal_01",
        questionText="What is the distribution of proved coal reserves by state in 2025?",
        status="EXECUTABLE",
        analyticsSpec={
            "operation": "group_aggregate",
            "measure": {"column": "Proved_2025", "agg": "sum", "unit": "MT"},
            "groupBy": [{"column": "State_UT"}],
            "sort": {"by": "measure", "order": "desc"},
            "topN": 10,
        },
        resolvedRoles=ResolvedRoles(
            measures=["Proved_2025"],
            dimensions=["State_UT"],
        ),
        normalizationPlan=NormalizationPlan(type="NONE"),  # Direct column access for single-year query
        formulaSpec=FormulaSpec(type="DIRECT"),
        outputContract={
            "components": [
                {"kind": "narrative", "maxWords": 90},
                {"kind": "table", "templateRef": "tt_coal_state"},
                {"kind": "chart", "chartType": "grouped_bar", "xAxis": "State_UT", "yAxis": "Proved_2025"},
            ]
        },
        lineage=LineageRef(
            sourceQuestionId="q_coal_01",
            sourceEntityIds=["ent_proved", "ent_state"],
            sourceColumnIds=["Proved_2025", "State_UT"],
            sourceTableId="table_1.1",
        ),
    )

    # Growth rate question — REQUIRES FormulaSpec
    growth_plan = QuestionExecutionPlan(
        planId="plan_q_coal_growth",
        questionId="q_coal_02",
        questionText="What is the year-over-year growth in proved coal reserves by state?",
        status="EXECUTABLE",
        analyticsSpec={
            "operation": "derive",
            "measure": {"column": "growth_proved", "agg": "none", "unit": "percent"},
            "groupBy": [{"column": "State_UT"}],
            "sort": {"by": "measure", "order": "desc"},
        },
        resolvedRoles=ResolvedRoles(
            measures=["Proved_2024", "Proved_2025"],
            dimensions=["State_UT"],
        ),
        normalizationPlan=NormalizationPlan(type="DERIVE_COLUMN",
            expression="(Proved_2025 - Proved_2024) / Proved_2024 * 100",
            outputColumn="growth_proved"),
        formulaSpec=FormulaSpec(
            type="GROWTH",
            numeratorColumn="Proved_2025",
            denominatorColumn="Proved_2024",
            multiplier=100.0,
            unitConversion="percent",
            timeWindow={"current": "2025", "prior": "2024"},
        ),
        outputContract={
            "components": [
                {"kind": "narrative", "maxWords": 90},
                {"kind": "chart", "chartType": "bar", "xAxis": "State_UT", "yAxis": "growth_proved"},
            ]
        },
        lineage=LineageRef(
            sourceQuestionId="q_coal_02",
            sourceEntityIds=["ent_proved", "ent_state"],
            sourceColumnIds=["Proved_2024", "Proved_2025", "State_UT"],
            sourceTableId="table_1.1",
            transformations=["derive:growth"],
        ),
    )

    readiness = ExecutionReadinessReport(executableCount=2, degradedCount=0, blockedCount=0)

    return ExecutionBundle(
        templateId="tpl_energy_ch1",
        datasetId="ds_energy_2025",
        bindingAstId="bind_energy_001",
        status="READY",
        datasetAst=dataset,
        bindingAst=binding,
        statisticalContext=StatisticalContext(
            geographyLevel="state_ut",
            timeCoverage=["2024", "2025"],
            unitRegistry={"Proved_2024": "MT", "Proved_2025": "MT", "Indicated_2024": "MT"},
            sourceNotes=["Energy Statistics India 2025, Chapter 1"],
            footnotes=["As on 1st April 2025"],
            estimateStatus="revised",
            referenceDate="As on 1st April 2025",
        ),
        plans=[plan, growth_plan],
        readinessReport=readiness,
        dataframeRef={"type": "csv", "path": "storage/uploads/energy_ch1_reserves.csv"},
        frozenAt="2025-06-10T00:00:00Z",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Validation: ensure fixtures round-trip correctly
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    print("=" * 70)
    print("FIXTURE 1: PLFS Simple")
    print("=" * 70)
    plfs = fixture_plfs_simple()
    plfs_dict = plfs.to_dict()
    plfs_rt = ExecutionBundle.from_dict(plfs_dict)
    assert plfs_rt.status == "READY"
    assert plfs_rt.templateId == "tpl_plfs_annual_v1"
    assert len(plfs_rt.plans) == 1
    assert plfs_rt.plans[0].status == "EXECUTABLE"
    assert plfs_rt.plans[0].formulaSpec.type == "DIRECT"
    assert plfs_rt.statisticalContext.surveyRound == "PLFS Annual 2024-25"
    print(f"  ✓ Status: {plfs_rt.status}")
    print(f"  ✓ Plans: {len(plfs_rt.plans)} executable")
    print(f"  ✓ Contract: {plfs_rt.contractVersion}")
    print(f"  ✓ Round-trip: OK")
    print(f"  ✓ JSON size: {len(json.dumps(plfs_dict))} bytes")

    print()
    print("=" * 70)
    print("FIXTURE 2: Energy Wide")
    print("=" * 70)
    energy = fixture_energy_wide()
    energy_dict = energy.to_dict()
    energy_rt = ExecutionBundle.from_dict(energy_dict)
    assert energy_rt.status == "READY"
    assert energy_rt.templateId == "tpl_energy_ch1"
    assert len(energy_rt.plans) == 2
    assert energy_rt.plans[1].formulaSpec.type == "GROWTH"
    assert energy_rt.plans[1].normalizationPlan.type == "DERIVE_COLUMN"
    assert energy_rt.statisticalContext.estimateStatus == "revised"
    print(f"  ✓ Status: {energy_rt.status}")
    print(f"  ✓ Plans: {len(energy_rt.plans)} executable")
    print(f"  ✓ Plan[1] formula: {energy_rt.plans[1].formulaSpec.type}")
    print(f"  ✓ Plan[1] normalization: {energy_rt.plans[1].normalizationPlan.type}")
    print(f"  ✓ Statistical context: {energy_rt.statisticalContext.referenceDate}")
    print(f"  ✓ Round-trip: OK")
    print(f"  ✓ JSON size: {len(json.dumps(energy_dict))} bytes")

    print()
    print("=" * 70)
    print("PHASE 1 COMPLETE — All contracts valid")
    print("=" * 70)
