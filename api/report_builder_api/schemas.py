from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel


class TemplateOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    page_count: Optional[int] = None
    extraction_method: Optional[str] = None
    block_count: int
    source_hash: Optional[str] = None
    created_at: Optional[str] = None


class TemplateCreateOut(TemplateOut):
    ast: dict[str, Any]


class GenerateRequest(BaseModel):
    analysis_id: int
    template_id: Optional[int] = None  # None => use builtin MoSPI default


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
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


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
