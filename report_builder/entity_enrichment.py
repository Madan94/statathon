"""E6 — Alias & ValueDomain Enrichment.

Takes normalized entities (E2) + table semantics (E3) + statistical context (E4)
and enriches entities so binder resolver has strong matching material.

Adds:
- Useful aliases (canonical variants, physical columns, glossary, domain)
- Alias scope (global vs table_local vs domain_local)
- Negative alias guard (rejects/scopes dangerous generic aliases)
- ValueDomain inference (ratio, categorical, ordinal, count)
- Aggregation hints
- Format hints

Usage:
    from report_builder.entity_enrichment import enrich_entities
    result = enrich_entities(normalized_entities, table_structures, context, families)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from report_builder.entity_id_generator import MOSPI_ABBREVIATIONS


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class AliasCandidate:
    alias: str = ""
    source: str = ""
    scope: str = "global"
    tableId: str | None = None
    score: float = 0.5
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"alias": self.alias, "source": self.source, "scope": self.scope, "score": self.score}
        if self.tableId:
            d["tableId"] = self.tableId
        return d


@dataclass
class ValueDomainResult:
    kind: str = "open"
    members: list[str] | str = field(default_factory=list)
    expectedCardinality: int | None = None
    min: float | None = None
    max: float | None = None
    format: str | None = None
    allowOther: bool = True
    confidence: float = 0.5
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind}
        if isinstance(self.members, list) and self.members:
            d["members"] = list(self.members)
        elif self.members == "open":
            d["members"] = "open"
        if self.expectedCardinality is not None:
            d["expectedCardinality"] = self.expectedCardinality
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.format:
            d["format"] = self.format
        if not self.allowOther:
            d["allowOther"] = False
        return d


@dataclass
class EntityEnrichmentResult:
    entities: list[Any] = field(default_factory=list)
    aliasStats: dict[str, int] = field(default_factory=dict)
    domainStats: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"entityCount": len(self.entities), "aliasStats": self.aliasStats, "domainStats": self.domainStats, "diagnostics": self.diagnostics}


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_GENERIC_ALIASES = frozenset({
    "total", "value", "data", "energy", "potential", "distribution",
    "state", "year", "period", "type", "source", "category",
    "number", "count", "amount", "share", "rate", "index",
    "name", "area", "level", "status", "class", "group",
})

_ABBREV_TO_FULL: dict[str, str] = {v: k for k, v in MOSPI_ABBREVIATIONS.items()}

_GEOGRAPHY_CARDINALITY = {"state_ut": 36, "district": 780, "region": 6}

_KNOWN_ENUMS: dict[str, list[str]] = {
    "sector": ["Rural", "Urban"],
    "gender": ["Male", "Female", "Transgender"],
    "rural_urban": ["Rural", "Urban"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Alias generation
# ─────────────────────────────────────────────────────────────────────────────


def generate_aliases(entity: Any, table_structures: list[Any] | None = None, glossary: dict[str, str] | None = None, domain: str = "") -> list[AliasCandidate]:
    """Generate alias candidates from multiple sources."""
    candidates: list[AliasCandidate] = []
    name = _get(entity, "canonicalName") or ""
    etype = _get(entity, "entityType") or ""
    unit = _get(entity, "unit") or ""
    entity_id = _get(entity, "entityId") or ""
    if not name:
        return candidates

    name_lower = name.lower().strip()
    words = name.split()

    # Source 1: Canonical variants
    if len(words) >= 2 and len(words[0]) >= 4 and words[0].lower() not in _GENERIC_ALIASES:
        candidates.append(AliasCandidate(alias=words[0], source="canonical_variant", scope="global", score=0.7, reason="first_word"))

    if name != name_lower:
        candidates.append(AliasCandidate(alias=name_lower, source="canonical_variant", scope="global", score=0.6, reason="lowercase"))

    if unit == "percent" and "percent" not in name_lower and "%" not in name:
        candidates.append(AliasCandidate(alias=f"{name} (%)", source="canonical_variant", scope="global", score=0.7, reason="with_unit"))
        candidates.append(AliasCandidate(alias=f"Distribution (%)", source="canonical_variant", scope="domain_local", score=0.5, reason="distribution_alias"))

    # Source 2: Physical column names
    phys_cols = _get(entity, "physicalColumns") or []
    norm_hints = _get(entity, "normalizationHints") or {}
    period_cols = norm_hints.get("periodColumns") or []
    for col in set(phys_cols + period_cols):
        if col and col != name:
            candidates.append(AliasCandidate(alias=col, source="physical_column", scope="table_local", score=0.8, reason="physical_column"))

    # Source 3: Glossary/abbreviation
    if name_lower in MOSPI_ABBREVIATIONS:
        candidates.append(AliasCandidate(alias=MOSPI_ABBREVIATIONS[name_lower].upper(), source="glossary", scope="global", score=0.95, reason="abbreviation"))

    if entity_id.startswith("ent_"):
        slug = entity_id[4:].upper()
        if slug in _ABBREV_TO_FULL:
            candidates.append(AliasCandidate(alias=_ABBREV_TO_FULL[slug].title(), source="glossary", scope="global", score=0.9, reason="expansion"))

    # Source 4: Slash/spacing variants
    if "/" in name:
        parts = [p.strip() for p in name.split("/") if p.strip() and len(p.strip()) >= 2]
        for p in parts:
            candidates.append(AliasCandidate(alias=p, source="canonical_variant", scope="global", score=0.6, reason="slash_part"))

    # State/UT specific
    if "state" in name_lower and ("ut" in name_lower or "/" in name):
        for v in ["State", "States", "State/UT", "States/UTs", "States/ UTs", "Region"]:
            if v.lower() != name_lower:
                candidates.append(AliasCandidate(alias=v, source="canonical_variant", scope="global", score=0.7, reason="geo_variant"))

    # Underscore variant
    underscore = name.replace(" ", "_").replace("/", "_")
    if underscore != name and len(underscore) > 3:
        candidates.append(AliasCandidate(alias=underscore, source="canonical_variant", scope="global", score=0.5, reason="underscore"))

    return candidates


def filter_aliases(aliases: list[AliasCandidate], entity: Any) -> list[AliasCandidate]:
    """Filter aliases using negative alias guard. Scopes generic aliases."""
    name = (_get(entity, "canonicalName") or "").lower().strip()
    filtered: list[AliasCandidate] = []
    seen: set[str] = set()

    for alias in aliases:
        al = alias.alias.lower().strip()
        if not al or len(al) < 2 or al in seen or al == name:
            continue
        seen.add(al)

        if al in _GENERIC_ALIASES:
            alias.scope = "table_local"
            alias.score = min(alias.score, 0.3)

        if len(al) <= 2 and alias.source != "glossary":
            continue

        filtered.append(alias)

    filtered.sort(key=lambda a: -a.score)
    return filtered[:8]


# ─────────────────────────────────────────────────────────────────────────────
# ValueDomain inference
# ─────────────────────────────────────────────────────────────────────────────


def infer_value_domain(entity: Any, table_structures: list[Any] | None = None, context: Any | None = None, measure_families: list[Any] | None = None) -> ValueDomainResult:
    """Infer valueDomain based on entity type, unit, and context."""
    etype = _get(entity, "entityType") or ""
    unit = _get(entity, "unit") or ""
    scope = _get(entity, "scope") or ""
    aggregation = _get(entity, "aggregation") or ""
    is_derived = _get(entity, "isDerived") or False
    name_lower = (_get(entity, "canonicalName") or "").lower()
    existing = _get(entity, "valueDomain") or {}

    # Preserve well-formed existing domain
    if isinstance(existing, dict) and existing.get("kind") and existing.get("kind") != "open":
        members = existing.get("members")
        if isinstance(members, list) and members:
            return ValueDomainResult(kind=existing["kind"], members=members, min=existing.get("min"), max=existing.get("max"), format=existing.get("format"), expectedCardinality=existing.get("expectedCardinality"), allowOther=existing.get("allowOther", True), confidence=0.9, source="preserved")

    # Measures
    if etype == "measure":
        if unit == "percent" or is_derived:
            return ValueDomainResult(kind="ratio", min=0, max=100, confidence=0.9, source="unit_inference")
        if unit in ("MW", "GW", "million_tonnes", "billion_cubic_metres", "crore_inr", "lakh_inr"):
            return ValueDomainResult(kind="ratio", min=0, confidence=0.8, source="unit_inference")
        if aggregation == "count":
            return ValueDomainResult(kind="count", min=0, confidence=0.8, source="aggregation_inference")
        return ValueDomainResult(kind="ratio", min=0, confidence=0.5, source="default_measure")

    # Time
    if etype == "time":
        members = existing.get("members") or []
        fmt = existing.get("format") or "YYYY"
        if isinstance(members, list) and members:
            return ValueDomainResult(kind="ordinal", members=members, format=fmt, confidence=0.9, source="period_members")
        return ValueDomainResult(kind="temporal", format=fmt, confidence=0.6, source="time_type")

    # Dimensions
    if etype == "dimension":
        if scope == "geography" or any(g in name_lower for g in ("state", "district", "region")):
            geo_key = "state_ut"
            for k in ("district", "region"):
                if k in name_lower:
                    geo_key = k
                    break
            return ValueDomainResult(kind="categorical", members="open", expectedCardinality=_GEOGRAPHY_CARDINALITY.get(geo_key, 36), allowOther=True, confidence=0.85, source="geography_inference")

        for key, members in _KNOWN_ENUMS.items():
            if key in name_lower:
                return ValueDomainResult(kind="categorical", members=members, allowOther=True, confidence=0.8, source="known_enum")

        # Family category dimension
        if measure_families:
            entity_id = _get(entity, "entityId") or ""
            for family in measure_families:
                cat_dim = family.categoryDimension if hasattr(family, "categoryDimension") else (family.get("categoryDimension") if isinstance(family, dict) else None)
                if cat_dim and cat_dim == entity_id:
                    family_members = family.members if hasattr(family, "members") else (family.get("members") or [])
                    member_labels = []
                    for m in family_members:
                        label = m.label if hasattr(m, "label") else (m.get("label") if isinstance(m, dict) else "")
                        is_total = m.isTotal if hasattr(m, "isTotal") else (m.get("isTotal") if isinstance(m, dict) else False)
                        if label and not is_total:
                            member_labels.append(label)
                    if member_labels:
                        return ValueDomainResult(kind="categorical", members=member_labels, allowOther=False, confidence=0.85, source="family_members")

        return ValueDomainResult(kind="categorical", members="open", confidence=0.4, source="default_dimension")

    return ValueDomainResult(kind="open", confidence=0.2, source="default")


# ─────────────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────────────


def enrich_entities(entities: list[Any], table_structures: list[Any] | None = None, statistical_context: Any | None = None, measure_families: list[Any] | None = None, glossary: dict[str, str] | None = None, domain: str = "") -> EntityEnrichmentResult:
    """Enrich entities with aliases, valueDomain, aggregation, and format."""
    result = EntityEnrichmentResult()
    with_aliases = 0
    with_domain = 0
    with_agg = 0

    # Load domain-specific unit rules for inferring missing units
    _unit_rules: dict[str, str] = {}
    try:
        from report_builder.domain_packs.plfs_press_release import PLFS_UNIT_RULES
        _unit_rules = PLFS_UNIT_RULES
    except ImportError:
        pass

    for entity in entities:
        # Unit inference from domain pack (if missing)
        if not _get(entity, "unit"):
            name = _get(entity, "name") or ""
            inferred_unit = _unit_rules.get(name)
            if not inferred_unit:
                # Try alias match
                for alias in (_get(entity, "aliases") or []):
                    inferred_unit = _unit_rules.get(alias)
                    if inferred_unit:
                        break
            # Also infer from name patterns
            if not inferred_unit:
                name_lower = name.lower()
                if "rate" in name_lower or "ratio" in name_lower or "share" in name_lower:
                    inferred_unit = "percent"
                elif "earning" in name_lower or "income" in name_lower or "wage" in name_lower:
                    inferred_unit = "INR"
                elif "hours" in name_lower:
                    inferred_unit = "hours_per_week"
                elif "years" in name_lower or "education" in name_lower:
                    inferred_unit = "years"
            if inferred_unit:
                if isinstance(entity, dict):
                    entity["unit"] = inferred_unit
                elif hasattr(entity, "unit"):
                    entity.unit = inferred_unit

        # Aliases
        raw = generate_aliases(entity, table_structures, glossary, domain)
        filtered = filter_aliases(raw, entity)
        existing = set(_get(entity, "aliases") or [])
        new_aliases = [a.alias for a in filtered if a.alias not in existing]
        all_aliases = list(existing) + new_aliases
        if hasattr(entity, "aliases"):
            entity.aliases = all_aliases
        elif isinstance(entity, dict):
            entity["aliases"] = all_aliases
        if all_aliases:
            with_aliases += 1

        # ValueDomain
        vd = infer_value_domain(entity, table_structures, statistical_context, measure_families)
        vd_dict = vd.to_dict()
        if hasattr(entity, "valueDomain"):
            entity.valueDomain = vd_dict
        elif isinstance(entity, dict):
            entity["valueDomain"] = vd_dict
        if vd.kind != "open":
            with_domain += 1

        # Aggregation
        if not _get(entity, "aggregation"):
            unit = _get(entity, "unit") or ""
            is_derived = _get(entity, "isDerived") or False
            is_total = _get(entity, "isTotal") or False
            etype = _get(entity, "entityType") or ""
            agg = None
            if unit == "percent" or is_derived:
                agg = "reported_value"
            elif is_total:
                agg = "sum"
            elif etype == "measure" and unit:
                agg = "sum"
            if agg:
                if hasattr(entity, "aggregation"):
                    entity.aggregation = agg
                elif isinstance(entity, dict):
                    entity["aggregation"] = agg
                with_agg += 1

        # Format
        if not _get(entity, "format"):
            unit = _get(entity, "unit") or ""
            fmt = None
            if unit == "percent":
                fmt = "percent.1"
            elif unit in ("million_tonnes", "billion_cubic_metres", "crore_inr"):
                fmt = "number.2"
            elif unit in ("MW", "GW"):
                fmt = "number.0"
            if fmt:
                if hasattr(entity, "format"):
                    entity.format = fmt
                elif isinstance(entity, dict):
                    entity["format"] = fmt

        result.entities.append(entity)

    result.aliasStats = {"withAliases": with_aliases, "without": len(entities) - with_aliases, "totalGenerated": sum(len(_get(e, "aliases") or []) for e in entities)}
    result.domainStats = {"withDomain": with_domain, "without": len(entities) - with_domain}
    result.diagnostics = {"inputCount": len(entities), "aliasStats": result.aliasStats, "domainStats": result.domainStats, "aggregationInferred": with_agg}
    return result


# ─────────────────────────────────────────────────────────────────────────────


def _get(obj: Any, attr: str) -> Any:
    if obj is None:
        return None
    if hasattr(obj, attr):
        return getattr(obj, attr)
    if isinstance(obj, dict):
        return obj.get(attr)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline-level wrapper (used by extraction_pipeline.py pass 2.7)
# ─────────────────────────────────────────────────────────────────────────────


def enrich_document_map(document_map: dict) -> dict:
    """Enrich all entities in a document_map dict (pass 2.7 entry point).

    Reads:
        document_map["all_entities"]
        document_map["table_structures"]
        document_map["statistical_context"]
        document_map["measure_families"]
        document_map["domain"]

    Writes back:
        document_map["all_entities"] (enriched in-place with aliases + valueDomain)
        document_map["glossary"] (extracted from enrichment)
        document_map["enrichment_summary"] (stats)

    Returns the mutated document_map.
    """
    entities = document_map.get("all_entities") or []
    if not entities:
        return document_map

    table_structures = document_map.get("table_structures") or []
    statistical_context = document_map.get("statistical_context")
    measure_families = document_map.get("measure_families") or []
    domain = document_map.get("domain") or ""

    result = enrich_entities(
        entities=entities,
        table_structures=table_structures,
        statistical_context=statistical_context,
        measure_families=measure_families,
        glossary=None,
        domain=domain,
    )

    # Write back enriched entities
    document_map["all_entities"] = result.entities or entities
    document_map["enrichment_summary"] = {
        "with_aliases": result.aliasStats.get("withAliases", 0),
        "with_value_domain": result.domainStats.get("withDomain", 0),
        "with_aggregation": result.diagnostics.get("aggregationInferred", 0),
        "total": len(entities),
    }

    return document_map
