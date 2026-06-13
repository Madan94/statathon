"""Entity Extractor — mines entities from all VLM page sources.

Extracts entities from 7 source types:
  1. Table headers (highest confidence)
  2. Chart axis labels
  3. Chart legends
  4. Section headings
  5. Narrative bold/key terms
  6. Footnotes/source citations
  7. Formula variables (lowest confidence)

Each entity is classified and confidence-ranked by source type.
"""
from __future__ import annotations

import re
import logging
from typing import Any

from ast_core.schema import TemplateEntity, ENTITY_SOURCE_TYPES
from template_engine.vlm.schemas import VLMPageResult, VLMEntity, VLMRegion
from template_engine.extraction.entity_classifier import classify_entity_type

logger = logging.getLogger(__name__)

# Confidence multipliers by source type (higher = more trustworthy)
_SOURCE_CONFIDENCE: dict[str, float] = {
    "table_header": 1.0,
    "chart_axis": 0.95,
    "chart_legend": 0.90,
    "section_heading": 0.80,
    "narrative_term": 0.70,
    "footnote": 0.60,
    "formula_variable": 0.55,
}

# Noise terms to filter out
_NOISE_TERMS = frozenset({
    "table", "figure", "chart", "source", "note", "notes", "total",
    "sl", "no", "sr", "page", "contd", "contd.", "annexure",
    "all india", "india", "the", "and", "for", "of", "in", "to",
})

_MIN_ENTITY_LENGTH = 2
_MAX_ENTITY_LENGTH = 80


def extract_entities(pages: list[VLMPageResult]) -> list[TemplateEntity]:
    """Extract and classify entities from all VLM page results.

    Args:
        pages: List of VLMPageResult from VLM extraction.

    Returns:
        List of TemplateEntity objects, deduplicated and confidence-ranked.
    """
    raw_entities: list[TemplateEntity] = []
    entity_counter = 0

    for page in pages:
        # 1. Entities already identified by VLM
        for vlm_ent in page.entities:
            if not _is_valid_entity_name(vlm_ent.name):
                continue
            entity_counter += 1
            raw_entities.append(TemplateEntity(
                entityId=f"ent_{entity_counter:04d}",
                name=vlm_ent.name.strip(),
                entityType=vlm_ent.entityType or classify_entity_type(vlm_ent.name, vlm_ent.sourceType),
                sourceType=vlm_ent.sourceType,
                confidence=vlm_ent.confidence * _SOURCE_CONFIDENCE.get(vlm_ent.sourceType, 0.7),
                aliases=[],
                pageIndex=page.pageIndex,
                sourceContext=vlm_ent.context,
            ))

        # 2. Additional entity mining from table headers
        for table in page.tables:
            for header in table.headers:
                name = _clean_entity_name(header)
                if not _is_valid_entity_name(name):
                    continue
                # Skip if VLM already captured this
                if _already_captured(name, raw_entities, page.pageIndex):
                    continue
                entity_counter += 1
                raw_entities.append(TemplateEntity(
                    entityId=f"ent_{entity_counter:04d}",
                    name=name,
                    entityType=classify_entity_type(name, "table_header"),
                    sourceType="table_header",
                    confidence=_SOURCE_CONFIDENCE["table_header"] * 0.85,
                    aliases=[header.strip()] if header.strip() != name else [],
                    pageIndex=page.pageIndex,
                    sourceContext=f"Table header: {header}",
                ))

        # 3. Chart axis/legend entities
        for chart in page.charts:
            for axis_name in [chart.xAxis, chart.yAxis]:
                name = _clean_entity_name(axis_name)
                if not _is_valid_entity_name(name):
                    continue
                if _already_captured(name, raw_entities, page.pageIndex):
                    continue
                entity_counter += 1
                source_type = "chart_axis"
                raw_entities.append(TemplateEntity(
                    entityId=f"ent_{entity_counter:04d}",
                    name=name,
                    entityType=classify_entity_type(name, source_type),
                    sourceType=source_type,
                    confidence=_SOURCE_CONFIDENCE[source_type] * 0.85,
                    pageIndex=page.pageIndex,
                    sourceContext=f"Chart axis: {axis_name}",
                ))

            for legend_item in chart.legendItems:
                name = _clean_entity_name(legend_item)
                if not _is_valid_entity_name(name):
                    continue
                if _already_captured(name, raw_entities, page.pageIndex):
                    continue
                entity_counter += 1
                raw_entities.append(TemplateEntity(
                    entityId=f"ent_{entity_counter:04d}",
                    name=name,
                    entityType="dimension",
                    sourceType="chart_legend",
                    confidence=_SOURCE_CONFIDENCE["chart_legend"] * 0.85,
                    pageIndex=page.pageIndex,
                    sourceContext=f"Chart legend: {legend_item}",
                ))

        # 4. Heading-based entity mining
        for region in page.regions:
            if region.role in ("heading_h1", "heading_h2", "title"):
                heading_entities = _extract_from_heading(region, page.pageIndex, entity_counter)
                for ent in heading_entities:
                    if not _already_captured(ent.name, raw_entities, page.pageIndex):
                        entity_counter += 1
                        ent.entityId = f"ent_{entity_counter:04d}"
                        raw_entities.append(ent)

        # 5. Footnote/formula entities
        for region in page.regions:
            if region.role == "footnote":
                footnote_entities = _extract_from_footnote(region, page.pageIndex, entity_counter)
                for ent in footnote_entities:
                    if not _already_captured(ent.name, raw_entities, page.pageIndex):
                        entity_counter += 1
                        ent.entityId = f"ent_{entity_counter:04d}"
                        raw_entities.append(ent)
            elif region.role == "formula":
                formula_entities = _extract_from_formula(region, page.pageIndex, entity_counter)
                for ent in formula_entities:
                    if not _already_captured(ent.name, raw_entities, page.pageIndex):
                        entity_counter += 1
                        ent.entityId = f"ent_{entity_counter:04d}"
                        raw_entities.append(ent)

    logger.info("Extracted %d raw entities from %d pages", len(raw_entities), len(pages))
    return raw_entities


