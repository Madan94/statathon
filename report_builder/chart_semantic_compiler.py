"""E11 — Chart/Figure Semantic Compiler.

Converts detected figures/charts into value-free FigureSemanticModel objects.

CRITICAL: This module NEVER stores chart values, pie percentages, bar heights,
or series data. It stores only:
- chart type
- subject
- entity links (category, measures, dimensions)
- caption template (value-free)
- provenance

Usage:
    from report_builder.chart_semantic_compiler import compile_figure_semantics
    result = compile_figure_semantics(detected_figures, tables, entities)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from report_builder.chart_panel_parser import parse_chart_panel_title


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FigureSemanticModel:
    """Value-free semantic model for one chart/figure."""
    figureTemplateId: str = ""
    figureNumber: str | None = None
    page: int | None = None

    # Type and intent
    chartType: str = "unknown"          # pie | bar | grouped_bar | stacked_bar | line | map | unknown
    chartSubject: str = ""

    # Entity links
    categoryEntityRef: str | None = None
    measureRefs: list[str] = field(default_factory=list)
    dimensionRef: str | None = None
    periodRef: str | None = None
    panel: str | None = None
    filters: list[dict[str, Any]] = field(default_factory=list)

    # Template (value-free)
    captionTemplate: str = ""
    axisLabels: dict[str, str] = field(default_factory=dict)
    legendLabels: list[str] = field(default_factory=list)

    # Provenance
    detectionMethod: str = "heuristic"  # vlm_detection | caption_analysis | proximity_inference | table_context | heuristic
    confidence: float = 0.5
    relatedTableId: str | None = None
    relatedQuestionId: str | None = None
    sectionRef: str | None = None
    sourceRefs: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "figureTemplateId": self.figureTemplateId,
            "chartType": self.chartType,
            "chartSubject": self.chartSubject,
            "captionTemplate": self.captionTemplate,
            "detectionMethod": self.detectionMethod,
            "confidence": self.confidence,
        }
        if self.figureNumber:
            d["figureNumber"] = self.figureNumber
        if self.page is not None:
            d["page"] = self.page
        if self.categoryEntityRef:
            d["categoryEntityRef"] = self.categoryEntityRef
        if self.measureRefs:
            d["measureRefs"] = list(self.measureRefs)
        if self.dimensionRef:
            d["dimensionRef"] = self.dimensionRef
        if self.periodRef:
            d["periodRef"] = self.periodRef
        if self.panel:
            d["panel"] = self.panel
        if self.filters:
            d["filters"] = list(self.filters)
        if self.axisLabels:
            d["axisLabels"] = dict(self.axisLabels)
        if self.legendLabels:
            d["legendLabels"] = list(self.legendLabels)
        if self.relatedTableId:
            d["relatedTableId"] = self.relatedTableId
        if self.sectionRef:
            d["sectionRef"] = self.sectionRef
        if self.diagnostics:
            d["diagnostics"] = list(self.diagnostics)
        return d


@dataclass
class ChartSemanticResult:
    """Batch result of chart/figure compilation."""
    figures: list[FigureSemanticModel] = field(default_factory=list)
    unresolvedFigures: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "figureCount": len(self.figures),
            "unresolvedCount": len(self.unresolvedFigures),
            "counts": dict(self.counts),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Chart type inference
# ─────────────────────────────────────────────────────────────────────────────

_PIE_SIGNALS = re.compile(r'\b(pie|circle|slices?|distribution\s+of|composition|share\s+of|proportion)\b', re.IGNORECASE)
_BAR_SIGNALS = re.compile(r'\b(bar|ranking|comparison|top\s+\w+|highest|lowest|statewise|compare|states?\s+by)\b', re.IGNORECASE)
_LINE_SIGNALS = re.compile(r'\b(trend|over\s+time|growth|year[\s-]over[\s-]year|time\s*series|temporal)\b', re.IGNORECASE)
_MAP_SIGNALS = re.compile(r'\b(map|geographical|geograph|spatial|region[\s-]wise)\b', re.IGNORECASE)
_STACKED_SIGNALS = re.compile(r'\b(stacked|composition\s+by|breakdown|structure)\b', re.IGNORECASE)


def infer_chart_type(
    vlm_shape: str | None = None,
    caption: str = "",
    question_type: str | None = None,
    nearby_table: Any = None,
) -> str:
    """Infer chart type from available signals.

    Priority: vlm_shape > caption patterns > question_type > heuristic
    """
    # VLM shape detection (highest confidence)
    if vlm_shape:
        shape_lower = vlm_shape.lower()
        if "circle" in shape_lower or "pie" in shape_lower:
            return "pie"
        if "bar" in shape_lower or "rect" in shape_lower:
            return "bar"
        if "line" in shape_lower:
            return "line"
        if "map" in shape_lower:
            return "map"
        if "stack" in shape_lower:
            return "stacked_bar"

    # Caption text analysis (order matters: more specific first)
    if caption:
        if _STACKED_SIGNALS.search(caption):
            return "stacked_bar"
        if _MAP_SIGNALS.search(caption):
            return "map"
        if _PIE_SIGNALS.search(caption):
            return "pie"
        if _BAR_SIGNALS.search(caption):
            return "bar"
        if _LINE_SIGNALS.search(caption):
            return "line"

    # Question type hint
    if question_type:
        qt = question_type.lower()
        if qt == "trend":
            return "line"
        if qt in ("comparison", "ranking"):
            return "bar"
        if qt == "composition":
            return "pie"

    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Subject extraction
# ─────────────────────────────────────────────────────────────────────────────

# Data value patterns to strip from captions (value-free guard)
_DATA_VALUE_RE = re.compile(r'\b\d{2,}\.\d+\b|\b\d{4,}\b|[₹$€]\s*[\d,]+')


def extract_chart_subject(
    caption: str,
    section_title: str = "",
    nearby_table: Any = None,
) -> str:
    """Extract the semantic subject of a chart from caption/context.

    Returns a clean, value-free subject string.
    """
    if not caption and not section_title:
        return "Unknown chart subject"

    # Use caption first, fall back to section
    source = caption.strip() if caption else section_title.strip()

    # Strip data values (value-free guard)
    cleaned = _DATA_VALUE_RE.sub("", source).strip()
    # Remove trailing number artifacts
    cleaned = re.sub(r'\s+\d+\s*$', '', cleaned)
    # Remove figure number prefix
    cleaned = re.sub(r'^(Fig(ure)?\.?\s*\d+(\.\d+)?[:\s]*)', '', cleaned, flags=re.IGNORECASE).strip()

    # If nothing left, use section title
    if not cleaned or len(cleaned) < 5:
        cleaned = section_title.strip() if section_title else "Chart"

    return cleaned


# ─────────────────────────────────────────────────────────────────────────────
# Entity linking
# ─────────────────────────────────────────────────────────────────────────────


def link_chart_entities(
    subject: str,
    entities: list[Any] | None = None,
    table_models: list[Any] | None = None,
) -> dict[str, Any]:
    """Link a chart's subject to entity IDs.

    Returns dict with: categoryEntityRef, measureRefs, dimensionRef, periodRef, confidence
    """
    result: dict[str, Any] = {
        "categoryEntityRef": None,
        "measureRefs": [],
        "dimensionRef": None,
        "periodRef": None,
        "confidence": 0.3,
    }

    if not entities:
        return result

    subject_lower = subject.lower()

    # Build entity lookup
    entity_map: dict[str, dict[str, Any]] = {}
    for ent in entities:
        name = _get(ent, "canonicalName") or ""
        eid = _get(ent, "entityId") or ""
        etype = _get(ent, "entityType") or ""
        aliases = _get(ent, "aliases") or []
        if eid:
            entity_map[eid] = {"name": name, "type": etype, "aliases": aliases}

    # Find matching entities by subject keywords
    matched_measures: list[str] = []
    matched_dimensions: list[str] = []
    matched_category: str | None = None

    subject_tokens = set(re.findall(r"[a-z0-9]+", subject_lower))

    def _alias_matches(alias: str) -> bool:
        alias_low = alias.lower().strip()
        if not alias_low:
            return False
        # Short abbreviations like UR must match as tokens, not substrings inside
        # rural/urban/manufacturing.
        if len(alias_low) <= 3:
            return alias_low in subject_tokens
        return alias_low in subject_lower

    for eid, info in entity_map.items():
        name_lower = info["name"].lower()
        etype = info["type"]

        # Check if entity name appears in subject
        if name_lower and (name_lower in subject_lower or any(_alias_matches(a) for a in info["aliases"] if a)):
            if etype == "measure":
                matched_measures.append(eid)
            elif etype == "dimension":
                matched_dimensions.append(eid)
            elif etype == "time":
                result["periodRef"] = eid

    # Subject keywords for common patterns
    if "reserve" in subject_lower and not matched_category:
        # Look for reserve category entity
        for eid, info in entity_map.items():
            if "category" in info["name"].lower() or "reserve" in info["name"].lower():
                if info["type"] == "dimension":
                    matched_category = eid
                    break

    # Geography pattern
    if any(g in subject_lower for g in ("geographical", "statewise", "state", "region")):
        for eid, info in entity_map.items():
            if info["type"] == "dimension" and any(g in info["name"].lower() for g in ("state", "region", "geography")):
                if eid not in matched_dimensions:
                    matched_dimensions.append(eid)
                break

    # Renewable/energy pattern
    if any(e in subject_lower for e in ("renewable", "energy", "power", "potential")):
        for eid, info in entity_map.items():
            if info["type"] == "measure" and any(e in info["name"].lower() for e in ("solar", "wind", "hydro", "biomass", "power", "energy")):
                if eid not in matched_measures:
                    matched_measures.append(eid)

    # Assign results
    # PLFS-specific correction: "average number of years in formal education" is
    # frequently mislinked to Average Weekly Hours because both had generic
    # "Average" aliases. Prefer the education-years measure when explicit.
    if "formal education" in subject_lower or "years in formal education" in subject_lower:
        for eid, info in entity_map.items():
            if info["type"] == "measure" and (
                "education" in info["name"].lower() or any("education" in a.lower() for a in info["aliases"])
            ):
                matched_measures = [eid]
                break

    if any(k in subject_lower for k in ("earning", "earnings", "wage", "salary")):
        for eid, info in entity_map.items():
            if info["type"] == "measure" and (
                "earnings" in info["name"].lower() or any("earnings" in a.lower() or "wage" in a.lower() for a in info["aliases"])
            ):
                matched_measures = [eid]
                break

    if "weekly hours" in subject_lower or "hours per week" in subject_lower:
        for eid, info in entity_map.items():
            if info["type"] == "measure" and "weekly hours" in info["name"].lower():
                matched_measures = [eid]
                break

    result["measureRefs"] = matched_measures[:5]
    if matched_dimensions:
        result["dimensionRef"] = matched_dimensions[0]
    if matched_category:
        result["categoryEntityRef"] = matched_category

    # Confidence based on matches
    total_matches = len(matched_measures) + len(matched_dimensions) + (1 if matched_category else 0)
    if total_matches >= 2:
        result["confidence"] = 0.7
    elif total_matches == 1:
        result["confidence"] = 0.5
    else:
        result["confidence"] = 0.3

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Caption template (value-free)
# ─────────────────────────────────────────────────────────────────────────────


def make_caption_template(subject: str, periodRef: str | None = None) -> str:
    """Create a value-free caption template.

    Allowed: "Coal reserves by reserve category, {{period.current}}"
    Forbidden: "Coal reserves were 400.7 billion tonnes"
    """
    # Strip any leaked values
    template = _DATA_VALUE_RE.sub("", subject).strip()
    template = re.sub(r'\s{2,}', ' ', template)

    if periodRef:
        template += ", {{period.current}}"

    return template


# ─────────────────────────────────────────────────────────────────────────────
# Main compiler
# ─────────────────────────────────────────────────────────────────────────────


def compile_single_figure(
    figure: dict[str, Any],
    tables: list[Any] | None = None,
    entities: list[Any] | None = None,
    sections: list[Any] | None = None,
) -> FigureSemanticModel:
    """Compile one detected figure into a FigureSemanticModel."""
    model = FigureSemanticModel()

    # Basic fields
    fig_id = figure.get("figureId") or figure.get("id") or f"fig_{figure.get('page', 0)}"
    model.figureTemplateId = f"ft_{_slugify(fig_id)}"
    model.figureNumber = figure.get("figureNumber") or figure.get("figure_number")
    model.page = figure.get("page")
    model.sectionRef = figure.get("section_heading") or figure.get("sectionRef")

    # Caption and title
    caption = figure.get("caption") or figure.get("title") or ""
    section_title = figure.get("section_heading") or ""

    # Chart type
    vlm_shape = figure.get("chartType") or figure.get("chart_type") or figure.get("vlm_shape")
    model.chartType = infer_chart_type(vlm_shape, caption, figure.get("questionType"), None)
    model.detectionMethod = "vlm_detection" if vlm_shape else "caption_analysis" if caption else "heuristic"

    # Subject (value-free)
    model.chartSubject = extract_chart_subject(caption, section_title)

    # Value-free guard on caption
    if _DATA_VALUE_RE.search(caption):
        model.diagnostics.append(f"DATA_IN_CAPTION: original caption contained data values (stripped)")

    # Entity linking
    links = link_chart_entities(model.chartSubject, entities, tables)
    panel_semantics = parse_chart_panel_title(caption or model.chartSubject, entities)
    model.categoryEntityRef = links["categoryEntityRef"]
    model.measureRefs = panel_semantics.measureRefs or links["measureRefs"]
    model.dimensionRef = (panel_semantics.dimensionRefs[0] if panel_semantics.dimensionRefs else None) or links["dimensionRef"]
    model.periodRef = links["periodRef"]
    model.panel = panel_semantics.panel or None
    model.filters = panel_semantics.filters
    model.confidence = max(links["confidence"], panel_semantics.confidence)
    if panel_semantics.figureNumber and not model.figureNumber:
        model.figureNumber = panel_semantics.figureNumber

    # Caption template
    model.captionTemplate = make_caption_template(model.chartSubject, model.periodRef)

    # Legend labels from chart type + subject
    if model.chartType == "pie" and model.categoryEntityRef:
        model.legendLabels = []  # Will be populated from category dimension members at render time

    # Axis labels
    if model.chartType in ("bar", "grouped_bar"):
        if model.dimensionRef:
            model.axisLabels["x"] = "{{dimension.name}}"
        if model.measureRefs:
            model.axisLabels["y"] = "{{measure.name}}"

    # Related table (proximity-based)
    if tables and model.page is not None:
        for t in tables:
            t_page = t.page if hasattr(t, "page") else (t.get("page") if isinstance(t, dict) else None)
            t_id = t.tableId if hasattr(t, "tableId") else (t.get("tableId") if isinstance(t, dict) else None)
            if t_page is not None and abs(t_page - model.page) <= 2:
                model.relatedTableId = t_id
                break

    # Source refs
    model.sourceRefs = [{"sourceType": "figure_detection", "page": model.page}]

    return model


def compile_figure_semantics(
    detected_figures: list[dict[str, Any]],
    tables: list[Any] | None = None,
    entities: list[Any] | None = None,
    sections: list[Any] | None = None,
) -> ChartSemanticResult:
    """Compile all detected figures into semantic models.

    Args:
        detected_figures: Raw figure dicts from VLM/LayoutLM detection.
        tables: TableSemanticModel list from E3.
        entities: Enriched entities from E6.
        sections: Section nodes from document structure.

    Returns:
        ChartSemanticResult with compiled figures and diagnostics.
    """
    result = ChartSemanticResult()

    for fig in detected_figures:
        try:
            model = compile_single_figure(fig, tables, entities, sections)
            if model.chartType == "unknown" and not model.chartSubject:
                result.unresolvedFigures.append({
                    "figureId": fig.get("figureId"),
                    "page": fig.get("page"),
                    "reason": "no_type_or_subject",
                })
            else:
                result.figures.append(model)
        except Exception as e:
            result.unresolvedFigures.append({
                "figureId": fig.get("figureId"),
                "page": fig.get("page"),
                "reason": f"compilation_error: {e}",
            })

    result.counts = {
        "input": len(detected_figures),
        "compiled": len(result.figures),
        "unresolved": len(result.unresolvedFigures),
    }
    result.diagnostics.append(
        f"Compiled {len(result.figures)} figures, {len(result.unresolvedFigures)} unresolved"
    )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '_', text.lower().strip()).strip('_')
    return slug[:30] if slug else "unknown"


def _get(obj: Any, attr: str) -> Any:
    if obj is None:
        return None
    if hasattr(obj, attr):
        return getattr(obj, attr)
    if isinstance(obj, dict):
        return obj.get(attr)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: PIB Infographic Semantics + Section-Aware Classification
# ─────────────────────────────────────────────────────────────────────────────

# Extended chart types for PIB press releases
PIB_VISUAL_TYPES = frozenset({
    "infographic_panel",
    "metric_card_panel",
    "visual_summary",
    "mixed_infographic",
})

# All valid chart types (extended with PIB types)
ALL_CHART_TYPES = frozenset({
    "pie", "bar", "grouped_bar", "stacked_bar", "line", "map",
    "infographic_panel", "metric_card_panel", "visual_summary", "mixed_infographic",
    "unknown",
})


def classify_pib_visual_panel(
    figure: dict[str, Any],
    section: Any = None,
    caption: str = "",
    entities: list[Any] | None = None,
) -> tuple[str, float, list[str]]:
    """Classify a PIB visual panel using section context.

    Returns (chart_type, confidence, related_entity_names).

    Classification strategy:
    1. Caption keywords → traditional chart type
    2. Section title keywords → PIB infographic type
    3. No caption + PIB section with expected entities → infographic_panel
    4. BackMatter → visual_summary (lower priority)
    """
    diagnostics: list[str] = []

    # 1. Try caption-based classification first (may override to traditional chart)
    if caption:
        if _PIE_SIGNALS.search(caption) or _STACKED_SIGNALS.search(caption):
            return "pie", 0.75, []
        if _BAR_SIGNALS.search(caption):
            return "bar", 0.75, []
        if _LINE_SIGNALS.search(caption):
            return "line", 0.75, []

    # 2. Section-based classification
    if section is not None:
        title = ""
        expected_ents: list[str] = []
        is_back = False

        if hasattr(section, "title"):
            title = section.title
            expected_ents = section.expectedEntities or []
            is_back = section.isBackMatter
        elif isinstance(section, dict):
            title = section.get("title", "")
            expected_ents = section.get("expectedEntities") or []
            is_back = section.get("isBackMatter", False)

        title_lower = title.lower()

        # BackMatter figures → visual_summary
        if is_back:
            diagnostics.append("backMatter_section")
            return "visual_summary", 0.50, expected_ents[:2]

        # Section keyword → PIB visual type (ORDER MATTERS: specific before generic)
        # Industry/manufacturing BEFORE rate indicators (avoids "ur" substring in "manufacturing")
        if any(k in title_lower for k in ("manufacturing", "industry")):
            diagnostics.append("industry_section")
            return "infographic_panel", 0.70, expected_ents

        if any(k in title_lower for k in ("proportion", "regular wage", "employment status", "status in")):
            diagnostics.append("composition_section")
            return "infographic_panel", 0.70, expected_ents

        # Rate indicators: use word-boundary-safe check (avoid "ur" matching "manufacturing")
        _rate_patterns = [r'\blfpr\b', r'\bwpr\b', r'\bur\b', r'unemployment', r'labour force participation', r'worker population ratio']
        if any(re.search(p, title_lower) for p in _rate_patterns):
            diagnostics.append("rate_indicator_section")
            return "metric_card_panel", 0.72, expected_ents

        if any(k in title_lower for k in ("earning", "wage", "salary", "female worker")):
            diagnostics.append("earnings_section")
            return "metric_card_panel", 0.68, expected_ents

        if any(k in title_lower for k in ("education", "formal", "years")):
            diagnostics.append("education_section")
            return "visual_summary", 0.65, expected_ents

        if any(k in title_lower for k in ("snapshot", "key finding", "highlight")):
            diagnostics.append("snapshot_section")
            return "mixed_infographic", 0.65, expected_ents

        # Has expected entities but no specific match → generic infographic
        if expected_ents:
            diagnostics.append("section_with_entities_fallback")
            return "infographic_panel", 0.60, expected_ents

    # 3. No section or caption → unknown with low confidence
    return "unknown", 0.30, []


def compile_section_graph_figures(
    section_graph: Any,
    entities: list[Any] | None = None,
    doc_type: str = "statistical_annual_report",
) -> ChartSemanticResult:
    """Compile figures from SectionGraph into FigureSemanticModels.

    For PIB press releases, uses section context to classify infographic panels.
    Returns ChartSemanticResult compatible with the existing compiler output.
    """
    result = ChartSemanticResult()

    if section_graph is None:
        return result

    # Get all sections (analytic + backMatter)
    all_sections = []
    if hasattr(section_graph, "sections"):
        all_sections = list(section_graph.sections) + list(section_graph.backMatter)
    elif isinstance(section_graph, dict):
        all_sections = section_graph.get("sections", []) + section_graph.get("backMatter", [])

    # Build entity lookup
    entity_map: dict[str, str] = {}  # lowercase name → entityId
    if entities:
        for ent in entities:
            name = (_get(ent, "canonicalName") or _get(ent, "name") or "").lower()
            eid = _get(ent, "entityId") or ""
            if name and eid:
                entity_map[name] = eid
                for alias in (_get(ent, "aliases") or []):
                    if alias:
                        entity_map[alias.lower()] = eid

    fig_counter = 0
    for section in all_sections:
        sec_id = section.sectionId if hasattr(section, "sectionId") else section.get("sectionId", "")
        sec_title = section.title if hasattr(section, "title") else section.get("title", "")
        figure_regions = section.figureRegions if hasattr(section, "figureRegions") else section.get("figureRegions", [])

        for fig_region in figure_regions:
            fig_counter += 1
            page = fig_region.get("page") if isinstance(fig_region, dict) else getattr(fig_region, "page", None)
            caption = fig_region.get("text", "") if isinstance(fig_region, dict) else ""

            # Classify using section context
            chart_type, confidence, related_ent_names = classify_pib_visual_panel(
                figure=fig_region,
                section=section,
                caption=caption,
                entities=entities,
            )

            # Resolve entity names to IDs
            measure_refs: list[str] = []
            dimension_ref: str | None = None
            category_ref: str | None = None

            for ent_name in related_ent_names:
                eid = entity_map.get(ent_name.lower(), "")
                if not eid:
                    # Partial match
                    for k, v in entity_map.items():
                        if ent_name.lower() in k or k in ent_name.lower():
                            eid = v
                            break
                if eid:
                    # Determine role from entity type
                    ent_obj = next((e for e in (entities or []) if (_get(e, "entityId") or "") == eid), None)
                    etype = _get(ent_obj, "entityType") if ent_obj else ""
                    if etype == "measure":
                        if eid not in measure_refs:
                            measure_refs.append(eid)
                    elif etype == "dimension":
                        if not dimension_ref:
                            dimension_ref = eid
                        elif not category_ref:
                            category_ref = eid

            # Build FigureSemanticModel
            fig_id = f"sg_fig_{fig_counter:02d}"
            subject = extract_chart_subject(caption, sec_title)

            model = FigureSemanticModel(
                figureTemplateId=f"ft_{_slugify(fig_id)}",
                page=page,
                chartType=chart_type,
                chartSubject=subject,
                categoryEntityRef=category_ref,
                measureRefs=measure_refs,
                dimensionRef=dimension_ref,
                captionTemplate=make_caption_template(subject),
                detectionMethod="section_graph",
                confidence=confidence,
                sectionRef=sec_id,
            )
            result.figures.append(model)

    result.counts = {
        "input": fig_counter,
        "compiled": len(result.figures),
        "unresolved": len(result.unresolvedFigures),
        "pib_panels": sum(1 for f in result.figures if f.chartType in PIB_VISUAL_TYPES),
    }
    result.diagnostics.append(
        f"SectionGraph: {len(result.figures)} figures compiled "
        f"({result.counts['pib_panels']} PIB panels)"
    )

    return result
