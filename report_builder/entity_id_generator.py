"""E5 — Semantic Entity ID Generator.

Assigns stable, human-readable, semantic IDs to clean entities.

Replaces sequential ent_001, ent_002 with meaningful slugs:
    ent_proved_reserves
    ent_state_ut
    ent_distribution_percent
    ent_lfpr

IDs are:
- Semantic: human-readable, debuggable
- Stable: same concept → same ID across reruns
- Unique: no collisions within one blueprint
- Deterministic: computed from canonical name + type

Usage:
    from report_builder.entity_id_generator import assign_entity_ids, generate_entity_id
    entities = assign_entity_ids(semantic_entities)
"""
from __future__ import annotations

import re
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Known MoSPI indicator abbreviations
# ─────────────────────────────────────────────────────────────────────────────

MOSPI_ABBREVIATIONS: dict[str, str] = {
    "labour force participation rate": "lfpr",
    "worker population ratio": "wpr",
    "unemployment rate": "ur",
    "gross domestic product": "gdp",
    "consumer price index": "cpi",
    "wholesale price index": "wpi",
    "gross value added": "gva",
    "net national income": "nni",
    "human development index": "hdi",
    "total fertility rate": "tfr",
    "infant mortality rate": "imr",
    "per capita income": "pci",
    "gross fixed capital formation": "gfcf",
    "compound annual growth rate": "cagr",
    "net domestic product": "ndp",
    "gross national income": "gni",
    "personal disposable income": "pdi",
}

# ─────────────────────────────────────────────────────────────────────────────
# Core ID generation
# ─────────────────────────────────────────────────────────────────────────────


def detect_known_indicator(name: str) -> str | None:
    """Check if name matches a known MoSPI indicator → abbreviation.

    Returns abbreviation string or None.
    """
    name_lower = name.lower().strip()
    return MOSPI_ABBREVIATIONS.get(name_lower)


def slugify_entity_name(name: str) -> str:
    """Convert entity canonical name to a URL-safe slug.

    Rules:
    - Lowercase
    - Remove parenthetical content: "Distribution (%)" → "distribution"
    - Replace % with "percent"
    - Replace / - spaces with _
    - Remove non-alphanumeric except _
    - Collapse multiple underscores
    - Max 40 chars
    - Strip leading/trailing _
    """
    if not name:
        return "unknown"

    slug = name.strip()

    # Handle special patterns BEFORE removing parens
    slug = slug.replace("(%)", "percent")
    slug = slug.replace("%", "percent")

    # Remove other parenthetical content (units go to unit field, not ID)
    slug = re.sub(r'\([^)]*\)', '', slug)

    # Lowercase
    slug = slug.lower()

    # Replace separators with _
    slug = slug.replace("/", "_").replace("-", "_").replace(" ", "_")

    # Handle States/UTs special case
    slug = re.sub(r'states?_*u?t?s?', 'state_ut', slug)

    # Remove non-alphanumeric except _
    slug = re.sub(r'[^a-z0-9_]', '', slug)

    # Collapse underscores
    slug = re.sub(r'_+', '_', slug)

    # Strip edges
    slug = slug.strip('_')

    # Max length
    if len(slug) > 40:
        slug = slug[:40].rstrip('_')

    return slug or "unknown"


def generate_entity_id(
    canonical_name: str,
    entity_type: str = "",
    context: dict[str, Any] | None = None,
) -> str:
    """Generate a semantic entity ID from canonical name.

    Examples:
        "Proved Reserves" → "ent_proved_reserves"
        "States/UTs" → "ent_state_ut"
        "Distribution (%)" → "ent_distribution_percent"
        "Labour Force Participation Rate" → "ent_lfpr"
        "Solar Energy" → "ent_solar_energy"
        "Year/Period" → "ent_period"
    """
    # Check known abbreviation first
    abbrev = detect_known_indicator(canonical_name)
    if abbrev:
        return f"ent_{abbrev}"

    # Special time entity
    name_lower = canonical_name.lower().strip()
    if entity_type == "time" or name_lower in ("period", "year", "year/period", "survey period", "time"):
        return "ent_period"

    # Slugify
    slug = slugify_entity_name(canonical_name)
    return f"ent_{slug}"


