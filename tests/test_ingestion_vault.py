"""Immutable ingestion vault + audit trail tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from template_engine.ingestion.pdf_loader import PageData, TextBlock
from template_engine.ingestion.ingestion_vault import (
    build_ingestion_manifest,
    persist_post_ingestion_vault,
    vault_keys_for_hash,
)


def test_vault_keys_for_hash():
    h = "a" * 64
    pdf_key, manifest_key = vault_keys_for_hash(h)
    assert pdf_key.endswith("/source.pdf")
    assert manifest_key.endswith("/ingestion_manifest.json")
    assert h[:2] in pdf_key


def test_build_ingestion_manifest(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    pages = [
        PageData(
            page_index=0,
            width=612,
            height=792,
            text_blocks=[TextBlock(text="Title", font_size=14, bold=True)],
            raw_text="Title",
        )
    ]
    manifest = build_ingestion_manifest(pdf, pages, "colpali", source_filename="sample.pdf")
    assert manifest["manifest_schema_version"] == "1.0"
    assert manifest["page_count"] == 1
    assert manifest["extraction_method"] == "colpali"
    assert len(manifest["page_summaries_meta"]) == 1


@patch("template_engine.ingestion.ingestion_vault._log_audit_row", return_value=42)
@patch("template_engine.ingestion.ingestion_vault._upload_vault_artifacts")
@patch("template_engine.ingestion.ingestion_vault.immutable_vault_required", return_value=True)
def test_persist_post_ingestion_vault_strict(mock_required, mock_upload, mock_audit, tmp_path):
    pdf = tmp_path / "t.pdf"
    pdf.write_bytes(b"%PDF-1.4 content")
    mock_upload.return_value = ("vault/pdf/key", "vault/manifest/key")
    pages = [PageData(page_index=0, width=100, height=100, raw_text="x")]

    result = persist_post_ingestion_vault(
        pdf,
        pages,
        "colpali",
        user_id=1,
        extraction_job_id=9,
        source_filename="t.pdf",
    )

    assert result.vault_pdf_key == "vault/pdf/key"
    assert result.audit_id == 42
    mock_upload.assert_called_once()
    mock_audit.assert_called_once()
    assert result.manifest["page_count"] == 1


@patch("object_storage.object_store.build_default_store")
@patch("template_engine.ingestion.ingestion_vault.immutable_vault_required", return_value=True)
def test_persist_raises_when_s3_fails(mock_required, mock_build_store, tmp_path):
    from object_storage.object_store import StorageConfigError

    mock_build_store.side_effect = StorageConfigError("no bucket")
    pdf = tmp_path / "t.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    pages = [PageData(page_index=0, width=100, height=100, raw_text="x")]

    with pytest.raises(RuntimeError, match="Immutable vault"):
        persist_post_ingestion_vault(pdf, pages, "colpali")


@patch("template_engine.ingestion.ingestion_vault.immutable_vault_required", return_value=False)
def test_persist_skips_upload_when_not_required(mock_required, tmp_path):
    pdf = tmp_path / "t.pdf"
    pdf.write_bytes(b"%PDF-1.4 skip")
    pages = [PageData(page_index=0, width=100, height=100, raw_text="x")]

    result = persist_post_ingestion_vault(pdf, pages, "colpali")
    assert result.source_hash
    assert "source.pdf" in result.vault_pdf_key
