"""Value-free template emission (migration plan P1).

Splits the single blended Enterprise AST produced by ``pass4_assemble_ast`` into the
two value-free template files defined by the gold standard:

    \u2460 template.ast.json        \u2014 render skeleton (structure only; no values, no prose)
    \u2461 template.blueprint.json  \u2014 analytic brain (entities, topics\u2192questions; no values)

"Value-free" follows the MODERATE policy (loop decision Q4):
    ALLOWED  : structural labels (section titles, column headers, axis labels),
               entity names/types, aliases, units/formats, enum members, glossary,
               and structural numerics (bbox, font sizes, counts, confidence, page refs).
    FORBIDDEN: measured data values (table rows, chart series, facts) and report prose
               (body-paragraph content, figure captions).

The skeleton is produced by clearing the value-bearing slots of the assembled AST; the
``assert_value_free`` validator then proves those slots are empty before the file is written.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Subtrees that may carry extracted prose / values and must NEVER appear in a template.
_VALUE_LADEN_SUBTREES = ("extracted_assets", "pipeline_trace", "questions")


# ─────────────────────────────────────────────────────────────────────────────
# Slot clearing
# ─────────────────────────────────────────────────────────────────────────────

def clear_prefilled_slots(skeleton: dict[str, Any]) -> dict[str, Any]:
    """Empty every value-bearing slot in a render skeleton, in place, and return it.

    Clears: paragraph content, table rows/cells, chart series/data, figure captions,
    and the fact graph. Leaves all structural labels and metadata intact.
    """
    content = skeleton.get("contentAST") or {}
    for block in (content.get("paragraphs") or []) + (content.get("blocks") or []):
        if "content" in block:
            block["content"] = ""
        block.setdefault("slot", {})["status"] = "empty"

    for table in (skeleton.get("tableAST") or {}).get("tables") or []:
        table["rows"] = []
        if "cells" in table:
            table["cells"] = []
        for fn in table.get("footnotes") or []:
            if isinstance(fn, dict) and "text" in fn:
                fn["text"] = ""
        table.setdefault("slot", {})["status"] = "empty"

    for chart in (skeleton.get("chartAST") or {}).get("charts") or []:
        chart["series"] = []
        if "dataPoints" in chart:
            chart["dataPoints"] = []
        chart.setdefault("slot", {})["status"] = "empty"

    for figure in (skeleton.get("figureAST") or {}).get("figures") or []:
        if "caption" in figure:
            figure["caption"] = ""
        figure.setdefault("slot", {})["status"] = "empty"

    if "factGraph" in skeleton:
        skeleton["factGraph"] = {"facts": []}

    return skeleton


# ─────────────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────────────

def build_value_free_skeleton(ast: dict[str, Any]) -> dict[str, Any]:
    """Derive \u2460 template.ast.json (render skeleton) from the assembled AST."""
    meta = dict(ast.get("metadata") or {})
    template_id = meta.get("documentId") or "tpl_document"
    skeleton: dict[str, Any] = {
        "$schema": "bharatstat/template-ast/v1",
        "metadata": {
            "templateId": template_id,
            "blueprintRef": template_id,
            "name": meta.get("title", "Document"),
            "locale": meta.get("locale", "en-IN"),
            "version": meta.get("version", "1.0.0"),
            "valueFree": True,
            "generatedFrom": meta.get("title", "Document"),
        },
        "styleAST": ast.get("styleAST") or {"styles": []},
        "semanticAST": ast.get("semanticAST") or {"hierarchy": []},
        "contentAST": _copy(ast.get("contentAST") or {"paragraphs": []}),
        "tableAST": _copy(ast.get("tableAST") or {"tables": []}),
        "chartAST": _copy(ast.get("chartAST") or {"charts": []}),
        "figureAST": _copy(ast.get("figureAST") or {"figures": []}),
        "layoutAST": ast.get("layoutAST") or {"pages": []},
        "geometryAST": ast.get("geometryAST") or {"nodes": []},
    }
    return clear_prefilled_slots(skeleton)


def build_value_free_blueprint(ast: dict[str, Any]) -> dict[str, Any]:
    """Derive \u2461 template.blueprint.json (analytic brain) from the assembled AST."""
    bp = dict(ast.get("blueprint") or {})
    meta = dict(ast.get("metadata") or {})
    template_id = meta.get("documentId") or "tpl_document"
    blueprint: dict[str, Any] = {
        "$schema": "bharatstat/template-blueprint/v1",
        "templateMeta": {
            "templateId": template_id,
            "name": meta.get("title", "Document"),
            "locale": meta.get("locale", "en-IN"),
            "version": meta.get("version", "1.0.0"),
            "valueFree": True,
            "proseFree": True,
            "sourceDocument": meta.get("title", "Document"),
        },
        "entities": bp.get("entities") or [],
        "entitiesRejected": bp.get("entitiesRejected") or [],
        "topics": bp.get("topics") or [],
        "tableTemplates": bp.get("tableStructures") or bp.get("tableTemplates") or [],
        "documentMap": bp.get("documentMap") or {},
    }
    # Carry forward enrichment subtrees if a later pass produced them.
    for opt in ("glossary", "palette", "renderProfile", "figureTemplates"):
        if opt in bp:
            blueprint[opt] = bp[opt]
    return blueprint


def _copy(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


# ─────────────────────────────────────────────────────────────────────────────
# Value-free validator
# ─────────────────────────────────────────────────────────────────────────────

def assert_value_free(template: dict[str, Any], *, label: str = "template") -> list[str]:
    """Return a list of value-free violations. An empty list means the file is clean.

    Checks only the known value-bearing slots (MODERATE policy) so structural numerics
    such as bbox coordinates, font sizes and counts are never flagged.
    """
    violations: list[str] = []

    for sub in _VALUE_LADEN_SUBTREES:
        if template.get(sub):
            violations.append(f"{label}: forbidden subtree '{sub}' present")

    content = template.get("contentAST") or {}
    for block in (content.get("paragraphs") or []) + (content.get("blocks") or []):
        if (block.get("content") or "").strip():
            bid = block.get("id") or block.get("blockId") or "?"
            violations.append(f"{label}: contentAST block '{bid}' has non-empty content")

    for table in (template.get("tableAST") or {}).get("tables") or []:
        if table.get("rows"):
            violations.append(f"{label}: tableAST '{table.get('tableId')}' has {len(table['rows'])} rows")

    for chart in (template.get("chartAST") or {}).get("charts") or []:
        if chart.get("series") or chart.get("dataPoints"):
            violations.append(f"{label}: chartAST '{chart.get('chartId')}' has series/data")

    for figure in (template.get("figureAST") or {}).get("figures") or []:
        if (figure.get("caption") or "").strip():
            violations.append(f"{label}: figureAST '{figure.get('figureId')}' has a caption")

    if (template.get("factGraph") or {}).get("facts"):
        violations.append(f"{label}: factGraph has facts")

    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Emission
# ─────────────────────────────────────────────────────────────────────────────

def emit_templates(ast: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """Write \u2460 template.ast.json + \u2461 template.blueprint.json to ``out_dir``.

    Returns a report dict with the written paths and any value-free violations
    (violations are logged as warnings but do not block writing, so the artifacts
    remain inspectable during migration).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    skeleton = build_value_free_skeleton(ast)
    blueprint = build_value_free_blueprint(ast)

    violations = assert_value_free(skeleton, label="template.ast")
    violations += assert_value_free(blueprint, label="template.blueprint")

    skeleton_path = out_dir / "template.ast.json"
    blueprint_path = out_dir / "template.blueprint.json"
    with open(skeleton_path, "w", encoding="utf-8") as fh:
        json.dump(skeleton, fh, ensure_ascii=False, indent=2, default=str)
    with open(blueprint_path, "w", encoding="utf-8") as fh:
        json.dump(blueprint, fh, ensure_ascii=False, indent=2, default=str)

    if violations:
        logger.warning("[template_emit] %d value-free violation(s):", len(violations))
        for v in violations[:20]:
            logger.warning("    \u2717 %s", v)
    else:
        logger.info("[template_emit] \u2713 value-free invariant holds for \u2460 and \u2461")

    logger.info("  \u2713 Saved template.ast.json       \u2192 %s", skeleton_path)
    logger.info("  \u2713 Saved template.blueprint.json \u2192 %s", blueprint_path)
    return {
        "skeleton_path": str(skeleton_path),
        "blueprint_path": str(blueprint_path),
        "violations": violations,
    }


def legacy_emit_enabled() -> bool:
    """Whether to also emit the legacy blended AST (loop decision Q3; default OFF)."""
    return (os.getenv("EXTRACTION_EMIT_LEGACY") or "").strip().lower() in ("1", "true", "yes", "on")
