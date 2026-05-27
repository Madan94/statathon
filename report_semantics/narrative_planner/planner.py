"""Narrative planner — builds a section plan for a report based on dataset signals.

The planner inspects the DatasetSummary and analysis payload to decide:
  - Which sections to include
  - Which narratives are relevant
  - What data sources back each section
  - What word budget to allocate

Output: a ReportPlan (ordered list of SectionPlan objects) that the Scribe agent
uses to generate grounded, verifiable narratives section by section.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from report_semantics.summarizer.dataset_summarizer import DatasetSummary


@dataclass
class NarrativePlan:
    block_id: str
    section: str
    title: str
    kind: str           # narrative / table / chart / metric
    max_words: int
    data_sources: list[str]
    required_facts: list[str]
    tone: str = "official, neutral"
    verify_numbers: bool = True
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "section": self.section,
            "title": self.title,
            "kind": self.kind,
            "max_words": self.max_words,
            "data_sources": self.data_sources,
            "required_facts": self.required_facts,
            "tone": self.tone,
            "verify_numbers": self.verify_numbers,
            "notes": self.notes,
        }


@dataclass
class ReportPlan:
    dataset_type: str
    health_band: str
    sections: list[NarrativePlan] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_type": self.dataset_type,
            "health_band": self.health_band,
            "sections": [s.to_dict() for s in self.sections],
        }


def plan_report_sections(
    summary: DatasetSummary,
    analysis_payload: dict[str, Any],
) -> ReportPlan:
    """Build a complete section plan from dataset intelligence."""
    sections: list[NarrativePlan] = []

    # 1. Executive Summary — always present
    sections.append(NarrativePlan(
        block_id="exec_summary",
        section="executive_summary",
        title="Executive Summary",
        kind="narrative",
        max_words=250,
        data_sources=["health", "dataset_context", "semantic_mapping"],
        required_facts=["row_count", "column_count", "missing_pct", "health_score",
                        "anomaly_count", "dataset_type"],
        tone="official, formal, neutral",
        verify_numbers=True,
        notes="Cite health_score and row/column counts. MoSPI formal style.",
    ))

    # 2. Methodology — narrative; required if dataset_type is known
    if summary.dataset_type != "unknown":
        sections.append(NarrativePlan(
            block_id="methodology",
            section="methodology",
            title="Data Collection Methodology",
            kind="narrative",
            max_words=300,
            data_sources=["dataset_context", "mospi_ontology"],
            required_facts=["dataset_type", "row_count"],
            tone="technical, official",
            verify_numbers=False,
            notes="Describe dataset type, coverage, and statistical methodology.",
        ))

    # 3. Dataset Overview — table always
    sections.append(NarrativePlan(
        block_id="dataset_overview",
        section="data_overview",
        title="Dataset Overview",
        kind="table",
        max_words=0,
        data_sources=["health_summary"],
        required_facts=["row_count", "column_count", "missing_pct"],
        verify_numbers=False,
    ))

    # 4. Semantic Mapping — table if mapped columns present
    if summary.mapped_column_count > 0:
        sections.append(NarrativePlan(
            block_id="semantic_map",
            section="data_overview",
            title="Column Semantic Mapping",
            kind="table",
            max_words=0,
            data_sources=["semantic_mapping"],
            required_facts=["mapped_column_count"],
            verify_numbers=False,
        ))

    # 5. Data Quality — only if quality issues exist
    has_quality_issues = (
        summary.missing_pct > 1
        or summary.anomaly_count > 0
        or summary.duplicate_rows > 0
        or summary.imputation_count > 0
    )
    if has_quality_issues:
        sections.append(NarrativePlan(
            block_id="data_quality_narrative",
            section="data_quality",
            title="Data Quality Assessment",
            kind="narrative",
            max_words=280,
            data_sources=["health", "phase3.anomaly_candidates", "phase3.imputation_candidates"],
            required_facts=["missing_pct", "anomaly_count", "duplicate_rows", "imputation_targets"],
            tone="analytical, objective",
            verify_numbers=True,
            notes="Report every figure exactly. Flag high-missing columns by name.",
        ))

    # 6. Missing Values chart
    if summary.missing_pct > 0:
        sections.append(NarrativePlan(
            block_id="missing_values",
            section="data_quality",
            title="Missing Values by Column",
            kind="chart",
            max_words=0,
            data_sources=["missing_per_column"],
            required_facts=["missing_pct"],
            verify_numbers=False,
        ))

    # 7. Anomaly table
    if summary.anomaly_count > 0:
        sections.append(NarrativePlan(
            block_id="anomaly_detail",
            section="data_quality",
            title="Anomaly Detection Results",
            kind="table",
            max_words=0,
            data_sources=["phase3.anomaly_candidates"],
            required_facts=["anomaly_count"],
            verify_numbers=False,
        ))

    # 8. Imputation table
    if summary.imputation_count > 0:
        sections.append(NarrativePlan(
            block_id="imputation_detail",
            section="data_quality",
            title="Imputation Recommendations",
            kind="table",
            max_words=0,
            data_sources=["phase3.imputation_candidates"],
            required_facts=["imputation_targets"],
            verify_numbers=False,
        ))

    # 9. Key Findings — narrative
    sections.append(NarrativePlan(
        block_id="narrative_findings",
        section="findings",
        title="Key Findings & Statistical Insights",
        kind="narrative",
        max_words=450,
        data_sources=["health", "semantic_mapping", "clusters", "phase3", "column_statistics"],
        required_facts=["row_count", "missing_pct", "anomaly_count", "cluster_count",
                        "mapped_column_count", "key_patterns"],
        tone="analytical, evidence-based, official",
        verify_numbers=True,
        notes="Synthesize all prior findings. Every claim needs a source.",
    ))

    # 10. Correlation patterns
    if summary.highly_correlated_pairs:
        sections.append(NarrativePlan(
            block_id="correlation_insights",
            section="findings",
            title="Inter-column Relationships",
            kind="narrative",
            max_words=200,
            data_sources=["schema_graph", "priority_dependencies"],
            required_facts=["highly_correlated_pairs"],
            verify_numbers=True,
        ))

    # 11. Knowledge Graph
    sections.append(NarrativePlan(
        block_id="kg_export",
        section="relationships",
        title="Knowledge Graph Export",
        kind="metric",
        max_words=0,
        data_sources=["knowledge_graph"],
        required_facts=["kg_triples"],
        verify_numbers=False,
    ))

    # 12. Recommendations
    sections.append(NarrativePlan(
        block_id="recommendations",
        section="recommendations",
        title="Recommendations",
        kind="narrative",
        max_words=280,
        data_sources=["health", "phase3"],
        required_facts=["missing_pct", "anomaly_count", "health_band"],
        tone="prescriptive, official",
        verify_numbers=False,
        notes="Actionable recommendations based strictly on the data quality findings.",
    ))

    # 13. Audit Trail
    sections.append(NarrativePlan(
        block_id="audit_trail",
        section="appendix",
        title="Audit & Integrity",
        kind="metric",
        max_words=0,
        data_sources=["audit"],
        required_facts=["content_hash", "generated_at"],
        verify_numbers=False,
    ))

    return ReportPlan(
        dataset_type=summary.dataset_type,
        health_band=summary.health_band,
        sections=sections,
    )
