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

    for eid, info in entity_map.items():
        name_lower = info["name"].lower()
        etype = info["type"]

        # Check if entity name appears in subject
        if name_lower and (name_lower in subject_lower or any(a.lower() in subject_lower for a in info["aliases"] if a)):
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
    model.categoryEntityRef = links["categoryEntityRef"]
    model.measureRefs = links["measureRefs"]
    model.dimensionRef = links["dimensionRef"]
    model.periodRef = links["periodRef"]
    model.confidence = links["confidence"]

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
