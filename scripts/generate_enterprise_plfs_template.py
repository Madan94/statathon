"""Generate the built-in MoSPI PLFS enterprise template package.

The output is value-free: it defines report structure, entities, questions,
component contracts, and slot wiring, but no data values or generated prose.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TEMPLATE_ID = "tpl_mospi_plfs_enterprise_annual_v1"
TEMPLATE_VERSION = "1.1.0"
TEMPLATE_NAME = "MoSPI PLFS Annual Enterprise Report"
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "report_builder" / "gold_standard"


def measure(
    entity_id: str,
    name: str,
    aliases: list[str],
    unit: str,
    aggregation: str,
    *,
    fmt: str = "number.1",
    scope: str = "indicator",
) -> dict[str, Any]:
    value_domain = {"kind": "ratio", "min": 0, "max": 100} if unit == "percent" else {"kind": "open"}
    return {
        "entityId": entity_id,
        "canonicalName": name,
        "entityType": "measure",
        "aliases": aliases,
        "unit": unit,
        "format": fmt,
        "valueDomain": value_domain,
        "aggregation": aggregation,
        "aggregationPolicy": {
            "default": aggregation,
            "allowed": [aggregation, "reported_value"] if aggregation != "reported_value" else ["reported_value"],
            "disallow": ["sum"] if unit in {"percent", "percentage_points"} else [],
            "notes": "Percentages and rates must use reported values or same-grain numerator/denominator formulas; never sum or average row-level ratios.",
        },
        "scope": scope,
        "conceptFamily": "labour_market_measure" if scope != "weight" else "survey_design_weight",
        "dataRole": "indicator" if scope != "weight" else "weight",
        "binderHints": {
            "matchPriority": aliases,
            "requiresUnitEvidence": True,
            "unitSynonyms": [unit, "%"] if unit == "percent" else [unit],
            "preferExactAlias": True,
        },
        "qualityRules": [
            {"ruleId": f"qr_{entity_id}_non_null", "severity": "warn", "condition": "non_null_rate >= 0.90"},
            {"ruleId": f"qr_{entity_id}_unit", "severity": "error", "condition": "unit_or_header_confirms_measure"},
        ],
        "evidenceRequirements": ["column_header", "unit_or_footnote", "source_table_or_statement"],
        "officerReview": {
            "required": scope != "weight",
            "checklist": ["confirm unit", "confirm aggregation policy", "confirm source table lineage"],
        },
        "confidence": None,
    }


def dimension(
    entity_id: str,
    name: str,
    aliases: list[str],
    members: list[str] | str = "open",
    *,
    entity_type: str = "dimension",
    cardinality_hint: str = "medium",
    scope: str = "classifier",
) -> dict[str, Any]:
    value_domain: dict[str, Any] = {"kind": "categorical", "members": members}
    if isinstance(members, list):
        value_domain["allowOther"] = True
    return {
        "entityId": entity_id,
        "canonicalName": name,
        "entityType": entity_type,
        "aliases": aliases,
        "valueDomain": value_domain,
        "cardinalityHint": cardinality_hint,
        "scope": scope,
        "conceptFamily": "time" if entity_type == "time" else "metadata" if entity_type == "metadata" else "classifier",
        "dataRole": scope,
        "binderHints": {
            "matchPriority": aliases,
            "allowMemberSet": isinstance(members, list),
            "allowOpenVocabulary": members == "open",
            "requiresMemberEvidence": isinstance(members, list),
        },
        "qualityRules": [
            {"ruleId": f"qr_{entity_id}_domain", "severity": "warn", "condition": "members_match_or_are_mapped"}
        ],
        "evidenceRequirements": ["column_header", "sample_values", "source_table_or_statement"],
        "officerReview": {
            "required": entity_type in {"time", "dimension"},
            "checklist": ["confirm member mapping", "confirm hierarchy level", "confirm whether filtering or grouping"],
        },
        "confidence": None,
    }


ENTITIES = [
    measure("ent_lfpr", "Labour Force Participation Rate", ["LFPR", "Labour Force Participation Rate", "participation rate", "LFPR (%)", "LFPR_ps_ss"], "percent", "reported_value", fmt="percent.1"),
    measure("ent_wpr", "Worker Population Ratio", ["WPR", "Worker Population Ratio", "worker population ratio", "WPR (%)", "WPR_ps_ss"], "percent", "reported_value", fmt="percent.1"),
    measure("ent_ur", "Unemployment Rate", ["UR", "Unemployment Rate", "unemployment rate", "UR (%)", "UR_ps_ss"], "percent", "reported_value", fmt="percent.1"),
    measure("ent_youth_ur", "Youth Unemployment Rate", ["Youth UR", "Youth Unemployment Rate", "UR 15-29", "youth unemployment"], "percent", "reported_value", fmt="percent.1"),
    measure("ent_female_lfpr", "Female Labour Force Participation Rate", ["Female LFPR", "Women LFPR", "Female Labour Force Participation Rate"], "percent", "reported_value", fmt="percent.1"),
    measure("ent_worker_share", "Worker Share", ["Worker Share", "share of workers", "worker distribution"], "percent", "reported_value", fmt="percent.1"),
    measure("ent_self_employed_share", "Self-employed Worker Share", ["Self-employed", "Self employed share", "self employment share"], "percent", "reported_value", fmt="percent.1"),
    measure("ent_regular_wage_share", "Regular Wage Worker Share", ["Regular wage", "regular wage/salaried", "regular salaried share"], "percent", "reported_value", fmt="percent.1"),
    measure("ent_casual_labour_share", "Casual Labour Worker Share", ["Casual labour", "casual labor", "casual labour share"], "percent", "reported_value", fmt="percent.1"),
    measure("ent_agriculture_share", "Agriculture Worker Share", ["Agriculture", "agriculture sector", "agriculture share"], "percent", "reported_value", fmt="percent.1"),
    measure("ent_manufacturing_share", "Manufacturing Worker Share", ["Manufacturing", "manufacturing sector", "manufacturing share"], "percent", "reported_value", fmt="percent.1"),
    measure("ent_services_share", "Services Worker Share", ["Services", "service sector", "services share"], "percent", "reported_value", fmt="percent.1"),
    measure("ent_avg_weekly_hours", "Average Weekly Hours Worked", ["Average weekly hours", "hours worked", "weekly hours"], "hours_per_week", "mean", fmt="number.1"),
    measure("ent_avg_monthly_earnings", "Average Monthly Earnings", ["Average monthly earnings", "monthly earnings", "wage", "earnings"], "INR", "mean", fmt="currency.0"),
    measure("ent_formal_education_years", "Average Years in Formal Education", ["Formal education years", "years of education", "average years in formal education"], "years", "mean", fmt="number.1"),
    measure("ent_population_persons", "Estimated Population", ["Population", "estimated population", "persons"], "persons", "sum", fmt="number.0"),
    measure("ent_labour_force_persons", "Estimated Labour Force", ["Labour force", "labor force", "persons in labour force"], "persons", "sum", fmt="number.0"),
    measure("ent_employed_persons", "Estimated Employed Persons", ["Employed persons", "workers", "employed"], "persons", "sum", fmt="number.0"),
    measure("ent_unemployed_persons", "Estimated Unemployed Persons", ["Unemployed persons", "unemployed"], "persons", "sum", fmt="number.0"),
    measure("ent_rural_urban_gap", "Rural Urban Gap", ["Rural Urban Gap", "rural-urban gap", "urban rural difference"], "percentage_points", "reported_value", fmt="number.1"),
    measure("ent_gender_gap", "Gender Gap", ["Gender Gap", "male female gap", "gender difference"], "percentage_points", "reported_value", fmt="number.1"),
    measure("ent_weight", "Survey Weight", ["Weight", "Multiplier", "Sample weight", "survey weight"], "weight", "sum", fmt="number.3", scope="weight"),
    dimension("ent_state", "State/UT", ["State", "State/UT", "State or UT", "region", "State_UT"], "open", cardinality_hint="high"),
    dimension("ent_region", "Region", ["Region", "zone", "NSS region"], "open", cardinality_hint="medium"),
    dimension("ent_sector", "Sector", ["Sector", "Rural", "Urban", "rural/urban", "area"], ["Rural", "Urban"], cardinality_hint="low"),
    dimension("ent_gender", "Gender", ["Gender", "Sex", "Male", "Female", "Person", "Persons"], ["Male", "Female", "Person"], cardinality_hint="low"),
    dimension("ent_age_group", "Age Group", ["Age", "Age group", "15+", "15-29", "15-59", "age cohort"], ["15 years and above", "15-29 years", "15-59 years"], cardinality_hint="low", scope="filter"),
    dimension("ent_education_level", "Education Level", ["Education", "education level", "general education", "formal education"], "open"),
    dimension("ent_social_group", "Social Group", ["Social group", "caste group", "social category"], "open"),
    dimension("ent_religion", "Religion", ["Religion", "religious group"], "open"),
    dimension("ent_industry_group", "Industry Group", ["Industry", "NIC", "industry group", "sector of work"], "open"),
    dimension("ent_occupation_group", "Occupation Group", ["Occupation", "NCO", "occupation group"], "open"),
    dimension("ent_employment_status", "Status in Employment", ["Status in Employment", "self-employed", "regular wage", "casual labour"], ["Self-employed", "Regular wage/salaried", "Casual labour"]),
    dimension("ent_activity_status", "Activity Status", ["Activity status", "usual status", "ps+ss", "current weekly status", "CWS"], ["Usual status (ps+ss)", "Current weekly status"], scope="filter"),
    dimension("ent_worker_category", "Worker Category", ["Worker category", "main worker", "subsidiary worker"], "open"),
    dimension("ent_period", "Survey Period", ["Year", "Period", "Survey period", "round", "PLFS round"], "open", entity_type="time", scope="time"),
    dimension("ent_quarter", "Survey Quarter", ["Quarter", "Q1", "Q2", "Q3", "Q4"], ["Q1", "Q2", "Q3", "Q4"], entity_type="time", cardinality_hint="low", scope="time"),
    dimension("ent_month", "Survey Month", ["Month", "survey month"], "open", entity_type="time", scope="time"),
    dimension("ent_survey_round", "Survey Round", ["Survey round", "PLFS round", "round"], "open", entity_type="metadata", scope="metadata"),
    dimension("ent_estimate_status", "Estimate Status", ["Estimate status", "status", "provisional", "final"], ["Final", "Provisional", "Revised"], entity_type="metadata", scope="metadata"),
    dimension("ent_source_table", "Source Table", ["Table", "Statement", "source table", "table number"], "open", entity_type="metadata", scope="metadata"),
    dimension("ent_note", "Source Note", ["Note", "footnote", "remarks"], "open", entity_type="metadata", scope="metadata"),
]

ENTITY_LABEL = {e["entityId"]: e["canonicalName"] for e in ENTITIES}
ENTITY_UNIT = {e["entityId"]: e.get("unit") for e in ENTITIES}
ENTITY_FORMAT = {e["entityId"]: e.get("format") for e in ENTITIES}


def section(slug: str, title: str, measure_id: str, primary_dim: str, secondary_dim: str) -> dict[str, str]:
    return {
        "slug": slug,
        "title": title,
        "measure": measure_id,
        "primary": primary_dim,
        "secondary": secondary_dim,
    }


TOPIC_SPECS = [
    {
        "slug": "executive_overview",
        "title": "Executive statistical overview",
        "chapters": [
            ("headline_indicators", "Headline labour market indicators", [
                section("national_dashboard", "National indicator dashboard", "ent_lfpr", "ent_gender", "ent_sector"),
                section("labour_market_balance", "Labour force, employment, and unemployment balance", "ent_labour_force_persons", "ent_state", "ent_gender"),
                section("headline_gaps", "Headline rural-urban and gender gaps", "ent_gender_gap", "ent_sector", "ent_gender"),
            ]),
            ("policy_signals", "Policy-relevant movements and contrasts", [
                section("state_leaders_laggards", "State and UT leaders and laggards", "ent_wpr", "ent_state", "ent_sector"),
                section("youth_signal", "Youth labour market signal", "ent_youth_ur", "ent_age_group", "ent_gender"),
                section("women_work_signal", "Women work participation signal", "ent_female_lfpr", "ent_state", "ent_sector"),
            ]),
        ],
    },
    {
        "slug": "survey_design_coverage",
        "title": "Survey design, coverage, and estimation frame",
        "chapters": [
            ("coverage_frame", "Geographic and population coverage", [
                section("coverage_state", "State and UT coverage", "ent_population_persons", "ent_state", "ent_sector"),
                section("coverage_sector", "Rural and urban survey coverage", "ent_population_persons", "ent_sector", "ent_region"),
                section("coverage_demography", "Demographic coverage profile", "ent_population_persons", "ent_gender", "ent_age_group"),
            ]),
            ("estimation_frame", "Survey weights, periods, and estimate status", [
                section("weights", "Survey weight distribution", "ent_weight", "ent_state", "ent_sector"),
                section("periods", "Survey period and quarter coverage", "ent_population_persons", "ent_period", "ent_quarter"),
                section("estimate_status", "Estimate status and source table coverage", "ent_population_persons", "ent_estimate_status", "ent_source_table"),
            ]),
        ],
    },
    {
        "slug": "lfpr",
        "title": "Labour Force Participation Rate",
        "chapters": [
            ("lfpr_national", "National LFPR patterns", [
                section("lfpr_gender", "LFPR by gender", "ent_lfpr", "ent_gender", "ent_sector"),
                section("lfpr_sector", "LFPR by rural-urban sector", "ent_lfpr", "ent_sector", "ent_gender"),
                section("lfpr_age", "LFPR by age group", "ent_lfpr", "ent_age_group", "ent_gender"),
            ]),
            ("lfpr_geography", "Geographic LFPR differences", [
                section("lfpr_state", "LFPR by State/UT", "ent_lfpr", "ent_state", "ent_sector"),
                section("lfpr_region", "LFPR by region", "ent_lfpr", "ent_region", "ent_gender"),
                section("lfpr_gap", "LFPR rural-urban and gender gaps", "ent_rural_urban_gap", "ent_state", "ent_gender"),
            ]),
        ],
    },
    {
        "slug": "wpr",
        "title": "Worker Population Ratio",
        "chapters": [
            ("wpr_national", "National WPR profile", [
                section("wpr_gender", "WPR by gender", "ent_wpr", "ent_gender", "ent_sector"),
                section("wpr_sector", "WPR by sector", "ent_wpr", "ent_sector", "ent_gender"),
                section("wpr_age", "WPR by age group", "ent_wpr", "ent_age_group", "ent_gender"),
            ]),
            ("wpr_geography", "State and regional employment intensity", [
                section("wpr_state", "WPR by State/UT", "ent_wpr", "ent_state", "ent_sector"),
                section("wpr_region", "WPR by region", "ent_wpr", "ent_region", "ent_gender"),
                section("wpr_worker_category", "WPR by worker category", "ent_wpr", "ent_worker_category", "ent_gender"),
            ]),
        ],
    },
    {
        "slug": "unemployment",
        "title": "Unemployment Rate",
        "chapters": [
            ("ur_national", "National unemployment profile", [
                section("ur_gender", "UR by gender", "ent_ur", "ent_gender", "ent_sector"),
                section("ur_sector", "UR by sector", "ent_ur", "ent_sector", "ent_gender"),
                section("ur_age", "UR by age group", "ent_ur", "ent_age_group", "ent_gender"),
            ]),
            ("ur_priority_groups", "Priority group unemployment analysis", [
                section("ur_youth", "Youth unemployment", "ent_youth_ur", "ent_age_group", "ent_gender"),
                section("ur_state", "UR by State/UT", "ent_ur", "ent_state", "ent_sector"),
                section("ur_education", "UR by education level", "ent_ur", "ent_education_level", "ent_gender"),
            ]),
        ],
    },
    {
        "slug": "employment_composition",
        "title": "Employment composition and status in employment",
        "chapters": [
            ("status_employment", "Status in employment", [
                section("self_employed", "Self-employed worker share", "ent_self_employed_share", "ent_employment_status", "ent_gender"),
                section("regular_wage", "Regular wage and salaried worker share", "ent_regular_wage_share", "ent_employment_status", "ent_sector"),
                section("casual_labour", "Casual labour worker share", "ent_casual_labour_share", "ent_employment_status", "ent_gender"),
            ]),
            ("composition_demography", "Composition across demographic groups", [
                section("composition_gender", "Employment composition by gender", "ent_worker_share", "ent_gender", "ent_employment_status"),
                section("composition_sector", "Employment composition by sector", "ent_worker_share", "ent_sector", "ent_employment_status"),
                section("composition_social", "Employment composition by social group", "ent_worker_share", "ent_social_group", "ent_gender"),
            ]),
        ],
    },
    {
        "slug": "industry_occupation",
        "title": "Industry, occupation, hours, and earnings",
        "chapters": [
            ("industry_distribution", "Industry distribution of workers", [
                section("agriculture", "Agriculture worker share", "ent_agriculture_share", "ent_state", "ent_gender"),
                section("manufacturing", "Manufacturing worker share", "ent_manufacturing_share", "ent_state", "ent_sector"),
                section("services", "Services worker share", "ent_services_share", "ent_state", "ent_gender"),
            ]),
            ("work_quality", "Hours worked and earnings", [
                section("weekly_hours", "Average weekly hours worked", "ent_avg_weekly_hours", "ent_industry_group", "ent_gender"),
                section("monthly_earnings", "Average monthly earnings", "ent_avg_monthly_earnings", "ent_occupation_group", "ent_gender"),
                section("earnings_sector", "Earnings by sector and status", "ent_avg_monthly_earnings", "ent_sector", "ent_employment_status"),
            ]),
        ],
    },
    {
        "slug": "demography_education",
        "title": "Demographic, social, and education cuts",
        "chapters": [
            ("education_profile", "Education and labour market participation", [
                section("education_years", "Average years in formal education", "ent_formal_education_years", "ent_gender", "ent_sector"),
                section("education_lfpr", "LFPR by education level", "ent_lfpr", "ent_education_level", "ent_gender"),
                section("education_earnings", "Earnings by education level", "ent_avg_monthly_earnings", "ent_education_level", "ent_gender"),
            ]),
            ("social_demographic_profile", "Social and demographic breakdowns", [
                section("social_lfpr", "LFPR by social group", "ent_lfpr", "ent_social_group", "ent_gender"),
                section("religion_wpr", "WPR by religion", "ent_wpr", "ent_religion", "ent_sector"),
                section("age_earnings", "Earnings by age group", "ent_avg_monthly_earnings", "ent_age_group", "ent_gender"),
            ]),
        ],
    },
    {
        "slug": "geography_time_annex",
        "title": "Geographic patterns, time trends, and annexures",
        "chapters": [
            ("geographic_synthesis", "Geographic synthesis", [
                section("regional_clusters", "Regional labour market clusters", "ent_wpr", "ent_region", "ent_state"),
                section("state_gap", "State-level gap diagnostics", "ent_gender_gap", "ent_state", "ent_sector"),
                section("district_ready", "District-ready template extension", "ent_lfpr", "ent_state", "ent_region"),
            ]),
            ("time_trends_annex", "Time trends and annexure-ready outputs", [
                section("annual_trends", "Annual trend across key indicators", "ent_lfpr", "ent_period", "ent_gender"),
                section("quarter_trends", "Quarterly movement across key indicators", "ent_wpr", "ent_quarter", "ent_sector"),
                section("annexure_tables", "Annexure table and glossary coverage", "ent_population_persons", "ent_source_table", "ent_note"),
            ]),
        ],
    },
]


def required_entities(measure_id: str, primary_dim: str, secondary_dim: str) -> list[dict[str, Any]]:
    out = [
        {"entityId": measure_id, "role": "measure", "required": True},
        {"entityId": primary_dim, "role": "grouping", "required": True},
        {"entityId": secondary_dim, "role": "grouping", "required": False},
        {"entityId": "ent_period", "role": "time", "required": True, "periodRole": "current"},
        {"entityId": "ent_age_group", "role": "filter", "required": False, "defaultMember": "15 years and above"},
    ]
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in out:
        key = (item["entityId"], item["role"])
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


def analytics_spec(measure_id: str, group_ids: list[str], *, operation: str = "group_aggregate", top_n: int | None = None) -> dict[str, Any]:
    unit = ENTITY_UNIT.get(measure_id)
    agg = "reported_value" if unit in {"percent", "percentage_points"} else "mean" if unit in {"INR", "years", "hours_per_week"} else "sum"
    return {
        "operation": operation,
        "measure": {"entityRef": measure_id, "agg": agg, "unit": unit},
        "groupBy": [{"entityRef": g} for g in group_ids],
        "filters": [{"entityRef": "ent_age_group", "op": "eq", "valueFrom": "defaultMember"}],
        "sort": {"by": "measure", "order": "desc"},
        "topN": top_n,
        "time": {"entityRef": "ent_period", "periodRole": "current"},
        "grain": {
            "required": ["measure", "groupBy", "time"],
            "sameGrainBeforeFormula": True,
            "notes": "Every statistic is computed after grouping to the declared question grain; row-ratio averaging is prohibited.",
        },
        "weighting": {
            "weightEntityRef": "ent_weight",
            "required": False,
            "policy": "use_when_bound_and_valid_else_reported_value",
        },
        "readiness": {
            "missingRequiredEntity": "BLOCKED",
            "missingOptionalEntity": "DEGRADED",
            "missingTime": "DEGRADED_SNAPSHOT",
            "invalidAggregation": "BLOCKED",
        },
        "audit": {
            "requiresLineage": True,
            "requiresAggregationTrace": True,
            "requiresFilterTrace": True,
        },
    }


def officer_customization_contract() -> dict[str, Any]:
    return {
        "customizationVersion": "officer.template.controls.v1",
        "principles": [
            "Every control changes structure, presentation, or scope only; it must not fabricate data.",
            "Controls must preserve binder readiness gates and source lineage.",
            "Optional content can be hidden, but blocked required questions cannot be silently generated.",
        ],
        "controls": [
            {
                "controlId": "page_budget",
                "label": "Page budget",
                "type": "single_select",
                "default": "standard_60_pages",
                "options": [
                    {"value": "brief_40_pages", "label": "Brief 40-45 pages", "targetPages": [40, 45]},
                    {"value": "standard_60_pages", "label": "Standard 55-65 pages", "targetPages": [55, 65]},
                    {"value": "expanded_75_pages", "label": "Expanded 70-80 pages", "targetPages": [70, 80]},
                ],
            },
            {
                "controlId": "geography_depth",
                "label": "Geography depth",
                "type": "single_select",
                "default": "state_ut",
                "options": ["national", "rural_urban", "state_ut", "region_state_ut"],
            },
            {
                "controlId": "priority_lens",
                "label": "Policy lens",
                "type": "multi_select",
                "default": ["women", "youth", "state_variation"],
                "options": ["women", "youth", "rural_urban", "education", "industry", "earnings", "state_variation"],
            },
            {
                "controlId": "output_channels",
                "label": "Outputs",
                "type": "multi_select",
                "default": ["html", "pdf", "annexure_tables"],
                "options": ["html", "pdf", "docx_ready_ast", "annexure_tables", "provenance_log"],
            },
            {
                "controlId": "narrative_style",
                "label": "Narrative style",
                "type": "single_select",
                "default": "formal_statistical",
                "options": ["formal_statistical", "policy_brief", "technical_annexure"],
            },
            {
                "controlId": "visual_density",
                "label": "Visual density",
                "type": "single_select",
                "default": "balanced",
                "options": ["table_heavy", "balanced", "chart_heavy"],
            },
        ],
        "officerEditableFields": [
            "cover.title",
            "cover.subtitle",
            "publication.status",
            "reporting.period",
            "topic.enabled",
            "chapter.enabled",
            "section.enabled",
            "question.priority",
            "component.visibility",
            "chart.type",
            "table.sort",
            "annexure.include",
            "source_note.override",
        ],
        "lockedFields": [
            "entity.aggregationPolicy",
            "question.requiredEntities.required",
            "question.analyticsSpec.readiness",
            "formulaSpec.type",
            "slot.lineage",
        ],
    }


def data_contract() -> dict[str, Any]:
    required_measures = ["ent_lfpr", "ent_wpr", "ent_ur"]
    required_dimensions = ["ent_sector", "ent_gender", "ent_period"]
    return {
        "contractVersion": "mospi.plfs.dataset.contract.v1",
        "minimumViableDataset": {
            "requiredMeasures": required_measures,
            "requiredDimensions": required_dimensions,
            "recommendedMeasures": ["ent_youth_ur", "ent_female_lfpr", "ent_population_persons", "ent_weight"],
            "recommendedDimensions": ["ent_state", "ent_age_group", "ent_education_level", "ent_employment_status"],
        },
        "acceptedInputShapes": [
            {
                "shapeId": "published_table_wide",
                "description": "Indicator columns appear wide by LFPR/WPR/UR or similar names.",
                "normalizationNeeded": "WIDE_TO_LONG_OPTIONAL",
            },
            {
                "shapeId": "tidy_indicator_long",
                "description": "One indicator/value pair per row with dimensions as columns.",
                "normalizationNeeded": "PIVOT_OR_FILTER_BINDING",
            },
            {
                "shapeId": "state_sector_panel",
                "description": "State/UT, rural/urban, gender, age, period, and measures in panel form.",
                "normalizationNeeded": "NONE_OR_LIGHT_CANONICALIZATION",
            },
        ],
        "unitRegistry": {
            "percent": {"display": "%", "validRange": [0, 100], "aggregation": "reported_value"},
            "percentage_points": {"display": "percentage points", "aggregation": "reported_value"},
            "persons": {"display": "persons", "aggregation": "sum"},
            "INR": {"display": "INR", "aggregation": "mean"},
            "hours_per_week": {"display": "hours/week", "aggregation": "mean"},
            "weight": {"display": "weight", "aggregation": "sum"},
        },
        "qualityThresholds": {
            "minRows": 1,
            "maxMissingRequiredEntityPct": 0,
            "warnMissingRecommendedEntityPct": 35,
            "minQuestionExecutabilityPct": 70,
            "minLineageCoveragePct": 95,
        },
        "normalizationHints": [
            "Trim whitespace in headers and categorical values.",
            "Map Male/Female/Person and Rural/Urban variants before S3.",
            "Keep source table identifiers as metadata columns where available.",
            "Preserve original column names in lineage even after canonicalization.",
        ],
    }


def binder_deliverable_contract() -> dict[str, Any]:
    return {
        "contractVersion": "binding.s3_5.enterprise.deliverables.v1",
        "stageExpectations": {
            "S0_profile": ["datasetSignature", "column roles", "unit hints", "value domains", "source file metadata"],
            "S1_entity_resolution": ["entityBinding per canonical entity", "candidate columns", "risk flags", "evidence snippets"],
            "S2_officer_review": ["confirmed/rejected/overridden entities", "share policies", "manual entities", "column ownership"],
            "S3_question_binding": ["questionBinding per nested question", "resolved roles", "filters", "time status", "blocked reasons"],
            "S3_5_execution_ready": ["ExecutionBundle", "plan status", "lineage refs", "formulaSpec", "normalization plan", "readiness gate"],
        },
        "requiredOutputs": [
            "BindingAST.datasetSignature",
            "BindingAST.entityBindings",
            "BindingAST.questionBindings",
            "ReviewedPlan.planTree",
            "ReviewedPlan.semanticSlotGraph",
            "ExecutionBundle.plans",
            "coverage.issues",
        ],
        "blockingRules": [
            "NOT_READY blocks generation.",
            "BLOCKED execution plans are not adapted into runnable analytics.",
            "Missing denominator/base/timeWindow for formulas is BLOCKED, not DEGRADED.",
            "reported_value never falls through to mean when values disagree.",
        ],
        "reviewDashboardNeeds": [
            "show unresolved required entities first",
            "show question executability by topic/chapter/section",
            "show slot lineage for narrative/metric/chart/table/provenance",
            "show officer-editable controls without changing locked statistical contracts",
        ],
    }


def publication_contract() -> dict[str, Any]:
    return {
        "publicationVersion": "mospi.enterprise.report.publication.v1",
        "targetPageRange": {"minimum": 40, "standard": 60, "maximum": 80},
        "frontMatter": [
            {"id": "cover", "pages": 1, "officerEditable": True},
            {"id": "publication_control", "pages": 1, "officerEditable": True},
            {"id": "executive_summary", "pages": 2, "officerEditable": True},
            {"id": "contents", "pages": 1, "officerEditable": False},
            {"id": "survey_notes", "pages": 1, "officerEditable": True},
        ],
        "analyticalBody": {
            "topics": 9,
            "chapters": 18,
            "sections": 54,
            "sectionPagePolicy": "one analytical section starts on a fresh flow region; compact mode may combine low-priority sections",
        },
        "backMatter": [
            {"id": "definitions", "pages": 2},
            {"id": "methodology_notes", "pages": 2},
            {"id": "annexure_tables", "pages": 4},
            {"id": "provenance_log", "pages": 1},
        ],
        "accessibility": {
            "requiresAltText": True,
            "requiresTableHeaders": True,
            "requiresSourceNotes": True,
            "colorContrast": "WCAG_AA",
        },
    }


def formula_catalog() -> dict[str, Any]:
    return {
        "supportedFormulaTypes": [
            {"type": "DIRECT", "policy": "Use reported value or aggregate physical measure according to entity aggregation policy."},
            {"type": "SHARE", "policy": "Aggregate numerator and denominator at same grain, then divide."},
            {"type": "RATE", "policy": "Aggregate numerator and denominator at same grain, multiply by declared multiplier."},
            {"type": "RATIO", "policy": "Aggregate both sides at same grain; never average row ratios."},
            {"type": "GROWTH", "policy": "Requires current and comparison period."},
            {"type": "CAGR", "policy": "Requires explicit timeWindow."},
            {"type": "INDEX", "policy": "Requires explicit baseValue or base period."},
        ],
        "default": {"type": "DIRECT"},
        "blockedWhenMissing": ["denominatorColumn", "timeWindow", "baseValue", "sameGrainGrouping"],
    }


def question(
    topic_slug: str,
    chapter_slug: str,
    section_slug: str,
    section_title: str,
    measure_id: str,
    primary_dim: str,
    secondary_dim: str,
    variant: int,
) -> dict[str, Any]:
    qid = f"q_{section_slug}_{variant:02d}"
    measure_name = ENTITY_LABEL[measure_id]
    primary_name = ENTITY_LABEL[primary_dim]
    secondary_name = ENTITY_LABEL[secondary_dim]
    is_rank = variant == 2 and primary_dim != "ent_state"
    operation = "rank" if is_rank else "group_aggregate"
    groups = ["ent_state", primary_dim] if is_rank else [primary_dim, secondary_dim]
    groups = list(dict.fromkeys(groups))
    intent = (
        f"Rank State/UTs by {measure_name} with {primary_name} context for {section_title}."
        if is_rank
        else f"Compare {measure_name} by {primary_name} and {secondary_name} for {section_title}."
    )
    chart_type = "horizontal_bar" if is_rank else "grouped_bar"
    components = [
        {
            "componentId": f"{qid}_narrative",
            "kind": "narrative",
            "order": 1,
            "outputContract": {
                "type": "prose",
                "minWords": 80,
                "maxWords": 150,
                "requiresEvidence": True,
                "requiresCaveatWhenDegraded": True,
            },
            "narrativeTemplate": {
                "tone": "formal-statistical",
                "pattern": "headline_then_evidence_then_caveat",
                "mustMention": [measure_id, primary_dim],
                "maxWords": 150,
            },
            "customization": {
                "officerEditable": True,
                "controls": ["tone", "length", "include_caveat", "include_policy_signal"],
                "locked": ["mustMention", "evidenceRef"],
            },
            "refs": {"contentRef": f"p_{qid}_narrative", "analyticsRef": qid, "evidenceRef": f"ev_{qid}"},
        },
        {
            "componentId": f"{qid}_metric",
            "kind": "formula_metric",
            "order": 2,
            "outputContract": {
                "type": "metric",
                "metricEntityRef": measure_id,
                "format": ENTITY_FORMAT.get(measure_id),
                "requiresUnit": True,
                "requiresLineage": True,
            },
            "formulaSpec": {"type": "DIRECT", "measureEntityRef": measure_id},
            "customization": {
                "officerEditable": True,
                "controls": ["show_delta", "show_rank", "display_precision"],
                "locked": ["formulaSpec.type", "metricEntityRef"],
            },
            "refs": {"contentRef": f"m_{qid}_metric", "analyticsRef": qid, "evidenceRef": f"ev_{qid}"},
        },
        {
            "componentId": f"{qid}_chart",
            "kind": "chart",
            "order": 3,
            "outputContract": {
                "type": "chart",
                "chartType": chart_type,
                "xAxis": primary_dim,
                "yAxis": measure_id,
                "requiresAltText": True,
                "requiresSourceNote": True,
            },
            "customization": {
                "officerEditable": True,
                "controls": ["chartType", "topN", "sortOrder", "colorTheme", "showDataLabels"],
                "allowedChartTypes": ["grouped_bar", "horizontal_bar", "line", "heatmap"],
                "locked": ["xAxis.entityRef", "yAxis.entityRef", "analyticsRef"],
            },
            "refs": {"chartRef": f"chart_{qid}", "figureRef": f"fig_{qid}", "analyticsRef": qid, "evidenceRef": f"ev_{qid}"},
        },
        {
            "componentId": f"{qid}_table",
            "kind": "table",
            "order": 4,
            "outputContract": {
                "type": "table",
                "tableTemplateRef": f"tt_{qid}",
                "requiresHeaderUnits": True,
                "requiresFootnotes": True,
            },
            "customization": {
                "officerEditable": True,
                "controls": ["topN", "sortOrder", "includeTotalRow", "decimalPlaces"],
                "locked": ["entity columns", "source footnote"],
            },
            "refs": {"tableRef": f"table_{qid}", "analyticsRef": qid, "evidenceRef": f"ev_{qid}"},
        },
        {
            "componentId": f"{qid}_provenance",
            "kind": "provenance",
            "order": 5,
            "outputContract": {"type": "source_note", "requiresLineage": True},
            "customization": {
                "officerEditable": True,
                "controls": ["source_note_text", "include_table_number", "include_extraction_confidence"],
                "locked": ["lineageRef", "datasetSignature"],
            },
            "refs": {"contentRef": f"p_{qid}_provenance", "analyticsRef": qid, "evidenceRef": f"ev_{qid}"},
        },
    ]
    return {
        "questionId": qid,
        "intent": intent,
        "questionText": intent,
        "questionType": "ranking" if is_rank else "comparison",
        "priority": variant,
        "requiredEntities": required_entities(measure_id, primary_dim, secondary_dim),
        "analyticsSpec": analytics_spec(measure_id, groups, operation=operation, top_n=10 if is_rank else None),
        "formulaSpec": {"type": "DIRECT", "measureEntityRef": measure_id},
        "answerStructure": {"components": components},
        "officerIntent": {
            "decisionUse": "Identify reportable contrasts, priority groups, and caveats for official release.",
            "primaryAudience": ["MoSPI officer", "state statistics officer", "policy analyst"],
            "reviewFocus": [measure_id, primary_dim, secondary_dim, "ent_period"],
        },
        "dataRequirements": {
            "requiredEntities": [measure_id, primary_dim, "ent_period"],
            "optionalEntities": [secondary_dim, "ent_age_group", "ent_weight", "ent_source_table"],
            "minimumRows": 1,
            "preferredGrain": [primary_dim, secondary_dim, "ent_period"],
        },
        "binderContract": {
            "s3StatusWhenComplete": "executable",
            "s3StatusWhenMissingOptionalGrouping": "degraded",
            "s3StatusWhenMissingMeasureOrPrimaryGrouping": "blocked",
            "mustEmitLineage": True,
            "mustPreserveSlotIds": True,
        },
        "qualityGates": [
            {"gateId": f"gate_{qid}_measure_bound", "severity": "error", "condition": f"{measure_id} is confirmed"},
            {"gateId": f"gate_{qid}_primary_group_bound", "severity": "error", "condition": f"{primary_dim} is confirmed"},
            {"gateId": f"gate_{qid}_time_bound", "severity": "warn", "condition": "ent_period is confirmed or snapshot mode is explicit"},
            {"gateId": f"gate_{qid}_lineage", "severity": "error", "condition": "all answer components have lineage"},
        ],
        "answerPlan": {
            "sequence": ["narrative", "metric", "chart", "table", "provenance"],
            "pageWeight": 0.5,
            "fallbackWhenDegraded": "show available metric/table with explicit caveat and source note",
            "blockedWhen": ["required measure unresolved", "primary grouping unresolved", "invalid aggregation policy"],
        },
        "customization": {
            "officerEditable": True,
            "controls": ["enabled", "priority", "componentVisibility", "chartType", "topN", "narrativeTone"],
            "defaultVisibility": True,
            "compactMode": {"keep": ["metric", "table", "provenance"], "optional": ["chart", "narrative"]},
        },
        "provenanceRequirements": {
            "lineageRef": f"lin_{qid}",
            "evidenceRef": f"ev_{qid}",
            "requiresDatasetSignature": True,
            "requiresSourceTable": False,
            "requiresAggregationTrace": True,
        },
        "reviewChecklist": [
            "Confirm the selected measure is the official concept for this section.",
            "Confirm grouping values are correctly mapped and ordered.",
            "Confirm source notes and table references are present before publication.",
            "Check whether degraded optional dimensions should be hidden or manually bound.",
        ],
        "generationMethod": "enterprise_built_in_pattern",
        "outlineRefs": {
            "topicId": f"topic_{topic_slug}",
            "chapterId": f"chapter_{chapter_slug}",
            "sectionId": f"section_{section_slug}",
        },
        "estimatedPageWeight": 0.5,
    }


def build_blueprint() -> dict[str, Any]:
    topics: list[dict[str, Any]] = []
    table_templates: list[dict[str, Any]] = []
    figure_templates: list[dict[str, Any]] = []
    document_order: list[str] = []

    for topic_order, topic_spec in enumerate(TOPIC_SPECS, start=1):
        topic_id = f"topic_{topic_spec['slug']}"
        document_order.append(topic_id)
        topic = {
            "topicId": topic_id,
            "title": topic_spec["title"],
            "order": topic_order,
            "semanticRef": topic_id,
            "officerSummary": f"Review and publish the {topic_spec['title'].lower()} storyline with auditable statistics and source notes.",
            "pageBudget": {"brief": 3, "standard": 6, "expanded": 8},
            "customization": {
                "officerEditable": True,
                "controls": ["enabled", "priority", "include_in_executive_summary", "compact_mode"],
            },
            "chapters": [],
        }
        for chapter_order, (chapter_slug, chapter_title, sections) in enumerate(topic_spec["chapters"], start=1):
            chapter_id = f"chapter_{chapter_slug}"
            chapter = {
                "chapterId": chapter_id,
                "title": chapter_title,
                "order": chapter_order,
                "chapterType": "analytical",
                "officerSummary": f"Detailed chapter covering {chapter_title.lower()}.",
                "pageBudget": {"brief": 1, "standard": 3, "expanded": 4},
                "qualityGate": {"minimumExecutableQuestions": 1, "missingAllQuestions": "BLOCKED"},
                "sections": [],
            }
            for section_order, sec in enumerate(sections, start=1):
                section_id = f"section_{sec['slug']}"
                questions = [
                    question(topic_spec["slug"], chapter_slug, sec["slug"], sec["title"], sec["measure"], sec["primary"], sec["secondary"], 1),
                    question(topic_spec["slug"], chapter_slug, sec["slug"], sec["title"], sec["measure"], sec["primary"], sec["secondary"], 2),
                ]
                chapter["sections"].append({
                    "sectionId": section_id,
                    "title": sec["title"],
                    "order": section_order,
                    "sectionArchetype": "metric_chart_table_provenance",
                    "pagePlan": {
                        "standardPages": 1,
                        "compactPages": 0.5,
                        "expandedPages": 1.5,
                        "preferredBreak": "start_new_flow_region",
                    },
                    "officerControls": ["enabled", "priority", "chartType", "tableTopN", "includeProvenanceNote"],
                    "deliverables": ["narrative", "headline_metric", "chart", "table", "source_note"],
                    "readinessGate": {
                        "minimumExecutableQuestions": 1,
                        "ifAllQuestionsBlocked": "BLOCKED",
                        "ifOptionalOnlyMissing": "DEGRADED",
                    },
                    "questions": questions,
                })
                for q in questions:
                    qid = q["questionId"]
                    measure_id = q["requiredEntities"][0]["entityId"]
                    dim_id = q["requiredEntities"][1]["entityId"]
                    table_templates.append({
                        "tableTemplateId": f"tt_{qid}",
                        "title": q["intent"],
                        "columns": [
                            {"columnId": f"col_{qid}_group", "header": ENTITY_LABEL[dim_id], "role": "dimension", "entityRef": dim_id, "align": "left", "format": None},
                            {"columnId": f"col_{qid}_measure", "header": ENTITY_LABEL[measure_id], "role": "measure", "entityRef": measure_id, "unit": ENTITY_UNIT.get(measure_id), "format": ENTITY_FORMAT.get(measure_id), "align": "right"},
                        ],
                        "dimensions": [dim_id],
                        "measures": [measure_id],
                        "sorting": {"defaultBy": f"col_{qid}_measure", "defaultOrder": "desc", "officerEditable": True},
                        "displayControls": {
                            "topN": 10,
                            "includeTotalRow": False,
                            "showMissingAs": "-",
                            "officerEditable": ["topN", "sortOrder", "includeTotalRow", "decimalPlaces"],
                        },
                        "accessibility": {"requiresHeaderScope": True, "requiresUnitInHeader": True},
                        "lineagePolicy": {"requiresSourceTable": False, "requiresDatasetSignature": True, "locked": True},
                        "footnotes": [
                            {"noteId": f"fn_source_{qid}", "marker": "Source", "textTemplate": "Source: {{dataset.title}}, {{period.current}}."},
                            {"noteId": f"fn_scope_{qid}", "marker": "Note", "textTemplate": "Estimates follow PLFS concepts and definitions for the selected population universe."},
                        ],
                        "emptyPolicy": "show_dash",
                    })
                    figure_templates.append({
                        "figureTemplateId": f"ft_{qid}",
                        "captionTemplate": f"{ENTITY_LABEL[measure_id]} by {ENTITY_LABEL[dim_id]}, {{{{period.current}}}}",
                        "chartId": f"chart_{qid}",
                        "numbering": "Figure {{topic.order}}.{{chapter.order}}.{{seq}}",
                        "accessibility": {"requiresAltText": True, "altTextTemplate": q["intent"]},
                        "displayControls": {
                            "showDataLabels": True,
                            "showLegend": True,
                            "officerEditable": ["chartType", "palette", "topN", "showDataLabels"],
                        },
                        "lineagePolicy": {"requiresEvidenceRef": True, "locked": True},
                    })
            topic["chapters"].append(chapter)
        topics.append(topic)

    return {
        "$schema": "bharatstat/template-blueprint/v1",
        "_doc": "VALUE-FREE + PROSE-FREE enterprise analytic brain for a 40+ page MoSPI PLFS annual report. Contains no observed values and no generated prose; it defines structure, controls, contracts, and officer review needs.",
        "templateMeta": {
            "templateId": TEMPLATE_ID,
            "name": TEMPLATE_NAME,
            "domain": "labour_force",
            "reportType": "mospi_enterprise_annual",
            "locale": "en-IN",
            "version": TEMPLATE_VERSION,
            "sourceDocument": "Periodic Labour Force Survey Annual Report",
            "valueFree": True,
            "proseFree": True,
            "targetPageCount": "40-80",
            "standardPageCount": 60,
            "description": "Enterprise built-in template with nested topics, chapters, sections, executable question contracts, answer structures, officer customization controls, data contracts, and slot wiring for full-length MoSPI-style report generation.",
            "templateClass": "enterprise_publication",
            "releaseStage": "built_in_officer_ready",
            "createdBy": "BharatStat deterministic template generator",
            "lastUpdated": "2026-06-12",
            "compatibleStages": ["S0", "S1", "S2", "S3", "S3.5", "S4", "S5", "S6", "S7"],
            "governance": {
                "ownerRole": "MoSPI report officer",
                "reviewRoles": ["statistical reviewer", "publication reviewer", "data steward"],
                "approvalRequiredFor": ["locked statistical contracts", "publication status", "source note overrides"],
                "auditMode": "lineage_required",
            },
        },
        "enterprisePlan": {
            "targetPages": 60,
            "minimumPages": 40,
            "maximumPages": 80,
            "outlineDepth": ["topic", "chapter", "section", "question", "answer_component"],
            "buildSteps": [
                "Bind dataset columns to canonical MoSPI entities.",
                "Resolve every section question into executable S3/S3.5 roles.",
                "Fill narrative, metric, chart, table, and provenance slots per question.",
                "Assemble front matter, 54 analytical sections, and annexure/back matter.",
                "Run readiness and provenance gates before S4 generation.",
            ],
            "officerDeliverables": [
                "searchable topic/chapter/section review tree",
                "entity binding matrix with evidence and risk",
                "question readiness dashboard",
                "slot lineage map",
                "publication profile controls",
                "annexure and provenance export",
            ],
        },
        "officerCustomization": officer_customization_contract(),
        "dataContract": data_contract(),
        "binderDeliverableContract": binder_deliverable_contract(),
        "publicationContract": publication_contract(),
        "formulaCatalog": formula_catalog(),
        "qualityGateProfile": {
            "profileId": "mospi_enterprise_quality_v1",
            "minimumBinderReadinessScore": 80,
            "minimumQuestionExecutabilityPct": 70,
            "minimumLineageCoveragePct": 95,
            "failOn": ["missing required measure", "invalid formula", "missing source lineage for published component"],
            "warnOn": ["missing optional grouping", "snapshot time fallback", "low confidence entity match"],
        },
        "officerWorkbench": {
            "defaultViews": ["template_overview", "data_contract", "entity_review", "question_readiness", "publication_controls"],
            "quickFilters": ["blocked", "degraded", "missing_lineage", "officer_editable", "locked_contract"],
            "primaryActions": ["confirm entity", "override binding", "hide optional section", "promote reviewed plan", "export provenance"],
        },
        "glossary": {
            "LFPR": "Labour Force Participation Rate.",
            "WPR": "Worker Population Ratio.",
            "UR": "Unemployment Rate.",
            "usual_status": "Usual status based on principal and subsidiary status.",
            "cws": "Current weekly status.",
            "sector": "Rural or Urban household sector.",
            "reported_value": "Published or source-provided value used directly when it is deterministic at the selected grain.",
            "ExecutionBundle": "S3.5 handoff contract consumed by generation; blocked plans are not executed.",
        },
        "palette": {
            "paletteId": "pal_mospi_enterprise",
            "sequential": ["#0B5394", "#3D85C6", "#6FA8DC", "#9FC5E8", "#CFE2F3"],
            "categorical": {"Rural": "#1F7A1F", "Urban": "#0B5394", "Male": "#0B5394", "Female": "#CC4125", "Person": "#666666"},
            "semantic": {"positive": "#1F7A1F", "negative": "#CC0000", "neutral": "#666666", "caution": "#F6B26B"},
        },
        "renderProfile": {
            "numberFormat": {"locale": "en-IN", "grouping": "lakh-crore", "decimalSeparator": "."},
            "percentFormat": {"decimals": 1, "suffix": "%"},
            "currencyFormat": {"symbol": "INR", "grouping": "lakh-crore", "decimals": 0},
            "fontFamily": "Noto Sans",
            "pageSize": "A4",
            "densityModes": {
                "brief_40_pages": {"combineLowPrioritySections": True, "maxChartsPerSection": 1},
                "standard_60_pages": {"combineLowPrioritySections": False, "maxChartsPerSection": 1},
                "expanded_75_pages": {"includeAnnexureDetail": True, "maxChartsPerSection": 2},
            },
        },
        "entities": ENTITIES,
        "topics": topics,
        "tableTemplates": table_templates,
        "figureTemplates": figure_templates,
        "externalTableReferences": [
            {"refId": f"annex_table_{i:02d}", "title": f"Annexure table placeholder {i:02d}", "required": False}
            for i in range(1, 13)
        ],
        "documentMap": {
            "order": document_order,
            "frontMatter": ["cover", "foreword", "executive_summary", "toc", "survey_notes"],
            "backMatter": ["definitions", "methodology_notes", "glossary", "annexure_tables", "provenance_log"],
            "estimatedPages": {"frontMatter": 6, "analyticalSections": 54, "backMatter": 8, "total": 68},
            "pageModes": {
                "brief_40_pages": {"frontMatter": 5, "analyticalSections": 34, "backMatter": 4, "total": 43},
                "standard_60_pages": {"frontMatter": 6, "analyticalSections": 54, "backMatter": 8, "total": 68},
                "expanded_75_pages": {"frontMatter": 8, "analyticalSections": 60, "backMatter": 10, "total": 78},
            },
        },
    }


def build_ast_and_slots(blueprint: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    figures: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    flow: list[str] = []
    slots: list[dict[str, Any]] = []
    question_slot_count = 0

    def add_slot(component: dict[str, Any], qid: str, topic_id: str, chapter_id: str, section_id: str) -> str:
        nonlocal question_slot_count
        component_id = component["componentId"]
        kind = component["kind"]
        refs = component.get("refs") or {}
        ast_kind = "content"
        ast_block_id = refs.get("contentRef") or f"p_{component_id}"
        if kind == "chart":
            ast_kind = "chart"
            ast_block_id = refs.get("chartRef") or f"chart_{qid}"
        elif kind == "table":
            ast_kind = "table"
            ast_block_id = refs.get("tableRef") or f"table_{qid}"
        slot_id = f"slot_{component_id}"
        slots.append({
            "slotId": slot_id,
            "astBlockId": ast_block_id,
            "astKind": ast_kind,
            "source": "enterprise_built_in",
            "confidence": 1.0,
            "topicId": topic_id,
            "chapterId": chapter_id,
            "sectionId": section_id,
            "questionId": qid,
            "componentId": component_id,
            "componentKind": kind,
            "lineageRequired": True,
            "officerEditable": bool((component.get("customization") or {}).get("officerEditable", False)),
            "lockedFields": (component.get("customization") or {}).get("locked", []),
        })
        question_slot_count += 1
        return ast_block_id

    def add_document_block(doc_id: str, title: str, role: str, page_role: str, style_ref: str = "s_body") -> None:
        nonlocal page_num, order
        block_id = f"doc_{doc_id}"
        slot_id = f"slot_doc_{doc_id}"
        section_id = f"section_doc_{doc_id}"
        region_id = f"rg_doc_{doc_id}"
        blocks.append({
            "blockId": block_id,
            "kind": role,
            "styleRef": style_ref,
            "content": "",
            "slot": {"fillFrom": f"component_doc_{doc_id}", "status": "empty"},
            "officerEditable": True,
        })
        sections.append({
            "sectionId": section_id,
            "title": title,
            "level": 0,
            "order": order,
            "styleRef": style_ref,
            "children": [block_id],
            "documentRole": page_role,
        })
        pages.append({
            "pageId": f"pg_{page_num:03d}",
            "size": "A4",
            "role": page_role,
            "regions": [{"regionId": region_id, "role": page_role, "bindsTo": section_id, "bbox": None}],
        })
        flow.append(region_id)
        slots.append({
            "slotId": slot_id,
            "astBlockId": block_id,
            "astKind": "content",
            "source": "enterprise_built_in_document_control",
            "confidence": 1.0,
            "questionId": None,
            "componentId": f"component_doc_{doc_id}",
            "componentKind": role,
            "documentRole": page_role,
            "lineageRequired": role in {"executive_summary", "methodology_note", "provenance_log"},
            "officerEditable": True,
            "lockedFields": ["datasetSignature"] if role in {"provenance_log", "source_note"} else [],
        })
        page_num += 1
        order += 1

    order = 1
    page_num = 1
    for doc_id, title, role, page_role, style_ref in [
        ("cover_title", "Cover and report identity", "cover_title", "front_matter_cover", "s_h1"),
        ("publication_control", "Publication control and approval status", "publication_control", "front_matter_control", "s_body"),
        ("executive_summary", "Executive summary", "executive_summary", "front_matter_summary", "s_body"),
        ("contents", "Table of contents", "toc", "front_matter_contents", "s_body"),
        ("survey_notes", "Survey concepts and notes", "methodology_note", "front_matter_notes", "s_note"),
    ]:
        add_document_block(doc_id, title, role, page_role, style_ref)

    for topic in blueprint["topics"]:
        topic_id = topic["topicId"]
        sections.append({"sectionId": topic_id, "title": topic["title"], "level": 1, "order": order, "styleRef": "s_h1", "topicRef": topic_id, "children": []})
        order += 1
        for chapter in topic["chapters"]:
            chapter_id = chapter["chapterId"]
            sections.append({"sectionId": chapter_id, "title": chapter["title"], "level": 2, "order": order, "styleRef": "s_h2", "topicRef": topic_id, "children": []})
            order += 1
            for sec in chapter["sections"]:
                section_id = sec["sectionId"]
                children: list[str] = []
                for q in sec["questions"]:
                    qid = q["questionId"]
                    measure_id = q["requiredEntities"][0]["entityId"]
                    dim_id = q["requiredEntities"][1]["entityId"]
                    for comp in q["answerStructure"]["components"]:
                        ast_block_id = add_slot(comp, qid, topic_id, chapter_id, section_id)
                        kind = comp["kind"]
                        if kind == "narrative":
                            blocks.append({"blockId": ast_block_id, "kind": "paragraph", "styleRef": "s_body", "content": "", "biQuery": qid, "templateQuestion": q["intent"], "slot": {"fillFrom": comp["componentId"], "status": "empty"}})
                            children.append(ast_block_id)
                        elif kind == "formula_metric":
                            blocks.append({"blockId": ast_block_id, "kind": "metric", "styleRef": "s_metric", "content": "", "biQuery": qid, "templateQuestion": q["intent"], "slot": {"fillFrom": comp["componentId"], "status": "empty"}})
                            children.append(ast_block_id)
                        elif kind == "chart":
                            chart_id = ast_block_id
                            charts.append({"chartId": chart_id, "biQuery": qid, "chartType": comp["outputContract"].get("chartType", "grouped_bar"), "title": q["intent"], "xAxis": {"entityRef": dim_id, "label": ENTITY_LABEL[dim_id]}, "yAxis": {"entityRef": measure_id, "label": ENTITY_LABEL[measure_id], "unit": ENTITY_UNIT.get(measure_id)}, "paletteRef": "pal_mospi_enterprise", "series": [], "slot": {"fillFrom": comp["componentId"], "status": "empty"}})
                            figure_id = f"fig_{qid}"
                            figures.append({"figureId": figure_id, "templateRef": f"ft_{qid}", "caption": "", "captionTemplate": f"{ENTITY_LABEL[measure_id]} by {ENTITY_LABEL[dim_id]}, {{{{period.current}}}}", "chartRef": chart_id, "styleRef": "s_caption", "slot": {"status": "empty"}})
                            children.append(figure_id)
                        elif kind == "table":
                            table_id = ast_block_id
                            tables.append({"tableId": table_id, "templateRef": f"tt_{qid}", "biQuery": qid, "title": q["intent"], "columns": [{"columnId": f"col_{qid}_group", "header": ENTITY_LABEL[dim_id], "role": "dimension", "entityRef": dim_id, "align": "left", "format": None}, {"columnId": f"col_{qid}_measure", "header": ENTITY_LABEL[measure_id], "role": "measure", "entityRef": measure_id, "unit": ENTITY_UNIT.get(measure_id), "format": ENTITY_FORMAT.get(measure_id), "align": "right"}], "rows": [], "footnotes": [{"noteId": f"fn_{qid}_source", "text": "", "textTemplate": "Source: {{dataset.title}}, {{period.current}}."}], "slot": {"fillFrom": comp["componentId"], "status": "empty"}})
                            children.append(table_id)
                        elif kind == "provenance":
                            blocks.append({"blockId": ast_block_id, "kind": "source_note", "styleRef": "s_note", "content": "", "biQuery": qid, "templateQuestion": q["intent"], "slot": {"fillFrom": comp["componentId"], "status": "empty"}})
                            children.append(ast_block_id)
                sections.append({"sectionId": section_id, "title": sec["title"], "level": 3, "order": order, "styleRef": "s_h3", "topicRef": topic_id, "chapterRef": chapter_id, "children": children})
                region_id = f"rg_{section_id}"
                pages.append({"pageId": f"pg_{page_num:03d}", "size": "A4", "regions": [{"regionId": region_id, "role": "section_flow", "bindsTo": section_id, "bbox": None}]})
                flow.append(region_id)
                page_num += 1
                order += 1

    for doc_id, title, role, page_role, style_ref in [
        ("definitions", "Definitions and concepts", "methodology_note", "back_matter_definitions", "s_note"),
        ("methodology_notes", "Methodology notes", "methodology_note", "back_matter_methodology", "s_note"),
        ("annexure_tables", "Annexure table index", "annexure_index", "back_matter_annexure", "s_body"),
        ("provenance_log", "Provenance and audit log", "provenance_log", "back_matter_provenance", "s_note"),
    ]:
        add_document_block(doc_id, title, role, page_role, style_ref)

    ast = {
        "$schema": "bharatstat/template-ast/v1",
        "_doc": "VALUE-FREE render skeleton for the MoSPI PLFS enterprise built-in package. All content, rows, series, captions, and officer text fields are empty placeholders.",
        "metadata": {
            "templateId": TEMPLATE_ID,
            "blueprintRef": TEMPLATE_ID,
            "name": TEMPLATE_NAME,
            "locale": "en-IN",
            "version": TEMPLATE_VERSION,
            "valueFree": True,
            "generatedFrom": "enterprise_built_in_plfs_generator",
            "targetPageRange": "40-80",
            "standardPageCount": 60,
            "officerReady": True,
            "auditRequired": True,
        },
        "styleAST": {"styles": [
            {"styleId": "s_h1", "role": "heading1", "font": "Noto Sans", "sizePt": 18, "bold": True, "color": "#0B5394"},
            {"styleId": "s_h2", "role": "heading2", "font": "Noto Sans", "sizePt": 15, "bold": True, "color": "#1155CC"},
            {"styleId": "s_h3", "role": "heading3", "font": "Noto Sans", "sizePt": 13, "bold": True, "color": "#1C4587"},
            {"styleId": "s_body", "role": "body", "font": "Noto Sans", "sizePt": 11, "bold": False, "color": "#222222"},
            {"styleId": "s_metric", "role": "metric", "font": "Noto Sans", "sizePt": 16, "bold": True, "color": "#0B5394"},
            {"styleId": "s_table", "role": "tableCell", "font": "Noto Sans", "sizePt": 9, "align": "right"},
            {"styleId": "s_caption", "role": "caption", "font": "Noto Sans", "sizePt": 9, "italic": True, "color": "#555555"},
            {"styleId": "s_note", "role": "sourceNote", "font": "Noto Sans", "sizePt": 8, "color": "#666666"},
        ]},
        "customizationAST": {
            "controls": officer_customization_contract()["controls"],
            "documentControls": [
                {"controlId": "cover_title", "slotId": "slot_doc_cover_title", "required": True},
                {"controlId": "publication_status", "slotId": "slot_doc_publication_control", "required": True},
                {"controlId": "executive_summary", "slotId": "slot_doc_executive_summary", "required": False},
                {"controlId": "survey_notes", "slotId": "slot_doc_survey_notes", "required": False},
            ],
            "lockedStatisticalFields": officer_customization_contract()["lockedFields"],
        },
        "publicationAST": {
            "pageModes": publication_contract()["targetPageRange"],
            "frontMatterPages": 5,
            "analyticalPages": 54,
            "backMatterPages": 4,
            "minimumCompletePages": 40,
            "standardCompletePages": len(pages),
        },
        "officerGuideAST": {
            "reviewOrder": ["data contract", "entity bindings", "question readiness", "component slots", "publication controls"],
            "mustResolveBeforePublish": ["blocked required questions", "missing source lineage", "invalid aggregation"],
            "safeCustomizations": officer_customization_contract()["officerEditableFields"],
        },
        "semanticAST": {"sections": sections},
        "contentAST": {"blocks": blocks},
        "tableAST": {"tables": tables},
        "chartAST": {"charts": charts},
        "figureAST": {"figures": figures},
        "layoutAST": {"pages": pages},
        "geometryAST": {"_doc": "Relative flow only. Absolute bounding boxes are computed by the layout engine.", "flow": flow},
    }
    graph = {
        "$schema": "bharatstat/semantic-slot-graph/v1",
        "templateId": TEMPLATE_ID,
        "slots": slots,
        "issues": [],
        "counts": {
            "questions": sum(len(sec["questions"]) for topic in blueprint["topics"] for chapter in topic["chapters"] for sec in chapter["sections"]),
            "components": question_slot_count,
            "documentSlots": len(slots) - question_slot_count,
            "slotsCreated": len(slots),
            "semanticSlots": len(slots),
        },
        "slotPolicies": {
            "questionSlots": "filled by S4-S6 analytics, visuals, narrative, and provenance",
            "documentControlSlots": "filled by officer profile, publication controls, or deterministic defaults",
            "missingLineage": "publish_blocking_for_question_slots",
        },
    }
    return ast, graph


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    blueprint = build_blueprint()
    ast, graph = build_ast_and_slots(blueprint)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(OUT_DIR / "plfs_enterprise_annual.template.blueprint.json", blueprint)
    write_json(OUT_DIR / "plfs_enterprise_annual.template.ast.json", ast)
    write_json(OUT_DIR / "plfs_enterprise_annual.semantic_slot_graph.json", graph)
    print(
        json.dumps(
            {
                "templateId": TEMPLATE_ID,
                "topics": len(blueprint["topics"]),
                "chapters": sum(len(t["chapters"]) for t in blueprint["topics"]),
                "sections": sum(len(c["sections"]) for t in blueprint["topics"] for c in t["chapters"]),
                "questions": graph["counts"]["questions"],
                "components": graph["counts"]["components"],
                "documentSlots": graph["counts"]["documentSlots"],
                "semanticSlots": graph["counts"]["semanticSlots"],
                "charts": len(ast["chartAST"]["charts"]),
                "tables": len(ast["tableAST"]["tables"]),
                "pages": len(ast["layoutAST"]["pages"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
