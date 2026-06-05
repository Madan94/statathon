"""Quality gates and cross-reference checks for enterprise AST."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from template_engine.ast.enterprise_schema import EnterpriseDocumentAST


def stable_checksum(payload: dict[str, Any]) -> str:
    """SHA-256 of normalized JSON excluding volatile metadata.updatedAt."""
    copy = json.loads(json.dumps(payload, sort_keys=True, default=str))
    meta = copy.get("metadata")
    if isinstance(meta, dict):
        meta.pop("updatedAt", None)
    raw = json.dumps(copy, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run_quality_gates(doc: EnterpriseDocumentAST | dict[str, Any]) -> dict[str, Any]:
    """Return quality report with errors, warnings, and score."""
    if isinstance(doc, dict):
        try:
            model = EnterpriseDocumentAST.from_dict(doc)
        except Exception as exc:
            return {
                "passed": False,
                "score": 0.0,
                "errors": [f"schema_validation: {exc}"],
                "warnings": [],
            }
    else:
        model = doc

    errors: list[str] = []
    warnings: list[str] = []

    if not model.metadata.checksum:
        errors.append("metadata.checksum is required")
    if not model.metadata.documentId:
        errors.append("metadata.documentId is required")
    if model.metadata.version != "2.0":
        warnings.append(f"metadata.version is {model.metadata.version}, expected 2.0")

    if not model.layoutAST.pages:
        errors.append("layoutAST.pages must be non-empty")
    if not model.semanticAST.nodes:
        errors.append("semanticAST.nodes must be non-empty")

    asset_ids = {a.assetId for a in model.assetAST.assets if a.assetId}
    for fig in model.figureAST.figures:
        if fig.assetRef and fig.assetRef not in asset_ids:
            warnings.append(f"figure {fig.figureId} assetRef {fig.assetRef} not in assetAST")

    content_ids = {p.id for p in model.contentAST.paragraphs if p.id}
    table_ids = {t.tableId for t in model.tableAST.tables if t.tableId}
    geo_ids = {n.nodeId for n in model.geometryAST.nodes if n.nodeId}

    for page in model.layoutAST.pages:
        for blk in page.blocks:
            if blk.refId and blk.refType == "content" and blk.refId not in content_ids:
                warnings.append(f"layout block {blk.blockId} missing content ref {blk.refId}")
            if blk.refId and blk.refType == "table" and blk.refId not in table_ids:
                warnings.append(f"layout block {blk.blockId} missing table ref {blk.refId}")

    for gid in geo_ids:
        if gid and not any(
            p.id == gid for p in model.contentAST.paragraphs
        ) and not any(t.tableId == gid for t in model.tableAST.tables):
            pass  # geometry may use geo_* prefix

    if not model.contentAST.paragraphs and not model.tableAST.tables:
        warnings.append("no contentAST paragraphs or tableAST tables extracted")

    if len(model.retrievalAST.chunks) > 500:
        warnings.append("retrievalAST exceeds 500 chunks; consider trimming")

    score = 1.0
    score -= 0.25 * len(errors)
    score -= 0.05 * min(len(warnings), 10)
    score = max(0.0, min(1.0, score))

    return {
        "passed": len(errors) == 0,
        "score": round(score, 3),
        "errors": errors,
        "warnings": warnings,
    }
