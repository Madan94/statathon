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
        "_doc": _GOLD_AST_DOC,
        "metadata": {
            "templateId": template_id,
            "blueprintRef": template_id,
            "name": meta.get("title", "Document"),
            "locale": meta.get("locale", "en-IN"),
            "version": meta.get("version", "1.0.0"),
            "valueFree": True,
            "generatedFrom": meta.get("title", "Document"),
        },
        "styleAST": conform_style_ast(ast.get("styleAST")),
        "semanticAST": conform_semantic_ast(ast.get("semanticAST")),
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
        "_doc": _GOLD_BP_DOC,
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
    # any that an upstream pass (e.g. fully-offline) never produced. The deduped detected
    # figures seed figure synthesis so real charts are not lost when the question
    # generator under-wires chart components. figureAST entries retain their ids (the
    # chartAST copies lose theirs when merged), so they are the reliable seed.
    return conform_blueprint(blueprint, charts=_detected_chart_figures(ast))


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

# Top-level provenance strings (gold parity). Templates are self-describing.
_GOLD_AST_DOC = (
    "VALUE-FREE render skeleton. Keeps every structural label (headings, column "
    "headers, roles, units, formats, palette refs, slot wiring) but NO data: "
    'content="", rows=[], series=[], caption="". Pairs 1:1 with '
    "template.blueprint.json by shared IDs. The binder clones this, fills the slots "
    "from a dataset, and emits report.output.ast.json."
)
_GOLD_BP_DOC = (
    "VALUE-FREE + PROSE-FREE analytic brain. Defines WHAT to compute and HOW to "
    "render. Contains NO numbers, NO sentences, NO dataset. Pairs 1:1 with "
    "template.ast.json by shared IDs."
)

# Default style tokens (gold shape). Injected when an upstream pass emits no styles so
# the ``styleRef: s_body`` references in contentAST/tableAST never dangle.
_GOLD_DEFAULT_STYLES: list[dict[str, Any]] = [
    {"styleId": "s_h1", "role": "heading1", "font": "Noto Sans", "sizePt": 18, "bold": True, "color": "#0B5394"},
    {"styleId": "s_body", "role": "body", "font": "Noto Sans", "sizePt": 11, "bold": False, "color": "#222222"},
    {"styleId": "s_table", "role": "tableCell", "font": "Noto Sans", "sizePt": 9, "align": "right"},
    {"styleId": "s_caption", "role": "caption", "font": "Noto Sans", "sizePt": 9, "italic": True, "color": "#555555"},
]

# Specific component kinds → the gold generic kind. The question generator emits
# fine-grained kinds (``data_table``, ``metric_card`` …); the gold model + binder use
# four generics. We keep the specific kind under ``componentKind`` for renderers.
_GENERIC_KIND: dict[str, str] = {
    "data_table": "table", "table": "table", "matrix": "table",
    "metric_card": "metric", "metric": "metric", "kpi": "metric", "stat": "metric",
    "narrative_paragraph": "narrative", "narrative": "narrative",
    "paragraph": "narrative", "text": "narrative", "prose": "narrative",
}


def _generic_component_kind(kind: Any) -> str:
    """Map a specific component kind to the gold generic (narrative/chart/table/metric)."""
    k = str(kind or "").strip().lower()
    if _is_chart_kind(k):
        return "chart"
    return _GENERIC_KIND.get(k, "narrative")


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


_CHART_KINDS = {
    "chart", "line_chart", "bar_chart", "grouped_bar_chart", "stacked_bar_chart",
    "column_chart", "pie_chart", "donut_chart", "area_chart", "scatter_plot",
    "scatter_chart", "bubble_chart", "histogram", "combo_chart", "map",
    "geographic_map", "geo_map", "choropleth",
}


def _is_chart_kind(kind: Any) -> bool:
    """True if a component/figure kind belongs to the chart family.

    The question generator emits *specific* kinds (``line_chart``, ``grouped_bar_chart``
    …); the gold model uses the generic ``"chart"``. Both must be recognised so charts
    are never silently dropped from ``figureTemplates``.
    """
    k = str(kind or "").strip().lower()
    return bool(k) and (
        k in _CHART_KINDS or k.endswith("_chart") or k.endswith("_plot") or k.endswith("_map")
    )


def _norm_chart_title(item: dict[str, Any]) -> str:
    raw = item.get("title") or item.get("caption") or item.get("description") or ""
    return " ".join(str(raw).strip().lower().split())


