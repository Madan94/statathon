"""Dataset ⇄ Template binding phase.

Resolves every blueprint entity to dataset column(s) for every question, under
human confirmation, producing ``datasetAST`` + ``bindingAST`` + a coverage report.

See ``report_builder/README_BINDING_PHASE.md`` for the full architecture.

Pipeline (this phase): S0 profile → S1 resolve → S2 confirm → S3 question-resolve.
BI execution (S4) and slot-fill/render (S5/S6) are a deferred downstream contract.
"""
from __future__ import annotations

from report_builder.binding.schema import (
    BindingAST,
    BindingCandidate,
    BoundColumn,
    ColumnGroup,
    ColumnProfile,
    CoverageIssue,
    CoverageReport,
    DatasetAST,
    EntityBinding,
    QuestionBinding,
    ReshapeRecipe,
    ResolvedFilter,
    ResolvedRoles,
    ResolvedTime,
)

__all__ = [
    "BindingAST",
    "BindingCandidate",
    "BoundColumn",
    "ColumnGroup",
    "ColumnProfile",
    "CoverageIssue",
    "CoverageReport",
    "DatasetAST",
    "EntityBinding",
    "QuestionBinding",
    "ReshapeRecipe",
    "ResolvedFilter",
    "ResolvedRoles",
    "ResolvedTime",
]
