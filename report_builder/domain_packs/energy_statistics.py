"""Domain Pack: Energy Statistics Annual Report.

Provides domain-specific entities, units, value domains, and deterministic
question templates for MoSPI Energy Statistics reports (Chapter 1: Reserves & Potential).

Used by:
- template_compiler.py (entity canonicalization, question generation)
- entity_enrichment.py (unit inference)
- question_compiler.py (Energy deterministic questions)
"""
from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Energy Domain Entities
# ─────────────────────────────────────────────────────────────────────────────

ENERGY_ENTITIES: list[dict[str, Any]] = [
    {"name": "State/UT", "aliases": ["States/ UTs", "States/UTs", "States/ UTs/ Region", "Region"], "entityType": "dimension", "unit": None},
    {"name": "Survey Period", "aliases": ["Period", "Year", "2024", "2025", "As on"], "entityType": "dimension", "unit": None},
    {"name": "Reserve Category", "aliases": ["Proved", "Indicated", "Inferred", "category"], "entityType": "dimension", "unit": None},
    {"name": "Coal Reserves", "aliases": ["Coal", "Estimated Reserves of Coal"], "entityType": "measure", "unit": "million_tonnes"},
    {"name": "Lignite Reserves", "aliases": ["Lignite", "Estimated Reserves of Lignite"], "entityType": "measure", "unit": "million_tonnes"},
    {"name": "Crude Oil Reserves", "aliases": ["Crude Oil", "Oil Reserves"], "entityType": "measure", "unit": "million_tonnes"},
    {"name": "Natural Gas Reserves", "aliases": ["Natural Gas", "Gas Reserves"], "entityType": "measure", "unit": "billion_cubic_metres"},
    {"name": "Total Reserves", "aliases": ["Total"], "entityType": "measure", "unit": "million_tonnes"},
    {"name": "Distribution Percent", "aliases": ["Distribution", "Distribution (%)", "%"], "entityType": "measure", "unit": "percent"},
    {"name": "Wind Power", "aliases": ["Wind Power@ 150m", "Wind"], "entityType": "measure", "unit": "MW"},
    {"name": "Solar Energy", "aliases": ["Solar", "Solar Power"], "entityType": "measure", "unit": "MW"},
    {"name": "Small Hydro Power", "aliases": ["Small Hydro", "Small Hydro Power*"], "entityType": "measure", "unit": "MW"},
    {"name": "Biomass Power", "aliases": ["Biomass"], "entityType": "measure", "unit": "MW"},
    {"name": "Large Hydro", "aliases": ["Large Hydro Power"], "entityType": "measure", "unit": "MW"},
    {"name": "Renewable Power Potential", "aliases": ["Renewable Power", "Renewable Energy Potential", "Total Potential"], "entityType": "measure", "unit": "MW"},
    {"name": "Energy Source", "aliases": ["Source", "Sourcewise"], "entityType": "dimension", "unit": None},
]


# ─────────────────────────────────────────────────────────────────────────────
# Energy Deterministic Question Templates
# ─────────────────────────────────────────────────────────────────────────────