def dedupe_charts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse speculative duplicate charts that share a page + title.

    Small vision models echo the prompt's example ``["bar_chart","line_chart"]`` for
    every chart page, yielding two empty-series entries with an identical (page, title).
    These are the same figure guessed twice, so they are merged into one slot whose
    candidate types are preserved under ``chartTypes``. Charts with distinct titles — or
    no title — are kept separate (conservative).
    """
    out: list[dict[str, Any]] = []
    index: dict[tuple[Any, str], int] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        title = _norm_chart_title(it)
        key = (it.get("page"), title)
        ctype = it.get("chartType")
        if title and key in index:
            tgt = out[index[key]]
            types = tgt.setdefault("chartTypes", [tgt["chartType"]] if tgt.get("chartType") else [])
            if ctype and ctype not in types:
                types.append(ctype)
            continue
        index[key] = len(out)
        out.append(it)
    return out


def _detected_chart_figures(ast: dict[str, Any]) -> list[dict[str, Any]]:
    """Deduped, chart-like detected figures used to seed ``figureTemplates``.

    Prefers ``figureAST.figures`` (entries keep their ``chartId``/``figureId`` after the
    pipeline merges charts into figures) and falls back to ``chartAST.charts``. Only
    chart-type figures are kept so decorative images do not become figure templates.
    """
    figs = (ast.get("figureAST") or {}).get("figures") or []
    charts = (ast.get("chartAST") or {}).get("charts") or []
    pool = figs or charts
    chart_like = [
        c for c in pool
        if isinstance(c, dict) and (
            c.get("type") == "chart" or _is_chart_kind(c.get("chartType") or c.get("type"))
        )
    ]
    return dedupe_charts(chart_like or pool)


def synthesize_figure_templates(
    blueprint: dict[str, Any], charts: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Derive ``figureTemplates`` from chart components and/or detected charts.

    Gold shape: ``{figureTemplateId, captionTemplate, chartId, numbering}``. One per
    distinct chart. Two complementary sources, deduped by ``chartId``:

    1. **Question-driven** (gold model): each ``answerStructure.components`` entry whose
       kind is in the chart family (``chart`` or any ``*_chart`` / ``*_plot`` / ``*_map``).
       The question generator emits specific kinds (``line_chart`` etc.), so matching only
       the literal ``"chart"`` silently dropped every figure — the cause of empty
       ``figureTemplates`` (UI shows zero charts).
    2. **Chart-driven**: any chart detected in ``chartAST`` that no question wired, so
       genuinely-present figures still surface in the template.
    """
    figures: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    seen_ids: set[str] = set()

    def _emit(chart_id: str, fig_ref: str, title: str, *also: str) -> None:
        seen_refs.add(fig_ref)
        for ident in (chart_id, *also):
            if ident:
                seen_ids.add(ident)
        figures.append({
            "figureTemplateId": fig_ref,
            "captionTemplate": f"{(title or 'Figure').rstrip('.')}, {{{{period.current}}}}",
            "chartId": chart_id,
            "numbering": "Figure {{topic.order}}.{{seq}}",
        })

    # 1. question-driven (gold model)
    for topic in blueprint.get("topics") or []:
        for q in topic.get("questions") or []:
            for comp in (q.get("answerStructure") or {}).get("components") or []:
                if not _is_chart_kind(comp.get("kind") or comp.get("type")):
                    continue
                refs = comp.get("refs") or {}
                chart_id = refs.get("chartRef") or comp.get("componentId") or ""
                fig_ref = refs.get("figureRef") or f"ft_{chart_id}"
                if fig_ref in seen_refs or (chart_id and chart_id in seen_ids):
                    continue
                _emit(chart_id, fig_ref, q.get("intent") or topic.get("title") or "Figure",
                      refs.get("figureRef") or "")

    # 2. chart-driven (detected charts no question referenced). The chartAST entries lose
    #    their id when merged into figureAST, so a detected chart is keyed by either id;
    #    skip any already represented by a question's chartRef / figureRef.
    for ch in charts or []:
        chart_id = ch.get("chartId") or ch.get("figureId") or ""
        fig_id = ch.get("figureId") or ch.get("chartId") or ""
        if not chart_id or chart_id in seen_ids or fig_id in seen_ids:
            continue
        fig_ref = f"ft_{chart_id}"
        if fig_ref in seen_refs:
            continue
        _emit(chart_id, fig_ref, ch.get("title") or ch.get("caption") or "Figure", fig_id)

    return figures


def conform_style_ast(style_ast: Any) -> dict[str, Any]:
    """Ensure styleAST carries the gold style tokens so ``styleRef``s never dangle."""
    styles = (style_ast or {}).get("styles") if isinstance(style_ast, dict) else None
    if isinstance(styles, list) and styles:
        return {"styles": styles}
    return {"styles": [dict(s) for s in _GOLD_DEFAULT_STYLES]}


def conform_semantic_ast(sem: Any) -> dict[str, Any]:
    """Strip internal diagnostics (``_quality``) so the template matches the gold shape."""
    if not isinstance(sem, dict):
        return {"sections": []}
    return {k: v for k, v in sem.items() if not str(k).startswith("_")}


