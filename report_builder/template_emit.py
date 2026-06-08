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
    skeleton = clear_prefilled_slots(skeleton)
    topics = (ast.get("blueprint") or {}).get("topics") or []
    return compact_skeleton_ast(skeleton, topics)


def build_value_free_blueprint(ast: dict[str, Any]) -> dict[str, Any]:
    """Derive \u2461 template.blueprint.json (analytic brain) from the assembled AST."""
    bp = dict(ast.get("blueprint") or {})
    meta = dict(ast.get("metadata") or {})
    template_id = _normalize_template_id(meta, bp)
    blueprint: dict[str, Any] = {
        "$schema": "bharatstat/template-blueprint/v1",
        "templateMeta": {
            "templateId": template_id,
            "name": meta.get("title", "Document"),
            "domain": meta.get("domain") or bp.get("domain") or "general",
            "locale": meta.get("locale", "en-IN"),
            "version": meta.get("version", "1.0.0"),
            "valueFree": True,
            "proseFree": True,
            "sourceDocument": meta.get("title", "Document"),
        },
        "entities": bp.get("entities") or [],
        "topics": bp.get("topics") or [],
        "tableTemplates": bp.get("tableStructures") or bp.get("tableTemplates") or [],
        "documentMap": bp.get("documentMap") or {},
    }
    # Carry forward enrichment subtrees if a later pass produced them.
    for opt in ("glossary", "palette", "renderProfile", "figureTemplates"):
        if opt in bp:
            blueprint[opt] = bp[opt]
    # Coerce every optional subtree to the gold-standard schema shape, synthesizing
    # any that an upstream pass (e.g. fully-offline) never produced.
    return conform_blueprint(blueprint)


# ─────────────────────────────────────────────────────────────────────────────
# Gold-standard schema conformance
#
# The two-file model must always match the shape of
# report_builder/gold_standard/template.blueprint.json regardless of which passes
# ran (offline vs Gemini). These helpers reshape / backfill the optional subtrees
# so the output is schema-conformant by construction.
# ─────────────────────────────────────────────────────────────────────────────

# Canonical MoSPI render profile (en-IN, lakh-crore grouping, ₹). Matches gold.
_GOLD_RENDER_PROFILE: dict[str, Any] = {
    "numberFormat": {"locale": "en-IN", "grouping": "lakh-crore", "decimalSeparator": "."},
    "percentFormat": {"decimals": 1, "suffix": "%"},
    "currencyFormat": {"symbol": "\u20b9", "grouping": "lakh-crore", "decimals": 0},
    "fontFamily": "Noto Sans",
    "pageSize": "A4",
}

# Canonical palette in the gold shape (paletteId + sequential[] + categorical{} + semantic{}).
_GOLD_PALETTE: dict[str, Any] = {
    "paletteId": "pal_mospi_default",
    "sequential": ["#0B5394", "#3D85C6", "#6FA8DC", "#9FC5E8", "#CFE2F3"],
    "categorical": {
        "Rural": "#1F7A1F", "Urban": "#0B5394",
        "Male": "#0B5394", "Female": "#CC4125", "Total": "#666666",
    },
    "semantic": {"positive": "#1F7A1F", "negative": "#CC0000", "neutral": "#666666"},
}


