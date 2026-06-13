"""Entity Deduplicator — merges duplicate entities across pages.

Entities may appear on multiple pages (e.g., "State" in table headers on pages 3, 5, 7).
This module consolidates them into unique entries, boosting confidence for
entities confirmed across multiple sources.
"""
from __future__ import annotations

import logging
from difflib import SequenceMatcher

from ast_core.schema import TemplateEntity

logger = logging.getLogger(__name__)

# Similarity threshold for fuzzy dedup (0.0-1.0)
_SIMILARITY_THRESHOLD = 0.85


def deduplicate_entities(entities: list[TemplateEntity]) -> list[TemplateEntity]:
    """Deduplicate entities, merging duplicates and boosting confidence.

    Strategy:
      1. Exact name match (case-insensitive) → merge immediately
      2. Fuzzy name match (>85% similar) → merge if same entity type
      3. Merge: keep highest confidence, collect all aliases, track all pages

    Returns:
        Deduplicated list with consolidated confidence scores.
    """
    if not entities:
        return []

    # Group by normalized name
    groups: dict[str, list[TemplateEntity]] = {}
    for ent in entities:
        key = ent.name.lower().strip()
        groups.setdefault(key, []).append(ent)

    # Merge exact matches
    merged: list[TemplateEntity] = []
    used_keys: set[str] = set()

    for key, group in groups.items():
        if key in used_keys:
            continue
        used_keys.add(key)
        merged.append(_merge_group(group))

    # Fuzzy dedup pass
    final: list[TemplateEntity] = []
    consumed: set[int] = set()

    for i, ent_a in enumerate(merged):
        if i in consumed:
            continue

        merge_candidates = [ent_a]

        for j, ent_b in enumerate(merged[i + 1:], start=i + 1):
            if j in consumed:
                continue
            if ent_a.entityType != ent_b.entityType:
                continue
            similarity = _name_similarity(ent_a.name, ent_b.name)
            if similarity >= _SIMILARITY_THRESHOLD:
                merge_candidates.append(ent_b)
                consumed.add(j)

        consumed.add(i)
        final.append(_merge_group(merge_candidates))

    # Re-assign entity IDs
    for idx, ent in enumerate(final):
        ent.entityId = f"ent_{idx + 1:04d}"

    logger.info("Deduplicated %d → %d entities", len(entities), len(final))
    return final


def _merge_group(group: list[TemplateEntity]) -> TemplateEntity:
    """Merge a group of duplicate entities into one."""
    if len(group) == 1:
        return group[0]

    # Pick the one with highest confidence as base
    base = max(group, key=lambda e: e.confidence)

    # Boost confidence: entity confirmed across multiple sources
    source_types = set(e.sourceType for e in group)
    pages = set(e.pageIndex for e in group if e.pageIndex >= 0)

    # Multi-source confirmation boost: +0.05 per additional source type
    confirmation_boost = min(0.15, (len(source_types) - 1) * 0.05)
    boosted_confidence = min(1.0, base.confidence + confirmation_boost)

    # Collect all aliases
    all_aliases: set[str] = set()
    for e in group:
        all_aliases.update(e.aliases)
        if e.name.lower() != base.name.lower():
            all_aliases.add(e.name)
    all_aliases.discard(base.name)

    # Richest source context
    best_context = max(group, key=lambda e: len(e.sourceContext)).sourceContext

    return TemplateEntity(
        entityId=base.entityId,
        name=base.name,
        entityType=base.entityType,
        sourceType=base.sourceType,
        confidence=boosted_confidence,
        aliases=sorted(all_aliases),
        pageIndex=min(pages) if pages else -1,
        sourceContext=best_context,
    )


def _name_similarity(a: str, b: str) -> float:
    """Compute string similarity ratio (0.0-1.0)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ---------------------------------------------------------------------------
# Scoped dedup (Step 5: topic-scoped with cross-refs for GEO/TIME)
# ---------------------------------------------------------------------------

_GLOBAL_ENTITY_TYPES = frozenset({"geo", "time", "temporal", "geographic", "location"})


def deduplicate_entities_scoped(
    entities: list[TemplateEntity],
    topic_map: dict[str, list[str]] | None = None,
    similarity_threshold: float | None = None,
) -> list[TemplateEntity]:
    """Scope-aware dedup: dedup within each topic, cross-ref GEO/TIME globally.

    Args:
        entities: Raw extracted entities (may have .scope set or not)
        topic_map: mapping of topic_id -> list of page indices.
                   If provided, entities are assigned to topics by pageIndex.
        similarity_threshold: override the default fuzzy match threshold

    Returns:
        Deduplicated, scoped entities with crossRefs populated for global types.
    """
    threshold = similarity_threshold or _SIMILARITY_THRESHOLD

    if not entities:
        return []

    # Assign scopes based on topic_map if entities don't have scope set
    if topic_map:
        page_to_topic: dict[int, str] = {}
        for tid, pages in topic_map.items():
            for p in pages:
                page_to_topic[int(p)] = tid
        for ent in entities:
            if not ent.scope and ent.pageIndex >= 0:
                ent.scope = page_to_topic.get(ent.pageIndex, "global")
            elif not ent.scope:
                ent.scope = "global"

    # Group by scope
    scope_groups: dict[str, list[TemplateEntity]] = {}
    for ent in entities:
        scope_groups.setdefault(ent.scope or "global", []).append(ent)

    # Dedup within each scope independently
    all_deduped: list[TemplateEntity] = []
    for scope, group in scope_groups.items():
        deduped = deduplicate_entities(group)
        for ent in deduped:
            ent.scope = scope
        all_deduped.extend(deduped)

    # Assign temporary unique IDs before cross-ref pass
    for idx, ent in enumerate(all_deduped):
        ent.entityId = f"ent_{idx + 1:04d}"

    # Cross-ref pass: link GEO/TIME entities across scopes
    global_types = [e for e in all_deduped if e.entityType.lower() in _GLOBAL_ENTITY_TYPES]
    for ent in global_types:
        for other in global_types:
            if other.entityId == ent.entityId:
                continue
            if other.scope == ent.scope:
                continue
            sim = _name_similarity(ent.name, other.name)
            if sim >= threshold and other.entityId not in ent.crossRefs:
                ent.crossRefs.append(other.entityId)

    logger.info(
        "Scoped dedup: %d → %d entities across %d scopes, %d cross-refs",
        len(entities), len(all_deduped), len(scope_groups),
        sum(len(e.crossRefs) for e in all_deduped),
    )
    return all_deduped
