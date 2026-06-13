"""Generate the built-in MoSPI Energy Statistics enterprise template package.

Platinum-grade, value-free + prose-free analytic brain for a compact (<=9 page)
energy reserves and renewable-potential report. Emits three coordinated JSONs
under one template id:

  * energy_enterprise_annual.template.blueprint.json   - analytic brain
  * energy_enterprise_annual.template.ast.json         - render skeleton
  * energy_enterprise_annual.semantic_slot_graph.json  - slot wiring

The package contains NO observed values and NO generated prose. It defines
structure, entities, executable question contracts (with DIRECT / SHARE /
GROWTH formulas), officer customization controls, data + binder + publication
contracts, and the slot lineage map that the S0-S3.5 binder consumes and the
S4-S6 generation pipeline fills. Output JSON shapes mirror the binder-accepted
PLFS enterprise package exactly so the binder accepts and hands off without
re-derivation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TEMPLATE_ID = "tpl_mospi_energy_enterprise_annual_v1"
TEMPLATE_VERSION = "1.0.0"
TEMPLATE_NAME = "MoSPI Energy Statistics Enterprise Report"
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "report_builder" / "gold_standard"

# Compact publication: pack analytical sections onto shared pages so the whole
# package renders in <= 9 A4 pages including front and back matter.
MAX_PAGES = 9
SECTIONS_PER_PAGE = 2

# Unit display + binder synonym registry for energy measures.
UNIT_SYNONYMS = {
    "million_tonnes": ["million_tonnes", "MT", "Million Tonnes", "mt"],
    "billion_cubic_metres": ["billion_cubic_metres", "BCM", "Billion Cubic Metres", "bcm"],
    "MW": ["MW", "Megawatt", "megawatt", "MWp"],
    "GW": ["GW", "Gigawatt", "gigawatt"],
    "percent": ["percent", "%", "per cent", "share"],
    "percentage_points": ["percentage_points", "percentage points", "pp"],
}
UNIT_DISPLAY = {
    "million_tonnes": "MT",
    "billion_cubic_metres": "BCM",
    "MW": "MW",
    "GW": "GW",
    "percent": "%",
    "percentage_points": "percentage points",
}


def measure(
    entity_id: str,
    name: str,
    aliases: list[str],
    unit: str,
    aggregation: str,
    *,
    fmt: str = "number.2",
    scope: str = "indicator",
    is_total: bool = False,
    is_derived: bool = False,
) -> dict[str, Any]:
    value_domain: dict[str, Any] = (
        {"kind": "ratio", "min": 0, "max": 100} if unit == "percent" else {"kind": "ratio", "min": 0}
    )
    disallow = ["sum"] if unit in {"percent", "percentage_points"} else []
    return {
        "entityId": entity_id,
        "canonicalName": name,
        "entityType": "measure",
        "aliases": aliases,
        "unit": unit,
        "unitDisplay": UNIT_DISPLAY.get(unit, unit),
        "format": fmt,
        "valueDomain": value_domain,
        "aggregation": aggregation,
        "aggregationPolicy": {
            "default": aggregation,
            "allowed": [aggregation, "reported_value"] if aggregation != "reported_value" else ["reported_value"],
            "disallow": disallow,
            "notes": (
                "Shares and percentages must use reported values or same-grain "
                "numerator/denominator formulas; never sum or average row-level ratios. "
                "Physical reserves and capacities are additive and aggregate by sum."
            ),
        },
        "scope": scope,
        "conceptFamily": "energy_share" if is_derived else "energy_indicator",
        "dataRole": "indicator",
        "isTotal": is_total,
        "isDerived": is_derived,
        "binderHints": {
            "matchPriority": aliases,
            "requiresUnitEvidence": True,
            "unitSynonyms": UNIT_SYNONYMS.get(unit, [unit]),
            "preferExactAlias": True,
        },
        "qualityRules": [
            {"ruleId": f"qr_{entity_id}_non_null", "severity": "warn", "condition": "non_null_rate >= 0.90"},
            {"ruleId": f"qr_{entity_id}_unit", "severity": "error", "condition": "unit_or_header_confirms_measure"},
            {"ruleId": f"qr_{entity_id}_non_negative", "severity": "error", "condition": "min_value >= 0"},
        ],
        "evidenceRequirements": ["column_header", "unit_or_footnote", "source_table_or_statement"],
        "officerReview": {
            "required": True,
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
    # --- Conventional reserve measures ---
    measure("ent_coal_reserves", "Coal Reserves", ["Coal", "Coal Reserves", "Estimated Coal Reserves", "Coal (MT)"], "million_tonnes", "sum"),
    measure("ent_lignite_reserves", "Lignite Reserves", ["Lignite", "Lignite Reserves", "Lignite (MT)"], "million_tonnes", "sum"),
    measure("ent_proved_reserves", "Proved Reserves", ["Proved", "Proved Reserve", "Estimated Proved"], "million_tonnes", "sum"),
    measure("ent_indicated_reserves", "Indicated Reserves", ["Indicated", "Indicated Reserve"], "million_tonnes", "sum"),
    measure("ent_inferred_reserves", "Inferred Reserves", ["Inferred", "Inferred Reserve"], "million_tonnes", "sum"),
    measure("ent_total_reserves", "Total Reserves", ["Total", "Grand Total", "Total Reserves"], "million_tonnes", "sum", is_total=True),
    measure("ent_crude_oil_reserves", "Crude Oil Reserves", ["Crude Oil", "Crude Oil Estimated", "Oil Reserves"], "million_tonnes", "sum"),
    measure("ent_natural_gas_reserves", "Natural Gas Reserves", ["Natural Gas", "Gas Reserves", "Natural Gas Estimated"], "billion_cubic_metres", "sum"),
    measure("ent_reserve_distribution_pct", "Reserve Distribution Share", ["Distribution", "Distribution (%)", "Share", "Percentage Distribution"], "percent", "reported_value", fmt="percent.1", is_derived=True),
    # --- Renewable potential measures ---
    measure("ent_wind_power", "Wind Power Potential", ["Wind", "Wind Power Potential", "Wind Energy"], "MW", "sum", fmt="number.0"),
    measure("ent_solar_energy", "Solar Energy Potential", ["Solar", "Solar Power", "Solar Potential"], "MW", "sum", fmt="number.0"),
    measure("ent_small_hydro_power", "Small Hydro Power Potential", ["Small Hydro", "SHP"], "MW", "sum", fmt="number.0"),
    measure("ent_biomass_power", "Biomass Power Potential", ["Biomass", "Bio Power"], "MW", "sum", fmt="number.0"),
    measure("ent_cogeneration_bagasse", "Cogeneration-Bagasse Potential", ["Cogeneration", "Bagasse", "Cogen-Bagasse"], "MW", "sum", fmt="number.0"),
    measure("ent_large_hydro", "Large Hydro Potential", ["Large Hydro", "Large Hydro Power", "Large Hydroelectric"], "MW", "sum", fmt="number.0"),
    measure("ent_total_renewable_potential", "Total Renewable Potential", ["Total Renewable", "Total Potential", "Total RE Potential"], "MW", "sum", fmt="number.0", is_total=True),
    measure("ent_renewable_share_pct", "Renewable Source Share", ["Renewable Share", "Source Share", "Share of Potential"], "percent", "reported_value", fmt="percent.1", is_derived=True),
    # --- Dimensions ---
    dimension("ent_state_ut", "State/UT", ["State", "State/UT", "States/UTs", "States/ UTs", "Region", "State_UT"], "open", cardinality_hint="high", scope="geography"),
    dimension("ent_region", "Region", ["Region", "Zone", "NSS region"], ["North", "South", "East", "West", "Central", "North-East"], cardinality_hint="low", scope="geography"),
    dimension("ent_reserve_category", "Reserve Category", ["Category", "Reserve Type", "Classification"], ["Proved", "Indicated", "Inferred"], cardinality_hint="low", scope="classifier"),
    dimension("ent_energy_source", "Energy Source", ["Source", "Renewable Source", "Power Source"], ["Wind", "Solar", "Small Hydro", "Biomass", "Cogeneration-Bagasse", "Large Hydro"], cardinality_hint="low", scope="classifier"),
    dimension("ent_period", "Reference Period", ["Year", "Period", "As on", "Reference Year"], ["2024", "2025"], entity_type="time", cardinality_hint="low", scope="time"),
    dimension("ent_estimate_status", "Estimate Status", ["Estimate status", "status", "provisional", "assessed"], ["Final", "Provisional", "Assessed"], entity_type="metadata", scope="metadata"),
    dimension("ent_source_table", "Source Table", ["Table", "Statement", "source table", "table number"], "open", entity_type="metadata", scope="metadata"),
    dimension("ent_note", "Source Note", ["Note", "footnote", "remarks"], "open", entity_type="metadata", scope="metadata"),
]

ENTITY_LABEL = {e["entityId"]: e["canonicalName"] for e in ENTITIES}
ENTITY_UNIT = {e["entityId"]: e.get("unit") for e in ENTITIES}
ENTITY_FORMAT = {e["entityId"]: e.get("format") for e in ENTITIES}


def section(
    slug: str,
    title: str,
    measure_id: str,
    primary_dim: str,
    secondary_dim: str,
    *,
    formula: str = "DIRECT",
    denominator: str | None = None,
    comparison_period: str | None = None,
) -> dict[str, Any]:
    return {
        "slug": slug,
        "title": title,
        "measure": measure_id,
        "primary": primary_dim,
        "secondary": secondary_dim,
        "formula": formula,
        "denominator": denominator,
        "comparisonPeriod": comparison_period,
    }


# Two topics, four chapters, six sections (one question per section) -> compact.
TOPIC_SPECS = [
    {
        "slug": "conventional_reserves",
        "title": "Conventional Energy Reserves",
        "summary": "Coal, lignite, and hydrocarbon reserves across States/UTs with reserve-category structure.",
        "chapters": [
            ("coal_lignite", "Coal and Lignite Reserves", [
                section("coal_state", "Coal reserves by State/UT", "ent_coal_reserves", "ent_state_ut", "ent_reserve_category", formula="DIRECT"),
                section("reserve_category", "Reserve distribution by category", "ent_proved_reserves", "ent_reserve_category", "ent_state_ut", formula="SHARE", denominator="ent_total_reserves"),
            ]),
            ("hydrocarbons", "Hydrocarbon Reserves", [
                section("hydrocarbon_state", "Crude oil reserves by State/UT", "ent_crude_oil_reserves", "ent_state_ut", "ent_region", formula="DIRECT"),
            ]),
        ],
    },
    {
        "slug": "renewable_potential",
        "title": "Renewable Energy Potential",
        "summary": "Estimated renewable energy potential by source and geography, with source-mix structure.",
        "chapters": [
            ("re_capacity", "Renewable Capacity Potential", [
                section("renewable_source", "Potential by renewable source", "ent_wind_power", "ent_energy_source", "ent_region", formula="DIRECT"),
                section("renewable_state", "Renewable potential by State/UT", "ent_solar_energy", "ent_state_ut", "ent_energy_source", formula="DIRECT"),
            ]),
            ("re_mix", "Renewable Source Mix", [
                section("renewable_share", "Source share of total renewable potential", "ent_wind_power", "ent_energy_source", "ent_region", formula="SHARE", denominator="ent_total_renewable_potential"),
            ]),
        ],
    },
]


def required_entities(spec: dict[str, Any]) -> list[dict[str, Any]]:
    measure_id = spec["measure"]
    primary_dim = spec["primary"]
    secondary_dim = spec["secondary"]
    out: list[dict[str, Any]] = [
        {"entityId": measure_id, "role": "measure", "required": True},
        {"entityId": primary_dim, "role": "grouping", "required": True},
        {"entityId": secondary_dim, "role": "grouping", "required": False},
        {"entityId": "ent_period", "role": "time", "required": True, "periodRole": "current", "defaultMember": "2025"},
    ]
    if spec["formula"] == "SHARE" and spec.get("denominator"):
        out.append({"entityId": spec["denominator"], "role": "denominator", "required": True})
    if spec["formula"] == "GROWTH":
        out.append({"entityId": "ent_period", "role": "time", "required": True, "periodRole": "comparison", "defaultMember": spec.get("comparisonPeriod", "2024")})
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in out:
        key = (item["entityId"], item["role"], item.get("periodRole", ""))
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


def analytics_spec(spec: dict[str, Any], group_ids: list[str], *, operation: str = "group_aggregate", top_n: int | None = None) -> dict[str, Any]:
    measure_id = spec["measure"]
    unit = ENTITY_UNIT.get(measure_id)
    agg = "reported_value" if unit in {"percent", "percentage_points"} else "sum"
    out: dict[str, Any] = {
        "operation": operation,
        "measure": {"entityRef": measure_id, "agg": agg, "unit": unit},
        "groupBy": [{"entityRef": g} for g in group_ids],
        "filters": [],
        "sort": {"by": "measure", "order": "desc"},
        "topN": top_n,
        "time": {"entityRef": "ent_period", "periodRole": "current"},
        "grain": {
            "required": ["measure", "groupBy", "time"],
            "sameGrainBeforeFormula": True,
            "notes": "Every statistic is computed after grouping to the declared question grain; row-ratio averaging is prohibited.",
        },
        "weighting": {
            "weightEntityRef": None,
            "required": False,
            "policy": "physical_reserves_are_self_weighting",
        },
        "readiness": {
            "missingRequiredEntity": "BLOCKED",
            "missingOptionalEntity": "DEGRADED",
            "missingTime": "DEGRADED_SNAPSHOT",
            "missingDenominator": "BLOCKED",
            "missingComparisonPeriod": "BLOCKED",
            "invalidAggregation": "BLOCKED",
        },
        "audit": {
            "requiresLineage": True,
            "requiresAggregationTrace": True,
            "requiresFilterTrace": True,
        },
    }
    if spec["formula"] == "SHARE" and spec.get("denominator"):
        out["formula"] = {
            "type": "SHARE",
            "numeratorEntityRef": measure_id,
            "denominatorEntityRef": spec["denominator"],
            "multiplier": 100,
            "sameGrain": True,
            "policy": "Aggregate numerator and denominator at the same grain, then divide.",
        }
    elif spec["formula"] == "GROWTH":
        out["formula"] = {
            "type": "GROWTH",
            "measureEntityRef": measure_id,
            "currentPeriodRole": "current",
            "comparisonPeriodRole": "comparison",
            "policy": "Requires both current and comparison period at same grain.",
        }
    else:
        out["formula"] = {"type": "DIRECT", "measureEntityRef": measure_id}
    return out


def formula_spec(spec: dict[str, Any]) -> dict[str, Any]:
    if spec["formula"] == "SHARE" and spec.get("denominator"):
        return {
            "type": "SHARE",
            "numeratorEntityRef": spec["measure"],
            "denominatorEntityRef": spec["denominator"],
            "multiplier": 100,
            "sameGrain": True,
            "blockedWhenMissing": ["denominatorEntityRef", "sameGrainGrouping"],
        }
    if spec["formula"] == "GROWTH":
        return {
            "type": "GROWTH",
            "measureEntityRef": spec["measure"],
            "currentPeriodRole": "current",
            "comparisonPeriodRole": "comparison",
            "blockedWhenMissing": ["comparisonPeriod"],
        }
    return {"type": "DIRECT", "measureEntityRef": spec["measure"]}


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
                "default": "standard_8_pages",
                "options": [
                    {"value": "brief_6_pages", "label": "Brief 5-6 pages", "targetPages": [5, 6]},
                    {"value": "standard_8_pages", "label": "Standard 7-8 pages", "targetPages": [7, 8]},
                    {"value": "full_9_pages", "label": "Full 9 pages", "targetPages": [9, 9]},
                ],
            },
            {"controlId": "geography_depth", "label": "Geography depth", "type": "single_select", "default": "state_ut", "options": ["national", "region", "state_ut", "region_state_ut"]},
            {"controlId": "energy_lens", "label": "Energy lens", "type": "multi_select", "default": ["coal", "renewables"], "options": ["coal", "lignite", "hydrocarbons", "renewables", "reserve_category", "source_mix"]},
            {"controlId": "output_channels", "label": "Outputs", "type": "multi_select", "default": ["html", "pdf"], "options": ["html", "pdf", "docx_ready_ast", "annexure_tables", "provenance_log"]},
            {"controlId": "narrative_style", "label": "Narrative style", "type": "single_select", "default": "formal_statistical", "options": ["formal_statistical", "policy_brief", "technical_annexure"]},
            {"controlId": "visual_density", "label": "Visual density", "type": "single_select", "default": "balanced", "options": ["table_heavy", "balanced", "chart_heavy"]},
        ],
        "officerEditableFields": [
            "cover.title", "cover.subtitle", "publication.status", "reporting.period",
            "topic.enabled", "chapter.enabled", "section.enabled", "question.priority",
            "component.visibility", "chart.type", "table.sort", "annexure.include", "source_note.override",
        ],
        "lockedFields": [
            "entity.aggregationPolicy", "question.requiredEntities.required",
            "question.analyticsSpec.readiness", "formulaSpec.type", "slot.lineage",
        ],
    }


def data_contract() -> dict[str, Any]:
    return {
        "contractVersion": "mospi.energy.dataset.contract.v1",
        "minimumViableDataset": {
            "requiredMeasures": ["ent_coal_reserves", "ent_wind_power"],
            "requiredDimensions": ["ent_state_ut", "ent_period"],
            "recommendedMeasures": ["ent_proved_reserves", "ent_total_reserves", "ent_crude_oil_reserves", "ent_natural_gas_reserves", "ent_solar_energy", "ent_total_renewable_potential"],
            "recommendedDimensions": ["ent_reserve_category", "ent_energy_source", "ent_region"],
        },
        "acceptedInputShapes": [
            {"shapeId": "reserve_table_wide", "description": "Reserve columns wide by Proved/Indicated/Inferred/Total.", "normalizationNeeded": "WIDE_TO_LONG_OPTIONAL"},
            {"shapeId": "renewable_source_wide", "description": "Renewable potential columns wide by source (Wind/Solar/...).", "normalizationNeeded": "WIDE_TO_LONG_OPTIONAL"},
            {"shapeId": "state_panel_long", "description": "State/UT, source/category, period, and value in tidy panel form.", "normalizationNeeded": "NONE_OR_LIGHT_CANONICALIZATION"},
        ],
        "unitRegistry": {
            "million_tonnes": {"display": "MT", "validRange": [0, None], "aggregation": "sum"},
            "billion_cubic_metres": {"display": "BCM", "validRange": [0, None], "aggregation": "sum"},
            "MW": {"display": "MW", "validRange": [0, None], "aggregation": "sum"},
            "percent": {"display": "%", "validRange": [0, 100], "aggregation": "reported_value"},
            "percentage_points": {"display": "percentage points", "aggregation": "reported_value"},
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
            "Map State/UT name variants and reserve-category labels before S3.",
            "Keep source table identifiers as metadata columns where available.",
            "Preserve original column names in lineage even after canonicalization.",
            "Coal/lignite are MT; natural gas is BCM; renewable potential is MW - confirm units before binding.",
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
        "publicationVersion": "mospi.enterprise.energy.report.publication.v1",
        "targetPageRange": {"minimum": 6, "standard": 8, "maximum": 9},
        "hardPageCap": MAX_PAGES,
        "frontMatter": [
            {"id": "cover", "pages": 1, "officerEditable": True},
            {"id": "executive_summary", "pages": 1, "officerEditable": True},
            {"id": "contents", "pages": 1, "officerEditable": False},
        ],
        "analyticalBody": {
            "topics": len(TOPIC_SPECS),
            "chapters": sum(len(t["chapters"]) for t in TOPIC_SPECS),
            "sections": sum(len(c[2]) for t in TOPIC_SPECS for c in t["chapters"]),
            "sectionsPerPage": SECTIONS_PER_PAGE,
            "sectionPagePolicy": "two compact analytical sections share one flow page to honour the 9-page cap",
        },
        "backMatter": [
            {"id": "methodology_notes", "pages": 1},
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
            {"type": "SHARE", "policy": "Aggregate numerator and denominator at same grain, then divide and scale by 100."},
            {"type": "RATE", "policy": "Aggregate numerator and denominator at same grain, multiply by declared multiplier."},
            {"type": "RATIO", "policy": "Aggregate both sides at same grain; never average row ratios."},
            {"type": "GROWTH", "policy": "Requires current and comparison period at same grain."},
            {"type": "CAGR", "policy": "Requires explicit timeWindow."},
            {"type": "INDEX", "policy": "Requires explicit baseValue or base period."},
        ],
        "default": {"type": "DIRECT"},
        "usedInThisTemplate": ["DIRECT", "SHARE"],
        "blockedWhenMissing": ["denominatorColumn", "timeWindow", "baseValue", "sameGrainGrouping"],
    }


def statistical_context() -> dict[str, Any]:
    return {
        "sourceDocument": "Energy Statistics India",
        "ministry": "Ministry of Statistics and Programme Implementation",
        "domain": "energy",
        "chapters": ["Energy Reserves and Potential", "Renewable Energy Potential"],
        "geographyLevel": "state_ut",
        "timeCoverage": ["2024", "2025"],
        "referenceDates": ["As on 1st April 2025"],
        "dataSources": ["Geological Survey of India", "CMPDI", "MNRE", "Ministry of Petroleum and Natural Gas"],
        "footnotes": ["P: Provisional", "*: Assessed potential", "#: Includes pumped storage"],
        "glossary": {
            "CMPDI": "Central Mine Planning and Design Institute",
            "GSI": "Geological Survey of India",
            "MNRE": "Ministry of New and Renewable Energy",
            "BCM": "Billion Cubic Metres",
            "MT": "Million Tonnes",
            "MW": "Megawatt",
            "Proved Reserves": "Reserves established with the highest degree of geological confidence.",
            "Reserve Category": "Geological confidence classification: Proved, Indicated, or Inferred.",
            "reported_value": "Published or source-provided value used directly when it is deterministic at the selected grain.",
            "ExecutionBundle": "S3.5 handoff contract consumed by generation; blocked plans are not executed.",
        },
    }


def measure_families() -> list[dict[str, Any]]:
    return [
        {
            "familyId": "mf_reserves_by_category",
            "baseConcept": "Coal Reserves",
            "categoryDimension": "ent_reserve_category",
            "members": [
                {"label": "Proved", "entityRef": "ent_proved_reserves", "isTotal": False, "isDerived": False},
                {"label": "Indicated", "entityRef": "ent_indicated_reserves", "isTotal": False, "isDerived": False},
                {"label": "Inferred", "entityRef": "ent_inferred_reserves", "isTotal": False, "isDerived": False},
                {"label": "Total", "entityRef": "ent_total_reserves", "isTotal": True, "isDerived": False},
                {"label": "Distribution", "entityRef": "ent_reserve_distribution_pct", "isTotal": False, "isDerived": True, "unit": "percent"},
            ],
            "modelingAdvice": "both",
            "normalizationHint": "WIDE_TO_LONG",
        },
        {
            "familyId": "mf_renewable_potential_by_source",
            "baseConcept": "Renewable Energy Potential",
            "categoryDimension": "ent_energy_source",
            "members": [
                {"label": "Wind Power", "entityRef": "ent_wind_power", "isTotal": False, "isDerived": False},
                {"label": "Solar Energy", "entityRef": "ent_solar_energy", "isTotal": False, "isDerived": False},
                {"label": "Small Hydro", "entityRef": "ent_small_hydro_power", "isTotal": False, "isDerived": False},
                {"label": "Biomass Power", "entityRef": "ent_biomass_power", "isTotal": False, "isDerived": False},
                {"label": "Cogeneration-Bagasse", "entityRef": "ent_cogeneration_bagasse", "isTotal": False, "isDerived": False},
                {"label": "Large Hydro", "entityRef": "ent_large_hydro", "isTotal": False, "isDerived": False},
                {"label": "Total Renewable", "entityRef": "ent_total_renewable_potential", "isTotal": True, "isDerived": False},
            ],
            "modelingAdvice": "category_dimension",
            "normalizationHint": "WIDE_TO_LONG",
        },
    ]


def question(topic_slug: str, chapter_slug: str, spec: dict[str, Any]) -> dict[str, Any]:
    section_slug = spec["slug"]
    section_title = spec["title"]
    measure_id = spec["measure"]
    primary_dim = spec["primary"]
    secondary_dim = spec["secondary"]
    formula = spec["formula"]
    qid = f"q_{section_slug}_01"
    measure_name = ENTITY_LABEL[measure_id]
    primary_name = ENTITY_LABEL[primary_dim]
    secondary_name = ENTITY_LABEL[secondary_dim]
    is_rank = primary_dim == "ent_state_ut"
    if formula == "SHARE":
        operation = "share"
    elif formula == "GROWTH":
        operation = "growth"
    elif is_rank:
        operation = "rank"
    else:
        operation = "group_aggregate"
    groups = list(dict.fromkeys([primary_dim, secondary_dim]))
    if formula == "SHARE":
        intent = f"Decompose the share of {measure_name} within total {section_title.lower()} by {primary_name}."
    elif is_rank:
        intent = f"Rank States/UTs by {measure_name} for {section_title.lower()}."
    else:
        intent = f"Compare {measure_name} by {primary_name} and {secondary_name} for {section_title.lower()}."
    chart_type = "horizontal_bar" if is_rank else "grouped_bar"

    components = [
        {
            "componentId": f"{qid}_narrative",
            "kind": "narrative",
            "order": 1,
            "outputContract": {"type": "prose", "minWords": 50, "maxWords": 95, "requiresEvidence": True, "requiresCaveatWhenDegraded": True},
            "narrativeTemplate": {"tone": "formal-statistical", "pattern": "headline_then_evidence_then_caveat", "mustMention": [measure_id, primary_dim], "maxWords": 95},
            "customization": {"officerEditable": True, "controls": ["tone", "length", "include_caveat", "include_policy_signal"], "locked": ["mustMention", "evidenceRef"]},
            "refs": {"contentRef": f"p_{qid}_narrative", "analyticsRef": qid, "evidenceRef": f"ev_{qid}"},
        },
        {
            "componentId": f"{qid}_metric",
            "kind": "formula_metric",
            "order": 2,
            "outputContract": {"type": "metric", "metricEntityRef": measure_id, "format": ENTITY_FORMAT.get(measure_id), "requiresUnit": True, "requiresLineage": True},
            "formulaSpec": formula_spec(spec),
            "customization": {"officerEditable": True, "controls": ["show_delta", "show_rank", "display_precision"], "locked": ["formulaSpec.type", "metricEntityRef"]},
            "refs": {"contentRef": f"m_{qid}_metric", "analyticsRef": qid, "evidenceRef": f"ev_{qid}"},
        },
        {
            "componentId": f"{qid}_chart",
            "kind": "chart",
            "order": 3,
            "outputContract": {"type": "chart", "chartType": chart_type, "xAxis": primary_dim, "yAxis": measure_id, "requiresAltText": True, "requiresSourceNote": True},
            "customization": {"officerEditable": True, "controls": ["chartType", "topN", "sortOrder", "colorTheme", "showDataLabels"], "allowedChartTypes": ["grouped_bar", "horizontal_bar", "stacked_bar", "line"], "locked": ["xAxis.entityRef", "yAxis.entityRef", "analyticsRef"]},
            "refs": {"chartRef": f"chart_{qid}", "figureRef": f"fig_{qid}", "analyticsRef": qid, "evidenceRef": f"ev_{qid}"},
        },
        {
            "componentId": f"{qid}_table",
            "kind": "table",
            "order": 4,
            "outputContract": {"type": "table", "tableTemplateRef": f"tt_{qid}", "requiresHeaderUnits": True, "requiresFootnotes": True},
            "customization": {"officerEditable": True, "controls": ["topN", "sortOrder", "includeTotalRow", "decimalPlaces"], "locked": ["entity columns", "source footnote"]},
            "refs": {"tableRef": f"table_{qid}", "analyticsRef": qid, "evidenceRef": f"ev_{qid}"},
        },
        {
            "componentId": f"{qid}_provenance",
            "kind": "provenance",
            "order": 5,
            "outputContract": {"type": "source_note", "requiresLineage": True},
            "customization": {"officerEditable": True, "controls": ["source_note_text", "include_table_number", "include_extraction_confidence"], "locked": ["lineageRef", "datasetSignature"]},
            "refs": {"contentRef": f"p_{qid}_provenance", "analyticsRef": qid, "evidenceRef": f"ev_{qid}"},
        },
    ]

    return {
        "questionId": qid,
        "intent": intent,
        "questionText": intent,
        "questionType": "share_decomposition" if formula == "SHARE" else "ranking" if is_rank else "comparison",
        "priority": 1,
        "requiredEntities": required_entities(spec),
        "analyticsSpec": analytics_spec(spec, groups, operation=operation, top_n=10 if is_rank else None),
        "formulaSpec": formula_spec(spec),
        "answerStructure": {"components": components},
        "officerIntent": {
            "decisionUse": "Identify reportable energy contrasts, leading States/UTs, and reserve/source structure for official release.",
            "primaryAudience": ["MoSPI officer", "energy statistics officer", "policy analyst"],
            "reviewFocus": [measure_id, primary_dim, secondary_dim, "ent_period"],
        },
        "dataRequirements": {
            "requiredEntities": [e["entityId"] for e in required_entities(spec) if e.get("required")],
            "optionalEntities": [secondary_dim, "ent_source_table", "ent_estimate_status"],
            "minimumRows": 1,
            "preferredGrain": [primary_dim, secondary_dim, "ent_period"],
        },
        "binderContract": {
            "s3StatusWhenComplete": "executable",
            "s3StatusWhenMissingOptionalGrouping": "degraded",
            "s3StatusWhenMissingMeasureOrPrimaryGrouping": "blocked",
            "s3StatusWhenMissingDenominator": "blocked" if formula == "SHARE" else "n/a",
            "mustEmitLineage": True,
            "mustPreserveSlotIds": True,
        },
        "qualityGates": [
            {"gateId": f"gate_{qid}_measure_bound", "severity": "error", "condition": f"{measure_id} is confirmed"},
            {"gateId": f"gate_{qid}_primary_group_bound", "severity": "error", "condition": f"{primary_dim} is confirmed"},
            {"gateId": f"gate_{qid}_time_bound", "severity": "warn", "condition": "ent_period is confirmed or snapshot mode is explicit"},
            {"gateId": f"gate_{qid}_lineage", "severity": "error", "condition": "all answer components have lineage"},
        ] + ([{"gateId": f"gate_{qid}_denominator_bound", "severity": "error", "condition": f"{spec['denominator']} is confirmed for SHARE"}] if formula == "SHARE" else []),
        "answerPlan": {
            "sequence": ["narrative", "metric", "chart", "table", "provenance"],
            "pageWeight": 0.5,
            "fallbackWhenDegraded": "show available metric/table with explicit caveat and source note",
            "blockedWhen": ["required measure unresolved", "primary grouping unresolved", "missing denominator for SHARE", "invalid aggregation policy"],
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
            "Confirm the selected measure is the official energy concept for this section.",
            "Confirm grouping values (States/UTs, categories, sources) are correctly mapped and ordered.",
            "Confirm units (MT / BCM / MW / %) match the source headers.",
            "For shares, confirm the denominator (total) is bound at the same grain.",
            "Confirm source notes and table references are present before publication.",
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
            "officerSummary": topic_spec["summary"],
            "pageBudget": {"brief": 1, "standard": 2, "expanded": 3},
            "customization": {"officerEditable": True, "controls": ["enabled", "priority", "include_in_executive_summary", "compact_mode"]},
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
                "pageBudget": {"brief": 0.5, "standard": 1, "expanded": 1.5},
                "qualityGate": {"minimumExecutableQuestions": 1, "missingAllQuestions": "BLOCKED"},
                "sections": [],
            }
            for section_order, spec in enumerate(sections, start=1):
                section_id = f"section_{spec['slug']}"
                q = question(topic_spec["slug"], chapter_slug, spec)
                chapter["sections"].append({
                    "sectionId": section_id,
                    "title": spec["title"],
                    "order": section_order,
                    "sectionArchetype": "metric_chart_table_provenance",
                    "formulaType": spec["formula"],
                    "pagePlan": {"standardPages": 0.5, "compactPages": 0.5, "expandedPages": 1.0, "preferredBreak": "share_flow_region"},
                    "officerControls": ["enabled", "priority", "chartType", "tableTopN", "includeProvenanceNote"],
                    "deliverables": ["narrative", "headline_metric", "chart", "table", "source_note"],
                    "readinessGate": {"minimumExecutableQuestions": 1, "ifAllQuestionsBlocked": "BLOCKED", "ifOptionalOnlyMissing": "DEGRADED"},
                    "questions": [q],
                })
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
                    "displayControls": {"topN": 10, "includeTotalRow": spec["formula"] == "SHARE", "showMissingAs": "-", "officerEditable": ["topN", "sortOrder", "includeTotalRow", "decimalPlaces"]},
                    "accessibility": {"requiresHeaderScope": True, "requiresUnitInHeader": True},
                    "lineagePolicy": {"requiresSourceTable": False, "requiresDatasetSignature": True, "locked": True},
                    "footnotes": [
                        {"noteId": f"fn_source_{qid}", "marker": "Source", "textTemplate": "Source: {{dataset.title}}, {{period.current}}."},
                        {"noteId": f"fn_scope_{qid}", "marker": "Note", "textTemplate": "Estimates follow Energy Statistics India concepts and units for the selected universe."},
                    ],
                    "emptyPolicy": "show_dash",
                })
                figure_templates.append({
                    "figureTemplateId": f"ft_{qid}",
                    "captionTemplate": f"{ENTITY_LABEL[measure_id]} by {ENTITY_LABEL[dim_id]}, {{{{period.current}}}}",
                    "chartId": f"chart_{qid}",
                    "numbering": "Figure {{topic.order}}.{{chapter.order}}.{{seq}}",
                    "accessibility": {"requiresAltText": True, "altTextTemplate": q["intent"]},
                    "displayControls": {"showDataLabels": True, "showLegend": True, "officerEditable": ["chartType", "palette", "topN", "showDataLabels"]},
                    "lineagePolicy": {"requiresEvidenceRef": True, "locked": True},
                })
            topic["chapters"].append(chapter)
        topics.append(topic)

    total_sections = sum(len(c["sections"]) for t in topics for c in t["chapters"])
    analytical_pages = -(-total_sections // SECTIONS_PER_PAGE)  # ceil

    return {
        "$schema": "bharatstat/template-blueprint/v1",
        "contractVersion": "template.extraction.v2",
        "_doc": "VALUE-FREE + PROSE-FREE platinum enterprise analytic brain for a compact (<=9 page) MoSPI Energy Statistics report. Contains no observed values and no generated prose; it defines structure, controls, contracts, formulas, and officer review needs.",
        "templateMeta": {
            "templateId": TEMPLATE_ID,
            "name": TEMPLATE_NAME,
            "domain": "energy",
            "reportType": "mospi_enterprise_energy_annual",
            "locale": "en-IN",
            "version": TEMPLATE_VERSION,
            "sourceDocument": "Energy Statistics India",
            "valueFree": True,
            "proseFree": True,
            "targetPageCount": "6-9",
            "standardPageCount": 8,
            "hardPageCap": MAX_PAGES,
            "description": "Platinum enterprise built-in energy template: nested topics, chapters, sections, executable question contracts with DIRECT and SHARE formulas, answer structures, officer customization controls, data + binder + publication contracts, and slot wiring for compact MoSPI-style energy report generation.",
            "templateClass": "enterprise_publication",
            "releaseStage": "built_in_officer_ready",
            "createdBy": "BharatStat deterministic template generator",
            "lastUpdated": "2026-06-13",
            "compatibleStages": ["S0", "S1", "S2", "S3", "S3.5", "S4", "S5", "S6", "S7"],
            "governance": {
                "ownerRole": "MoSPI energy report officer",
                "reviewRoles": ["statistical reviewer", "publication reviewer", "data steward"],
                "approvalRequiredFor": ["locked statistical contracts", "publication status", "source note overrides"],
                "auditMode": "lineage_required",
            },
        },
        "statisticalContext": statistical_context(),
        "enterprisePlan": {
            "targetPages": 8,
            "minimumPages": 6,
            "maximumPages": MAX_PAGES,
            "outlineDepth": ["topic", "chapter", "section", "question", "answer_component"],
            "buildSteps": [
                "Bind dataset columns to canonical energy entities.",
                "Resolve every section question into executable S3/S3.5 roles (including SHARE denominators).",
                "Fill narrative, metric, chart, table, and provenance slots per question.",
                "Assemble front matter, compact analytical sections, and methodology/provenance back matter.",
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
        "measureFamilies": measure_families(),
        "qualityGateProfile": {
            "profileId": "mospi_energy_enterprise_quality_v1",
            "minimumBinderReadinessScore": 80,
            "minimumQuestionExecutabilityPct": 70,
            "minimumLineageCoveragePct": 95,
            "failOn": ["missing required measure", "missing SHARE denominator", "invalid formula", "missing source lineage for published component"],
            "warnOn": ["missing optional grouping", "snapshot time fallback", "low confidence entity match"],
        },
        "officerWorkbench": {
            "defaultViews": ["template_overview", "data_contract", "entity_review", "question_readiness", "publication_controls"],
            "quickFilters": ["blocked", "degraded", "missing_lineage", "officer_editable", "locked_contract"],
            "primaryActions": ["confirm entity", "override binding", "hide optional section", "promote reviewed plan", "export provenance"],
        },
        "glossary": statistical_context()["glossary"],
        "palette": {
            "paletteId": "pal_mospi_energy",
            "sequential": ["#0B5394", "#3D85C6", "#6FA8DC", "#9FC5E8", "#CFE2F3"],
            "categorical": {"Proved": "#0B5394", "Indicated": "#3D85C6", "Inferred": "#6FA8DC", "Total": "#333333", "Wind": "#1F7A1F", "Solar": "#E69138", "Small Hydro": "#3D85C6", "Biomass": "#6AA84F", "Large Hydro": "#0B5394"},
            "semantic": {"positive": "#1F7A1F", "negative": "#CC0000", "neutral": "#666666", "caution": "#F6B26B"},
        },
        "renderProfile": {
            "numberFormat": {"locale": "en-IN", "grouping": "lakh-crore", "decimalSeparator": "."},
            "percentFormat": {"decimals": 1, "suffix": "%"},
            "fontFamily": "Noto Sans",
            "pageSize": "A4",
            "densityModes": {
                "brief_6_pages": {"combineLowPrioritySections": True, "maxChartsPerSection": 1, "sectionsPerPage": 2},
                "standard_8_pages": {"combineLowPrioritySections": False, "maxChartsPerSection": 1, "sectionsPerPage": 2},
                "full_9_pages": {"includeAnnexureDetail": True, "maxChartsPerSection": 1, "sectionsPerPage": 2},
            },
        },
        "entities": ENTITIES,
        "topics": topics,
        "tableTemplates": table_templates,
        "figureTemplates": figure_templates,
        "externalTableReferences": [
            {"refId": "annex_table_01", "title": "Annexure: State/UT reserve detail", "required": False},
            {"refId": "annex_table_02", "title": "Annexure: Renewable potential by source", "required": False},
        ],
        "documentMap": {
            "order": document_order,
            "frontMatter": ["cover", "executive_summary", "contents"],
            "backMatter": ["methodology_notes", "provenance_log"],
            "estimatedPages": {"frontMatter": 3, "analyticalSections": analytical_pages, "backMatter": 2, "total": 3 + analytical_pages + 2},
            "pageModes": {
                "brief_6_pages": {"frontMatter": 2, "analyticalSections": analytical_pages, "backMatter": 1, "total": 3 + analytical_pages},
                "standard_8_pages": {"frontMatter": 3, "analyticalSections": analytical_pages, "backMatter": 2, "total": 5 + analytical_pages},
                "full_9_pages": {"frontMatter": 3, "analyticalSections": analytical_pages + 1, "backMatter": 2, "total": 6 + analytical_pages},
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
    order = 1
    page_num = 1

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

    # --- Front matter ---
    for doc_id, title, role, page_role, style_ref in [
        ("cover_title", "Cover and report identity", "cover_title", "front_matter_cover", "s_h1"),
        ("executive_summary", "Executive summary", "executive_summary", "front_matter_summary", "s_body"),
        ("contents", "Table of contents", "toc", "front_matter_contents", "s_body"),
    ]:
        add_document_block(doc_id, title, role, page_role, style_ref)

    # --- Analytical body: pack SECTIONS_PER_PAGE sections per shared flow page ---
    pending_regions: list[str] = []

    def flush_page() -> None:
        nonlocal page_num, pending_regions
        if not pending_regions:
            return
        pages.append({
            "pageId": f"pg_{page_num:03d}",
            "size": "A4",
            "role": "section_flow",
            "regions": [{"regionId": rid, "role": "section_flow", "bindsTo": rid.replace("rg_", "section_", 1), "bbox": None} for rid in pending_regions],
        })
        page_num += 1
        pending_regions = []

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
                            charts.append({"chartId": chart_id, "biQuery": qid, "chartType": comp["outputContract"].get("chartType", "grouped_bar"), "title": q["intent"], "xAxis": {"entityRef": dim_id, "label": ENTITY_LABEL[dim_id]}, "yAxis": {"entityRef": measure_id, "label": ENTITY_LABEL[measure_id], "unit": ENTITY_UNIT.get(measure_id)}, "paletteRef": "pal_mospi_energy", "series": [], "slot": {"fillFrom": comp["componentId"], "status": "empty"}})
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
                flow.append(region_id)
                pending_regions.append(region_id)
                order += 1
                if len(pending_regions) >= SECTIONS_PER_PAGE:
                    flush_page()
    flush_page()

    # --- Back matter ---
    for doc_id, title, role, page_role, style_ref in [
        ("methodology_notes", "Methodology and definitions", "methodology_note", "back_matter_methodology", "s_note"),
        ("provenance_log", "Provenance and audit log", "provenance_log", "back_matter_provenance", "s_note"),
    ]:
        add_document_block(doc_id, title, role, page_role, style_ref)

    ast = {
        "$schema": "bharatstat/template-ast/v1",
        "_doc": "VALUE-FREE render skeleton for the MoSPI Energy Statistics enterprise built-in package. All content, rows, series, captions, and officer text fields are empty placeholders.",
        "metadata": {
            "templateId": TEMPLATE_ID,
            "blueprintRef": TEMPLATE_ID,
            "name": TEMPLATE_NAME,
            "locale": "en-IN",
            "version": TEMPLATE_VERSION,
            "valueFree": True,
            "generatedFrom": "enterprise_built_in_energy_generator",
            "targetPageRange": "6-9",
            "standardPageCount": 8,
            "hardPageCap": MAX_PAGES,
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
                {"controlId": "executive_summary", "slotId": "slot_doc_executive_summary", "required": False},
                {"controlId": "methodology_notes", "slotId": "slot_doc_methodology_notes", "required": False},
            ],
            "lockedStatisticalFields": officer_customization_contract()["lockedFields"],
        },
        "publicationAST": {
            "pageModes": publication_contract()["targetPageRange"],
            "frontMatterPages": 3,
            "analyticalPages": len([p for p in pages if p.get("role") == "section_flow"]),
            "backMatterPages": 2,
            "minimumCompletePages": 6,
            "standardCompletePages": len(pages),
            "hardPageCap": MAX_PAGES,
        },
        "officerGuideAST": {
            "reviewOrder": ["data contract", "entity bindings", "question readiness", "component slots", "publication controls"],
            "mustResolveBeforePublish": ["blocked required questions", "missing SHARE denominator", "missing source lineage", "invalid aggregation"],
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
    write_json(OUT_DIR / "energy_enterprise_annual.template.blueprint.json", blueprint)
    write_json(OUT_DIR / "energy_enterprise_annual.template.ast.json", ast)
    write_json(OUT_DIR / "energy_enterprise_annual.semantic_slot_graph.json", graph)
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
                "pageCapOk": len(ast["layoutAST"]["pages"]) <= MAX_PAGES,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