def _slugify_id(text: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")
    return slug or "document"


def _normalize_template_id(meta: dict[str, Any], bp: dict[str, Any]) -> str:
    """Produce a stable, well-formed templateId (never the broken ``doc_offline-``)."""
    raw = (
        meta.get("documentId")
        or (bp.get("templateMeta") or {}).get("templateId")
        or meta.get("templateId")
        or ""
    )
    raw = str(raw).strip()
    # Reject empty, trailing-dash, or sentinel ids produced by the offline path.
    if not raw or raw.rstrip("-_") in ("", "doc_offline", "doc", "tpl_document", "template"):
        title = meta.get("title") or bp.get("title") or "document"
        return f"tpl_{_slugify_id(title)}_v1"
    return raw.rstrip("-_")


def conform_glossary(glossary: Any) -> dict[str, str]:
    """Coerce a glossary into the gold ``{TERM: definition}`` map (from list or dict)."""
    out: dict[str, str] = {}
    if isinstance(glossary, dict):
        for k, v in glossary.items():
            if isinstance(v, str):
                out[str(k)] = v
            elif isinstance(v, dict):
                out[str(k)] = str(v.get("definition") or v.get("text") or "")
    elif isinstance(glossary, list):
        for item in glossary:
            if not isinstance(item, dict):
                continue
            term = item.get("term") or item.get("key") or item.get("name")
            definition = item.get("definition") or item.get("text") or ""
            if term:
                out[str(term)] = str(definition)
    return out


def conform_palette(palette: Any) -> dict[str, Any]:
    """Coerce a palette into the gold shape (sequential[] + categorical{} + semantic{})."""
    if not isinstance(palette, dict) or not palette:
        return dict(_GOLD_PALETTE)
    out: dict[str, Any] = {
        "paletteId": palette.get("paletteId") or _GOLD_PALETTE["paletteId"],
        "sequential": palette.get("sequential") or list(_GOLD_PALETTE["sequential"]),
    }
    # categorical: gold is a {label: color} map; tolerate a bare list by mapping to defaults.
    cat = palette.get("categorical")
    if isinstance(cat, dict) and cat:
        out["categorical"] = cat
    else:
        out["categorical"] = dict(_GOLD_PALETTE["categorical"])
    # semantic: prefer existing; else derive from a legacy ``roles`` block; else default.
    sem = palette.get("semantic")
    if isinstance(sem, dict) and sem:
        out["semantic"] = sem
    else:
        roles = palette.get("roles") or {}
        out["semantic"] = {
            "positive": roles.get("delta_up") or _GOLD_PALETTE["semantic"]["positive"],
            "negative": roles.get("delta_down") or _GOLD_PALETTE["semantic"]["negative"],
            "neutral": roles.get("prior") or _GOLD_PALETTE["semantic"]["neutral"],
        }
    return out


def synthesize_figure_templates(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive ``figureTemplates`` from any chart components referenced by questions.

    Gold shape: ``{figureTemplateId, captionTemplate, chartId, numbering}``. One per
    distinct chart referenced in an ``answerStructure.components`` entry of kind chart.
    """
    figures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for topic in blueprint.get("topics") or []:
        for q in topic.get("questions") or []:
            for comp in (q.get("answerStructure") or {}).get("components") or []:
                if comp.get("kind") != "chart":
                    continue
                refs = comp.get("refs") or {}
                chart_id = refs.get("chartRef") or comp.get("componentId")
                fig_ref = refs.get("figureRef") or f"ft_{chart_id}"
                if fig_ref in seen:
                    continue
                seen.add(fig_ref)
                title = q.get("intent") or topic.get("title") or "Figure"
                figures.append({
                    "figureTemplateId": fig_ref,
                    "captionTemplate": f"{title.rstrip('.')}, {{{{period.current}}}}",
                    "chartId": chart_id,
                    "numbering": "Figure {{topic.order}}.{{seq}}",
                })
    return figures


def conform_blueprint(blueprint: dict[str, Any]) -> dict[str, Any]:
    """Reshape/backfill optional subtrees so the blueprint matches the gold schema.

    Idempotent. Guarantees: glossary is a ``{TERM: def}`` map, palette is the gold
    shape, ``renderProfile`` and ``figureTemplates`` are present. The diagnostic
    ``entitiesRejected`` list (absent from gold) is dropped from the template.
    """
    blueprint.pop("entitiesRejected", None)
    blueprint["glossary"] = conform_glossary(blueprint.get("glossary"))
    blueprint["palette"] = conform_palette(blueprint.get("palette"))

    rp = blueprint.get("renderProfile")
    blueprint["renderProfile"] = rp if isinstance(rp, dict) and rp else dict(_GOLD_RENDER_PROFILE)

    ft = blueprint.get("figureTemplates")
    if not (isinstance(ft, list) and ft):
        blueprint["figureTemplates"] = synthesize_figure_templates(blueprint)
    return blueprint


def compact_skeleton_ast(
    skeleton: dict[str, Any], topics: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Compact a value-free render skeleton to the gold template shape.

    A template is a *reusable* skeleton, so instance-specific physical layout (every
    raw OCR block with absolute bounding boxes, every extracted paragraph) is replaced
    by a small set of logical regions that bind to semantic / content / figure / table
    elements, and geometry becomes a *relative* flow. Absolute coordinates are
    recomputed by the layout engine at render time (per the gold ``geometryAST`` doc).

    Idempotent. ``topics`` (``blueprint.topics``) drive one narrative content slot per
    question, wired by ``biQuery`` — robust to upstream component-ref wiring gaps.
    """
    topics = topics or []

    # ── contentAST: one narrative slot per question (gold model), wired by biQuery ──
    content_blocks: list[dict[str, Any]] = []
    for topic in topics:
        for q in topic.get("questions") or []:
            qid = q.get("questionId") or q.get("id")
            if not qid:
                continue
            content_blocks.append({
                "blockId": f"p_{qid}",
                "kind": "paragraph",
                "styleRef": "s_body",
                "content": "",
                "biQuery": qid,
                "templateQuestion": q.get("intent") or q.get("sourceHeading") or "",
                "slot": {"status": "empty"},
            })
    skeleton["contentAST"] = {"blocks": content_blocks, "lists": [], "quotes": []}

    # ── layoutAST: logical regions  +  geometryAST: relative flow ──
    regions: list[dict[str, Any]] = []
    flow: list[str] = []
    seen: set[str] = set()

    def _add(src_id: Any, role: str) -> None:
        if not src_id:
            return
        rid = f"rg_{src_id}"
        if rid in seen:
            return
        seen.add(rid)
        regions.append({"regionId": rid, "role": role, "bindsTo": str(src_id), "bbox": None})
        flow.append(rid)

    sem = skeleton.get("semanticAST") or {}

    # One heading region per *top-level* section only. The full nested outline lives in
    # semanticAST; the render flow tracks major regions (and avoids amplifying upstream
    # heading-misdetection noise into hundreds of layout regions).
    sections = sem.get("hierarchy") or sem.get("sections") or sem.get("nodes") or []
    for n in sections:
        if isinstance(n, dict):
            _add(n.get("nodeId") or n.get("sectionId") or n.get("id"), "heading")
    for blk in content_blocks:
        _add(blk["blockId"], "body")
    for fig in (skeleton.get("figureAST") or {}).get("figures") or []:
        _add(fig.get("figureId") or fig.get("id"), "figure")
    for tbl in (skeleton.get("tableAST") or {}).get("tables") or []:
        _add(tbl.get("tableId") or tbl.get("id"), "table")

    skeleton["layoutAST"] = {"pages": [{"pageId": "pg_1", "size": "A4", "regions": regions}]}
    skeleton["geometryAST"] = {
        "_doc": "Relative flow only. Absolute bounding boxes are computed by the layout engine at render time.",
        "flow": flow,
    }
    return skeleton


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

    # Diagnostic rejected entities are NOT part of the gold template; persist them to a
    # sidecar so the hygiene information remains inspectable without bloating ②.
    rejected = ((ast.get("blueprint") or {}).get("entitiesRejected")) or []
    if rejected:
        diag_path = out_dir / "template.diagnostics.json"
        with open(diag_path, "w", encoding="utf-8") as fh:
            json.dump({"entitiesRejected": rejected}, fh, ensure_ascii=False, indent=2, default=str)
        logger.info("  \u24d8 Saved %d rejected entit(ies) \u2192 %s", len(rejected), diag_path)

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
