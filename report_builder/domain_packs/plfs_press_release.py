"""Domain Pack: PLFS Press Release.

Provides domain-specific entities, units, value domains, and deterministic
question templates for PIB/PLFS press-release PDFs.

Used by:
- extraction_pipeline.py (pass 2.5 pre-seeding)
- question_compiler.py (PIB deterministic questions)
- entity_enrichment.py (unit inference)
- extraction_diagnostics.py (doc-type-aware scoring)
"""
from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# PLFS Domain Entities (complete ontology)
# ─────────────────────────────────────────────────────────────────────────────

PLFS_ENTITIES: list[dict[str, Any]] = [
    # ── Measures (rate/ratio indicators) ──
    {
        "name": "Labour Force Participation Rate",
        "aliases": ["LFPR", "Labour Force Participation"],
        "entityType": "measure",
        "unit": "percent",
        "valueDomain": {"kind": "ratio", "min": 0, "max": 100},
        "source": "domain_pack",
    },
    {
        "name": "Worker Population Ratio",
        "aliases": ["WPR", "Worker Population"],
        "entityType": "measure",
        "unit": "percent",
        "valueDomain": {"kind": "ratio", "min": 0, "max": 100},
        "source": "domain_pack",
    },
    {
        "name": "Unemployment Rate",
        "aliases": ["UR", "Unemployment"],
        "entityType": "measure",
        "unit": "percent",
        "valueDomain": {"kind": "ratio", "min": 0, "max": 100},
        "source": "domain_pack",
    },
    {
        "name": "Worker Share",
        "aliases": ["Percentage Distribution", "proportion of workers", "share of workers"],
        "entityType": "measure",
        "unit": "percent",
        "valueDomain": {"kind": "ratio", "min": 0, "max": 100},
        "source": "domain_pack",
    },
    {
        "name": "Average Weekly Hours",
        "aliases": ["weekly hours", "hours worked", "hours per week"],
        "entityType": "measure",
        "unit": "hours_per_week",
        "valueDomain": {"kind": "ratio", "min": 0, "max": 168},
        "source": "domain_pack",
    },
    {
        "name": "Average Monthly Earnings",
        "aliases": ["monthly earnings", "earnings", "average earnings", "wages"],
        "entityType": "measure",
        "unit": "INR",
        "valueDomain": {"kind": "ratio", "min": 0},
        "source": "domain_pack",
    },
    {
        "name": "Formal Education Years",
        "aliases": ["years of education", "formal education", "education years", "average years"],
        "entityType": "measure",
        "unit": "years",
        "valueDomain": {"kind": "ratio", "min": 0, "max": 25},
        "source": "domain_pack",
    },
    # ── Dimensions ──
    {
        "name": "Gender",
        "aliases": ["Male", "Female", "Persons", "sex"],
        "entityType": "dimension",
        "unit": None,
        "valueDomain": {"kind": "categorical", "members": ["Male", "Female", "Persons"]},
        "source": "domain_pack",
    },
    {
        "name": "Sector",
        "aliases": ["Rural", "Urban", "Rural/Urban", "area"],
        "entityType": "dimension",
        "unit": None,
        "valueDomain": {"kind": "categorical", "members": ["Rural", "Urban"]},
        "source": "domain_pack",
    },
    {
        "name": "Age Group",
        "aliases": ["15+", "15-29", "15-59", "Youth", "age cohort"],
        "entityType": "dimension",
        "unit": None,
        "valueDomain": {"kind": "categorical", "members": ["15 years and above", "15-29 years", "15-59 years"]},
        "source": "domain_pack",
    },
    {
        "name": "Employment Status",
        "aliases": ["Status in Employment", "self-employed", "regular wage", "casual labour", "employment type"],
        "entityType": "dimension",
        "unit": None,
        "valueDomain": {"kind": "categorical", "members": ["Self-employed", "Regular wage/salaried", "Casual labour"]},
        "source": "domain_pack",
    },
    {
        "name": "Industry",
        "aliases": ["sector of work", "manufacturing", "services", "agriculture", "construction"],
        "entityType": "dimension",
        "unit": None,
        "valueDomain": {"kind": "categorical", "members": ["Agriculture", "Manufacturing", "Construction", "Services", "Other"]},
        "source": "domain_pack",
    },
    {
        "name": "Survey Period",
        "aliases": ["Survey Year", "period", "2024", "2025", "January-December"],
        "entityType": "dimension",
        "unit": None,
        "valueDomain": {"kind": "temporal", "grain": "annual"},
        "source": "domain_pack",
    },
    {
        "name": "Activity Status",
        "aliases": ["Usual Status", "ps+ss", "CWS", "principal status", "subsidiary status"],
        "entityType": "dimension",
        "unit": None,
        "valueDomain": {"kind": "categorical", "members": ["Usual Status (ps+ss)", "CWS"]},
        "source": "domain_pack",
    },
    # ── Metadata ──
    {
        "name": "Periodic Labour Force Survey",
        "aliases": ["PLFS"],
        "entityType": "metadata",
        "unit": None,
        "valueDomain": None,
        "source": "domain_pack",
    },
    {
        "name": "MoSPI",
        "aliases": ["Ministry of Statistics", "NSO", "National Statistical Office"],
        "entityType": "metadata",
        "unit": None,
        "valueDomain": None,
        "source": "domain_pack",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# PIB Deterministic Question Templates
# ─────────────────────────────────────────────────────────────────────────────

PLFS_QUESTION_TEMPLATES: list[dict[str, Any]] = [
    {
        "templateId": "plfs_snapshot",
        "intent": "Summarize headline LFPR, WPR, and UR indicators for the current period.",
        "questionType": "snapshot",
        "priority": 1,
        "requiredEntities": [
            {"entityRef": "Labour Force Participation Rate", "role": "measure", "required": True},
            {"entityRef": "Worker Population Ratio", "role": "measure", "required": True},
            {"entityRef": "Unemployment Rate", "role": "measure", "required": True},
            {"entityRef": "Survey Period", "role": "filter", "required": True},
        ],
        "analyticsSpec": {"operation": "summary", "measures": ["LFPR", "WPR", "UR"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 120}},
            {"kind": "metric_card", "outputContract": {"type": "metric_cards", "count": 3}},
        ]},
        "sectionMatch": ["key findings", "snapshot", "highlights"],
    },
    {
        "templateId": "plfs_lfpr_comparison",
        "intent": "Compare LFPR by sector and gender for persons aged 15 years and above.",
        "questionType": "comparison",
        "priority": 2,
        "requiredEntities": [
            {"entityRef": "Labour Force Participation Rate", "role": "measure", "required": True},
            {"entityRef": "Gender", "role": "grouping", "required": True},
            {"entityRef": "Sector", "role": "grouping", "required": False},
        ],
        "analyticsSpec": {"operation": "group_aggregate", "measure": "LFPR", "groupBy": ["Gender", "Sector"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "grouped_bar"}},
        ]},
        "sectionMatch": ["lfpr", "labour force participation"],
    },
    {
        "templateId": "plfs_wpr_comparison",
        "intent": "Compare WPR by sector and gender for persons aged 15 years and above.",
        "questionType": "comparison",
        "priority": 2,
        "requiredEntities": [
            {"entityRef": "Worker Population Ratio", "role": "measure", "required": True},
            {"entityRef": "Gender", "role": "grouping", "required": True},
            {"entityRef": "Sector", "role": "grouping", "required": False},
        ],
        "analyticsSpec": {"operation": "group_aggregate", "measure": "WPR", "groupBy": ["Gender", "Sector"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "grouped_bar"}},
        ]},
        "sectionMatch": ["wpr", "worker population"],
    },
    {
        "templateId": "plfs_ur_comparison",
        "intent": "Compare Unemployment Rate by sector and gender for persons aged 15 years and above.",
        "questionType": "comparison",
        "priority": 2,
        "requiredEntities": [
            {"entityRef": "Unemployment Rate", "role": "measure", "required": True},
            {"entityRef": "Gender", "role": "grouping", "required": True},
            {"entityRef": "Sector", "role": "grouping", "required": False},
        ],
        "analyticsSpec": {"operation": "group_aggregate", "measure": "UR", "groupBy": ["Gender", "Sector"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "grouped_bar"}},
        ]},
        "sectionMatch": ["unemployment", "ur "],
    },
    {
        "templateId": "plfs_employment_status",
        "intent": "Show percentage distribution of workers by status in employment.",
        "questionType": "composition",
        "priority": 2,
        "requiredEntities": [
            {"entityRef": "Worker Share", "role": "measure", "required": True},
            {"entityRef": "Employment Status", "role": "grouping", "required": True},
            {"entityRef": "Survey Period", "role": "filter", "required": False},
        ],
        "analyticsSpec": {"operation": "composition", "measure": "Worker Share", "groupBy": ["Employment Status"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "pie"}},
        ]},
        "sectionMatch": ["proportion of workers", "employment status", "regular wage", "self-employed"],
    },
    {
        "templateId": "plfs_industry",
        "intent": "Show distribution of workers by industry of work.",
        "questionType": "composition",
        "priority": 2,
        "requiredEntities": [
            {"entityRef": "Worker Share", "role": "measure", "required": True},
            {"entityRef": "Industry", "role": "grouping", "required": True},
        ],
        "analyticsSpec": {"operation": "composition", "measure": "Worker Share", "groupBy": ["Industry"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "bar"}},
        ]},
        "sectionMatch": ["manufacturing", "service sector", "industry", "worker participation"],
    },
    {
        "templateId": "plfs_earnings",
        "intent": "Compare average monthly earnings by employment type and gender.",
        "questionType": "comparison",
        "priority": 2,
        "requiredEntities": [
            {"entityRef": "Average Monthly Earnings", "role": "measure", "required": True},
            {"entityRef": "Gender", "role": "grouping", "required": True},
            {"entityRef": "Employment Status", "role": "grouping", "required": False},
        ],
        "analyticsSpec": {"operation": "group_aggregate", "measure": "Average Monthly Earnings", "groupBy": ["Gender", "Employment Status"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "grouped_bar"}},
        ]},
        "sectionMatch": ["earnings", "female workers", "monthly earnings"],
    },
    {
        "templateId": "plfs_education",
        "intent": "Compare average years of formal education by gender and sector.",
        "questionType": "comparison",
        "priority": 3,
        "requiredEntities": [
            {"entityRef": "Formal Education Years", "role": "measure", "required": True},
            {"entityRef": "Gender", "role": "grouping", "required": True},
            {"entityRef": "Sector", "role": "grouping", "required": False},
        ],
        "analyticsSpec": {"operation": "group_aggregate", "measure": "Formal Education Years", "groupBy": ["Gender", "Sector"]},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 80}},
            {"kind": "chart", "outputContract": {"type": "chart", "chartType": "bar"}},
        ]},
        "sectionMatch": ["education", "formal education", "years"],
    },
    {
        "templateId": "plfs_methodology",
        "intent": "Describe the survey methodology, sample design, and key definitions.",
        "questionType": "descriptive",
        "priority": 4,
        "requiredEntities": [
            {"entityRef": "Periodic Labour Force Survey", "role": "context", "required": True},
        ],
        "analyticsSpec": {"operation": "describe"},
        "answerStructure": {"components": [
            {"kind": "narrative", "outputContract": {"type": "prose", "maxWords": 200}},
        ]},
        "sectionMatch": ["methodology", "endnote", "sample size", "conceptual framework", "introduction"],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# PIB Template Metadata
# ─────────────────────────────────────────────────────────────────────────────

PLFS_TEMPLATE_META: dict[str, Any] = {
    "domain": "labour_force",
    "sourceOrganization": "Ministry of Statistics and Programme Implementation (MoSPI)",
    "reportType": "pib_press_release",
    "indicators": ["LFPR", "WPR", "UR"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Unit inference rules for PLFS entities
# ─────────────────────────────────────────────────────────────────────────────

PLFS_UNIT_RULES: dict[str, str] = {
    "Labour Force Participation Rate": "percent",
    "Worker Population Ratio": "percent",
    "Unemployment Rate": "percent",
    "Worker Share": "percent",
    "Average Weekly Hours": "hours_per_week",
    "Average Monthly Earnings": "INR",
    "Formal Education Years": "years",
    "LFPR": "percent",
    "WPR": "percent",
    "UR": "percent",
}


# ─────────────────────────────────────────────────────────────────────────────
# Text-first entity extraction signals (regex patterns for PIB text)
# ─────────────────────────────────────────────────────────────────────────────

PIB_TEXT_ENTITY_PATTERNS: list[dict[str, Any]] = [
    {"pattern": r"\bLFPR\b|Labour Force Participation Rate", "entity": "Labour Force Participation Rate"},
    {"pattern": r"\bWPR\b|Worker Population Ratio", "entity": "Worker Population Ratio"},
    {"pattern": r"\bUR\b|Unemployment Rate", "entity": "Unemployment Rate"},
    {"pattern": r"self[- ]?employed|regular wage|casual labour|status in employment", "entity": "Employment Status"},
    {"pattern": r"manufactur|service sector|agriculture|construction|industry of work", "entity": "Industry"},
    {"pattern": r"earning|wages|monthly income", "entity": "Average Monthly Earnings"},
    {"pattern": r"weekly hours|hours worked|average hours", "entity": "Average Weekly Hours"},
    {"pattern": r"formal education|years of education|education years", "entity": "Formal Education Years"},
    {"pattern": r"male|female|gender|persons", "entity": "Gender"},
    {"pattern": r"\brural\b|\burban\b|sector", "entity": "Sector"},
    {"pattern": r"age.?group|15[- ]?29|15[- ]?59|15 years and above|youth", "entity": "Age Group"},
    {"pattern": r"survey.?period|2024|2025|january.*december", "entity": "Survey Period"},
    {"pattern": r"usual status|ps\+ss|CWS|current weekly|principal.?status", "entity": "Activity Status"},
    {"pattern": r"proportion|percentage distribution|share of workers", "entity": "Worker Share"},
    {"pattern": r"sample size|sample design|FSU|households surveyed", "entity": "Sample Size"},
]


# ─────────────────────────────────────────────────────────────────────────────
# Doc-type scoring adjustments
# ─────────────────────────────────────────────────────────────────────────────

PIB_SCORING_OVERRIDES: dict[str, Any] = {
    "tableSemantics": {"weight": 0.0, "neutral": True, "reason": "PIB press releases have no data tables"},
    "chartSemantics": {"weight": 0.5, "rename": "infographicSemantics"},
    "questionCompleteness": {"weight": 1.5, "reason": "Questions are the primary output for PIB"},
    "entityCompleteness": {"weight": 1.2},
    "unitCoverage": {"weight": 1.0},
}

PIB_SUPPRESSED_WARNINGS: set[str] = {
    "NO_TABLE_TEMPLATES",
    "TABLE_MISSING_COLUMN_GROUPS",
}
