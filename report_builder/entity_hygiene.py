"""E1 — Entity Hygiene Compiler.

Turns raw entity candidates into classified semantic candidates or quarantined noise.

Architecture: Reject → Classify → Evidence → Route

    raw candidates (from Pass 0-2)
      ↓
    Stage 1: Rejection (OCR fragments, broken text, noise)
      ↓  → quarantine with reasons
    Stage 2: Classification (signal-based bucket assignment)
      ↓  → each survivor gets bucket + confidence
    Stage 3: Routing (entity / topic / glossary / geography member)
      ↓
    Output: EntityHygieneResult

Usage:
    from report_builder.entity_hygiene import run_entity_hygiene, EntityClassificationContext
    ctx = EntityClassificationContext(source_priority=0)
    result = run_entity_hygiene(candidates, ctx)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Enums and models
# ─────────────────────────────────────────────────────────────────────────────


class EntityBucket(Enum):
    ANALYTIC_MEASURE = "measure"
    ANALYTIC_DIMENSION = "dimension"
    TIME_PERIOD = "time"
    GEOGRAPHY_MEMBER = "geography_value"
    TABLE_HEADER = "table_header"
    CHART_LABEL = "chart_label"
    TOPIC_HEADING = "topic"
    GLOSSARY_CONCEPT = "glossary"
    NOISE = "noise"


@dataclass
class ClassificationSignal:
    signal: str = ""
    score: float = 0.0
    source: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"signal": self.signal, "score": self.score, "source": self.source, "detail": self.detail}


@dataclass
class SourceRef:
    sourceType: str = ""
    tableId: str | None = None
    figureId: str | None = None
    regionRef: str | None = None
    page: int | None = None
    bbox: list[float] = field(default_factory=list)
    headerPath: list[str] = field(default_factory=list)
    physicalColumn: str | None = None
    confidence: float = 0.85

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"sourceType": self.sourceType, "confidence": self.confidence}
        if self.tableId:
            d["tableId"] = self.tableId
        if self.figureId:
            d["figureId"] = self.figureId
        if self.regionRef:
            d["regionRef"] = self.regionRef
        if self.page is not None:
            d["page"] = self.page
        if self.bbox:
            d["bbox"] = list(self.bbox)
        if self.headerPath:
            d["headerPath"] = list(self.headerPath)
        if self.physicalColumn:
            d["physicalColumn"] = self.physicalColumn
        return d


@dataclass
class SemanticEntity:
    """A classified entity candidate ready for ID assignment (E5)."""
    rawText: str = ""
    canonicalName: str = ""
    bucket: EntityBucket = EntityBucket.NOISE
    entityType: str = ""                # measure | dimension | time | filter
    classificationSignals: list[ClassificationSignal] = field(default_factory=list)
    classificationConfidence: float = 0.0
    sourceRefs: list[SourceRef] = field(default_factory=list)
    sourcePriority: int = 6
    aliases: list[str] = field(default_factory=list)
    unit: str | None = None
    valueDomain: dict[str, Any] = field(default_factory=dict)
    aggregation: str | None = None
    familyRef: str | None = None
    normalizationHints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rawText": self.rawText,
            "canonicalName": self.canonicalName,
            "bucket": self.bucket.value,
            "entityType": self.entityType,
            "classificationSignals": [s.to_dict() for s in self.classificationSignals],
            "classificationConfidence": self.classificationConfidence,
            "sourceRefs": [s.to_dict() for s in self.sourceRefs],
            "sourcePriority": self.sourcePriority,
            "aliases": list(self.aliases),
            "unit": self.unit,
            "valueDomain": dict(self.valueDomain),
            "aggregation": self.aggregation,
        }


@dataclass
class QuarantinedItem:
    text: str = ""
    reason: str = ""
    sourcePage: int | None = None
    sourceType: str = ""
    confidence: float = 0.0
    signals: list[ClassificationSignal] = field(default_factory=list)
    relatedEntities: list[str] = field(default_factory=list)
    recoverable: bool = False
    suggestedBucket: EntityBucket | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "text": self.text,
            "reason": self.reason,
            "sourceType": self.sourceType,
            "recoverable": self.recoverable,
        }
        if self.sourcePage is not None:
            d["sourcePage"] = self.sourcePage
        if self.suggestedBucket:
            d["suggestedBucket"] = self.suggestedBucket.value
        return d


@dataclass
class EntityHygieneResult:
    entities: list[SemanticEntity] = field(default_factory=list)
    topics: list[dict[str, Any]] = field(default_factory=list)
    glossary: list[dict[str, Any]] = field(default_factory=list)
    geographyMembers: list[dict[str, Any]] = field(default_factory=list)
    quarantine: list[QuarantinedItem] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entityCount": len(self.entities),
            "topicCount": len(self.topics),
            "glossaryCount": len(self.glossary),
            "geographyMemberCount": len(self.geographyMembers),
            "quarantineCount": len(self.quarantine),
            "diagnostics": self.diagnostics,
        }


@dataclass
class EntityClassificationContext:
    """Context for classification decisions."""
    source_priority: int = 6            # Default: vlm_freeform (lowest)
    source_type: str = "vlm_freeform_entity"
    page: int | None = None
    table_id: str | None = None
    nearby_entities: list[str] = field(default_factory=list)
    document_domain: str = ""           # energy | labour_force | ...


# ─────────────────────────────────────────────────────────────────────────────
# Detection patterns (signal families, NOT hardcoded blocklists)
# ─────────────────────────────────────────────────────────────────────────────

# OCR fragment patterns (broken word artifacts)
_OCR_PATTERNS = [
    # Two short words where second looks like a word fragment
    re.compile(r'^[A-Z][a-z]{1,6}\s+[a-z]{2,6}$'),
    # "X rves", "X ential" — space inside what should be one word
    re.compile(r'\b[a-z]{1,4}\s+[a-z]{3,}$'),
    # Contains "r \d+\.\d+" (partial table reference)
    re.compile(r'\br\s+\d+\.\d+'),
    # Very short with uppercase+lowercase mismatch
    re.compile(r'^[A-Z][a-z]+\s[a-z]{2,4}$'),
]

# Topic/heading indicator words
_TOPIC_INDICATORS = frozenset({
    "introduction", "overview", "highlights", "conclusion", "summary",
    "background", "objective", "methodology", "framework", "perspective",
    "classification", "global", "national", "international", "appendix",
    "annexure", "preface", "foreword", "acknowledgement",
})

# Heading suffix words (combined with another word = heading, not entity)
_HEADING_SUFFIXES = frozenset({
    "introduction", "overview", "management", "implementation",
    "development", "assessment", "classification", "perspective",
    "potential", "scenario", "policy", "programme",
})

# MoSPI measure keywords (signal, not rule)
_MEASURE_KEYWORDS = frozenset({
    "reserves", "production", "consumption", "capacity", "potential",
    "generation", "import", "export", "rate", "ratio", "percentage",
    "distribution", "share", "growth", "value", "quantity", "area",
    "population", "employment", "expenditure", "income", "output",
    "power", "energy", "installed", "estimated", "total",
})

# MoSPI dimension keywords
_DIMENSION_KEYWORDS = frozenset({
    "state", "states", "ut", "uts", "region", "district",
    "sector", "category", "type", "source", "fuel", "mineral",
    "gender", "age", "status", "class", "group", "commodity",
})

# Time patterns
_TIME_RE = re.compile(r'^(19|20)\d{2}(-\d{2,4})?$|^Q[1-4]\s+(19|20)\d{2}$|^FY\s*\d{4}')

# Unit patterns in text
_UNIT_INDICATORS = re.compile(r'\(%\)|\(MW\)|\(MT\)|\(BCM\)|\(crore\)|\(lakh\)', re.IGNORECASE)

# Geography patterns (common Indian geography terms)
_GEOGRAPHY_MEMBERS_RE = re.compile(
    r'^(Andhra Pradesh|Arunachal Pradesh|Assam|Bihar|Chhattisgarh|Goa|Gujarat|Haryana|'
    r'Himachal Pradesh|Jharkhand|Karnataka|Kerala|Madhya Pradesh|Maharashtra|Manipur|'
    r'Meghalaya|Mizoram|Nagaland|Odisha|Punjab|Rajasthan|Sikkim|Tamil Nadu|Telangana|'
    r'Tripura|Uttar Pradesh|Uttarakhand|West Bengal|Delhi|Chandigarh|Puducherry|'
    r'All India|India|Total|Grand Total)$',
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Rejection (is this noise?)
# ─────────────────────────────────────────────────────────────────────────────


def is_ocr_fragment(text: str) -> bool:
    """Detect broken OCR fragments that should never be entities."""
    if not text or len(text) < 4:
        return True
    
    # Partial table/figure references
    if re.search(r'\br\s+\d+\.\d+', text):
        return True
    if re.search(r'^\w+\s+of\s+r\s+\d', text, re.IGNORECASE):
        return True
    
    # Interior space creating two "words" where second is a fragment of the first
    # Pattern: "Word frag" where frag looks like a suffix/ending
    words = text.split()
    if len(words) == 2:
        w1, w2 = words
        # Second word is short lowercase fragment that could be a word ending
        if w2.islower() and len(w2) <= 7:
            # Common OCR-break suffixes
            if w2.endswith(("rves", "ential", "enewable", "istr", "ial", "tion", "ment")):
                return True
            # Second word is very short and doesn't look like a real word
            if len(w2) <= 4 and w2 not in ("and", "the", "for", "all", "per", "oil", "gas", "coal"):
                # Check if first word is capitalized and second is lowercase fragment
                if w1[0].isupper() and w2[0].islower():
                    return True

    # Multi-word with a very short word in the middle that's a fragment
    # "Energy Re enewable" — "Re" is too short to be meaningful alone between two real words
    if len(words) >= 3:
        for i, w in enumerate(words[1:-1], 1):
            if len(w) <= 2 and w[0].isupper() and words[i+1][0].islower():
                # Short capitalized fragment between words → likely OCR break
                return True
    
    # "Highlights of r 1.1 Coal Rese" — contains partial reference
    if re.search(r'\b[A-Z][a-z]+\s+of\s+r\b', text):
        return True
    
    # Truncated at word boundary — ends with uppercase start of a word
    if re.search(r'\b[A-Z][a-z]{1,4}$', text) and len(text) > 10:
        # "Geographical Distr" — last word is truncated (< 5 chars, not a real word)
        last_word = words[-1] if words else ""
        if last_word and len(last_word) <= 5 and last_word not in (
            "Coal", "Gas", "Oil", "Wind", "Area", "Rate", "Per", "All", "MW", "MT",
            "Total", "India", "Urban", "Rural", "State", "Power", "Solar",
        ):
            return True
    
    return False


def is_topic_heading(text: str) -> bool:
    """Detect section/chapter headings that should be topics, not entities."""
    if not text:
        return False
    text_lower = text.lower().strip()
    words = text_lower.split()

    # Chapter/section prefix
    if re.match(r'^(chapter|section|part)\s+\d', text_lower):
        return True

    # Single topic word
    if text_lower in _TOPIC_INDICATORS:
        return True

    # "X Introduction", "X Overview" patterns
    if len(words) >= 2 and words[-1] in _HEADING_SUFFIXES:
        return True

    # "X and Y" or "X of Y" with topic words
    if len(words) <= 8 and any(w in _TOPIC_INDICATORS for w in words):
        # Allow topic classification even with measure/dimension words
        # if the topic keyword is a strong structural indicator
        topic_hits = [w for w in words if w in _TOPIC_INDICATORS]
        strong_topic = any(w in ("classification", "introduction", "overview", "summary",
                                  "methodology", "framework", "background") for w in topic_hits)
        if strong_topic:
            return True
        # Weaker topic words require NO measure/dimension words
        if not any(w in _MEASURE_KEYWORDS | _DIMENSION_KEYWORDS for w in words):
            return True

    # Long noun phrase with no measure/dimension signal (>4 words, all abstract)
    if len(words) > 4 and not any(w in _MEASURE_KEYWORDS | _DIMENSION_KEYWORDS for w in words):
        if all(w.isalpha() or w in ("and", "of", "the", "in", "for") for w in words):
            return True

    return False


def _is_too_short(text: str) -> bool:
    return len(text.strip()) < 3


def _is_too_long(text: str) -> bool:
    return len(text.strip()) > 80


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Classification (signal-based bucket scoring)
# ─────────────────────────────────────────────────────────────────────────────


def infer_entity_bucket(
    text: str,
    context: EntityClassificationContext,
) -> tuple[EntityBucket, list[ClassificationSignal]]:
    """Classify an entity candidate using multi-signal scoring.

    Returns (best_bucket, signals).
    """
    text_lower = text.lower().strip()
    words = text_lower.split()
    signals: list[ClassificationSignal] = []

    # Score accumulators per bucket
    scores: dict[EntityBucket, float] = {b: 0.0 for b in EntityBucket}

    # ── Source priority signal ──
    if context.source_priority <= 1:
        signals.append(ClassificationSignal("source_priority", 0.4, "context", f"priority={context.source_priority}"))
        # Table headers are very likely measure/dimension
        scores[EntityBucket.TABLE_HEADER] += 0.4
    elif context.source_priority <= 3:
        signals.append(ClassificationSignal("source_priority", 0.2, "context", f"priority={context.source_priority}"))
        scores[EntityBucket.CHART_LABEL] += 0.2

    # ── Measure keyword signal ──
    measure_hits = [w for w in words if w in _MEASURE_KEYWORDS]
    if measure_hits:
        score = min(0.35, len(measure_hits) * 0.15)
        signals.append(ClassificationSignal("measure_keyword", score, "pattern", f"hits={measure_hits}"))
        scores[EntityBucket.ANALYTIC_MEASURE] += score

    # ── Dimension keyword signal ──
    dim_hits = [w for w in words if w in _DIMENSION_KEYWORDS]
    if dim_hits:
        score = min(0.35, len(dim_hits) * 0.15)
        signals.append(ClassificationSignal("dimension_keyword", score, "pattern", f"hits={dim_hits}"))
        scores[EntityBucket.ANALYTIC_DIMENSION] += score

    # ── Unit/percent pattern ──
    if _UNIT_INDICATORS.search(text) or "%" in text:
        signals.append(ClassificationSignal("unit_pattern", 0.2, "pattern", "contains unit indicator"))
        scores[EntityBucket.ANALYTIC_MEASURE] += 0.2

    # ── Time pattern ──
    if _TIME_RE.match(text.strip()):
        signals.append(ClassificationSignal("time_pattern", 0.5, "pattern", "matches year/period"))
        scores[EntityBucket.TIME_PERIOD] += 0.5

    # ── Geography member ──
    if _GEOGRAPHY_MEMBERS_RE.match(text.strip()):
        signals.append(ClassificationSignal("geography_pattern", 0.5, "pattern", "known geography member"))
        scores[EntityBucket.GEOGRAPHY_MEMBER] += 0.5

    # ── Topic heading signal ──
    if any(w in _TOPIC_INDICATORS for w in words):
        score = 0.3
        signals.append(ClassificationSignal("topic_keyword", score, "pattern", "contains topic indicator"))
        scores[EntityBucket.TOPIC_HEADING] += score

    # ── Slash/UT pattern → dimension ──
    if "/" in text or "UT" in text.upper():
        signals.append(ClassificationSignal("slash_ut_pattern", 0.15, "pattern", "contains / or UT"))
        scores[EntityBucket.ANALYTIC_DIMENSION] += 0.15

    # ── Source type boost ──
    if context.source_type == "pdfplumber_table_header":
        scores[EntityBucket.ANALYTIC_MEASURE] += 0.15
        scores[EntityBucket.ANALYTIC_DIMENSION] += 0.15
    elif context.source_type in ("section_heading", "vlm_freeform_entity"):
        scores[EntityBucket.TOPIC_HEADING] += 0.1

    # ── Pick best bucket ──
    # TABLE_HEADER is an intermediate — resolve to measure or dimension
    if scores[EntityBucket.TABLE_HEADER] > 0:
        if scores[EntityBucket.ANALYTIC_MEASURE] >= scores[EntityBucket.ANALYTIC_DIMENSION]:
            scores[EntityBucket.ANALYTIC_MEASURE] += scores[EntityBucket.TABLE_HEADER]
        else:
            scores[EntityBucket.ANALYTIC_DIMENSION] += scores[EntityBucket.TABLE_HEADER]
        scores[EntityBucket.TABLE_HEADER] = 0

    best_bucket = max(scores, key=lambda b: scores[b])
    best_score = scores[best_bucket]

    # If no strong signal, default based on source
    if best_score < 0.15:
        if context.source_priority <= 1:
            best_bucket = EntityBucket.ANALYTIC_MEASURE
            best_score = 0.3
        else:
            best_bucket = EntityBucket.NOISE
            best_score = 0.1

    return best_bucket, signals


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3: Routing + main entry
# ─────────────────────────────────────────────────────────────────────────────


def classify_entity_candidate(
    candidate: dict[str, Any],
    context: EntityClassificationContext | None = None,
) -> SemanticEntity | QuarantinedItem:
    """Classify one entity candidate into a SemanticEntity or QuarantinedItem."""
    if context is None:
        context = EntityClassificationContext()

    text = (candidate.get("canonicalName") or candidate.get("name") or candidate.get("text") or "").strip()
    source_type = candidate.get("sourceType") or candidate.get("source") or context.source_type

    # Update context from candidate metadata
    ctx = EntityClassificationContext(
        source_priority=candidate.get("sourcePriority", context.source_priority),
        source_type=source_type,
        page=candidate.get("page", context.page),
        table_id=candidate.get("tableId", context.table_id),
        document_domain=context.document_domain,
    )

    def _candidate_refs(default_source: str | None = None, default_confidence: float = 0.85) -> list[SourceRef]:
        refs: list[SourceRef] = []
        for ref in candidate.get("sourceRefs") or []:
            if not isinstance(ref, dict):
                continue
            refs.append(SourceRef(
                sourceType=str(ref.get("sourceType") or default_source or source_type),
                tableId=ref.get("tableId"),
                figureId=ref.get("figureId"),
                regionRef=ref.get("regionRef") or ref.get("regionId"),
                page=ref.get("page", ctx.page),
                bbox=list(ref.get("bbox") or []),
                headerPath=list(ref.get("headerPath") or []),
                physicalColumn=ref.get("physicalColumn"),
                confidence=float(ref.get("confidence", default_confidence)),
            ))
        if refs:
            return refs
        return [SourceRef(
            sourceType=default_source or ctx.source_type,
            page=ctx.page,
            tableId=ctx.table_id,
            confidence=default_confidence,
        )]

    # ── Stage 0: Domain-pack / pre-seeded entity protection ──
    # These entities are domain-authoritative and skip all rejection gates.
    # They preserve their stated entityType, unit, aliases, and valueDomain.
    if source_type in ("domain_pack", "pre_seeded"):
        stated_type = candidate.get("entityType") or ""
        _ETYPE_BUCKET = {
            "measure": EntityBucket.ANALYTIC_MEASURE,
            "dimension": EntityBucket.ANALYTIC_DIMENSION,
            "time": EntityBucket.TIME_PERIOD,
            "metadata": EntityBucket.ANALYTIC_DIMENSION,  # route to entities, not glossary
        }
        bucket = _ETYPE_BUCKET.get(stated_type, EntityBucket.ANALYTIC_MEASURE)
        signals = [ClassificationSignal("domain_pack_protected", 0.95, source_type, f"entityType={stated_type}")]
        return SemanticEntity(
            rawText=text,
            canonicalName=text,
            bucket=bucket,
            entityType=stated_type or "measure",
            classificationSignals=signals,
            classificationConfidence=0.95,
            sourcePriority=0,
            sourceRefs=_candidate_refs(source_type, 0.95),
            aliases=candidate.get("aliases") or [],
            unit=candidate.get("unit"),
            valueDomain=candidate.get("valueDomain") or {},
        )

    # ── Stage 1: Reject noise ──
    if _is_too_short(text):
        return QuarantinedItem(text=text, reason="TOO_SHORT", sourceType=source_type, recoverable=False)

    if _is_too_long(text):
        return QuarantinedItem(text=text, reason="TOO_LONG", sourceType=source_type,
                              recoverable=True, suggestedBucket=EntityBucket.TOPIC_HEADING)

    if is_ocr_fragment(text):
        return QuarantinedItem(text=text, reason="OCR_FRAGMENT", sourceType=source_type,
                              confidence=0.1, recoverable=False)

    # ── Stage 1b: Route headings to topics ──
    if is_topic_heading(text):
        # Still create a SemanticEntity but with TOPIC_HEADING bucket
        signals = [ClassificationSignal("topic_heading_detected", 0.8, "hygiene", text)]
        return SemanticEntity(
            rawText=text,
            canonicalName=text,
            bucket=EntityBucket.TOPIC_HEADING,
            entityType="",
            classificationSignals=signals,
            classificationConfidence=0.8,
            sourcePriority=ctx.source_priority,
            sourceRefs=_candidate_refs(ctx.source_type),
        )

    # ── Stage 2: Signal-based classification ──
    bucket, signals = infer_entity_bucket(text, ctx)

    # Determine entityType from bucket
    entity_type = ""
    if bucket == EntityBucket.ANALYTIC_MEASURE:
        entity_type = "measure"
    elif bucket == EntityBucket.ANALYTIC_DIMENSION:
        entity_type = "dimension"
    elif bucket == EntityBucket.TIME_PERIOD:
        entity_type = "time"
    elif bucket == EntityBucket.GEOGRAPHY_MEMBER:
        entity_type = "dimension"
    elif bucket == EntityBucket.CHART_LABEL:
        entity_type = "measure"

    # Detect unit from text
    unit = None
    if "(%)" in text or "percent" in text.lower():
        unit = "percent"
    elif "(MW)" in text.upper():
        unit = "MW"
    elif "(MT)" in text.upper():
        unit = "million_tonnes"
    elif "(BCM)" in text.upper():
        unit = "billion_cubic_metres"

    # Clean canonical name (remove unit suffixes for cleaner names)
    canonical = text.strip()
    canonical = re.sub(r'\s*\([^)]*\)\s*$', '', canonical).strip()  # Remove trailing (...)
    if not canonical:
        canonical = text.strip()

    confidence = sum(s.score for s in signals) / max(len(signals), 1)

    return SemanticEntity(
        rawText=text,
        canonicalName=canonical,
        bucket=bucket,
        entityType=entity_type,
        classificationSignals=signals,
        classificationConfidence=min(confidence, 1.0),
        sourcePriority=ctx.source_priority,
        sourceRefs=_candidate_refs(ctx.source_type),
        unit=unit,
    )


def run_entity_hygiene(
    candidates: list[dict[str, Any]],
    context: EntityClassificationContext | None = None,
) -> EntityHygieneResult:
    """Main entry: classify all entity candidates.

    Args:
        candidates: Raw entity dicts from extraction (with canonicalName, entityType, etc.)
        context: Default classification context for candidates without metadata.

    Returns:
        EntityHygieneResult with routed entities, topics, glossary, quarantine.
    """
    if context is None:
        context = EntityClassificationContext()

    result = EntityHygieneResult()

    for candidate in candidates:
        classified = classify_entity_candidate(candidate, context)

        if isinstance(classified, QuarantinedItem):
            result.quarantine.append(classified)
            continue

        # Route by bucket
        if classified.bucket == EntityBucket.TOPIC_HEADING:
            result.topics.append({"title": classified.canonicalName, "rawText": classified.rawText})
        elif classified.bucket == EntityBucket.GLOSSARY_CONCEPT:
            result.glossary.append({"term": classified.canonicalName, "rawText": classified.rawText})
        elif classified.bucket == EntityBucket.GEOGRAPHY_MEMBER:
            result.geographyMembers.append({"name": classified.canonicalName, "rawText": classified.rawText})
        elif classified.bucket == EntityBucket.NOISE:
            result.quarantine.append(QuarantinedItem(
                text=classified.rawText, reason="LOW_SIGNAL_NOISE",
                sourceType=classified.sourceRefs[0].sourceType if classified.sourceRefs else "",
                recoverable=True, suggestedBucket=None,
            ))
        else:
            # Analytic entity (measure, dimension, time, chart_label, table_header)
            result.entities.append(classified)

    # Build diagnostics
    result.diagnostics = {
        "inputCount": len(candidates),
        "entityCount": len(result.entities),
        "topicCount": len(result.topics),
        "glossaryCount": len(result.glossary),
        "geographyMemberCount": len(result.geographyMembers),
        "quarantineCount": len(result.quarantine),
        "survivalRate": len(result.entities) / max(len(candidates), 1),
    }

    return result
