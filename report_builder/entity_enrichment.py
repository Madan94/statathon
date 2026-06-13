"""Entity enrichment (migration plan P5 / pass 2.7 / loop decisions Q16-Q19).

Pure, deterministic enrichment of typed entities into template-ready descriptors:

* ``enrich_entity``        \u2014 per-entity: canonicalName, aliases, unit, dtypeHint,
                             defaultFormat, valueDomain, glossaryRef (Q17/Q18).
* ``build_glossary``       \u2014 canonical MoSPI glossary + per-doc terms (Q19).
* ``build_palette``        \u2014 canonical MoSPI palette registry (Q19).
* ``enrich_document_map``  \u2014 orchestrator: enriches all_entities in place and
                             attaches ``glossary`` + ``palette`` to the map.

Layered strategy (Q17): regex + canonical glossary first; a VLM fallback is left
to the caller (the pipeline) for anything still unknown \u2014 this module never calls
an LLM or touches disk.
"""
from __future__ import annotations

import re
from typing import Any
from dataclasses import dataclass, field
from report_builder.entity_id_generator import MOSPI_ABBREVIATIONS

# ── Canonical MoSPI glossary (Q19): term \u2192 {definition, unit, dtype, format} ──
# Value-free schema metadata only \u2014 no measured numbers.
MOSPI_GLOSSARY: dict[str, dict[str, Any]] = {
    "lfpr": {"definition": "Labour Force Participation Rate \u2014 share of population in the labour force.",
             "unit": "percent", "dtype": "float", "format": "0.0%"},
    "wpr": {"definition": "Worker Population Ratio \u2014 share of population employed.",
            "unit": "percent", "dtype": "float", "format": "0.0%"},
    "ur": {"definition": "Unemployment Rate \u2014 share of labour force that is unemployed.",
           "unit": "percent", "dtype": "float", "format": "0.0%"},
    "mpce": {"definition": "Monthly Per Capita Consumption Expenditure.",
             "unit": "INR", "dtype": "float", "format": "\u20b9#,##,##0"},
    "cpi": {"definition": "Consumer Price Index.", "unit": "index", "dtype": "float", "format": "0.0"},
    "gdp": {"definition": "Gross Domestic Product.", "unit": "INR_crore", "dtype": "float", "format": "\u20b9#,##,##0"},
    "gva": {"definition": "Gross Value Added.", "unit": "INR_crore", "dtype": "float", "format": "\u20b9#,##,##0"},
    "gsdp": {"definition": "Gross State Domestic Product.", "unit": "INR_crore", "dtype": "float", "format": "\u20b9#,##,##0"},
}

# ── Canonical dimension members (Q18): closed low-cardinality enums ──
# High-cardinality dims (State, District) are left OPEN (members=[], domainType=open).
CANONICAL_DIM_MEMBERS: dict[str, list[str]] = {
    "sector": ["Rural", "Urban"],
    "gender": ["Male", "Female", "Transgender"],
    "sex": ["Male", "Female", "Transgender"],
    "area": ["Rural", "Urban"],
}
_OPEN_DIMENSIONS: frozenset[str] = frozenset({
    "state", "district", "region", "city", "village", "block", "industry",
    "occupation", "year", "quarter", "month", "round",
})

# ── Unit detection (Q17): layered regex over the entity name ──
_UNIT_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(rate|ratio|percent|share|proportion)\b|%", re.I), "percent", "0.0%"),
    (re.compile(r"\b(index)\b", re.I), "index", "0.0"),
    (re.compile(r"\u20b9|\b(rupees?|inr|wage|salary|earnings?|expenditure|income|mpce)\b", re.I),
     "INR", "\u20b9#,##,##0"),
    (re.compile(r"\b(crore|lakh)\b", re.I), "INR_crore", "\u20b9#,##,##0"),
    (re.compile(r"\b(tonnes?|kg|kilograms?|quintal)\b", re.I), "tonnes", "#,##0.0"),
    (re.compile(r"\b(mw|megawatt|gw|kwh)\b", re.I), "MW", "#,##0"),
    (re.compile(r"\b(count|number|total|persons?|workers?|population)\b", re.I), "count", "#,##,##0"),
    (re.compile(r"\b(years?)\b", re.I), "years", "0.0"),
]

