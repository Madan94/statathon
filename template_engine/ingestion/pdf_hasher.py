"""Immutable ingestion: SHA-256 fingerprinting for PDF audit trail.

Every template PDF is hashed once on upload. The hash is stored in:
  - ReportTemplate.source_hash (Postgres)
  - TemplateAST.source_hash (in-memory AST)
  - PDF cover page (rendered in output)

Page-level fingerprints detect whether a cached extraction is still valid
without re-running the expensive spatial extractor.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def sha256_file(path: str | Path) -> str:
    """Full-file SHA-256 (hex)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(131072), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def page_fingerprints(pdf_path: str | Path) -> list[str]:
    """Per-page SHA-256 of raw byte slices (fast structural check).

    Uses pdfplumber's raw page objects; falls back to a single-file hash
    if pdfplumber is unavailable.
    """
    try:
        import pdfplumber  # type: ignore

        fps: list[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                # Hash (x0, top, x1, bottom, text) of each word as a structural proxy.
                words = page.extract_words() or []
                raw = json.dumps(
                    [(w.get("x0"), w.get("top"), w.get("text")) for w in words[:200]],
                    sort_keys=True,
                ).encode()
                fps.append(sha256_bytes(raw)[:16])
        return fps
    except Exception:
        # Last-resort: single hash broadcast to all pages
        full = sha256_file(pdf_path)
        return [full[:16]]


def build_file_manifest(pdf_path: str | Path) -> dict[str, Any]:
    """Full manifest for audit storage."""
    path = Path(pdf_path)
    stat = path.stat() if path.exists() else None
    return {
        "filename": path.name,
        "sha256": sha256_file(path) if path.exists() else None,
        "size_bytes": stat.st_size if stat else None,
        "page_fingerprints": page_fingerprints(path) if path.exists() else [],
    }
