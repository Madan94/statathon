"""Immutable S3 vault + DB audit after PDF ingestion (strict)."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from template_engine.ingestion.pdf_hasher import build_file_manifest, sha256_file
from template_engine.ingestion.pdf_loader import PageData

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = "1.0"
VAULT_FAILURE_HINT = (
    "Immutable vault is required but failed. Configure STORAGE_PROVIDER=s3, S3_BUCKET, "
    "AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and IMMUTABLE_VAULT_REQUIRED=true."
)


@dataclass
class VaultPersistResult:
    source_hash: str
    vault_pdf_key: str
    vault_manifest_key: str
    manifest: dict[str, Any]
    audit_id: int | None = None


def immutable_vault_required() -> bool:
    return os.getenv("IMMUTABLE_VAULT_REQUIRED", "true").lower() in ("1", "true", "yes")


def vault_prefix() -> str:
    return (os.getenv("S3_VAULT_PREFIX") or "report_templates/immutable").strip().rstrip("/")


def vault_keys_for_hash(source_hash: str) -> tuple[str, str]:
    prefix = f"{vault_prefix()}/{source_hash[:2]}/{source_hash}"
    return f"{prefix}/source.pdf", f"{prefix}/ingestion_manifest.json"


def build_ingestion_manifest(
    pdf_path: Path,
    pages: list[PageData],
    extraction_method: str,
    *,
    source_filename: str | None = None,
) -> dict[str, Any]:
    base = build_file_manifest(pdf_path)
    page_summaries_meta = [
        {
            "page_index": p.page_index,
            "width": p.width,
            "height": p.height,
            "word_count": p.word_count,
            "table_count": len(p.tables or []),
            "heading_count": len(p.headings),
        }
        for p in pages
    ]
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "sha256": base.get("sha256"),
        "filename": source_filename or base.get("filename"),
        "size_bytes": base.get("size_bytes"),
        "page_count": len(pages),
        "extraction_method": extraction_method,
        "page_fingerprints": base.get("page_fingerprints") or [],
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "page_summaries_meta": page_summaries_meta,
    }


def _upload_vault_artifacts(
    pdf_path: Path,
    manifest: dict[str, Any],
    source_hash: str,
) -> tuple[str, str]:
    from object_storage.object_store import StorageConfigError, build_default_store

    try:
        store = build_default_store()
    except StorageConfigError as exc:
        raise RuntimeError(f"{exc}. {VAULT_FAILURE_HINT}") from exc

    pdf_key, manifest_key = vault_keys_for_hash(source_hash)
    raw = pdf_path.read_bytes()
    meta_base = {"sha256": source_hash, "artifact": "template-ingestion"}

    store.upload_object_body(
        pdf_key,
        raw,
        "application/pdf",
        metadata={**meta_base, "content-role": "source-pdf"},
    )
    manifest_bytes = json.dumps(manifest, indent=2, default=str).encode("utf-8")
    store.upload_object_body(
        manifest_key,
        manifest_bytes,
        "application/json",
        metadata={**meta_base, "content-role": "ingestion-manifest"},
    )
    logger.info("Immutable vault: uploaded %s and %s", pdf_key, manifest_key)
    return pdf_key, manifest_key


def _log_audit_row(
    *,
    source_hash: str,
    vault_pdf_key: str,
    vault_manifest_key: str,
    extraction_method: str,
    page_count: int,
    manifest: dict[str, Any],
    user_id: int | None,
    extraction_job_id: int | None,
    source_filename: str | None,
) -> int:
    from database.database import SessionLocal
    from repositories.template_ingestion_audit_repository import TemplateIngestionAuditRepository

    db = SessionLocal()
    try:
        repo = TemplateIngestionAuditRepository(db)
        row = repo.log_ingestion(
            source_hash=source_hash,
            vault_pdf_key=vault_pdf_key,
            vault_manifest_key=vault_manifest_key,
            extraction_method=extraction_method,
            page_count=page_count,
            user_id=user_id,
            extraction_job_id=extraction_job_id,
            source_filename=source_filename,
            status="ingested",
            payload={
                "manifest_schema_version": manifest.get("manifest_schema_version"),
                "page_fingerprints": manifest.get("page_fingerprints"),
            },
        )
        return int(row.id)
    except Exception as exc:
        db.rollback()
        raise RuntimeError(f"Template ingestion audit log failed: {exc}") from exc
    finally:
        db.close()


def persist_post_ingestion_vault(
    pdf_path: str | Path,
    pages: list[PageData],
    extraction_method: str,
    *,
    user_id: int | None = None,
    extraction_job_id: int | None = None,
    source_filename: str | None = None,
) -> VaultPersistResult:
    """Upload PDF + manifest to S3 and append audit row. Raises on failure when vault required."""
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found for vault: {path}")

    if not immutable_vault_required():
        logger.warning("IMMUTABLE_VAULT_REQUIRED=false — skipping vault (dev only)")
        source_hash = sha256_file(path)
        pdf_key, manifest_key = vault_keys_for_hash(source_hash)
        manifest = build_ingestion_manifest(
            path, pages, extraction_method, source_filename=source_filename
        )
        return VaultPersistResult(
            source_hash=source_hash,
            vault_pdf_key=pdf_key,
            vault_manifest_key=manifest_key,
            manifest=manifest,
        )

    source_hash = sha256_file(path)
    manifest = build_ingestion_manifest(
        path, pages, extraction_method, source_filename=source_filename
    )
    if manifest.get("sha256") and manifest["sha256"] != source_hash:
        logger.warning("Manifest sha256 mismatch with file hash; using file hash")
    manifest["sha256"] = source_hash

    vault_pdf_key, vault_manifest_key = _upload_vault_artifacts(path, manifest, source_hash)
    audit_id = _log_audit_row(
        source_hash=source_hash,
        vault_pdf_key=vault_pdf_key,
        vault_manifest_key=vault_manifest_key,
        extraction_method=extraction_method,
        page_count=len(pages),
        manifest=manifest,
        user_id=user_id,
        extraction_job_id=extraction_job_id,
        source_filename=source_filename or path.name,
    )

    return VaultPersistResult(
        source_hash=source_hash,
        vault_pdf_key=vault_pdf_key,
        vault_manifest_key=vault_manifest_key,
        manifest=manifest,
        audit_id=audit_id,
    )
