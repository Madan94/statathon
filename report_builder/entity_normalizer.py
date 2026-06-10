"""E2 — Canonical Entity Normalization + Measure Families.

Converts clean but flat/physical entities (from E1) into canonical
binder-ready semantic entities:

    "Proved 2024" + "Proved 2025" → one "Proved" measure + ent_period
    "Distribution 2024" + "Distribution 2025" → one "Distribution Percent" + ent_period
    Related measures → MeasureFamily with modeling advice

This is the bridge between entity hygiene (E1) and table semantics (E3).

Usage:
    from report_builder.entity_normalizer import normalize_entities
    result = normalize_entities(hygiene_result.entities)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from report_builder.entity_id_generator import generate_entity_id

# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PeriodExtraction:
    """Result of extracting a time period from an entity name."""
    originalName: str = ""
    stem: str = ""
    period: str | None = None
    periodFormat: str | None = None     # "YYYY" | "YYYY-YY" | "QN YYYY"
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "originalName": self.originalName,
            "stem": self.stem,
            "period": self.period,
            "periodFormat": self.periodFormat,
            "confidence": self.confidence,
        }


@dataclass
class MeasureFamilyMember:
    """One member in a measure family."""
    label: str = ""
    entityRef: str = ""
    isTotal: bool = False
    isDerived: bool = False
    unit: str | None = None
    periods: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "label": self.label,
            "entityRef": self.entityRef,
            "isTotal": self.isTotal,
            "isDerived": self.isDerived,
        }
        if self.unit:
            d["unit"] = self.unit
        if self.periods:
            d["periods"] = list(self.periods)
        return d


@dataclass
class MeasureFamily:
    """A group of related measures sharing a common domain."""
    familyId: str = ""
    baseConcept: str = ""
    categoryDimension: str | None = None
    members: list[MeasureFamilyMember] = field(default_factory=list)
    modelingAdvice: str = "separate_measures"  # separate_measures | category_dimension | both
    normalizationHint: str = "NONE"            # NONE | WIDE_TO_LONG

    def to_dict(self) -> dict[str, Any]:
        return {
            "familyId": self.familyId,
            "baseConcept": self.baseConcept,
            "categoryDimension": self.categoryDimension,
            "members": [m.to_dict() for m in self.members],
            "modelingAdvice": self.modelingAdvice,
            "normalizationHint": self.normalizationHint,
        }


@dataclass
class NormalizedEntity:
    """A canonical binder-ready entity after normalization."""
    entityId: str = ""
    canonicalName: str = ""
    entityType: str = ""
    aliases: list[str] = field(default_factory=list)
    unit: str | None = None
    valueDomain: dict[str, Any] = field(default_factory=dict)
    aggregation: str | None = None
    scope: str = "indicator"
    sourceRefs: list[dict[str, Any]] = field(default_factory=list)
    familyRef: str | None = None
    normalizationHints: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.85
    isTotal: bool = False
    isDerived: bool = False
    physicalColumns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "entityId": self.entityId,
            "canonicalName": self.canonicalName,
            "entityType": self.entityType,
            "aliases": list(self.aliases),
            "unit": self.unit,
            "valueDomain": dict(self.valueDomain),
            "aggregation": self.aggregation,
            "scope": self.scope,
            "confidence": self.confidence,
        }
        if self.familyRef:
            d["familyRef"] = self.familyRef
        if self.normalizationHints:
            d["normalizationHints"] = dict(self.normalizationHints)
        if self.physicalColumns:
            d["physicalColumns"] = list(self.physicalColumns)
        if self.isTotal:
            d["isTotal"] = True
        if self.isDerived:
            d["isDerived"] = True
        return d


@dataclass
class NormalizationResult:
    """Result of entity normalization."""
    entities: list[NormalizedEntity] = field(default_factory=list)
    periodEntity: NormalizedEntity | None = None
    measureFamilies: list[MeasureFamily] = field(default_factory=list)
    mergedEntities: list[dict[str, Any]] = field(default_factory=list)  # Log of merges
    quarantined: list[dict[str, Any]] = field(default_factory=list)
    normalizationLog: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entityCount": len(self.entities),
            "periodEntity": self.periodEntity.to_dict() if self.periodEntity else None,
            "measureFamilyCount": len(self.measureFamilies),
            "mergedCount": len(self.mergedEntities),
            "quarantinedCount": len(self.quarantined),
            "diagnostics": self.diagnostics,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Period extraction
# ─────────────────────────────────────────────────────────────────────────────

# Year patterns — ordered by specificity
_PERIOD_PATTERNS = [
    # "2023-24" or "2023–24" (Indian financial year)
    (re.compile(r'^(.+?)\s+((?:19|20)\d{2}[-–]\d{2,4})$'), "YYYY-YY"),
    # "2025" trailing year
    (re.compile(r'^(.+?)\s+((?:19|20)\d{2})$'), "YYYY"),
    # "(2024-25)" parenthetical
    (re.compile(r'^(.+?)\s*\(((?:19|20)\d{2}[-–]\d{2,4})\)$'), "YYYY-YY"),
    # "(2025)" parenthetical
    (re.compile(r'^(.+?)\s*\(((?:19|20)\d{2})\)$'), "YYYY"),
    # "Q1 2025" quarterly
    (re.compile(r'^(.+?)\s+(Q[1-4]\s+(?:19|20)\d{2})$'), "QN YYYY"),
]

# Names that should NEVER have period extracted (false positive guard)
_PERIOD_EXEMPT_RE = re.compile(
    r'(?:Table|Figure|Fig|Section|Chapter|Page)\s+\d'
    r'|(?:States?|UT|Region|District|Sector)[\s/]'
    r'|@\s*\d+'        # "Wind Power @ 150m"
    r'|\(%\)'          # "Distribution (%)"
    r'|(?:MW|MT|BCM|GW)\b',
    re.IGNORECASE,
)


def extract_period_from_name(name: str) -> PeriodExtraction:
    """Extract time period from an entity name.

    Returns PeriodExtraction with stem and period (or period=None if none found).

    Catches: "Proved 2025", "Value 2023-24", "Production (2024–25)", "Q1 2025"
    Does NOT extract from: "States/ UTs", "Distribution (%)", "Table 1.1", "Wind Power @ 150m"
    """
    name = name.strip()
    result = PeriodExtraction(originalName=name, stem=name, confidence=0.0)

    # Check exemptions first
    if _PERIOD_EXEMPT_RE.search(name):
        return result

    # Try each pattern
    for pattern, fmt in _PERIOD_PATTERNS:
        m = pattern.match(name)
        if m:
            stem = m.group(1).strip()
            period = m.group(2).strip()
            # Normalize dash
            period = period.replace("–", "-")
            # Validate stem is not empty or too short
            if stem and len(stem) >= 2:
                result.stem = stem
                result.period = period
                result.periodFormat = fmt
                result.confidence = 0.9
                return result

    return result


def normalize_entity_name(name: str) -> str:
    """Normalize entity canonical name (remove periods, clean symbols).

    "Proved 2025" → "Proved"
    "Distribution (%)" → "Distribution Percent"
    "States/ UTs" → "State/UT"
    "Total 2024" → "Total"
    """
    # Extract period first
    extraction = extract_period_from_name(name)
    stem = extraction.stem

    # Normalize specific patterns
    stem = stem.replace("(%)", "Percent").replace("%", "Percent")
    stem = re.sub(r'\s*/\s*', '/', stem)  # collapse " / " to "/"

    # States/UTs normalization
    if re.match(r'states?/?u?t?s?', stem, re.IGNORECASE):
        stem = "State/UT"

    # Clean trailing whitespace
    stem = stem.strip()

    return stem


# ─────────────────────────────────────────────────────────────────────────────
# Measure family detection
# ─────────────────────────────────────────────────────────────────────────────

# Known aggregate labels (not category members)
_TOTAL_LABELS = frozenset({"total", "grand total", "all india", "sub-total", "sub total"})

# Known derived/computed labels
_DERIVED_LABELS = frozenset({"distribution", "distribution percent", "share", "percentage", "proportion"})

# Reserve category family pattern
_RESERVE_CATEGORIES = frozenset({"proved", "indicated", "inferred"})

# Energy source family pattern
_ENERGY_SOURCES = frozenset({"wind", "solar", "small hydro", "biomass", "large hydro",
                              "wind power", "solar energy", "small hydro power", "biomass power", "large hydro"})


def detect_measure_families(
    entities: list[NormalizedEntity],
) -> list[MeasureFamily]:
    """Detect measure families from canonical entities.

    Families:
    - Reserve categories: Proved, Indicated, Inferred, Total, Distribution
    - Energy sources: Wind, Solar, Small Hydro, Biomass, Large Hydro
    - Commodity pairs: Crude Oil / Natural Gas
    """
    families: list[MeasureFamily] = []
    measures = [e for e in entities if e.entityType == "measure"]
    measure_names = {e.canonicalName.lower().strip() for e in measures}

    # Check for reserve category family
    reserve_hits = measure_names & _RESERVE_CATEGORIES
    if len(reserve_hits) >= 2:
        members = []
        for e in measures:
            name_low = e.canonicalName.lower().strip()
            if name_low in _RESERVE_CATEGORIES or name_low in _TOTAL_LABELS or name_low in _DERIVED_LABELS:
                members.append(MeasureFamilyMember(
                    label=e.canonicalName,
                    entityRef=e.entityId,
                    isTotal=(name_low in _TOTAL_LABELS),
                    isDerived=(name_low in _DERIVED_LABELS),
                    unit=e.unit,
                ))

        if len(members) >= 2:
            has_periods = any(e.physicalColumns for e in measures if e.canonicalName.lower() in reserve_hits)
            families.append(MeasureFamily(
                familyId="mf_reserves_by_category",
                baseConcept="Reserves",
                categoryDimension="ent_reserve_category",
                members=members,
                modelingAdvice="both" if has_periods else "category_dimension",
                normalizationHint="WIDE_TO_LONG" if has_periods else "NONE",
            ))

    # Check for energy source family
    energy_hits = measure_names & _ENERGY_SOURCES
    if len(energy_hits) >= 2:
        members = []
        for e in measures:
            if e.canonicalName.lower().strip() in _ENERGY_SOURCES:
                members.append(MeasureFamilyMember(
                    label=e.canonicalName,
                    entityRef=e.entityId,
                    unit=e.unit,
                ))
        if len(members) >= 2:
            families.append(MeasureFamily(
                familyId="mf_energy_sources",
                baseConcept="Energy Source",
                categoryDimension="ent_energy_source",
                members=members,
                modelingAdvice="category_dimension",
                normalizationHint="NONE",
            ))

    return families


def decide_family_modeling(family: MeasureFamily) -> str:
    """Decide how to model a measure family for binder.

    Rules (signal-based):
    - All members share unit and are additive → category_dimension
    - Members have DIFFERENT units → separate_measures
    - Year columns present → both + WIDE_TO_LONG
    - Contains derived (Distribution %) → separate from additive
    """
    units = {m.unit for m in family.members if m.unit and not m.isDerived}
    has_derived = any(m.isDerived for m in family.members)
    has_periods = family.normalizationHint == "WIDE_TO_LONG"

    if len(units) > 1:
        return "separate_measures"
    if has_periods:
        return "both"
    if has_derived and len(family.members) > 2:
        return "both"
    return "category_dimension"


# ─────────────────────────────────────────────────────────────────────────────
# Period entity creation
# ─────────────────────────────────────────────────────────────────────────────


def create_period_entity(periods: list[str]) -> NormalizedEntity:
    """Create the canonical ent_period entity from detected periods."""
    sorted_periods = sorted(set(periods))

    # Detect format
    fmt = "YYYY"
    if any("-" in p for p in sorted_periods):
        fmt = "YYYY-YY"

    return NormalizedEntity(
        entityId="ent_period",
        canonicalName="Period",
        entityType="time",
        aliases=["Year", "Period", "Survey Period", "Reference Year"],
        unit=None,
        valueDomain={"kind": "ordinal", "members": sorted_periods, "format": fmt},
        aggregation=None,
        scope="temporal",
        confidence=0.95,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main normalizer
# ─────────────────────────────────────────────────────────────────────────────


def normalize_entities(
    entities: list[Any],
    source_context: dict[str, Any] | None = None,
) -> NormalizationResult:
    """Normalize clean entities into canonical binder-ready form.

    Steps:
    1. Extract periods from entity names
    2. Group by canonical stem
    3. Merge year-suffixed siblings
    4. Create ent_period if periods found
    5. Detect measure families
    6. Quarantine remaining OCR/noise
    7. Assign final IDs

    Args:
        entities: List of SemanticEntity objects (from E1) or dicts.
        source_context: Optional context about source document.

    Returns:
        NormalizationResult with canonical entities, period, families.
    """
    result = NormalizationResult()
    all_periods: list[str] = []

    # Step 1+2: Extract periods and group by stem
    stem_groups: dict[str, list[dict[str, Any]]] = {}

    for entity in entities:
        # Support both SemanticEntity and dict
        if hasattr(entity, "canonicalName"):
            name = entity.canonicalName
            etype = entity.entityType
            unit = entity.unit
            raw_text = entity.rawText
            source_refs = [s.to_dict() for s in entity.sourceRefs] if hasattr(entity, "sourceRefs") else []
        else:
            name = entity.get("canonicalName") or entity.get("name") or ""
            etype = entity.get("entityType") or ""
            unit = entity.get("unit")
            raw_text = entity.get("rawText") or name
            source_refs = entity.get("sourceRefs") or []

        if not name:
            continue

        # Extract period
        extraction = extract_period_from_name(name)
        stem = normalize_entity_name(name)
        period = extraction.period

        if period:
            all_periods.append(period)

        # Quarantine remaining obvious OCR fragments
        if _looks_like_remaining_noise(stem):
            result.quarantined.append({"text": raw_text, "reason": "RESIDUAL_OCR_FRAGMENT", "stem": stem})
            result.normalizationLog.append(f"Quarantined residual noise: '{raw_text}'")
            continue

        # Group by normalized stem (case-insensitive)
        key = (stem.lower(), etype or "measure", unit or "")
        if key not in stem_groups:
            stem_groups[key] = []
        stem_groups[key].append({
            "stem": stem,
            "period": period,
            "originalName": name,
            "rawText": raw_text,
            "entityType": etype,
            "unit": unit,
            "sourceRefs": source_refs,
        })

    # Step 3: Merge year-suffixed siblings into canonical entities
    for (stem_key, etype, unit_key), group in stem_groups.items():
        stem = group[0]["stem"]  # Use first occurrence's stem (case preserved)
        periods_in_group = [g["period"] for g in group if g["period"]]
        physical_columns = [g["originalName"] for g in group]
        all_source_refs = []
        for g in group:
            all_source_refs.extend(g["sourceRefs"])

        # Detect special flags
        stem_lower = stem.lower().strip()
        is_total = stem_lower in _TOTAL_LABELS
        is_derived = stem_lower in _DERIVED_LABELS or "percent" in stem_lower

        # Determine unit
        entity_unit = unit_key or None
        if is_derived and not entity_unit:
            entity_unit = "percent"

        # Determine aggregation
        aggregation = None
        if is_total:
            aggregation = "sum"
        elif is_derived:
            aggregation = "reported_value"
        elif entity_unit == "percent":
            aggregation = "reported_value"

        # Build canonical entity
        canonical = NormalizedEntity(
            canonicalName=stem,
            entityType=etype or "measure",
            unit=entity_unit,
            aggregation=aggregation,
            isTotal=is_total,
            isDerived=is_derived,
            physicalColumns=physical_columns if len(group) > 1 else [],
            sourceRefs=all_source_refs,
            confidence=0.85,
        )

        # Assign aliases from physical column names
        if len(group) > 1:
            canonical.aliases = list(set(physical_columns) - {stem})
            canonical.normalizationHints = {
                "wide": True,
                "periodColumns": physical_columns,
                "periods": periods_in_group,
            }
            result.mergedEntities.append({
                "canonical": stem,
                "merged": physical_columns,
                "periods": periods_in_group,
            })
            result.normalizationLog.append(
                f"Merged {len(group)} variants into '{stem}': {physical_columns}"
            )

        # Set valueDomain
        if canonical.entityType == "dimension":
            canonical.valueDomain = {"kind": "categorical", "members": "open"}
            canonical.scope = "classifier"
        elif entity_unit == "percent":
            canonical.valueDomain = {"kind": "ratio", "min": 0, "max": 100}
        elif entity_unit:
            canonical.valueDomain = {"kind": "ratio", "min": 0}

        # Generate ID
        canonical.entityId = generate_entity_id(stem, canonical.entityType)

        result.entities.append(canonical)

    # Step 4: Create period entity if periods detected
    if all_periods:
        result.periodEntity = create_period_entity(all_periods)
        result.entities.append(result.periodEntity)
        result.normalizationLog.append(
            f"Created ent_period with {len(set(all_periods))} periods: {sorted(set(all_periods))}"
        )

    # Step 5: Detect measure families
    result.measureFamilies = detect_measure_families(result.entities)
    for family in result.measureFamilies:
        family.modelingAdvice = decide_family_modeling(family)
        # Link entities to family
        member_refs = {m.entityRef for m in family.members}
        for ent in result.entities:
            if ent.entityId in member_refs:
                ent.familyRef = family.familyId

    # Step 6: Diagnostics
    result.diagnostics = {
        "inputCount": len(entities),
        "outputEntityCount": len(result.entities),
        "periodsDetected": sorted(set(all_periods)),
        "mergedGroups": len(result.mergedEntities),
        "measureFamilies": len(result.measureFamilies),
        "quarantinedCount": len(result.quarantined),
        "periodEntityCreated": result.periodEntity is not None,
    }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _looks_like_remaining_noise(stem: str) -> bool:
    """Catch residual OCR/noise that survived E1 but doesn't make semantic sense."""
    if not stem or len(stem) < 3:
        return True

    # Pattern: "X ial" or similar broken suffix in middle
    if re.search(r'\b[a-z]{2,4}\s+[a-z]{2,4}\b', stem) and len(stem) < 25:
        words = stem.split()
        if len(words) >= 2 and any(
            w.endswith(("ial", "ble", "ive", "ent", "ous")) and len(w) <= 5
            for w in words
        ):
            return True

    return False
