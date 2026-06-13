"""Pydantic schemas for dataset review & approval APIs."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

DatasetSide = Literal["original", "processed"]
DownloadKind = Literal[
    "original_csv",
    "original_xlsx",
    "processed_csv",
    "processed_xlsx",
    "audit_summary",
    "transformation_summary",
]


class SnapshotMeta(BaseModel):
    stage: str
    version: int | None = None
    row_count: int = 0
    column_count: int = 0
    storage_path: str | None = None
    created_at: str | None = None


class DatasetMetaBlock(BaseModel):
    row_count: int = 0
    column_count: int = 0
    columns: list[str] = Field(default_factory=list)
    missing_cells: int = 0
    snapshot: SnapshotMeta | None = None


class ReviewSummaryBlock(BaseModel):
    rows_before: int = 0
    rows_after: int = 0
    rows_removed: int = 0
    columns_before: int = 0
    columns_after: int = 0
    columns_removed: int = 0
    columns_renamed: int = 0
    columns_excluded: int = 0
    missing_values_before: int = 0
    missing_values_after: int = 0
    rule_violations_fixed: int = 0
    anomalies_processed: int = 0
    values_imputed: int = 0


class DiffSummaryBlock(BaseModel):
    rows_removed: list[dict[str, Any]] = Field(default_factory=list)
    columns_removed: list[str] = Field(default_factory=list)
    columns_renamed: list[dict[str, str]] = Field(default_factory=list)
    columns_excluded: list[str] = Field(default_factory=list)
    values_changed: list[dict[str, Any]] = Field(default_factory=list)
    values_set_missing: list[dict[str, Any]] = Field(default_factory=list)
    missing_values_imputed: list[dict[str, Any]] = Field(default_factory=list)
    anomalies_handled: list[dict[str, Any]] = Field(default_factory=list)
    rules_applied: list[dict[str, Any]] = Field(default_factory=list)


class DatasetReviewResponse(BaseModel):
    analysis_id: int
    original_dataset: DatasetMetaBlock
    processed_dataset: DatasetMetaBlock
    summary: ReviewSummaryBlock
    diff_summary: DiffSummaryBlock
    snapshots: list[SnapshotMeta] = Field(default_factory=list)
    dataset_review_completed: bool = False
    missing_value_completed: bool = False
    can_approve: bool = False
    can_proceed_to_report: bool = False


class PaginatedRowsResponse(BaseModel):
    side: DatasetSide
    total_rows: int
    offset: int
    limit: int
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class ColumnChangeResponse(BaseModel):
    column: str
    before_label: str | None = None
    after_label: str | None = None
    rows_changed: int = 0
    reason: str = ""
    phase: str = ""
    sample_changes: list[dict[str, Any]] = Field(default_factory=list)


class RowInspectionResponse(BaseModel):
    side: DatasetSide
    row_index: int
    original_row: dict[str, Any] | None = None
    processed_row: dict[str, Any] | None = None
    changed_cells: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)


class DatasetReviewApproveResponse(BaseModel):
    success: bool = True
    analysis_id: int
    dataset_review_completed: bool = True
    can_proceed_to_report: bool = True