_ABBREV_RE = re.compile(r"\(([A-Z][A-Za-z0-9\+\-]{1,12})\)")


def _strip_parenthetical(name: str) -> str:
    bare = re.sub(r"\([^)]*\)", "", name)
    return re.sub(r"\s+", " ", bare).strip().rstrip("- ").strip()


def _glossary_key(name: str) -> str | None:
    """Match an entity name to a canonical glossary key via abbreviation or token."""
    low = name.lower()
    for m in _ABBREV_RE.finditer(name):
        if m.group(1).lower() in MOSPI_GLOSSARY:
            return m.group(1).lower()
    for key in MOSPI_GLOSSARY:
        if re.search(rf"\b{re.escape(key)}\b", low):
            return key
    return None


def _detect_unit_format(name: str, etype: str) -> tuple[str | None, str | None]:
    if etype != "measure":
        return None, None
    for rx, unit, fmt in _UNIT_RULES:
        if rx.search(name):
            return unit, fmt
    return None, None


def _value_domain(name: str, etype: str) -> dict[str, Any] | None:
    """Q18: dimension members \u2014 canonical closed enum, or open for high-cardinality."""
    if etype not in ("dimension", "filter"):
        return None
    low = name.lower()
    for key, members in CANONICAL_DIM_MEMBERS.items():
        if re.search(rf"\b{re.escape(key)}\b", low):
            return {"domainType": "closed", "members": list(members)}
    for key in _OPEN_DIMENSIONS:
        if re.search(rf"\b{re.escape(key)}\b", low):
            return {"domainType": "open", "members": []}
    return {"domainType": "open", "members": []}


def enrich_entity(entity: dict[str, Any]) -> dict[str, Any]:
    """Enrich a single typed entity in place with template descriptors (Q17/Q18/Q19).

    Idempotent: re-running does not clobber values already present.
    """
    name = entity.get("name") or ""
    etype = entity.get("entityType_hint") or entity.get("entityType") or "dimension"

    # canonicalName + aliases
    bare = _strip_parenthetical(name)
    entity.setdefault("canonicalName", bare or name)
    aliases = list(entity.get("aliases") or [])
    for m in _ABBREV_RE.finditer(name):
        if m.group(1) not in aliases and m.group(1) != name:
            aliases.append(m.group(1))
    if bare and bare != name and len(bare) >= 4 and bare not in aliases:
        aliases.append(bare)
    entity["aliases"] = aliases

    # glossary link
    gkey = _glossary_key(name)
    if gkey and not entity.get("glossaryRef"):
        entity["glossaryRef"] = gkey

    # unit + format (glossary first, then regex)
    if not entity.get("unit") or not entity.get("defaultFormat"):
        g = MOSPI_GLOSSARY.get(gkey or "")
        if g:
            entity.setdefault("unit", g["unit"])
            entity.setdefault("defaultFormat", g["format"])
            entity.setdefault("dtypeHint", g["dtype"])
        else:
            unit, fmt = _detect_unit_format(name, etype)
            if unit:
                entity.setdefault("unit", unit)
                entity.setdefault("defaultFormat", fmt)

    # dtype hint backstop
    if not entity.get("dtypeHint"):
        entity["dtypeHint"] = "float" if etype == "measure" else "string"

    # valueDomain (dimension members)
    vd = _value_domain(name, etype)
    if vd is not None and not entity.get("valueDomain"):
        entity["valueDomain"] = vd

    return entity


