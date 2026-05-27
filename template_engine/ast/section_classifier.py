"""Section classifier — maps extracted headings/regions to canonical report sections.

Canonical MoSPI section taxonomy:
  cover               → front matter (title, ministry, period)
  foreword            → foreword / preface / note
  executive_summary   → executive summary / abstract / key highlights
  methodology         → methodology / data collection / sampling
  data_overview       → dataset overview / variables / column inventory
  data_quality        → data quality / validation / missing values
  semantic_analysis   → semantic mapping / domain analysis / clustering
  findings            → findings / results / analysis / key indicators
  recommendations     → recommendations / conclusion / way forward
  appendix            → appendix / annex / technical notes
  audit               → audit / integrity / verification
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Keyword maps (lowercase)
# ---------------------------------------------------------------------------

_SECTION_KEYWORDS: list[tuple[str, list[str]]] = [
    ("cover", [
        "ministry of statistics", "government of india", "mospi", "survey report",
        "annual report", "reference period", "publication", "national sample survey",
    ]),
    ("foreword", [
        "foreword", "preface", "introduction", "overview", "note from",
        "from the director", "from the chairman",
    ]),
    ("executive_summary", [
        "executive summary", "abstract", "key highlights", "summary of findings",
        "highlights", "key results", "at a glance",
    ]),
    ("methodology", [
        "methodology", "data collection", "sampling design", "survey design",
        "sampling methodology", "data sources", "primary sample unit", "secondary sample unit",
        "psu", "ssu", "frame", "coverage", "scope", "schedule", "reference period",
        "collection method", "data entry", "field work",
    ]),
    ("data_overview", [
        "dataset overview", "data overview", "variable", "column inventory",
        "data description", "dataset description", "field description",
        "data dictionary", "codebook", "column profile", "schema",
    ]),
    ("data_quality", [
        "data quality", "validation", "missing values", "imputation", "anomaly",
        "outlier", "edit check", "quality indicator", "coverage rate",
        "response rate", "non-response",
    ]),
    ("semantic_analysis", [
        "semantic", "domain mapping", "clustering", "knowledge graph",
        "column mapping", "ontology", "classification",
    ]),
    ("findings", [
        "findings", "results", "analysis", "key indicators", "trends",
        "patterns", "observations", "estimates", "distribution",
        "cross tabulation", "percentage distribution",
    ]),
    ("recommendations", [
        "recommendation", "conclusion", "way forward", "future scope",
        "improvement", "suggestion", "policy implication",
    ]),
    ("appendix", [
        "appendix", "annex", "technical note", "glossary", "abbreviation",
        "formula", "questionnaire", "schedule", "table a", "table b",
    ]),
    ("audit", [
        "audit", "integrity", "hash", "tamper", "verification", "certificate",
        "checksum",
    ]),
]


def classify_heading(heading: str) -> str:
    """Map a heading string to a canonical section name."""
    h = heading.lower().strip()
    for section, keywords in _SECTION_KEYWORDS:
        for kw in keywords:
            if kw in h:
                return section
    # Title-page heuristics
    if re.match(r"^(chapter|section)\s+\d+\s*[:\-—]?\s*", h):
        return "findings"
    return "body"


# ---------------------------------------------------------------------------
# Block-kind inference
# ---------------------------------------------------------------------------

_CHART_HINTS = re.compile(
    r"(figure|chart|graph|diagram|distribution|histogram|bar|line|pie|scatter)", re.I
)
_TABLE_HINTS = re.compile(r"(table|statement|exhibit|annexure)\s+\d*", re.I)
_METRIC_HINTS = re.compile(
    r"(total|count|mean|median|rate|ratio|percentage|proportion|index|score)", re.I
)


def infer_block_kind(heading: str, has_tables: bool, has_charts: bool) -> str:
    if _CHART_HINTS.search(heading) or has_charts:
        return "chart"
    if _TABLE_HINTS.search(heading) or has_tables:
        return "table"
    if _METRIC_HINTS.search(heading):
        return "metric"
    return "narrative"


# ---------------------------------------------------------------------------
# BlockSpec dataclass (mirrors report_builder/blueprint.py for independence)
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedBlock:
    block_id: str
    kind: str
    title: str
    section: str
    required: bool
    hints: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "kind": self.kind,
            "title": self.title,
            "section": self.section,
            "required": self.required,
            "hints": self.hints,
        }
