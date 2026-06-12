"""Template repository — CRUD for ReportTemplate rows (Neon/Postgres).

The repository stores:
  - template_ast        (JSON) in ReportTemplate.ast_json
  - layout_metadata     (JSON) in ReportTemplate.layout_metadata
  - pdf_hash            in ReportTemplate.source_hash

It is used by the report_builder_api routes; the actual ORM model is in
api/database/models.py (ReportTemplate).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from template_engine.ast.ast_builder import TemplateAST
from template_engine.ast.template_serializer import deserialize_template, serialize_template

logger = logging.getLogger(__name__)


def save_template(db: Session, ast: TemplateAST, name: str, description: str | None = None) -> Any:
    """Persist a TemplateAST to the database. Returns the ORM row."""
    from database.models import ReportTemplate  # lazy import — keeps package independent

    existing = (
        db.query(ReportTemplate)
        .filter(ReportTemplate.source_hash == ast.source_hash)
        .first()
        if ast.source_hash
        else None
    )
    if existing:
        logger.info("Template with hash %s already exists (id=%s)", ast.source_hash, existing.id)
        return existing

    row = ReportTemplate(
        name=name,
        description=description,
        page_count=ast.page_count,
        extraction_method=ast.extraction_method,
        source_hash=ast.source_hash,
        ast_json=serialize_template(ast),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Saved template '%s' (id=%s, blocks=%s)", name, row.id, len(ast.blocks))
    return row


def load_template(db: Session, template_id: int) -> TemplateAST | None:
    """Load a TemplateAST from the database by ID."""
    from database.models import ReportTemplate

    row = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
    if not row:
        return None
    if not row.ast_json:
        return None
    try:
        return deserialize_template(row.ast_json)
    except Exception as exc:
        logger.warning("Failed to deserialize template %s: %s", template_id, exc)
        return None


def list_templates(db: Session) -> list[dict[str, Any]]:
    from database.models import ReportTemplate

    rows = db.query(ReportTemplate).order_by(ReportTemplate.id.desc()).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "page_count": r.page_count,
            "block_count": _block_count_from_ast_json(r.ast_json),
            "extraction_method": r.extraction_method,
            "source_hash": r.source_hash,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def delete_template(db: Session, template_id: int) -> bool:
    from database.models import ReportTemplate

    row = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def _block_count_from_ast_json(ast_json: Any) -> int:
    if not isinstance(ast_json, dict):
        return 0
    blocks = ast_json.get("blocks")
    if isinstance(blocks, list):
        return len(blocks)
    sections = ast_json.get("sections")
    if isinstance(sections, list):
        return len(sections)
    return 0