def conform_document_map(dm: Any, topics: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Coerce documentMap to the gold shape ``{order, frontMatter, backMatter}``.

    ``order`` is the topic reading order; front/back matter default to the canonical
    MoSPI scaffold. A legacy ``{chapters, sectionPatterns, title}`` map is discarded
    (its content is reconstructed from the topics, which are the source of truth).
    """
    order = [t.get("topicId") for t in (topics or []) if isinstance(t, dict) and t.get("topicId")]
    if isinstance(dm, dict) and isinstance(dm.get("order"), list) and dm["order"]:
        order = dm["order"]
    front = dm.get("frontMatter") if isinstance(dm, dict) else None
    back = dm.get("backMatter") if isinstance(dm, dict) else None
    return {
        "order": order,
        "frontMatter": front if isinstance(front, list) and front else ["title_page", "toc"],
        "backMatter": back if isinstance(back, list) and back else ["glossary", "notes"],
    }


_GOLD_ENTITY_TYPES = {"measure", "dimension", "time", "metric"}


def conform_entities(entities: Any, topics: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Drop extraction-noise entities and backfill ``canonicalName``.

    ``metadata``-type entities (page refs, source contexts) are scaffolding noise the
    gold model never carries; they are removed *unless* a question references them, so
    no ``requiredEntities``/``analyticsSpec`` ref is left dangling. Every surviving
    entity is guaranteed a ``canonicalName`` (backfilled from ``name``).
    """
    ents = entities if isinstance(entities, list) else []
    referenced: set[str] = set()
    for t in topics or []:
        for q in t.get("questions") or []:
            for re_ in q.get("requiredEntities") or []:
                if isinstance(re_, dict) and re_.get("entityId"):
                    referenced.add(re_["entityId"])
            spec = q.get("analyticsSpec") or {}
            for ref in _iter_entity_refs(spec):
                referenced.add(ref)
    out: list[dict[str, Any]] = []
    for e in ents:
        if not isinstance(e, dict):
            continue
        etype = str(e.get("entityType") or "").strip().lower()
        eid = e.get("entityId")
        if etype not in _GOLD_ENTITY_TYPES and eid not in referenced:
            continue
        e = dict(e)
        if not e.get("canonicalName"):
            e["canonicalName"] = e.get("name") or e.get("canonicalName") or eid or ""
        out.append(e)
    return out


def _iter_entity_refs(spec: Any):
    """Yield every ``entityRef`` value nested anywhere inside an analyticsSpec."""
    if isinstance(spec, dict):
        for k, v in spec.items():
            if k == "entityRef" and isinstance(v, str) and v:
                yield v
            else:
                yield from _iter_entity_refs(v)
    elif isinstance(spec, list):
        for item in spec:
            yield from _iter_entity_refs(item)


def conform_components(topics: list[dict[str, Any]] | None) -> None:
    """Normalise every answer component to the gold shape, in place, and wire refs.

    Gold component: ``{componentId, kind, order, outputContract, refs}`` (narrative
    also carries ``narrativeTemplate``). The question generator emits the legacy shape
    ``{componentId, type, renderOrder, constraints, refs:{}}`` with empty refs, so the
    binder cannot resolve a single content/chart/table target. We:

      • map the specific ``type`` → gold generic ``kind`` (keeping the specific under
        ``componentKind``),
      • copy ``renderOrder`` → ``order``,
      • synthesize an ``outputContract`` per kind,
      • wire deterministic refs: narrative → ``contentRef`` (the per-question content
        block ``p_{qid}``), chart → ``chartRef``/``figureRef`` so figure synthesis and
        the binder share one id.
    """
    for topic in topics or []:
        for q in topic.get("questions") or []:
            qid = q.get("questionId") or q.get("id") or ""
            comps = (q.get("answerStructure") or {}).get("components") or []
            for i, comp in enumerate(comps, start=1):
                if not isinstance(comp, dict):
                    continue
                specific = comp.get("componentKind") or comp.get("type") or comp.get("kind") or "narrative"
                kind = _generic_component_kind(specific)
                cid = comp.get("componentId") or f"{qid}_c{i}"
                comp["componentId"] = cid
                comp["componentKind"] = str(specific).strip().lower()
                comp["kind"] = kind
                comp["order"] = comp.get("order") or comp.get("renderOrder") or i
                comp.pop("renderOrder", None)
                comp.pop("type", None)
                refs = comp.get("refs") if isinstance(comp.get("refs"), dict) else {}
                if kind == "narrative":
                    comp["outputContract"] = comp.get("outputContract") or {
                        "type": "prose", "minWords": 40, "maxWords": 90,
                    }
                    comp.setdefault("narrativeTemplate", {
                        "tone": "formal-analytical", "pattern": "headline_then_gap", "maxWords": 90,
                    })
                    refs.setdefault("contentRef", f"p_{qid}" if qid else "")
                    refs.setdefault("analyticsRef", "")
                    refs.setdefault("evidenceRef", "")
                elif kind == "chart":
                    chart_ref = refs.get("chartRef") or f"chart_{cid}"
                    refs["chartRef"] = chart_ref
                    refs.setdefault("figureRef", f"ft_{chart_ref}")
                    refs.setdefault("analyticsRef", "")
                    refs.setdefault("evidenceRef", "")
                    comp["outputContract"] = comp.get("outputContract") or {
                        "type": "chart", "chartType": comp["componentKind"],
                    }
                elif kind == "table":
                    refs.setdefault("tableRef", refs.get("tableRef") or "")
                    refs.setdefault("analyticsRef", "")
                    refs.setdefault("evidenceRef", "")
                    comp["outputContract"] = comp.get("outputContract") or {"type": "table"}
                else:  # metric
                    refs.setdefault("analyticsRef", "")
                    refs.setdefault("evidenceRef", "")
                    comp["outputContract"] = comp.get("outputContract") or {"type": "metric"}
                comp["refs"] = refs
                comp.pop("constraints", None)


def conform_topics(topics: Any) -> list[dict[str, Any]]:
    """Backfill the gold-required ``order`` / ``semanticRef`` on each topic, in place."""
    out = topics if isinstance(topics, list) else []
    for idx, t in enumerate(out, start=1):
        if not isinstance(t, dict):
            continue
        t["order"] = t.get("order") or idx
        if "semanticRef" not in t:
            t["semanticRef"] = t.get("semanticRef") or ""
    conform_components(out)
    return out


def conform_blueprint(
    blueprint: dict[str, Any], charts: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Reshape/backfill optional subtrees so the blueprint matches the gold schema.

    Idempotent. Guarantees: glossary is a ``{TERM: def}`` map, palette is the gold
    shape, ``renderProfile`` and ``figureTemplates`` are present. ``charts`` (the
    deduped ``chartAST`` charts) let figure synthesis surface detected figures even when
    the question generator under-wires chart components. The diagnostic
    ``entitiesRejected`` list (absent from gold) is dropped from the template.
    """
    blueprint.pop("entitiesRejected", None)
    blueprint["glossary"] = conform_glossary(blueprint.get("glossary"))
    blueprint["palette"] = conform_palette(blueprint.get("palette"))

    # Normalise topics → questions → components (wire refs) before deriving templates,
    # then prune entity noise against the (now-stable) question refs.
    blueprint["topics"] = conform_topics(blueprint.get("topics"))
    blueprint["entities"] = conform_entities(blueprint.get("entities"), blueprint["topics"])
    blueprint["documentMap"] = conform_document_map(blueprint.get("documentMap"), blueprint["topics"])

    rp = blueprint.get("renderProfile")
    blueprint["renderProfile"] = rp if isinstance(rp, dict) and rp else dict(_GOLD_RENDER_PROFILE)

    ft = blueprint.get("figureTemplates")
    if not (isinstance(ft, list) and ft):
        blueprint["figureTemplates"] = synthesize_figure_templates(blueprint, charts=charts)
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

    # ── chartAST / figureAST: collapse speculative duplicate figures ──
    # Vision models echo the prompt's example chart pair on every page, doubling counts
    # (one figure detected twice as bar + line). Merge them so counts reflect reality.
    chart_ast = skeleton.get("chartAST") or {}
    if chart_ast.get("charts"):
        chart_ast["charts"] = dedupe_charts(chart_ast["charts"])
        skeleton["chartAST"] = chart_ast
    figure_ast = skeleton.get("figureAST") or {}
    if figure_ast.get("figures"):
        figure_ast["figures"] = dedupe_charts(figure_ast["figures"])
        skeleton["figureAST"] = figure_ast

    # ── contentAST: one narrative slot per question (gold model), wired by biQuery ──
    content_blocks: list[dict[str, Any]] = []
    for topic in topics:
        for q in topic.get("questions") or []:
            qid = q.get("questionId") or q.get("id")
            if not qid:
                continue
            comps = (q.get("answerStructure") or {}).get("components") or []
            fill_from = next(
                (c.get("componentId") for c in comps if isinstance(c, dict) and c.get("componentId")),
                f"{qid}_c1",
            )
            content_blocks.append({
                "blockId": f"p_{qid}",
                "kind": "paragraph",
                "styleRef": "s_body",
                "content": "",
                "biQuery": qid,
                "templateQuestion": q.get("intent") or q.get("sourceHeading") or "",
                "slot": {"fillFrom": fill_from, "status": "empty"},
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
