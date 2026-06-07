from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel


class DataFilterSpecIn(BaseModel):
    include_columns: Optional[list[str]] = None
    exclude_columns: Optional[list[str]] = None
    max_rows: Optional[int] = None
    min_complete_row_pct: Optional[float] = None


class TemplateUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    ast: Optional[dict[str, Any]] = None
    filter_config: Optional[DataFilterSpecIn | dict[str, Any]] = None


class TemplateOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    page_count: Optional[int] = None
    extraction_method: Optional[str] = None
    block_count: int
    source_hash: Optional[str] = None
    filter_config: Optional[dict[str, Any]] = None
    created_at: Optional[str] = None


class TemplateCreateOut(TemplateOut):
    ast: dict[str, Any]


class TemplateImportJsonIn(BaseModel):
    name: str
    description: Optional[str] = None
    ast: dict[str, Any]
    document_format: Optional[str] = None  # "energy_chapter" converts document/children AST


class TemplateExtractionJobOut(BaseModel):
    id: int
    status: str
    stage: Optional[str] = None
    progress_pct: int = 0
    template_name: str
    source_filename: Optional[str] = None
    source_hash: Optional[str] = None
    vault_object_key: Optional[str] = None
    extraction_method: Optional[str] = None
    stage_diagnostics: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    created_template_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ReadyAnalysisOut(BaseModel):
    analysis_id: int
    dataset_id: int
    filename: str
    row_count: int
    column_count: int
    status: str
    upload_status: Optional[str] = None
    created_at: Optional[str] = None


class GenerateRequest(BaseModel):
    analysis_id: int
    template_id: Optional[int] = None  # None => use builtin MoSPI default
    filter_config: Optional[DataFilterSpecIn | dict[str, Any]] = None


class CoordGenerateRequest(BaseModel):
    """Coordinate-exact report (fina-ast layout + Deep BI fill)."""
    analysis_id: int
    ast_path: Optional[str] = None  # default: test_data/fina-ast.json in repo
    domain: str = "economics"  # economics | energy
    use_gemini: bool = True


class CoordGenerateOut(BaseModel):
    job_id: int
    status: str
    stage: Optional[str] = None
    message: str = ""


class JobOut(BaseModel):
    id: int
    analysis_id: int
    template_id: Optional[int] = None
    status: str
    stage: Optional[str] = None
    content_hash: Optional[str] = None
    final_pdf_path: Optional[str] = None
    kg_export_path: Optional[str] = None
    error_message: Optional[str] = None
    filter_config: Optional[dict[str, Any]] = None
    delivery_log: Optional[list[dict[str, Any]]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DeliverRequest(BaseModel):
    channel: str  # email | webhook
    to: Optional[str] = None  # email address
    url: Optional[str] = None  # webhook URL


class CorrectionIn(BaseModel):
    block_id: str
    kind: str = "narrative_edit"
    before: Optional[str] = None
    after: Optional[str] = None
    diagnostics: Optional[dict[str, Any]] = None


class ChatIn(BaseModel):
    query: str


class InsertBlockIn(BaseModel):
    section: str
    block: dict[str, Any]
    position: Optional[int] = None  # None => append


class MoveBlockIn(BaseModel):
    block_id: str
    target_section: str
    target_position: Optional[int] = None
