"""Entity Slot Extraction Engine — extracts parameterizable slots from AST.

Given an Enterprise Document AST, identifies entities (organizations, metrics,
time periods, demographics) and creates template slots that can be filled
with new values to regenerate reports for different contexts.

Example:
    Entity: "India" (type=location)
    Slot: {slotId: "country", entityRef: "e_india", slotType: "label",
           currentValue: "India", description: "Target country for analysis"}

    When regenerating: replace "India" with "Brazil" → new report, same structure.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from report_builder.ast_schema import (
    Entity,
    EnterpriseDocumentAST,
    Fact,
    TemplateSlot,
)

logger = logging.getLogger(__name__)

# ─── Entity detection patterns ────────────────────────────────────────────────

_METRIC_PATTERNS = [
    # Percentages: "2.90%", "55%"
    re.compile(r'\b(\d{1,3}(?:\.\d{1,2})?)\s*%'),
    # Money: "₹1,234 crore", "$5.4 billion"
    re.compile(r'[₹$€£]\s*[\d,]+(?:\.\d+)?\s*(?:crore|billion|million|lakh|thousand)?', re.IGNORECASE),
    # Large numbers with units: "400.7 billion tonnes", "1,073.01 BCM"
    re.compile(r'(\d[\d,]*\.?\d*)\s*(billion|million|MW|GW|BCM|tonnes|MT|km|sq\.?\s*km)', re.IGNORECASE),
    # Year references: "2024-25", "FY2025"
    re.compile(r'(?:FY|fy)?\s*20\d{2}(?:-\d{2})?'),
    # Date: "01-04-2025", "March 31, 2025"
    re.compile(r'\d{1,2}[-/]\d{1,2}[-/]\d{4}'),
    re.compile(r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}', re.IGNORECASE),
]

_ORG_INDICATORS = [
    "Ministry", "Department", "Commission", "Corporation", "Authority",
    "Bureau", "Council", "Board", "Institute", "Survey", "Organisation",
    "Government", "Ltd", "Limited", "Inc", "IREDA", "MNRE", "GSI",
]

_DEMOGRAPHIC_INDICATORS = [
    "rural", "urban", "male", "female", "age group", "population",
    "household", "worker", "labour force", "employed", "unemployed",
    "literacy", "scheduled", "tribe", "caste",
]


def extract_entities_from_ast(ast: EnterpriseDocumentAST) -> list[Entity]:
    """Extract entities from content AST paragraphs.

    Scans all paragraphs and tables for:
        - Organizations (Ministry of X, Department of Y)
        - Metrics (percentages, large numbers with units)
        - Time periods (fiscal years, dates)
        - Locations (states, regions, countries)
        - Demographics (population groups)
    """
    entities: list[Entity] = []
    seen_names: set[str] = set()
    entity_counter = 0

    # ── Extract from paragraphs ──
    for para in ast.contentAST.paragraphs:
        text = para.content
        if not text:
            continue

        # Organizations
        for indicator in _ORG_INDICATORS:
            if indicator.lower() in text.lower():
                # Try to extract the full org name
                pattern = re.compile(
                    rf'(?:the\s+)?(\w[\w\s]{{0,40}}{re.escape(indicator)}[\w\s]{{0,20}}?)(?:\s*[\(,\.])',
                    re.IGNORECASE,
                )
                for match in pattern.finditer(text):
                    name = match.group(1).strip()
                    if name.lower() not in seen_names and len(name) > 5:
                        entity_counter += 1
                        entities.append(Entity(
                            entityId=f"e_{entity_counter:03d}",
                            type="org",
                            name=name,
                            context=text[:100],
                            mentions=[para.id],
                        ))
                        seen_names.add(name.lower())

        # Metrics (large numbers with units)
        for pattern in _METRIC_PATTERNS[:3]:
            for match in pattern.finditer(text):
                value = match.group(0).strip()
                if value and value not in seen_names:
                    entity_counter += 1
                    entities.append(Entity(
                        entityId=f"e_{entity_counter:03d}",
                        type="metric",
                        name=value,
                        context=text[max(0, match.start() - 30):match.end() + 50],
                        mentions=[para.id],
                    ))
                    seen_names.add(value)

        # Time periods
        for pattern in _METRIC_PATTERNS[3:]:
            for match in pattern.finditer(text):
                value = match.group(0).strip()
                if value and value not in seen_names:
                    entity_counter += 1
                    entities.append(Entity(
                        entityId=f"e_{entity_counter:03d}",
                        type="time",
                        name=value,
                        context=text[max(0, match.start() - 20):match.end() + 30],
                        mentions=[para.id],
                    ))
                    seen_names.add(value)

    logger.info("[entity-extract] Found %d entities from %d paragraphs",
                len(entities), len(ast.contentAST.paragraphs))
    return entities


def generate_template_slots(
    ast: EnterpriseDocumentAST,
    entities: list[Entity] | None = None,
) -> list[TemplateSlot]:
    """Generate template slots from entities for report parameterization.

    Each slot represents a value that can be swapped to regenerate the report
    for a different context (different year, country, organization, etc.).
    """
    if entities is None:
        entities = extract_entities_from_ast(ast)

    slots: list[TemplateSlot] = []
    slot_counter = 0

    for entity in entities:
        # Determine slot type based on entity type
        if entity.type == "metric":
            slot_type = "value"
            description = f"Numeric metric: {entity.context[:80]}"
        elif entity.type == "time":
            slot_type = "date"
            description = f"Time reference that changes each reporting period"
        elif entity.type == "org":
            slot_type = "label"
            description = f"Organization name referenced in the report"
        elif entity.type == "demographic":
            slot_type = "enum"
            description = f"Population segment or category"
        else:
            slot_type = "label"
            description = f"Entity: {entity.name}"

        slot_counter += 1
        slots.append(TemplateSlot(
            slotId=f"slot_{slot_counter:03d}",
            entityRef=entity.entityId,
            slotType=slot_type,
            currentValue=entity.name,
            description=description,
        ))

    # Add special slots for common parameterizable elements
    # Title slot
    if ast.metadata.title:
        slot_counter += 1
        slots.append(TemplateSlot(
            slotId=f"slot_{slot_counter:03d}",
            entityRef="metadata",
            slotType="label",
            currentValue=ast.metadata.title,
            description="Document title — changes per edition/version",
        ))

    # Table title slots
    for table in ast.tableAST.tables:
        if table.title:
            slot_counter += 1
            slots.append(TemplateSlot(
                slotId=f"slot_{slot_counter:03d}",
                entityRef=table.tableId,
                slotType="label",
                currentValue=table.title,
                description=f"Table title containing time-varying references",
            ))

    logger.info("[entity-extract] Generated %d template slots", len(slots))
    return slots


def generate_facts_from_content(ast: EnterpriseDocumentAST) -> list[Fact]:
    """Extract verifiable facts from content paragraphs.

    A fact is a statement containing a metric linked to an entity,
    which can be verified against source data.
    """
    facts: list[Fact] = []
    fact_counter = 0

    for para in ast.contentAST.paragraphs:
        text = para.content
        if not text or para.type in ("title", "subtitle", "heading", "chapter_heading"):
            continue

        # A fact-worthy paragraph contains at least one number
        has_number = bool(re.search(r'\d+\.?\d*', text))
        if not has_number:
            continue

        # Check if it's a substantive statement (not too short, not a heading)
        if len(text) < 50:
            continue

        fact_counter += 1
        facts.append(Fact(
            factId=f"fact_{fact_counter:03d}",
            statement=text[:300],
            entityRefs=[],  # Will be linked in post-processing
            sourceRef=para.id,
            confidence=0.8,
        ))

    logger.info("[entity-extract] Extracted %d facts", len(facts))
    return facts


def enrich_ast_with_entities(ast_dict: dict[str, Any]) -> dict[str, Any]:
    """Take a raw AST dict, validate it, extract entities/slots/facts, and return enriched AST.

    This is the main entry point for Phase 2 entity enrichment.
    """
    # Validate incoming AST
    validated = EnterpriseDocumentAST.model_validate(ast_dict)

    # Extract entities
    entities = extract_entities_from_ast(validated)

    # Generate slots
    slots = generate_template_slots(validated, entities)

    # Extract facts
    facts = generate_facts_from_content(validated)

    # Update the AST
    validated.entityGraph.entities = entities
    validated.templateSlots.slots = slots
    validated.factGraph.facts = facts

    # Return as dict
    result = validated.model_dump()
    logger.info(
        "[entity-extract] ✓ Enriched AST: %d entities, %d slots, %d facts",
        len(entities), len(slots), len(facts),
    )
    return result