ENERGY_QUESTION_TEMPLATES: list[dict[str, Any]] = [
    {
        "templateId": "energy_coal_rank",
        "intent": "Rank States/UTs by proved coal reserves for the current period.",
        "questionType": "ranking",
        "priority": 1,
        "requiredEntities": [
            {"entityRef": "Coal Reserves", "role": "measure", "required": True},
            {"entityRef": "State/UT", "role": "grouping", "required": True},
        ],
        "analyticsSpec": {"operation": "rank", "measure": "Coal Reserves", "groupBy": ["State/UT"], "topN": 10},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "bar"}},
            {"kind": "table", "outputContract": {"type": "table"}},
        ]},
        "sectionMatch": ["coal", "reserves of coal"],
    },
    {
        "templateId": "energy_coal_compare",
        "intent": "Compare total coal reserves across States/UTs for the current period.",
        "questionType": "comparison",
        "priority": 1,
        "requiredEntities": [
            {"entityRef": "Coal Reserves", "role": "measure", "required": True},
            {"entityRef": "State/UT", "role": "grouping", "required": True},
            {"entityRef": "Reserve Category", "role": "grouping", "required": False},
        ],
        "analyticsSpec": {"operation": "group_aggregate", "measure": "Coal Reserves", "groupBy": ["State/UT"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "grouped_bar"}},
            {"kind": "table", "outputContract": {"type": "table"}},
        ]},
        "sectionMatch": ["coal", "reserves"],
    },
    {
        "templateId": "energy_coal_composition",
        "intent": "Show composition of coal reserves by reserve category for the current period.",
        "questionType": "composition",
        "priority": 2,
        "requiredEntities": [
            {"entityRef": "Coal Reserves", "role": "measure", "required": True},
            {"entityRef": "Reserve Category", "role": "grouping", "required": True},
        ],
        "analyticsSpec": {"operation": "composition", "measure": "Coal Reserves", "groupBy": ["Reserve Category"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "pie"}},
        ]},
        "sectionMatch": ["coal", "category", "composition"],
    },
    {
        "templateId": "energy_coal_yoy",
        "intent": "Compare year-over-year change in proved coal reserves.",
        "questionType": "trend",
        "priority": 2,
        "requiredEntities": [
            {"entityRef": "Coal Reserves", "role": "measure", "required": True},
            {"entityRef": "Survey Period", "role": "time", "required": True},
        ],
        "analyticsSpec": {"operation": "growth", "measure": "Coal Reserves", "groupBy": ["Survey Period"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "grouped_bar"}},
        ]},
        "sectionMatch": ["coal", "change", "trend", "year"],
    },
    {
        "templateId": "energy_oil_gas_compare",
        "intent": "Compare crude oil and natural gas reserves by region for the current period.",
        "questionType": "comparison",
        "priority": 1,
        "requiredEntities": [
            {"entityRef": "Crude Oil Reserves", "role": "measure", "required": True},
            {"entityRef": "Natural Gas Reserves", "role": "measure", "required": False},
            {"entityRef": "State/UT", "role": "grouping", "required": True},
        ],
        "analyticsSpec": {"operation": "group_aggregate", "measure": "Crude Oil Reserves", "groupBy": ["State/UT"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "grouped_bar"}},
            {"kind": "table", "outputContract": {"type": "table"}},
        ]},
        "sectionMatch": ["crude oil", "natural gas", "region"],
    },
    {
        "templateId": "energy_renewable_compare",
        "intent": "Compare renewable power potential across States/UTs by energy source.",
        "questionType": "comparison",
        "priority": 1,
        "requiredEntities": [
            {"entityRef": "Renewable Power Potential", "role": "measure", "required": True},
            {"entityRef": "State/UT", "role": "grouping", "required": True},
            {"entityRef": "Energy Source", "role": "grouping", "required": False},
        ],
        "analyticsSpec": {"operation": "group_aggregate", "measure": "Renewable Power Potential", "groupBy": ["State/UT", "Energy Source"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "grouped_bar"}},
            {"kind": "table", "outputContract": {"type": "table"}},
        ]},
        "sectionMatch": ["renewable", "potential", "sourcewise", "statewise"],
    },
    {
        "templateId": "energy_renewable_rank",
        "intent": "Rank States/UTs by total renewable power potential.",
        "questionType": "ranking",
        "priority": 1,
        "requiredEntities": [
            {"entityRef": "Renewable Power Potential", "role": "measure", "required": True},
            {"entityRef": "State/UT", "role": "grouping", "required": True},
        ],
        "analyticsSpec": {"operation": "rank", "measure": "Renewable Power Potential", "groupBy": ["State/UT"], "topN": 10},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "bar"}},
        ]},
        "sectionMatch": ["renewable", "rank", "potential"],
    },
    {
        "templateId": "energy_lignite_compare",
        "intent": "Compare lignite reserves across States/UTs for the current period.",
        "questionType": "comparison",
        "priority": 2,
        "requiredEntities": [
            {"entityRef": "Lignite Reserves", "role": "measure", "required": True},
            {"entityRef": "State/UT", "role": "grouping", "required": True},
        ],
        "analyticsSpec": {"operation": "group_aggregate", "measure": "Lignite Reserves", "groupBy": ["State/UT"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "bar"}},
            {"kind": "table", "outputContract": {"type": "table"}},
        ]},
        "sectionMatch": ["lignite", "reserves"],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Compound Entity Merge Rules
# ─────────────────────────────────────────────────────────────────────────────

# Entities matching these patterns should be merged into canonical form
ENERGY_COMPOUND_MERGE: list[dict[str, str]] = [
    {"pattern": r"Crude Oil \d{4} Distribution", "canonical": "Distribution Percent", "reason": "year-specific distribution"},
    {"pattern": r"Crude Oil \d{4} Estimated", "canonical": "Crude Oil Reserves", "reason": "year-specific measure"},
    {"pattern": r"Natural Gas \d{4}", "canonical": "Natural Gas Reserves", "reason": "year-specific measure"},
    {"pattern": r"Proved \d{4}", "canonical": "Coal Reserves", "reason": "year-specific proved"},
    {"pattern": r"Indicated \d{4}", "canonical": "Coal Reserves", "reason": "year-specific indicated"},
    {"pattern": r"Inferred \d{4}", "canonical": "Coal Reserves", "reason": "year-specific inferred"},
]


# ─────────────────────────────────────────────────────────────────────────────
# Energy Template Metadata
# ─────────────────────────────────────────────────────────────────────────────

ENERGY_TEMPLATE_META: dict[str, Any] = {
    "domain": "energy",
    "sourceOrganization": "Ministry of Statistics and Programme Implementation (MoSPI)",
    "reportType": "statistical_annual_report",
    "indicators": ["Coal Reserves", "Lignite Reserves", "Crude Oil", "Natural Gas", "Renewable Power"],
}