def _clean_entity_name(raw: str) -> str:
    """Normalize entity name."""
    name = raw.strip()
    # Remove common suffixes like (₹), (%), (lakhs)
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    # Remove leading numbers/dots (e.g., "3.1 Overview")
    name = re.sub(r"^\d+[\.\)]\s*", "", name)
    return name.strip()


def _is_valid_entity_name(name: str) -> bool:
    """Filter noise and invalid entity names."""
    if not name or len(name) < _MIN_ENTITY_LENGTH or len(name) > _MAX_ENTITY_LENGTH:
        return False
    if name.lower() in _NOISE_TERMS:
        return False
    # Skip purely numeric
    if re.match(r"^[\d\s,.\-₹%]+$", name):
        return False
    return True


def _already_captured(name: str, entities: list[TemplateEntity], page_index: int) -> bool:
    """Check if entity already extracted (case-insensitive)."""
    name_lower = name.lower().strip()
    for e in entities:
        if e.name.lower().strip() == name_lower:
            return True
    return False


def _extract_from_heading(region: VLMRegion, page_index: int,
                          counter: int) -> list[TemplateEntity]:
    """Extract potential entities from section headings."""
    entities: list[TemplateEntity] = []
    text = region.text.strip()

    # Split by common separators: "by", "vs", "and", ":"
    parts = re.split(r"\s+(?:by|vs\.?|and|&|:)\s+", text, flags=re.IGNORECASE)

    for part in parts:
        name = _clean_entity_name(part)
        if _is_valid_entity_name(name) and len(name) > 3:
            entities.append(TemplateEntity(
                entityId="",  # will be assigned by caller
                name=name,
                entityType=classify_entity_type(name, "section_heading"),
                sourceType="section_heading",
                confidence=_SOURCE_CONFIDENCE["section_heading"] * 0.8,
                pageIndex=page_index,
                sourceContext=f"Heading: {text}",
            ))

    return entities


def _extract_from_footnote(region: VLMRegion, page_index: int,
                           counter: int) -> list[TemplateEntity]:
    """Extract source references from footnotes."""
    entities: list[TemplateEntity] = []
    text = region.text.strip()

    # Look for "Source: NSSO 68th Round" patterns
    source_match = re.search(r"source\s*:\s*(.+?)(?:\.|$)", text, re.IGNORECASE)
    if source_match:
        name = source_match.group(1).strip()[:60]
        if _is_valid_entity_name(name):
            entities.append(TemplateEntity(
                entityId="",
                name=name,
                entityType="metadata",
                sourceType="footnote",
                confidence=_SOURCE_CONFIDENCE["footnote"] * 0.8,
                pageIndex=page_index,
                sourceContext=f"Footnote: {text}",
            ))

    return entities


def _extract_from_formula(region: VLMRegion, page_index: int,
                          counter: int) -> list[TemplateEntity]:
    """Extract variable names from formula blocks."""
    entities: list[TemplateEntity] = []
    text = region.text.strip()

    # Look for "Where X = description" patterns
    var_matches = re.findall(
        r"(?:where|let)\s+(\w+)\s*(?:=|is|denotes)\s*(.+?)(?:,|;|\.|$)",
        text, re.IGNORECASE
    )
    for var_name, description in var_matches:
        desc_clean = description.strip()[:50]
        if len(var_name) >= 1 and len(desc_clean) > 3:
            entities.append(TemplateEntity(
                entityId="",
                name=desc_clean,
                entityType="measure",
                sourceType="formula_variable",
                confidence=_SOURCE_CONFIDENCE["formula_variable"] * 0.8,
                aliases=[var_name],
                pageIndex=page_index,
                sourceContext=f"Formula: {var_name} = {desc_clean}",
            ))

    return entities
