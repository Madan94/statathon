# MoSPI Template Compiler — Peak Standard Implementation Plan v2

> **Goal:** Transform extraction from "PDF parser producing noisy entities" into a **MoSPI Template Compiler** — a deterministic pipeline that compiles PDF structure into binder-ready, value-free, semantically rich template artifacts.  
> **Current score:** 6.2–6.8/10  
> **Target score:** 9+/10  
> **Branch:** `report-builder-ui`  
> **Contract version:** `template.extraction.v2`

---

## Table of Contents

1. [Central Design: TemplateSemanticGraph](#central-design-templatesemantic-graph)
2. [Phase E0: Extraction Contract + Schema Versioning](#phase-e0-extraction-contract--schema-versioning)
3. [Phase E1: Entity Hygiene Compiler](#phase-e1-entity-hygiene-compiler)
4. [Phase E2: Canonical Entity Normalization + Measure Families](#phase-e2-canonical-entity-normalization--measure-families)
5. [Phase E3: Table Header Semantic Compiler](#phase-e3-table-header-semantic-compiler)
6. [Phase E4: Statistical Context Extraction + Inheritance](#phase-e4-statistical-context-extraction--inheritance)
7. [Phase E5: Semantic Entity ID Generator](#phase-e5-semantic-entity-id-generator)
8. [Phase E6: Alias & ValueDomain Enrichment](#phase-e6-alias--valuedomain-enrichment)
9. [Phase E7: Question Compiler + Deterministic Templates](#phase-e7-question-compiler--deterministic-templates)
10. [Phase E8: Slot Wiring Validator + Layout Policy](#phase-e8-slot-wiring-validator--layout-policy)
11. [Phase E9: Extraction Diagnostics + Pass Scoring](#phase-e9-extraction-diagnostics--pass-scoring)
12. [Phase E10: Energy Gold Standard + Regression Tests](#phase-e10-energy-gold-standard--regression-tests)
13. [Phase E11: Chart/Figure Semantic Compiler](#phase-e11-chartfigure-semantic-compiler)
14. [Phase E12: Value-Free Contract Validator (Hard Gate)](#phase-e12-value-free-contract-validator-hard-gate)
15. [Phase E13: Extraction→Binder E2E Integration Test](#phase-e13-extractionbinder-e2e-integration-test)
16. [Implementation Order](#implementation-order)
17. [Peak Standard Checklist](#peak-standard-checklist)

---

## Central Design: TemplateSemanticGraph

The biggest architectural improvement. Instead of loose dicts flowing between modules, ALL extraction phases compile into a **single canonical intermediate representation**.

### Why

Without a shared graph:
- Each module passes loose dicts → quality drifts
- No single place to inspect full semantic state
- Hard to validate cross-references
- Hard to debug which pass introduced an error

### The Graph

```python
@dataclass
class TemplateSemanticGraph:
    """Central intermediate representation for the MoSPI Template Compiler.
    
    Every extraction phase reads from and writes to this graph.
    Final emission (template.ast.json + template.blueprint.json) reads ONLY from this graph.
    """
    # Document-level
    document: DocumentContext
    chapters: list[ChapterNode]
    sections: list[SectionNode]
    
    # Structural
    tables: list[TableSemanticModel]
    figures: list[FigureSemanticModel]
    
    # Semantic
    entities: list[SemanticEntity]
    measureFamilies: list[MeasureFamily]
    
    # Analytic
    topics: list[TopicPlan]
    questions: list[QuestionPlan]
    
    # Context
    statisticalContext: MoSPIStatisticalContext
    
    # Audit
    quarantine: list[QuarantinedItem]
    diagnostics: ExtractionDiagnostics
    passScores: dict[str, float]

@dataclass
class DocumentContext:
    documentId: str
    title: str
    domain: str                   # energy | labour_force | agriculture | trade | finance
    ministry: str
    publicationYear: str
    locale: str
    sourceFile: str

@dataclass
class ChapterNode:
    chapterId: str
    number: int
    title: str
    pageRange: tuple[int, int]
    sections: list[str]           # section IDs

@dataclass
class SectionNode:
    sectionId: str
    title: str
    chapterRef: str
    pageRange: tuple[int, int]
    tableRefs: list[str]
    figureRefs: list[str]
    topicRef: str | None          # linked topic in analytic plan
```

### Pipeline Flow

```
Pass 0-2: raw PDF signals
    ↓
Pass 2.5: Build TemplateSemanticGraph (entity hygiene, table semantics, context)
    ↓
Pass 3: Enrich graph (questions, answer structures)
    ↓
Pass 4: Emit from graph → template.ast.json + template.blueprint.json
    ↓
Pass 4.5: Validate graph + score diagnostics
    ↓
Pass 5 (optional): LLM enrichment of graph (aliases, domain detection)
    ↓
Final emit: Write validated artifacts
```

### Key Property

> **Nothing touches the final JSON directly. Everything modifies the TemplateSemanticGraph. Emission is a pure read from the graph.**

This makes validation, debugging, and testing dramatically easier.

---

## Phase E0: Extraction Contract + Schema Versioning

**Location:** `report_builder/extraction_contracts.py`  
**Effort:** 1.5 days  
**Priority:** Week 1 (must be first — defines the compile target)

### Why first

Every subsequent module needs to know what shape it must produce. Without a formal contract, each phase invents its own dict shape and quality drifts.

### Contract version

```python
EXTRACTION_CONTRACT_VERSION = "template.extraction.v2"
BINDER_MIN_BLUEPRINT_VERSION = "bharatstat/template-blueprint/v1"
```

### Compatibility modes

```python
class ExtractionMode(Enum):
    STRICT = "strict"     # Production: all gates must pass, no fallback
    WARN = "warn"         # Development: log failures, continue
    LEGACY = "legacy"     # Accept old outputs with warnings (migration)
```

### Entity contract (peak shape)

```python
@dataclass
class ExtractionEntityContract:
    """The FULL entity shape extraction must produce for binder to work optimally."""
    
    # Identity
    entityId: str               # Semantic slug: ent_proved_reserves
    canonicalName: str          # "Proved Reserves" (year-free, unit-free)
    entityType: str             # measure | dimension | time | filter
    
    # Binding support
    aliases: list[str]          # At least 2 for core entities
    unit: str | None            # Required for measures where inferable
    format: str | None          # percent.1, number.2, etc.
    valueDomain: dict           # {kind, min?, max?, members?, expectedCardinality?}
    aggregation: str | None     # sum | mean | weighted_ratio | reported_value | count
    
    # Context
    scope: str                  # indicator | classifier | geography | temporal
    cardinalityHint: str        # low | medium | high | open
    
    # Provenance (WHERE this entity was found)
    sourceRefs: list[dict]      # [{sourceType, tableId, page, headerPath, physicalColumn}]
    
    # Why this was classified as this type
    roleEvidence: list[dict]    # [{signal, score, detail}]
    
    # Known concerns
    riskFlags: list[dict]       # [{code, severity, message}]
    
    # Measure family membership (if part of a family)
    familyRef: str | None       # "mf_reserves_by_category"
    
    # Normalization hints for binder
    normalizationHints: dict    # {wide: bool, periodColumns: [], memberColumns: []}
    
    # Confidence
    confidence: float | None
```

### Question contract (peak shape)

```python
@dataclass
class ExtractionQuestionContract:
    """Every question must be compilable to QuestionExecutionPlan."""
    
    questionId: str             # Semantic: q_coal_reserves_state
    intent: str                 # Clear, specific analytical intent (8+ words)
    questionType: str           # comparison | trend | composition | ranking | summary
    
    # Entity bindings (all must resolve to real entities)
    requiredEntities: list[dict]  # [{entityId, role, required, defaultMember?}]
    
    # Execution spec (resolved to entity refs, not columns yet)
    analyticsSpec: dict         # {operation, measure, groupBy, filters, sort, topN}
    
    # Output shape
    answerStructure: dict       # {components: [{componentId, kind, order, outputContract}]}
    
    # Provenance
    sourceTable: str | None     # tableId this question is derived from
    generationMethod: str       # "table_pattern" | "llm" | "manual"
    
    # Budget tracking
    priority: int               # 1-5 (lower = higher priority)
```

### Blueprint contract

```python
@dataclass
class ExtractionBlueprintContract:
    """The complete template.blueprint.json shape."""
    
    # Schema
    schema: str                 # "bharatstat/template-blueprint/v1"
    contractVersion: str        # "template.extraction.v2"
    
    # Metadata
    templateMeta: dict          # {templateId, name, domain, locale, version, sourceDocument}
    
    # Core
    entities: list[ExtractionEntityContract]
    measureFamilies: list[dict]  # Concept family groupings
    topics: list[dict]          # [{topicId, title, questions[]}]
    
    # Templates
    tableTemplates: list[dict]  # Full table semantic models
    figureTemplates: list[dict] # Chart/figure semantic models
    
    # Context
    glossary: dict
    palette: dict
    renderProfile: dict
    documentMap: dict
    statisticalContext: dict    # {sourceDocument, chapter, referenceDate, footnotes}
    
    # Diagnostics (bundled for binder pre-check)
    extractionDiagnostics: dict
```

### Validation function

```python
def validate_extraction_contract(
    blueprint: dict,
    mode: ExtractionMode = ExtractionMode.STRICT,
) -> ExtractionValidationResult:
    """
    Validate blueprint against contract. Returns structured result.
    
    In STRICT mode: any error → reject.
    In WARN mode: errors become warnings, always passes.
    In LEGACY mode: missing fields backfilled with defaults.
    """
```

### JSON Schema export

```python
def export_json_schema() -> dict:
    """Generate JSON Schema from contract dataclasses for external validation."""
```

### Acceptance criteria

- [ ] Every module in E1-E13 writes to TemplateSemanticGraph using contract types
- [ ] `validate_extraction_contract()` runs before file emission
- [ ] Contract is versioned and backwards-compatible
- [ ] Binder's BlueprintQA passes on any blueprint that passes this contract
- [ ] Round-trip test: contract → to_dict → from_dict → validate

---

## Phase E1: Entity Hygiene Compiler

**Location:** `report_builder/entity_hygiene.py`  
**Effort:** 3 days  
**Priority:** Week 1 (biggest single impact)

### Architecture

A two-stage pipeline: **Reject** → **Classify** → **Evidence**

```
raw entity candidates (from Pass 0-2)
  ↓
Stage 1: Enhanced rejection (hard rules + learned patterns)
  ↓  [quarantined with reasons]
Stage 2: Semantic bucket classification
  ↓  [each survivor gets a bucket + confidence]
Stage 3: Role evidence generation
  ↓  [each entity explains WHY it's that type]
Output: SemanticEntity[] on the graph
```

### Stage 1: Rejection (extends current D1 system)

The current `_classify_entity_name()` handles 54 patterns. Add these:

```python
# Adaptive rejection signals (NOT hardcoded blocklists)
# These are PATTERN FAMILIES that catch variations

REJECTION_PATTERNS = {
    "truncated_fragment": {
        # Detects broken OCR where a word is split mid-syllable
        "signal": lambda s: (
            len(s.split()) == 2 and
            len(s) < 25 and
            any(len(w) <= 4 for w in s.split()) and
            not _is_known_short_entity(s)
        ),
        "examples": ["India rves", "Potential ential", "Energy Re enewable"],
    },
    
    "heading_as_entity": {
        # Headings contain topic-words but are NOT measurable concepts
        "signal": lambda s: (
            any(w in s.lower() for w in _TOPIC_INDICATOR_WORDS) and
            len(s.split()) <= 4 and
            not _is_table_header_match(s)
        ),
        "examples": ["Energy Introduction", "Potential Introduction", "Global Classification"],
    },
    
    "composite_fragment": {
        # Two capitalized words where second is a common heading suffix
        "signal": lambda s: (
            bool(re.match(r'^[A-Z][a-z]+\s+[A-Z][a-z]+(?:tion|ment|ence|ness)$', s)) and
            s.split()[-1].lower() in _HEADING_SUFFIX_WORDS
        ),
        "examples": ["Energy Introduction", "Resource Management", "Policy Implementation"],
    },
    
    "partial_table_reference": {
        # Contains table/figure number fragments
        "signal": lambda s: bool(re.search(r'\d+\.\d+\s+[A-Z]', s)) or "r 1." in s.lower(),
        "examples": ["Highlights of r 1.1 Coal Rese", "Table 1.2 shows"],
    },
}

# NOT hardcoded lists — these are SEMANTIC CATEGORIES that adapt
_TOPIC_INDICATOR_WORDS = {
    "introduction", "overview", "highlights", "conclusion", "summary",
    "background", "objective", "methodology", "framework", "perspective",
    "classification", "global", "national", "international",
}

_HEADING_SUFFIX_WORDS = {
    "introduction", "overview", "management", "implementation",
    "development", "assessment", "classification", "perspective",
}
```

**Key principle: NOT hardcoded blocklists but pattern families with examples.** The system learns rejection patterns from the quarantine log over time.

### Stage 2: Semantic Bucket Classification

```python
class EntityBucket(Enum):
    ANALYTIC_MEASURE = "measure"
    ANALYTIC_DIMENSION = "dimension"
    TIME_PERIOD = "time"
    GEOGRAPHY_MEMBER = "geography_value"  # Value, not entity
    TABLE_HEADER = "table_header"
    CHART_LABEL = "chart_label"
    TOPIC_HEADING = "topic"
    GLOSSARY_CONCEPT = "glossary"
    NOISE = "noise"
```

**Classification is signal-based, not rule-based.** Each candidate accumulates signals:

```python
@dataclass
class ClassificationSignal:
    signal: str          # "table_header_match", "measure_keyword", "numeric_context"
    score: float         # 0.0 - 1.0
    source: str          # "pdfplumber", "vlm", "pattern", "context"
    detail: str          # Human-readable explanation

def classify_entity(
    candidate: str,
    source_priority: int,
    context: EntityClassificationContext,
) -> tuple[EntityBucket, list[ClassificationSignal]]:
    """
    Multi-signal classification. NOT a decision tree — a scoring system.
    
    Signals are accumulated, then the highest-scoring bucket wins.
    Ties go to the more conservative bucket (topic > entity if unsure).
    """
```

### Source Priority (from extraction provenance)

```python
SOURCE_PRIORITIES = {
    0: "pdfplumber_table_header",      # Gold: actual table column header
    1: "pdfplumber_merged_header",     # Multi-row merged header
    2: "chart_axis_label",             # VLM-detected chart axis
    3: "chart_legend_label",           # VLM-detected legend
    4: "table_title_entity",           # Entity extracted from table title
    5: "section_heading",              # LayoutLM section heading
    6: "vlm_freeform_entity",          # VLM generic entity extraction
}
```

**Rule:** Only Priority 0-3 candidates become analytic entities directly. Priority 4-6 must have additional corroborating signals.

### Stage 3: Role Evidence

Every entity that passes classification gets evidence explaining WHY:

```python
@dataclass
class SemanticEntity:
    """Entity with full provenance and classification evidence."""
    entityId: str                        # Generated in E5
    canonicalName: str
    bucket: EntityBucket
    entityType: str                      # measure | dimension | time
    
    # Classification evidence (why this bucket)
    classificationSignals: list[ClassificationSignal]
    classificationConfidence: float
    
    # Source provenance (where found)
    sourceRefs: list[SourceRef]
    sourcePriority: int                  # Best source priority
    
    # Quarantine candidates (near-misses that were dropped)
    relatedQuarantined: list[str]        # IDs in quarantine log
    
    # Downstream fields (populated by later phases)
    aliases: list[str]
    unit: str | None
    valueDomain: dict
    aggregation: str | None
    familyRef: str | None
    normalizationHints: dict

@dataclass
class SourceRef:
    sourceType: str              # "table_header" | "chart_axis" | "vlm_entity" | ...
    tableId: str | None
    page: int
    headerPath: list[str]        # ["Coal Reserves", "Proved", "2025"]
    physicalColumn: str | None   # The actual column name in source table
    confidence: float
```

### Quarantine (reversible, auditable)

Nothing is silently dropped. Everything rejected goes to quarantine with full context:

```python
@dataclass
class QuarantinedItem:
    text: str
    reason: str                  # Pattern family that triggered rejection
    sourcePage: int
    sourceType: str              # "vlm_entity" | "heading" | etc.
    confidence: float
    signals: list[ClassificationSignal]
    relatedEntities: list[str]   # What valid entities are nearby (for debugging)
    
    # Recovery: if quarantine was wrong, human can promote to entity
    recoverable: bool
    suggestedBucket: EntityBucket | None
```

### Acceptance criteria

- [ ] Zero OCR fragments in blueprint.entities
- [ ] "Energy Introduction" → topicPlan, NOT entity
- [ ] "States/UTs", "Proved", "Distribution (%)" → entities with evidence
- [ ] Quarantine log explains every rejection (debuggable)
- [ ] Source priority respected (table headers win over VLM guesses)
- [ ] Each entity has 2+ classification signals explaining its type

---

## Phase E2: Canonical Entity Normalization + Measure Families

**Location:** `report_builder/entity_normalizer.py`  
**Effort:** 2 days  
**Priority:** Week 2

### Problem

Year-suffixed headers become separate entities. But MoSPI often has **concept families** where related measures share structure.

### Year/Period Extraction

```python
def extract_period_from_name(name: str) -> tuple[str, str | None]:
    """
    "Proved 2025" → ("Proved", "2025")
    "Value 2023-24" → ("Value", "2023-24")
    "Production (2024–25)" → ("Production", "2024-25")
    "LFPR" → ("LFPR", None)  # No period
    """
    # Adaptive patterns — not a single regex
    patterns = [
        re.compile(r'^(.+?)\s+((?:19|20)\d{2}(?:[-–]\d{2,4})?)$'),
        re.compile(r'^(.+?)\s*\(((?:19|20)\d{2}(?:[-–]\d{2,4})?)\)$'),
        re.compile(r'^(.+?)\s+(Q[1-4]\s+(?:19|20)\d{2})$'),
    ]
    for p in patterns:
        m = p.match(name)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return name, None
```

### Canonical Normalization

```python
def normalize_entities(
    entities: list[SemanticEntity],
    table_structures: list[TableSemanticModel],
) -> NormalizationResult:
    """
    1. Group entities by canonical stem (year-free, unit-free)
    2. Detect period dimension if any entity had year suffix
    3. Detect unit suffix → move to unit field
    4. Merge singular/plural: "State" / "States" → one entity
    5. Detect measure families
    6. Deduplicate across tables (same concept, different pages)
    """
```

### Measure Family Model

MoSPI tables often have related measures that can be modeled two ways:

```
Coal Reserves table:
  Proved | Indicated | Inferred | Total | Distribution (%)
```

This is a **measure family**:

```python
@dataclass
class MeasureFamily:
    """A group of related measures that share a common domain.
    
    Binder uses this to decide:
    - multi_measure_composition (treat as N separate measures)
    - group_aggregate by category (treat as 1 measure + 1 category dimension)
    """
    familyId: str                    # "mf_coal_reserves_by_category"
    baseConcept: str                 # "Coal Reserves"
    categoryDimension: str | None    # "ent_reserve_category" (if dimension modeling)
    members: list[MeasureFamilyMember]
    modelingAdvice: str              # "separate_measures" | "category_dimension" | "both"
    normalizationHint: str           # "WIDE_TO_LONG" | "NONE"

@dataclass
class MeasureFamilyMember:
    label: str                       # "Proved"
    entityRef: str                   # "ent_proved_reserves"
    isTotal: bool                    # True for "Total" (should not be summed)
    isDerived: bool                  # True for "Distribution (%)" (computed from others)
    unit: str | None                 # If different from family default
```

### When to use which model

```python
def decide_family_modeling(family: MeasureFamily, table: TableSemanticModel) -> str:
    """
    Heuristics (not hardcoded rules — signal-based):
    
    - If all members share same unit and are additive → "category_dimension"
      (e.g., Proved + Indicated + Inferred = Total → melt to reserve_category)
    
    - If members have DIFFERENT units → "separate_measures"
      (e.g., Production (MT) vs Distribution (%) → keep separate)
    
    - If table has period columns crossed with members → "both"
      (e.g., Proved 2024, Proved 2025, Indicated 2024 → needs category + period)
    
    The binder's S3 plan compiler uses modelingAdvice to choose NormalizationPlan.
    """
```

### Integration with TemplateSemanticGraph

```python
# After normalization, graph is updated:
graph.entities = normalized.canonical_entities
graph.measureFamilies = normalized.families
if normalized.period_entity:
    graph.entities.append(normalized.period_entity)
```

### Acceptance criteria

- [ ] "Proved 2024" + "Proved 2025" → one `ent_proved_reserves` + `ent_period`
- [ ] "Distribution (%)" → `ent_distribution_percent` with `unit="percent"`, flagged as `isDerived`
- [ ] Measure families detected for reserve tables
- [ ] `modelingAdvice` guides binder's NormalizationPlan
- [ ] Column groups preserved for table templates
- [ ] No information loss (physical column names in table template's columnSpecs)

---

## Phase E3: Table Header Semantic Compiler

**Location:** `report_builder/table_semantic_compiler.py`  
**Effort:** 4 days  
**Priority:** Week 2

### Architecture

```
pdfplumber raw table → TableCandidateClassifier → (REAL_TABLE only)
  → Header Hierarchy Parser → Column Semantics → Entity Linking → Unit Inheritance
  → TableSemanticModel
```

### Step 0: Table Candidate Classification (Ghost Filter)

Before any semantic work, classify whether a detected "table" is real:

```python
class TableClass(Enum):
    REAL_TABLE = "real"           # Statistical data table
    GHOST_TABLE = "ghost"         # Empty/near-empty bbox detection
    LAYOUT_GRID = "layout"       # Page layout structure, not data
    FORM_BOX = "form"            # Application form / questionnaire
    TOC_TABLE = "toc"            # Table of contents
    INDEX_TABLE = "index"        # Back-of-book index

def classify_table_candidate(
    table_data: dict,
    page_context: dict,
) -> TableClass:
    """
    Signal-based classification:
    
    Signals for REAL_TABLE:
    - fill_ratio > 0.40 (cells with content)
    - numeric_cell_ratio > 0.25 (actual data)
    - has_header_row (text in first row, numbers below)
    - has_table_title_nearby
    - reasonable dimensions (3+ cols, 3+ rows)
    
    Signals for GHOST_TABLE:
    - fill_ratio < 0.10
    - mostly blank cells
    - very large bbox relative to content
    
    Signals for LAYOUT_GRID:
    - uniform cell sizes
    - no numeric content
    - text is navigational ("Chapter 1", "Page 12")
    """
```

### Step 1: Header Hierarchy Parser

```python
@dataclass
class HeaderNode:
    """One node in the header hierarchy tree."""
    text: str
    role: str               # "dimension" | "measure_group" | "period" | "unit_note" | "total"
    children: list["HeaderNode"]
    span: int               # How many leaf columns this spans
    entityRef: str | None   # Linked entity (after E2 normalization)
    unit: str | None        # If this header carries unit info
    footnoteMarkers: list[str]  # ["*", "#", "@"]

def parse_header_hierarchy(
    raw_headers: list[list[str]],
    table_bbox: dict,
) -> list[HeaderNode]:
    """
    Handles MoSPI complexities:
    
    1. Multi-row headers (pdfplumber merges spanning cells)
    2. Blank cells → inherit parent label
    3. Repeated parent text → merge into spanning group
    4. Year patterns in leaf row → period children
    5. Unit in parentheses → extract to unit field, clean header text
    6. Footnote markers (*, #, @, P, R) → extract, clean header text
    7. Row stubs (first column hierarchy in body)
    """
```

### Step 2: Column Semantics

```python
@dataclass
class ColumnSpec:
    columnId: str               # "col_proved_2025"
    header: str                 # Leaf header text (cleaned)
    rawHeader: str              # Original text (with markers)
    entityRef: str              # "ent_proved_reserves"
    period: str | None          # "2025" (if time-series column)
    headerPath: list[str]       # ["Coal Reserves", "Proved", "2025"]
    unit: str                   # Inherited or explicit
    role: str                   # "measure" | "dimension" | "total" | "serial_number"
    footnoteMarkers: list[str]  # ["P"] → "Provisional"
    
    # Computed from column content profile
    dtype: str                  # "float" | "int" | "string"
    nullRatio: float            # % of blank/null cells

@dataclass
class ColumnGroupSpec:
    label: str                  # "Coal Reserves"
    entityRef: str              # "ent_proved_reserves" (may be family, not single)
    periods: list[str]          # ["2024", "2025"]
    unit: str                   # Inherited from parent header or table title
    span: int                   # Physical column count
    familyRef: str | None       # Link to MeasureFamily
```

### Step 3: Full Table Semantic Model

```python
@dataclass
class TableSemanticModel:
    tableId: str
    tableTitle: str
    page: int
    tableNumber: str                    # "Table 1.1"
    tableClass: TableClass              # REAL_TABLE (already filtered)
    
    # Header hierarchy
    headerTree: list[HeaderNode]
    
    # Semantic roles
    dimensions: list[str]               # Entity IDs: ["ent_state_ut"]
    measures: list[str]                 # Entity IDs (canonical, year-free)
    timeDimension: str | None           # "ent_period"
    
    # Column structure
    columnGroups: list[ColumnGroupSpec]
    columns: list[ColumnSpec]
    
    # Special rows (detected in body)
    totalRowLabels: list[str]           # ["All India", "Total", "Grand Total"]
    stubHierarchy: bool                 # True if first column has indent/hierarchy
    
    # MoSPI context
    unitNote: str
    footnotes: list[FootnoteSpec]
    sourceNote: str
    estimateStatus: str
    referenceDate: str
    
    # Normalization advice for binder
    normalizationAdvice: str            # "WIDE_TO_LONG" | "NONE" | "PIVOT"
    normalizationReason: str            # Why this normalization is needed
```

### Footnote handling

```python
@dataclass
class FootnoteSpec:
    marker: str                 # "*", "#", "P", "R", "1", "2"
    text: str                   # "Provisional estimates"
    scope: str                  # "column" | "row" | "table" | "cell"
    affectedColumns: list[str]  # Column IDs this applies to
    semanticMeaning: str | None # "provisional" | "revised" | "excluded" | "estimated"
```

### MoSPI table complexities handled

| Complexity | Handling |
|-----------|----------|
| Multi-row spanning headers | `parse_header_hierarchy` builds tree |
| Blank/merged cells in header | Inherit parent text |
| Year in leaf header | Detect as period, create columnGroup |
| Unit in table title "(Million Tonnes)" | Extract → table unitNote + column unit |
| Footnote markers in header "Proved*" | Extract → footnoteMarkers, clean header |
| "All India" / "Total" rows | Detect via totalRowLabels |
| Serial number first column | Detect dtype=int, sequential → mark as serial_number |
| Row stub hierarchy (indent) | Detect stubHierarchy flag |
| Ghost/empty tables | Rejected before semantic parsing |
| Source note below table | Text extraction from below-table bbox region |

### Acceptance criteria

- [ ] Ghost tables never reach semantic compiler
- [ ] Every real table has `dimensions[]`, `measures[]`, `columnGroups[]`
- [ ] Year columns → period dimension, NOT separate measures
- [ ] Units inherited from table title and propagated to columns
- [ ] `headerPath` traces from leaf to root for every column
- [ ] Footnote markers extracted and semantics inferred where possible
- [ ] Binder can infer correct `NormalizationPlan` from table template
- [ ] "All India" / "Total" detected (binder won't sum these)

---

## Phase E4: Statistical Context Extraction + Inheritance

**Location:** `report_builder/statistical_context_extractor.py`  
**Effort:** 2 days  
**Priority:** Week 2

### Context Inheritance Chain

The key insight: MoSPI statistical context **inherits down the hierarchy**.

```
Document context (ministry, publication year)
  ↓ inherits to
Chapter context (domain, topic area)
  ↓ inherits to
Table context (unit, estimate status, reference date)
  ↓ inherits to
Column group context (unit override if different)
  ↓ inherits to
Column context (footnote markers, specific period)
  ↓ inherits to
Entity context (final unit, aggregation, domain)
```

### Implementation

```python
@dataclass
class MoSPIStatisticalContext:
    """Hierarchical context with explicit inheritance tracking."""
    
    # Document level
    sourceDocument: str
    ministry: str
    publicationYear: str
    domain: str
    
    # Chapter level
    chapters: list[ChapterContext]

@dataclass
class ChapterContext:
    chapterId: str
    chapterNumber: int
    chapterTitle: str
    domain: str                   # May narrow document domain
    
    # Table-level contexts (per table in this chapter)
    tableContexts: list[TableContext]

@dataclass
class TableContext:
    tableId: str
    tableNumber: str
    tableTitle: str
    unitNote: str                 # "Million Tonnes"
    referenceDate: str            # "As on 1st April 2025"
    estimateStatus: str           # provisional | revised | final | quick_estimate
    footnotes: list[FootnoteSpec]
    sourceNotes: list[str]
    geographyLevel: str           # state_ut | district | all_india | rural_urban
    page: int
```

### Unit Inheritance with Conflict Resolution

```python
def resolve_unit_for_column(
    column: ColumnSpec,
    column_group: ColumnGroupSpec | None,
    table: TableSemanticModel,
    chapter: ChapterContext,
) -> tuple[str, str]:
    """
    Returns (resolved_unit, unit_source) using inheritance chain.
    
    Priority (highest wins):
    1. Explicit unit in column header text: "Distribution (%)" → percent
    2. Column group unit (from parent spanning header)
    3. Table unitNote (from table title)
    4. Chapter/domain default (rare)
    
    Conflict: if column says "%" but table says "MT" → column wins (it's more specific)
    """
    # Column-level explicit
    if column.unit:
        return column.unit, "column_header"
    
    # Column group level
    if column_group and column_group.unit:
        return column_group.unit, "column_group"
    
    # Table level
    if table.unitNote:
        return _normalize_unit(table.unitNote), "table_title"
    
    return "", "unknown"
```

### Conflict diagnostics

When inheritance produces a conflict, log it:

```python
@dataclass
class ContextConflict:
    code: str                    # "UNIT_OVERRIDE"
    column: str                  # Column ID
    parentUnit: str              # What parent says
    childUnit: str               # What column-level says
    resolution: str              # "child_wins" | "parent_wins"
    message: str                 # Human explanation
```

### Unit normalization (adaptive, not hardcoded map)

```python
def _normalize_unit(raw: str) -> str:
    """
    Normalize unit strings adaptively.
    
    Strategy: pattern families, not exact lookup.
    - Parenthetical: "(in Million Tonnes)" → "million_tonnes"
    - Abbreviation: "MT", "BCM", "MW" → standard form
    - Percentage: "%", "percentage", "per cent" → "percent"
    - Rate: "per 1000", "per lakh" → "per_1000", "per_lakh"
    - Currency: "₹ crore", "Rs. Lakh" → "crore_inr", "lakh_inr"
    
    Falls back to slugified raw string if unrecognized.
    """
```

### Estimate status detection (pattern families)

```python
ESTIMATE_STATUS_PATTERNS = [
    # Each is a pattern family, not a single string
    {"status": "provisional", "patterns": [r'\bP\b', r'\bProvisional\b', r'\bProv\.\b']},
    {"status": "revised", "patterns": [r'\bR\b', r'\bRevised\b', r'\bRev\.\b']},
    {"status": "quick_estimate", "patterns": [r'\bQE\b', r'\bQuick\s+Estimate\b']},
    {"status": "final", "patterns": [r'\bFinal\b', r'\bActual\b']},
    {"status": "advance_estimate", "patterns": [r'\bAE\b', r'\bAdvance\s+Estimate\b']},
]
```

### Acceptance criteria

- [ ] Every measure entity has `unit` when inferable from context chain
- [ ] Unit inheritance is explicit (tracked with `unitSource`)
- [ ] Conflicts detected and logged (not silently overridden)
- [ ] Blueprint carries `statisticalContext` at document + table level
- [ ] Binder's `StatisticalContext` in ExecutionBundle populated from this
- [ ] Estimate status detected from footnote markers and notes

---

## Phase E5: Semantic Entity ID Generator

**Location:** `report_builder/entity_id_generator.py`  
**Effort:** 1.5 days  
**Priority:** Week 1

### Design principle

IDs must be:
1. **Semantic** — human-readable, debuggable
2. **Stable** — same concept across reruns → same ID
3. **Unique** — no collisions within one blueprint
4. **Deterministic** — computed from semantic fingerprint, not sequence number

### Fingerprint-based ID generation

```python
def generate_entity_id(
    canonical_name: str,
    entity_type: str,
    context: EntityContext | None = None,
) -> str:
    """
    Generate stable semantic ID from entity properties.
    
    Step 1: Check abbreviation table for known indicators
    Step 2: Slugify canonical name
    Step 3: Collision detection + disambiguation
    Step 4: Prefix with "ent_"
    
    Fingerprint = hash(normalized_name + entity_type + domain_if_ambiguous)
    Same fingerprint → same ID across runs.
    """
```

### Abbreviation table (well-known MoSPI indicators)

```python
# These are NOT hardcoded outputs — they're RECOGNITION patterns
# that convert well-known long names to standard abbreviations.
# New indicators are handled by slugification, not by adding to this table.
MOSPI_KNOWN_INDICATORS = {
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
}
```

### Slugification (for non-abbreviated entities)

```python
def _slugify_entity(name: str, entity_type: str) -> str:
    """
    "Proved Reserves" → "proved_reserves"
    "States/UTs" → "state_ut"
    "Distribution (%)" → "distribution_percent"
    "Solar Energy" → "solar_energy"
    "Year/Period" → "period"
    
    Rules:
    - Lowercase
    - Replace spaces, slashes, hyphens with underscore
    - Remove parenthetical content (units go to unit field)
    - Replace "%" with "percent"
    - Collapse multiple underscores
    - Max 40 chars
    """
```

### Collision handling

```python
def _resolve_collision(base_id: str, existing_ids: set[str], context: EntityContext) -> str:
    """
    If "ent_distribution_percent" already exists (from a different table):
    
    Strategy 1: Check if they're the SAME concept (merge, don't disambiguate)
    Strategy 2: If different domains → "ent_coal_distribution_percent"
    Strategy 3: If same domain different table → "ent_distribution_percent_t2"
    
    Prefer Strategy 1 (merge) when semantics match.
    """
```

### Stability across reruns

```python
def ensure_stability(
    new_entities: list[SemanticEntity],
    previous_blueprint: dict | None = None,
) -> list[SemanticEntity]:
    """
    If a previous version of the blueprint exists:
    1. Match new entities to old by (canonical_name + entity_type)
    2. Preserve old ID for matched entities
    3. Generate new IDs only for genuinely new entities
    4. Log renamed/removed entities for audit
    
    This ensures saved binder confirmations remain valid across re-extractions.
    """
```

### Also generates semantic IDs for

```python
# Questions
"q_coal_reserves_state"          # from intent + table
"q_renewable_potential_source"

# Topics
"topic_energy_reserves"
"topic_coal_reserves"
"topic_renewable_energy"

# Table templates
"tt_coal_reserves_state"
"tt_lignite_reserves_state"

# Figure templates
"ft_coal_distribution_pie"
"ft_renewable_source_bar"
```

### Acceptance criteria

- [ ] No `ent_0XX` in output
- [ ] Same PDF re-extracted → same entity IDs
- [ ] Known MoSPI indicators use standard abbreviations
- [ ] Collisions resolved semantically (merge or disambiguate)
- [ ] All IDs are human-readable and meaningful
- [ ] Previous binder confirmations survive re-extraction

---

## Phase E6: Alias & ValueDomain Enrichment

**Location:** `report_builder/entity_enrichment.py`  
**Effort:** 2 days  
**Priority:** Week 3

### Alias generation (4-source strategy)

```python
def generate_aliases(
    entity: SemanticEntity,
    table_structures: list[TableSemanticModel],
    glossary: dict,
    domain_packs: dict,
) -> list[str]:
    """
    Source 1: Name variants (deterministic)
        "Proved Reserves" → ["Proved", "Proved Reserve", "proved reserves", "Proved_Reserves"]
    
    Source 2: Physical column names (from table headers where this entity appears)
        If entity appears as "Proved 2025" in table → add as alias
    
    Source 3: Glossary/abbreviation
        If glossary has "LFPR = Labour Force Participation Rate" → add "LFPR"
    
    Source 4: Domain-specific variations (adaptive per domain)
        Energy: "Coal" also matches "coal reserves", "coal production"
        Labour: "Employment" also matches "employed persons"
    
    Deduplication: lowercase + strip → unique set
    Quality: reject aliases that are substrings of other aliases (too generic)
    """
```

### Domain packs (NOT hardcoded per-entity — per-domain patterns)

```python
# Domain packs define PATTERNS, not individual entity mappings
DOMAIN_ALIAS_PATTERNS = {
    "energy": {
        # Pattern: resource entities get "{Resource}" and "{Resource} reserves/production"
        "measure_suffixes": ["reserves", "production", "consumption", "potential", "capacity"],
        # Pattern: geography members get common abbreviations
        "geography_patterns": {"States/UTs": ["State", "States", "State/UT"]},
    },
    "labour_force": {
        "measure_suffixes": ["rate", "ratio", "percentage"],
        "geography_patterns": {"Sector": ["Rural/Urban", "rural-urban", "area"]},
    },
}
```

### ValueDomain inference (signal-based)

```python
def infer_value_domain(
    entity: SemanticEntity,
    table_structures: list[TableSemanticModel],
) -> dict:
    """
    NOT a lookup table. Signal-based inference:
    
    For measures:
    - unit="percent" → {"kind": "ratio", "min": 0, "max": 100}
    - unit in physical units (MT, MW) → {"kind": "ratio", "min": 0}
    - aggregation="count" → {"kind": "count", "min": 0}
    - isDerived=True (Distribution) → {"kind": "ratio", "min": 0, "max": 100}
    
    For dimensions:
    - scope="geography" → {"kind": "categorical", "members": "open", "expectedCardinality": N}
    - scope="temporal" → {"kind": "ordinal", "format": detected_format}
    - Known enums (from table structure or VLM) → {"kind": "categorical", "members": [...]}
    
    Members are extracted from:
    - Column group labels (Reserve Category → ["Proved", "Indicated", "Inferred"])
    - Table first-column distinct values (if clearly enumerable, < 30 items)
    - Known MoSPI enums (sector: Rural/Urban, gender: Male/Female)
    """
```

### Structural member inference

For dimensions like "Reserve Category", extract members from table structure:

```python
def infer_dimension_members(
    entity: SemanticEntity,
    tables: list[TableSemanticModel],
) -> list[str] | None:
    """
    If this entity is a category dimension created from a measure family:
    - MeasureFamily members → dimension valueDomain.members
    
    Example:
    - MeasureFamily "mf_coal_reserves" has members [Proved, Indicated, Inferred, Total]
    - The corresponding category entity gets: members = ["Proved", "Indicated", "Inferred"]
    - "Total" is excluded (it's a computed aggregate, not a member)
    
    For geography: use "open" (too many members to enumerate)
    For period: use detected periods from table columns
    """
```

### Acceptance criteria

- [ ] Core entities have 2-5 aliases
- [ ] Measures have `valueDomain.kind` ("ratio" or "count")
- [ ] Dimensions have `valueDomain.kind` ("categorical" or "ordinal")
- [ ] Geography entities have `expectedCardinality`
- [ ] Period entities have detected format and known members
- [ ] Binder resolver confidence measurably improves (A/B test)
- [ ] No alias is a substring of the canonical name only (must add value)

---

## Phase E7: Question Compiler + Deterministic Templates

**Location:** `report_builder/question_compiler.py`  
**Effort:** 3 days  
**Priority:** Week 3

### Architecture change: deterministic-first, LLM-second

Current approach: LLM generates all questions → QA validates.

Better approach:
1. **Deterministic question templates** from table semantics (guaranteed quality)
2. **LLM enrichment** for nuanced/complex questions (optional layer)
3. **QA gate** validates everything before emit

### Deterministic question templates (from table patterns)

```python
class TableQuestionTemplate:
    """Template for generating questions from table semantic structure."""
    
    pattern: str              # "statewise_comparison" | "yoy_change" | "composition" | ...
    applicability: Callable   # When does this template apply?
    generator: Callable       # Generate the question dict

# Table pattern → question templates
TABLE_QUESTION_PATTERNS = {
    "statewise_wide_year": [
        # Table has: geography dimension + measures × periods
        {
            "pattern": "comparison_current",
            "intent_template": "Compare {measure} across {dimension} for {current_period}",
            "operation": "group_aggregate",
            "priority": 1,
        },
        {
            "pattern": "ranking_top_n",
            "intent_template": "Top {n} {dimension} by {measure} in {current_period}",
            "operation": "group_aggregate",
            "priority": 2,
            "extra": {"sort": {"by": "measure", "order": "desc"}, "topN": 10},
        },
        {
            "pattern": "yoy_change",
            "intent_template": "Year-over-year change in {measure} across {dimension}",
            "operation": "growth",
            "priority": 3,
            "requires": "multiple_periods",  # Only if 2+ periods detected
        },
    ],
    
    "multi_measure_composition": [
        # Table has: geography + multiple related measures (family)
        {
            "pattern": "composition_by_category",
            "intent_template": "Composition of {family_concept} by {category} for {dimension}",
            "operation": "group_aggregate",
            "priority": 2,
        },
    ],
    
    "single_measure_time_series": [
        # Table has: one measure across many time periods
        {
            "pattern": "trend_over_time",
            "intent_template": "Trend of {measure} over {period_range}",
            "operation": "trend",
            "priority": 1,
        },
        {
            "pattern": "cagr",
            "intent_template": "CAGR of {measure} from {start_period} to {end_period}",
            "operation": "cagr",
            "priority": 3,
            "requires": "period_span_3_plus",
        },
    ],
}
```

### Question budget (prevent over-generation)

```python
QUESTION_BUDGET = {
    "per_table": 4,              # Max 4 questions per major table
    "per_topic": 8,              # Max 8 questions per topic/section
    "per_blueprint": 30,         # Max 30 total questions
    "priority_cutoff": 4,        # Only generate priority 1-4
}

def apply_question_budget(
    questions: list[dict],
    budget: dict = QUESTION_BUDGET,
) -> list[dict]:
    """
    Select highest-priority questions within budget.
    Deduplicate by (requiredEntities + operation).
    Prefer deterministic over LLM-generated.
    """
```

### Question generation flow

```python
def compile_questions(
    graph: TemplateSemanticGraph,
) -> list[QuestionPlan]:
    """
    Step 1: For each table, match against TABLE_QUESTION_PATTERNS
            Generate deterministic questions from matching templates
    
    Step 2: For each topic without enough questions, use LLM to generate
            additional analytical questions (Pass 3 LLM call)
    
    Step 3: Validate all questions (E7 QA checks)
    
    Step 4: Apply question budget (priority + dedup)
    
    Step 5: Generate answerStructure for each question
    """
```

### AnswerStructure compilation

```python
def compile_answer_structure(
    question: dict,
    source_table: TableSemanticModel | None,
    source_figure: FigureSemanticModel | None,
) -> dict:
    """
    Deterministic answerStructure generation:
    
    Every question gets:
    - narrative component (always, order=1)
    - table component (if source table exists, order=2)
    - chart component (if meaningful for this question type, order=3)
    
    Chart type selection:
    - comparison → bar chart
    - composition → pie chart or stacked bar
    - trend → line chart
    - ranking → horizontal bar
    
    Each component gets:
    - componentId: "{questionId}_c{N}"
    - outputContract: {type, maxWords/columns/chartType}
    """
```

### QA validation (from friend's critique)

```python
class QuestionQA:
    """Validates questions are executable, not just plausible."""
    
    CHECKS = [
        "entity_refs_valid",          # All requiredEntities reference existing IDs
        "has_measure",                # At least one measure entity
        "has_analytics_spec",         # analyticsSpec exists with operation
        "measure_ref_consistent",     # analyticsSpec.measure matches requiredEntities
        "answer_structure_complete",  # components exist with IDs and kinds
        "intent_specific",            # Intent is 8+ words, not generic
        "question_type_valid",        # Known questionType
        "no_duplicate_operation",     # Not identical to another question
    ]
    
    def validate(self, question: dict, entity_registry: dict) -> QuestionDiagnostic:
        """Run all checks. Return diagnostic with pass/fail per check."""
    
    def auto_repair(self, question: dict, entity_registry: dict, tables: list) -> dict:
        """
        Repair common issues:
        - Missing operation → infer from questionType
        - Missing componentId → generate from questionId
        - Missing groupBy → infer from requiredEntities with role="grouping"
        - Missing sort → default for questionType
        - Weak intent → regenerate from template
        """
```

### Acceptance criteria

- [ ] Deterministic templates produce 60%+ of questions (not LLM-dependent)
- [ ] Every question passes binder `BlueprintQA`
- [ ] Question budget prevents blueprint bloat
- [ ] Auto-repair fixes common generation errors
- [ ] Each question has `generationMethod` ("table_pattern" or "llm")
- [ ] No orphan `requiredEntities`

---

## Phase E8: Slot Wiring Validator + Layout Policy

**Location:** `report_builder/slot_wiring.py`  
**Effort:** 1.5 days  
**Priority:** Week 4

### Cross-reference validation

```python
def validate_wiring(
    skeleton: dict,        # template.ast.json structure
    blueprint: dict,       # template.blueprint.json structure
) -> list[WiringIssue]:
    """
    Rule 1: Every question component → matching slot in skeleton
        narrative → contentAST block with biQuery ref
        table → tableAST table with biQuery ref
        chart → chartAST chart or figureAST figure with biQuery ref
    
    Rule 2: Every tableTemplate in blueprint → table in skeleton
    
    Rule 3: Every figureTemplate in blueprint → figure/chart in skeleton
    
    Rule 4: documentMap topic order = blueprint topic order
    
    Rule 5: No orphan slots (slots without matching question)
    
    Rule 6: No orphan questions (questions without matching slot)
    
    Rule 7: All component IDs unique
    
    Rule 8: All slot fillFrom refs resolve
    """
```

### Layout placement policy

```python
def compute_layout_placement(
    question: dict,
    source_table: TableSemanticModel | None,
    source_figure: FigureSemanticModel | None,
    section: SectionNode,
) -> list[SlotPlacement]:
    """
    Determines WHERE in the skeleton each component should appear.
    
    Policy (respects source PDF ordering):
    1. Narrative → content block in same section, before table
    2. Table → tableAST, positioned after narrative for same question
    3. Chart → chartAST, positioned after table (or after narrative if no table)
    
    If source PDF had: section → figure → table
    Preserve that order in skeleton layout.
    """
```

### Auto-wiring (repair)

```python
def auto_wire_missing_slots(
    skeleton: dict,
    blueprint: dict,
) -> tuple[dict, list[str]]:
    """
    For questions missing slots:
    - Create empty paragraph block in contentAST for narrative
    - Find nearest table by topic/page → wire biQuery
    - Find nearest chart → wire biQuery
    
    Returns (updated_skeleton, list_of_repairs_made)
    """
```

### Acceptance criteria

- [ ] All biQuery refs resolve to existing questions
- [ ] All tableTemplateRefs exist in blueprint
- [ ] All chartRefs exist
- [ ] documentMap matches topic ordering
- [ ] Zero orphan slots or orphan questions after auto-wire
- [ ] Repairs logged in diagnostics

---

## Phase E9: Extraction Diagnostics + Pass Scoring

**Location:** `report_builder/extraction_diagnostics.py`  
**Effort:** 1.5 days  
**Priority:** Week 4

### Pass-level scoring

```python
@dataclass
class ExtractionDiagnostics:
    """Complete extraction quality report."""
    
    # Overall
    status: str                     # "VALID" | "VALID_WITH_WARNINGS" | "INVALID"
    contractVersion: str            # "template.extraction.v2"
    binderReadinessScore: float     # 0.0 – 1.0 composite
    
    # Pass-level scores (where each pass contributed quality)
    passScores: dict[str, float]
    # {
    #   "pass0_text_tables": 0.87,
    #   "pass1_layout": 0.81,
    #   "pass2_vlm": 0.76,
    #   "pass2_5_semantic_graph": 0.84,
    #   "pass3_questions": 0.82,
    #   "pass4_assembly": 0.91,
    #   "pass4_5_validation": 0.88,
    # }
    
    # Category scores
    categoryScores: dict[str, float]
    # {
    #   "entityHygiene": 0.92,
    #   "entityCompleteness": 0.78,
    #   "tableSemantics": 0.85,
    #   "unitCoverage": 0.81,
    #   "questionCompleteness": 0.88,
    #   "answerStructureCompleteness": 0.90,
    #   "crossReferenceIntegrity": 0.95,
    #   "valueFreeCompliance": 1.0,
    #   "chartSemantics": 0.72,
    # }
    
    # Counts
    counts: ExtractionCounts
    
    # Issues
    blockingErrors: list[DiagnosticIssue]
    warnings: list[DiagnosticIssue]
    
    # Audit trail
    quarantinedItems: list[QuarantinedItem]
    repairsApplied: list[RepairRecord]
    
    # Binder compatibility prediction
    binderCompatibility: BnderCompatibilityPrediction

@dataclass
class ExtractionCounts:
    entities: int
    entitiesDropped: int
    entitiesRepaired: int
    measureFamilies: int
    questions: int
    questionsFromTemplates: int
    questionsFromLLM: int
    questionsDropped: int
    tables: int
    tablesGhost: int
    charts: int
    figures: int
    topics: int
    slotsWired: int
    slotsOrphaned: int

@dataclass
class BinderCompatibilityPrediction:
    blueprintQAWillPass: bool
    expectedResolverConfidence: str    # "high" | "medium" | "low"
    expectedIssues: list[str]         # Predicted binder problems
    recommendation: str               # "proceed" | "fix_entities" | "fix_questions"
```

### Scoring formula

```python
def compute_binder_readiness(category_scores: dict) -> float:
    """
    Weighted composite — weights reflect impact on binder success.
    
    entityHygiene:               25%  (noisy entities break everything)
    questionCompleteness:        20%  (questions drive execution plans)
    crossReferenceIntegrity:     15%  (broken refs = broken binding)
    tableSemantics:              15%  (table structure drives normalization)
    unitCoverage:                10%  (units drive formula validation)
    entityCompleteness:          10%  (aliases/domains help resolver)
    valueFreeCompliance:          5%  (should always be 1.0)
    """
```

### Fail thresholds

```python
THRESHOLD_POLICY = {
    "VALID": {"binderReadiness": 0.75, "blockingErrors": 0},
    "VALID_WITH_WARNINGS": {"binderReadiness": 0.50, "blockingErrors": 0},
    "INVALID": {"any_blocking_error": True, "or_readiness_below": 0.50},
}
```

### Acceptance criteria

- [ ] Every extraction run produces `template.diagnostics.json`
- [ ] Pass-level scores identify which pass needs improvement
- [ ] Category scores match what binder cares about
- [ ] Binder compatibility prediction is actionable
- [ ] Quarantine log is complete and debuggable
- [ ] `binderReadinessScore >= 0.75` required for VALID

---

## Phase E10: Energy Gold Standard + Regression Tests

**Location:** `report_builder/gold_standard/energy.*` + `tests/test_extraction_gold.py`  
**Effort:** 3 days  
**Priority:** Week 4

### Gold files

```
report_builder/gold_standard/energy.template.ast.json
report_builder/gold_standard/energy.template.blueprint.json
report_builder/gold_standard/energy.diagnostics.json
```

### What Energy Gold proves (beyond PLFS)

| Feature | PLFS Gold | Energy Gold |
|---------|-----------|-------------|
| Column groups | Simple | Wide year columns + measure families |
| headerPath | None | `["Coal Reserves", "Proved", "2025"]` |
| Unit inheritance | All percent | MT, BCM, MW, percent (mixed in one report) |
| Multi-table chapters | 1 table | 4+ tables per chapter |
| Period dimension | None | `ent_period` with ["2024", "2025"] |
| Footnotes | None | `["P: Provisional", "Source: GSI"]` |
| MeasureFamily | None | `mf_coal_reserves_by_category` |
| Geography | Simple sector | 36 State/UTs |
| Normalization hints | None | `WIDE_TO_LONG` for year columns |
| Chart templates | None | pie, bar, stacked_bar |
| Ghost table filter | N/A | Demonstrated in diagnostics |
| Question templates | LLM only | Deterministic from table patterns |

### Regression test suite

```python
# tests/test_extraction_gold.py

class TestEnergyGoldContract:
    """Gold standard must pass extraction contract."""
    
    def test_contract_valid(self):
        bp = load_gold("energy.template.blueprint.json")
        result = validate_extraction_contract(bp, mode=ExtractionMode.STRICT)
        assert result.status == "VALID"
    
    def test_binder_blueprint_qa_passes(self):
        bp = load_gold("energy.template.blueprint.json")
        qa = validate_blueprint_qa(bp)
        assert qa.status != "INVALID"
    
    def test_no_values_in_skeleton(self):
        ast = load_gold("energy.template.ast.json")
        assert_value_free(ast)
    
    def test_no_values_in_blueprint(self):
        bp = load_gold("energy.template.blueprint.json")
        assert_no_numeric_values(bp)
    
    def test_entity_ids_semantic(self):
        bp = load_gold("energy.template.blueprint.json")
        for ent in bp["entities"]:
            assert not re.match(r'^ent_\d+$', ent["entityId"])
    
    def test_entities_have_aliases(self):
        bp = load_gold("energy.template.blueprint.json")
        core = [e for e in bp["entities"] if e["entityType"] == "measure"]
        assert all(len(e.get("aliases", [])) >= 2 for e in core)
    
    def test_measures_have_units(self):
        bp = load_gold("energy.template.blueprint.json")
        measures = [e for e in bp["entities"] if e["entityType"] == "measure"]
        assert all(e.get("unit") for e in measures)
    
    def test_table_templates_have_column_groups(self):
        bp = load_gold("energy.template.blueprint.json")
        for tt in bp["tableTemplates"]:
            assert tt.get("columnGroups"), f"Table {tt['tableId']} missing columnGroups"
    
    def test_table_templates_have_header_path(self):
        bp = load_gold("energy.template.blueprint.json")
        for tt in bp["tableTemplates"]:
            for col in tt.get("columns", []):
                if col.get("role") == "measure":
                    assert col.get("headerPath"), f"Column {col['columnId']} missing headerPath"
    
    def test_questions_executable(self):
        bp = load_gold("energy.template.blueprint.json")
        entity_ids = {e["entityId"] for e in bp["entities"]}
        for topic in bp["topics"]:
            for q in topic["questions"]:
                for req in q["requiredEntities"]:
                    assert req["entityId"] in entity_ids
                assert q.get("analyticsSpec", {}).get("operation")
                assert q.get("answerStructure", {}).get("components")
    
    def test_slot_wiring_complete(self):
        ast = load_gold("energy.template.ast.json")
        bp = load_gold("energy.template.blueprint.json")
        issues = validate_wiring(ast, bp)
        assert not any(i.severity == "error" for i in issues)
    
    def test_statistical_context_present(self):
        bp = load_gold("energy.template.blueprint.json")
        ctx = bp.get("statisticalContext", {})
        assert ctx.get("sourceDocument")
        assert ctx.get("domain") == "energy"
    
    def test_measure_families_present(self):
        bp = load_gold("energy.template.blueprint.json")
        assert bp.get("measureFamilies")
    
    def test_diagnostics_valid(self):
        diag = load_gold("energy.diagnostics.json")
        assert diag["binderReadinessScore"] >= 0.85
        assert diag["status"] == "VALID"
    
    def test_gold_to_execution_bundle(self):
        """Integration: gold blueprint → binder → ExecutionBundle."""
        bp = load_gold("energy.template.blueprint.json")
        # Simulate binding with a matching dataset
        from tests.fixtures import energy_dataset
        # ... (full integration path)
```

### Acceptance criteria

- [ ] Energy gold files created with all features demonstrated
- [ ] All 15+ regression tests pass
- [ ] Gold is executable documentation (not just reference files)
- [ ] CI runs gold tests on every extraction pipeline change

---

## Phase E11: Chart/Figure Semantic Compiler

**Location:** `report_builder/chart_semantic_compiler.py`  
**Effort:** 2 days  
**Priority:** Week 3

### Problem

MoSPI Energy PDFs contain vector pie/bar charts. pdfplumber can't read them. LayoutLM/VLM detect them as figures but don't extract semantics. Templates need chart structure (type, subject, axes) WITHOUT chart values.

### FigureSemanticModel

```python
@dataclass
class FigureSemanticModel:
    """Semantic model for a chart/figure detected in the PDF."""
    
    figureTemplateId: str           # "ft_coal_distribution_pie"
    figureNumber: str | None        # "Figure 1.2"
    page: int
    
    # Type and intent
    chartType: str                  # "pie" | "bar" | "grouped_bar" | "stacked_bar" | "line" | "map"
    chartSubject: str               # "Coal reserves by reserve category"
    
    # Semantic links
    categoryEntityRef: str | None   # "ent_reserve_category" (what the slices/bars represent)
    measureRefs: list[str]          # ["ent_proved_reserves", ...] (what's being measured)
    dimensionRef: str | None        # "ent_state_ut" (if chart groups by geography)
    periodRef: str | None           # "ent_period" (if chart shows specific time)
    
    # Template slots
    captionTemplate: str            # "Distribution of {measure} by {category}, {period}"
    axisLabels: dict                # {"x": "State/UT", "y": "Million Tonnes"}
    legendLabels: list[str]         # ["Proved", "Indicated", "Inferred"]
    
    # Provenance
    detectionMethod: str            # "vlm_detection" | "caption_analysis" | "proximity_inference"
    confidence: float
    relatedTableId: str | None      # If chart visualizes a table's data
    relatedQuestionId: str | None   # Linked question in blueprint
    
    # Context
    sectionRef: str | None          # Section this figure belongs to
```

### Detection strategy

```python
def compile_figure_semantics(
    detected_figures: list[dict],     # From LayoutLM/VLM
    tables: list[TableSemanticModel], # From E3
    entities: list[SemanticEntity],   # From E1/E2
    sections: list[SectionNode],      # From graph
) -> list[FigureSemanticModel]:
    """
    Strategy (signal-based, not hardcoded):
    
    1. VLM detection: chart type, caption text
    2. Caption analysis: extract subject, measure, category from caption
    3. Proximity inference: nearest table → infer chart subject
    4. Section context: chart in "Coal Reserves" section → likely about coal
    5. Legend/axis labels (if VLM extracted them)
    
    For charts VLM can't fully parse:
    - Use caption + section context to infer subject
    - Link to nearest table by content proximity
    - Chart type from VLM shape detection (pie = circle, bar = rectangles)
    """
```

### Chart type inference from context

```python
def infer_chart_type(
    vlm_shape: str | None,       # "circle" | "rectangles" | "lines" | None
    caption: str,
    nearby_question: dict | None,
) -> str:
    """
    Signals:
    - VLM detects circular shape → "pie"
    - VLM detects vertical bars → "bar"
    - Caption says "distribution" → likely "pie"
    - Caption says "trend" or "over time" → likely "line"
    - Question is "comparison" type → "bar"
    - Question is "composition" type → "pie" or "stacked_bar"
    """
```

### Acceptance criteria

- [ ] Every detected figure has chartType and chartSubject
- [ ] Figure templates link to entities (measure + category/dimension)
- [ ] Charts linked to related tables and questions
- [ ] Caption templates are value-free (use `{measure}`, `{period}` placeholders)
- [ ] No chart series values in template (value-free!)
- [ ] Chart templates influence answerStructure generation (E7)

---

## Phase E12: Value-Free Contract Validator (Hard Gate)

**Location:** `report_builder/value_free_validator.py`  
**Effort:** 1 day  
**Priority:** Week 1 (hard invariant from the start)

### Purpose

This is a **hard gate** that BLOCKS emission if any values or prose leak into template files. It must be strict and non-negotiable.

### What is ALLOWED (structural)

```python
ALLOWED_NUMBERS = {
    "year_labels": r'^(19|20)\d{2}(-\d{2,4})?$',      # 2024, 2023-24
    "table_numbers": r'^Table\s+\d+\.\d+$',             # Table 1.1
    "figure_numbers": r'^Figure\s+\d+(\.\d+)?$',        # Figure 1.2
    "page_numbers": r'^\d{1,4}$',                       # in page refs
    "font_sizes": r'^\d{1,2}(\.\d)?$',                  # in style objects
    "bbox_coords": r'^\d+(\.\d+)?$',                    # in layout objects
    "confidence_scores": r'^0\.\d+$',                   # in metadata
    "cardinality": r'^\d{1,4}$',                        # expectedCardinality
    "component_order": r'^[1-9]$',                      # answerStructure order
}
```

### What is FORBIDDEN (data values)

```python
FORBIDDEN_PATTERNS = {
    "large_decimal": r'\d{2,}\.\d{1,}',     # 400.7, 11.29 (likely data)
    "percentage_value": r'\d+\.\d+%',        # 78.4% (likely computed)
    "currency_value": r'[₹$€]\s*[\d,]+',    # ₹1,234 (data)
    "paragraph_prose": lambda s: len(s) > 200 and not s.startswith("{"),  # Report prose
    "table_data_row": lambda row: all(isinstance(c, (int, float)) for c in row[1:]),
    "chart_series_value": lambda v: isinstance(v, (int, float)) and v > 1.0,
}
```

### Validator

```python
def assert_value_free(skeleton: dict, blueprint: dict) -> list[ValueLeakage]:
    """
    Scan both files for value/prose leakage.
    
    Check locations:
    - skeleton.contentAST.blocks[].content → must be "" or placeholder
    - skeleton.tableAST.tables[].rows → must be []
    - skeleton.chartAST.charts[].series → must be []
    - skeleton.figureAST.figures[].caption → must be "" or template
    - blueprint.entities[].* → no numeric data values
    - blueprint.topics[].questions[].intent → no actual answers
    
    Returns list of leakages. If any exist, emission is BLOCKED.
    """
```

### Integration

```python
# In template_emit.py, BEFORE writing files:
leakages = assert_value_free(skeleton, blueprint)
if leakages:
    logger.error("[BLOCKED] Value/prose leakage detected: %d violations", len(leakages))
    for leak in leakages:
        logger.error("  %s: %s at %s", leak.code, leak.detail, leak.path)
    if mode == ExtractionMode.STRICT:
        raise ValueLeakageError(leakages)
```

### Acceptance criteria

- [ ] Hard gate: emission blocked if ANY values leak
- [ ] Structural numbers (years, table numbers, bbox) whitelisted
- [ ] Data values (400.7, 78.4%) caught and rejected
- [ ] Prose paragraphs caught and rejected
- [ ] Gate runs automatically before every file write
- [ ] Zero false positives on gold standard files

---

## Phase E13: Extraction→Binder E2E Integration Test

**Location:** `tests/test_extraction_binder_e2e.py`  
**Effort:** 2 days  
**Priority:** Week 5 (final acceptance)

### The real proof

```python
class TestExtractionToBinderE2E:
    """
    The ultimate acceptance test:
    PDF → Extraction → ①② → BlueprintQA → Binder → ExecutionBundle
    
    This proves the entire pipeline works end-to-end.
    """
    
    def test_energy_pdf_to_execution_bundle(self):
        """
        Input: data/test2.pdf (Energy Statistics)
        + unified_energy_reserves_dataset.csv
        
        Expected:
        1. Extraction produces valid template.ast + blueprint
        2. BlueprintQA passes (VALID or VALID_WITH_WARNINGS)
        3. Resolver proposes bindings with confidence > 0.70
        4. Plan compiler produces QuestionExecutionPlans
        5. Readiness gate: majority READY or DEGRADED (not BLOCKED)
        6. ExecutionBundle has status READY or DEGRADED
        """
    
    def test_plfs_pdf_to_execution_bundle(self):
        """Same flow for PLFS (simpler case, should be higher confidence)."""
    
    def test_extraction_diagnostics_predict_binder_outcome(self):
        """
        Extraction diagnostics should predict binder success:
        - High binderReadinessScore → high resolver confidence
        - Low score → more DEGRADED/BLOCKED plans
        """
    
    def test_entity_hygiene_improves_resolver(self):
        """
        Compare resolver results:
        A: raw extraction (no hygiene) → resolver confidence
        B: with hygiene → resolver confidence
        
        B should be measurably better.
        """
    
    def test_aliases_improve_resolver(self):
        """
        Compare resolver results:
        A: entities without aliases → resolver confidence
        B: entities with aliases → resolver confidence
        
        B should match more entities with higher confidence.
        """
    
    def test_table_semantics_improve_normalization(self):
        """
        With table semantic model:
        - Binder correctly infers WIDE_TO_LONG normalization
        - Column groups detected
        - Period dimension resolved
        """
    
    def test_statistical_context_flows_to_bundle(self):
        """
        Extraction statistical context → Blueprint → Binder → ExecutionBundle.statisticalContext
        
        Verify: unitRegistry, sourceNotes, geographyLevel populated from extraction.
        """
    
    def test_frozen_bundle_from_extraction(self):
        """
        Full flow produces a frozen ExecutionBundle:
        - bindingAstId is stable
        - frozenAt is set
        - Repeated calls return same version (idempotent)
        """
```

### Acceptance criteria

- [ ] Energy PDF → ExecutionBundle succeeds end-to-end
- [ ] PLFS PDF → ExecutionBundle succeeds end-to-end
- [ ] Diagnostics correctly predict binder outcome
- [ ] Measurable improvement from hygiene + aliases + table semantics
- [ ] Statistical context flows through entire pipeline
- [ ] CI runs E2E test on extraction changes

---

## Implementation Order

```
┌─────────────────────────────────────────────────────────────────────────┐
│  WEEK 1: Foundation + Hard Gates                                         │
│                                                                         │
│  E0  Extraction Contract (compile target for all modules)               │
│  E12 Value-Free Validator (hard invariant from day 1)                   │
│  E1  Entity Hygiene Compiler (biggest single quality impact)            │
│  E5  Semantic Entity ID Generator (enables stable refs)                 │
│                                                                         │
│  After Week 1: entities are clean, IDs are semantic, values don't leak  │
├─────────────────────────────────────────────────────────────────────────┤
│  WEEK 2: Table Semantics + Context                                       │
│                                                                         │
│  E2  Canonical Normalization + Measure Families                         │
│  E3  Table Header Semantic Compiler (biggest structural impact)         │
│  E4  Statistical Context + Inheritance                                  │
│                                                                         │
│  After Week 2: tables are fully modeled, context flows, families exist  │
├─────────────────────────────────────────────────────────────────────────┤
│  WEEK 3: Enrichment + Charts + Questions                                 │
│                                                                         │
│  E6  Alias & ValueDomain Enrichment                                     │
│  E11 Chart/Figure Semantic Compiler                                     │
│  E7  Question Compiler + Deterministic Templates                        │
│                                                                         │
│  After Week 3: entities are rich, charts modeled, questions executable  │
├─────────────────────────────────────────────────────────────────────────┤
│  WEEK 4: Validation + Gold Standard                                      │
│                                                                         │
│  E8  Slot Wiring Validator + Layout Policy                              │
│  E9  Extraction Diagnostics + Pass Scoring                              │
│  E10 Energy Gold Standard + Regression Tests                            │
│                                                                         │
│  After Week 4: everything validated, scored, and proven against gold    │
├─────────────────────────────────────────────────────────────────────────┤
│  WEEK 5: Integration + Proof                                             │
│                                                                         │
│  E13 Extraction→Binder E2E Integration Test                             │
│  Performance tuning + edge case fixes from E2E results                  │
│  Final scorecard measurement                                            │
│                                                                         │
│  After Week 5: end-to-end proven, score measured, production-ready      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Why this order

| Decision | Reason |
|----------|--------|
| E0 first | Every module needs a compile target |
| E12 first | Value-free is a hard invariant — never allow regression |
| E1 before E2 | Must clean entities before normalizing them |
| E5 with E1 | Clean entities need semantic IDs immediately |
| E3 before E6 | Table structure drives alias/domain generation |
| E11 before E7 | Chart semantics influence question generation |
| E8 after E7 | Can't validate wiring until questions exist |
| E9 after E8 | Diagnostics score everything, must come last |
| E13 last | Integration test validates the full stack |

---

## Peak Standard Checklist

A template extraction is **peak standard** only when ALL of these are true:

```
HARD GATES (must pass, no exceptions):
├── [ ] template.ast.json is value-free (E12 validator passes)
├── [ ] template.blueprint.json is prose-free (E12 validator passes)
├── [ ] No OCR fragments in entities (E1 hygiene)
├── [ ] All entity IDs are semantic (E5 — no ent_0XX)
├── [ ] All question requiredEntities resolve to existing entities (E7 QA)
├── [ ] Extraction contract validates in STRICT mode (E0)
└── [ ] Binder BlueprintQA passes on the blueprint

QUALITY GATES (scored, must exceed threshold):
├── [ ] entityHygiene >= 0.85
├── [ ] entityCompleteness >= 0.70 (aliases + unit + domain)
├── [ ] tableSemantics >= 0.80 (columnGroups + headerPath + units)
├── [ ] unitCoverage >= 0.75 (measures with inferable units)
├── [ ] questionCompleteness >= 0.85 (analyticsSpec + answerStructure)
├── [ ] crossReferenceIntegrity >= 0.90
├── [ ] valueFreeCompliance = 1.00
├── [ ] binderReadinessScore >= 0.75
└── [ ] chartSemantics >= 0.60 (if charts exist)

SEMANTIC CORRECTNESS:
├── [ ] Headings are topics/sections, not entities
├── [ ] Time modeled as ent_period (not baked into measure names)
├── [ ] Measure families detected for related measures
├── [ ] Table templates have columnGroups + headerPath
├── [ ] Units inherited from context chain (not guessed)
├── [ ] Statistical context present (source, footnotes, estimate status)
├── [ ] Chart templates have type, subject, entity links
├── [ ] Questions are deterministic-first (60%+ from templates)
├── [ ] Slots wired bidirectionally (AST↔blueprint)
└── [ ] Diagnostics score is accurate and actionable

BINDER INTEGRATION:
├── [ ] Resolver achieves >= 0.80 average confidence
├── [ ] Plan compiler produces EXECUTABLE plans (not all DEGRADED)
├── [ ] Readiness gate produces READY or DEGRADED (not all BLOCKED)
├── [ ] ExecutionBundle.statisticalContext populated from extraction
├── [ ] Frozen bundle is stable across re-extractions
└── [ ] End-to-end test passes (PDF → ExecutionBundle)
```

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         MoSPI TEMPLATE COMPILER                              │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  Pass 0-2: Raw Signal Extraction                                       │  │
│  │  (pdfplumber + LayoutLMv3 + Qwen-VL)                                  │  │
│  │  → raw text, tables, regions, entities, structure                      │  │
│  └─────────────────────────────────┬──────────────────────────────────────┘  │
│                                    │                                         │
│  ┌─────────────────────────────────▼──────────────────────────────────────┐  │
│  │  Pass 2.5: TemplateSemanticGraph Construction                          │  │
│  │                                                                        │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐            │  │
│  │  │ E1: Entity  │  │ E3: Table    │  │ E4: Statistical   │            │  │
│  │  │   Hygiene   │  │   Semantic   │  │   Context +       │            │  │
│  │  │   Compiler  │  │   Compiler   │  │   Inheritance     │            │  │
│  │  └──────┬──────┘  └──────┬───────┘  └────────┬──────────┘            │  │
│  │         │                 │                    │                        │  │
│  │  ┌──────▼──────┐  ┌──────▼───────┐           │                        │  │
│  │  │ E2: Entity  │  │ E11: Chart   │           │                        │  │
│  │  │  Normalizer │  │   Semantic   │           │                        │  │
│  │  │  + Families │  │   Compiler   │           │                        │  │
│  │  └──────┬──────┘  └──────┬───────┘           │                        │  │
│  │         │                 │                    │                        │  │
│  │  ┌──────▼──────┐         │                    │                        │  │
│  │  │ E5: Semantic│         │                    │                        │  │
│  │  │   ID Gen    │         │                    │                        │  │
│  │  └──────┬──────┘         │                    │                        │  │
│  │         └────────────────┼────────────────────┘                        │  │
│  │                          │                                             │  │
│  │              ┌───────────▼───────────┐                                 │  │
│  │              │ TemplateSemanticGraph  │ ← CENTRAL REPRESENTATION       │  │
│  │              └───────────┬───────────┘                                 │  │
│  └──────────────────────────┼─────────────────────────────────────────────┘  │
│                             │                                                │
│  ┌──────────────────────────▼─────────────────────────────────────────────┐  │
│  │  Pass 3: Question Generation                                           │  │
│  │                                                                        │  │
│  │  ┌───────────────────┐  ┌──────────────────┐                          │  │
│  │  │ E7: Deterministic │  │ E6: Alias +      │                          │  │
│  │  │   Question        │  │   ValueDomain    │                          │  │
│  │  │   Templates       │  │   Enrichment     │                          │  │
│  │  └───────────────────┘  └──────────────────┘                          │  │
│  └──────────────────────────┬─────────────────────────────────────────────┘  │
│                             │                                                │
│  ┌──────────────────────────▼─────────────────────────────────────────────┐  │
│  │  Pass 4: Emit + Validate                                               │  │
│  │                                                                        │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │  │
│  │  │ E12: Value-  │  │ E8: Slot     │  │ E9: Extract  │                │  │
│  │  │  Free Gate   │  │   Wiring     │  │   Diagnostics│                │  │
│  │  │  (HARD GATE) │  │   Validator  │  │   + Scoring  │                │  │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                │  │
│  │         │                  │                  │                         │  │
│  │         └──────────────────┼──────────────────┘                         │  │
│  │                            │                                            │  │
│  │              ┌─────────────▼─────────────┐                              │  │
│  │              │ template_emit.py           │                              │  │
│  │              │ (read from graph → write)  │                              │  │
│  │              └─────────────┬─────────────┘                              │  │
│  └────────────────────────────┼────────────────────────────────────────────┘  │
│                               │                                              │
│              ┌────────────────┼────────────────┐                             │
│              ▼                ▼                 ▼                             │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────────┐               │
│  │ ① template.    │ │ ② template.    │ │ template.          │               │
│  │    ast.json    │ │    blueprint.  │ │    diagnostics.json │               │
│  │ (render skel)  │ │    json        │ │ (quality scores)    │               │
│  └───────┬────────┘ │ (analytic      │ └────────────────────┘               │
│          │           │  brain)        │                                      │
│          │           └────────┬───────┘                                      │
└──────────┼────────────────────┼──────────────────────────────────────────────┘
           │                    │
           └────────┬───────────┘
                    │
                    ▼
     ┌──────────────────────────────┐
     │  BINDER CONTRACT COMPILER    │
     │  (S0→S3.5→Freeze→S4 handoff) │
     └──────────────────────────────┘
```

---

## Final Score Targets

| Area | Current | After Plan | Peak |
|------|---------|-----------|------|
| Entity hygiene | 5.5/10 | 9/10 | 9.5/10 |
| Entity completeness | 4/10 | 8.5/10 | 9/10 |
| Table header semantics | 5/10 | 9/10 | 9.5/10 |
| Unit coverage | 3/10 | 8.5/10 | 9/10 |
| Question completeness | 7/10 | 9/10 | 9.5/10 |
| Cross-reference integrity | 6/10 | 9/10 | 9.5/10 |
| Value-free compliance | 9/10 | 10/10 | 10/10 |
| MoSPI statistical context | 3/10 | 8.5/10 | 9/10 |
| Semantic entity IDs | 2/10 | 9.5/10 | 10/10 |
| Chart semantics | 4/10 | 8/10 | 9/10 |
| Measure families | 0/10 | 8/10 | 9/10 |
| Diagnostics/scoring | 3/10 | 9/10 | 9.5/10 |
| Binder integration | 6/10 | 9/10 | 9.5/10 |
| **Overall** | **6.2/10** | **9/10** | **9.5/10** |

---

## The One Rule (unchanged)

> **Do not extract "everything seen." Compile only reusable report structure and analytic semantics.**

```
Raw PDF signals → TemplateSemanticGraph → Validated value-free artifacts → Binder-ready contract
```

That is the MoSPI Template Compiler.
