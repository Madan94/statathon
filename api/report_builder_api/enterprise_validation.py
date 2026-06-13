"""Enterprise AST v2.0 validation for report templates."""
from __future__ import annotations

from typing import Any

from template_engine.ast.enterprise_schema import EnterpriseDocumentAST
from template_engine.ast.migration_v1 import is_enterprise_ast, migrate_v1_blocks_to_enterprise
from template_engine.ast.quality import run_quality_gates, stable_checksum


def validate_enterprise_ast(
    payload: dict[str, Any],
    *,
    strict_quality: bool = False,
) -> dict[str, Any]:
    """Validate and normalize enterprise AST v2.0."""
    if not is_enterprise_ast(payload):
        payload = migrate_v1_blocks_to_enterprise(payload)

    doc = EnterpriseDocumentAST.from_dict(payload)
    out = doc.to_dict()

    if not out.get("metadata", {}).get("checksum"):
        out["metadata"]["checksum"] = stable_checksum(out)

    quality = run_quality_gates(out)
    out["quality_report"] = quality

    if strict_quality and not quality.get("passed"):
        errors = quality.get("errors") or ["quality gates failed"]
        raise ValueError("; ".join(errors))

    # Ensure legacy blocks projection exists for transitional clients
    if not out.get("blocks"):
        from template_engine.ast.enterprise_builder import _semantic_to_legacy_blocks
        from template_engine.ast.enterprise_schema import SemanticNode

        nodes = [SemanticNode.model_validate(n) for n in (out.get("semanticAST") or {}).get("nodes") or []]
        out["blocks"] = _semantic_to_legacy_blocks(nodes)

    return out