def build_glossary(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Q19: canonical MoSPI glossary terms that appear in this document, deduped."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for e in entities or []:
        gkey = e.get("glossaryRef") or _glossary_key(e.get("name") or "")
        if gkey and gkey in MOSPI_GLOSSARY and gkey not in seen:
            seen.add(gkey)
            g = MOSPI_GLOSSARY[gkey]
            out.append({
                "term": gkey.upper(),
                "definition": g["definition"],
                "unit": g["unit"],
                "format": g["format"],
                "source": "canonical_mospi",
            })
    return out


def build_palette() -> dict[str, Any]:
    """Q19: canonical MoSPI palette registry (value-free; doc overrides applied by caller)."""
    return {
        "paletteId": "mospi_default",
        "source": "canonical_mospi",
        "categorical": ["#1F4E79", "#C55A11", "#548235", "#7030A0", "#BF9000", "#2E75B6"],
        "sequential": ["#DEEBF7", "#9ECAE1", "#4292C6", "#08519C"],
        "diverging": ["#C55A11", "#F4B183", "#FFFFFF", "#9DC3E6", "#1F4E79"],
        "roles": {"current": "#1F4E79", "prior": "#9DC3E6", "delta_up": "#548235", "delta_down": "#C55A11"},
    }


def enrich_document_map(document_map: dict[str, Any]) -> dict[str, Any]:
    """Pass 2.7 orchestrator (Q16): enrich all_entities + attach glossary & palette.

    Pure + deterministic. Returns the same map (mutated in place).
    """
    entities = document_map.get("all_entities") or []
    for e in entities:
        enrich_entity(e)
    document_map["glossary"] = build_glossary(entities)
    document_map["palette"] = build_palette()
    return document_map


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
        _unit_rules = dict(PLFS_UNIT_RULES)
    except ImportError:
        pass

    # Energy domain unit rules (always loaded — applies to statistical reports)
    _ENERGY_UNIT_RULES: dict[str, str] = {
        "Coal Reserves": "million_tonnes",
        "Lignite Reserves": "million_tonnes",
        "Crude Oil": "million_tonnes",
        "Crude Oil Reserves": "million_tonnes",
        "Natural Gas": "billion_cubic_metres",
        "Natural Gas Reserves": "billion_cubic_metres",
        "Renewable Power": "MW",
        "Wind Power": "MW",
        "Solar Energy": "MW",
        "Small Hydro Power": "MW",
        "Small Hydro": "MW",
        "Biomass Power": "MW",
        "Large Hydro": "MW",
        "Proved Reserves": "million_tonnes",
        "Indicated Reserves": "million_tonnes",
        "Inferred Reserves": "million_tonnes",
        "Total Reserves": "million_tonnes",
        "Distribution": "percent",
        "Energy Reserves": "million_tonnes",
        "Reserves": "million_tonnes",
    }
    _unit_rules.update(_ENERGY_UNIT_RULES)

    for entity in entities:
        # Unit inference from domain pack (if missing)
        if not _get(entity, "unit"):
            name = _get(entity, "canonicalName") or _get(entity, "name") or ""
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
                elif "distribution" in name_lower or "percent" in name_lower:
                    inferred_unit = "percent"
                elif "earning" in name_lower or "income" in name_lower or "wage" in name_lower:
                    inferred_unit = "INR"
                elif "hours" in name_lower:
                    inferred_unit = "hours_per_week"
                elif "years" in name_lower or "education" in name_lower:
                    inferred_unit = "years"
                elif any(k in name_lower for k in ("coal", "lignite", "crude oil", "oil reserves")):
                    inferred_unit = "million_tonnes"
                elif "natural gas" in name_lower:
                    inferred_unit = "billion_cubic_metres"
                elif any(k in name_lower for k in ("solar", "wind", "hydro", "biomass", "renewable", "power potential")):
                    inferred_unit = "MW"
                elif "reserves" in name_lower:
                    inferred_unit = "million_tonnes"
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