def generate_topic_id(title: str) -> str:
    """Generate a semantic topic ID.

    "Energy Reserves and Potential" → "topic_energy_reserves_potential"
    "Coal Reserves" → "topic_coal_reserves"
    """
    slug = title.lower().strip()
    # Remove common stopwords
    for stop in ("and", "the", "of", "in", "for", "a", "an"):
        slug = re.sub(rf'\b{stop}\b', '', slug)
    slug = re.sub(r'[^a-z0-9]+', '_', slug).strip('_')
    slug = re.sub(r'_+', '_', slug)
    if len(slug) > 40:
        slug = slug[:40].rstrip('_')
    return f"topic_{slug}" if slug else "topic_unknown"


def generate_question_id(intent: str, source_table: str | None = None) -> str:
    """Generate a semantic question ID from intent.

    "Compare proved reserves across States/UTs" → "q_proved_reserves_state"
    """
    slug = intent.lower().strip()
    # Remove question words and common verbs
    for word in ("compare", "what", "how", "which", "show", "list", "describe",
                 "is", "are", "the", "of", "in", "for", "across", "by", "does", "do"):
        slug = re.sub(rf'\b{word}\b', '', slug)
    slug = re.sub(r'[^a-z0-9]+', '_', slug).strip('_')
    slug = re.sub(r'_+', '_', slug)
    if len(slug) > 35:
        slug = slug[:35].rstrip('_')
    return f"q_{slug}" if slug else "q_unknown"


def generate_table_template_id(title: str) -> str:
    """Generate table template ID from table title.

    "Statewise Estimated Reserves of Coal" → "tt_coal_reserves_state"
    """
    slug = title.lower().strip()
    for stop in ("statewise", "estimated", "of", "the", "in", "for", "a", "and"):
        slug = re.sub(rf'\b{stop}\b', '', slug)
    slug = re.sub(r'[^a-z0-9]+', '_', slug).strip('_')
    slug = re.sub(r'_+', '_', slug)
    if len(slug) > 35:
        slug = slug[:35].rstrip('_')
    return f"tt_{slug}" if slug else "tt_unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Batch assignment
# ─────────────────────────────────────────────────────────────────────────────


def assign_entity_ids(
    entities: list[Any],
    previous_blueprint: dict[str, Any] | None = None,
) -> list[Any]:
    """Assign semantic IDs to all entities. Handles collisions.

    Args:
        entities: List of SemanticEntity objects or dicts with canonicalName/entityType.
        previous_blueprint: Optional previous blueprint for ID stability.

    Returns:
        Same list with entityId populated.
    """
    # Build previous ID map for stability
    prev_map: dict[str, str] = {}
    if previous_blueprint:
        for ent in (previous_blueprint.get("entities") or []):
            name = (ent.get("canonicalName") or "").lower().strip()
            etype = ent.get("entityType") or ""
            eid = ent.get("entityId") or ""
            if name and eid and not re.match(r'^ent_\d{2,}$', eid):
                prev_map[f"{name}|{etype}"] = eid

    used_ids: set[str] = set()

    for entity in entities:
        # Support both SemanticEntity objects and dicts
        if hasattr(entity, "canonicalName"):
            name = entity.canonicalName
            etype = entity.entityType or ""
        else:
            name = entity.get("canonicalName") or entity.get("name") or ""
            etype = entity.get("entityType") or ""

        # Check previous mapping for stability
        prev_key = f"{name.lower().strip()}|{etype}"
        if prev_key in prev_map:
            eid = prev_map[prev_key]
        else:
            eid = generate_entity_id(name, etype)

        # Handle collision
        base_eid = eid
        counter = 2
        while eid in used_ids:
            eid = f"{base_eid}_{counter}"
            counter += 1

        used_ids.add(eid)

        # Assign
        if hasattr(entity, "entityId"):
            entity.entityId = eid
        elif isinstance(entity, dict):
            entity["entityId"] = eid

    return entities
