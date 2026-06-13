# BharatStat/Statathon — Binding Contract Compiler & Template Extraction Architecture

> **Version:** v3 (Hardening Pass 3 — June 2026)  
> **Branch:** `report-builder-ui`  
> **Contract Version:** `binding.executionBundle.v1`

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Template Extraction Pipeline](#template-extraction-pipeline)
3. [Binding Phase Architecture](#binding-phase-architecture)
4. [Data Models & Contracts](#data-models--contracts)
5. [Severity & Status Control](#severity--status-control)
6. [Freeze & Versioning](#freeze--versioning)
7. [API Surface](#api-surface)
8. [End-to-End Data Flow](#end-to-end-data-flow)

---

## System Overview

The system converts MoSPI PDF statistical reports into executable analytical reports through two major phases:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          TEMPLATE EXTRACTION                                  │
│                                                                              │
│  PDF Document ─→ Multi-Pass Pipeline ─→ Enterprise AST + Blueprint           │
│  (MoSPI report)   (Pass 0-5)              (entities, questions, structure)   │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          BINDING CONTRACT COMPILER                            │
│                                                                              │
│  Blueprint + Dataset ─→ S0→S3.5 Pipeline ─→ Frozen ExecutionBundle ─→ S4     │
│  (template entities)     (resolve/confirm)    (immutable handoff)    (exec)  │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Core Principle

> **Do not hand S4 raw bindings. Hand S4 confirmed question execution plans with statistical meaning.**

The binding phase is a **Contract Compiler** — it transforms loose blueprint intent into an immutable, severity-validated, execution-ready contract that S4 can consume without interpretation.

---

## Template Extraction Pipeline

**File:** `report_builder/extraction_pipeline.py`

### Architecture

The extraction pipeline uses a multi-pass approach combining layout analysis, vision-language models, and programmatic assembly to extract structured information from MoSPI PDF reports.

### Pass Structure

| Pass | Engine | Purpose | Output |
|------|--------|---------|--------|
| **Pass 0** | pdfplumber + pdf2image | PDF rasterization | Raw text, tables, words, 150dpi images |
| **Pass 1** | LayoutLMv3 (CPU, port 8001) | Layout region detection | Bounding boxes + type + text per region |
| **Pass 2** | Qwen2.5-VL (GPU, port 8002) | Entity + structure extraction | Entities, semantic structure (NOT text/values) |
| **Pass 2.5** | Programmatic (no LLM) | Document Knowledge Graph | Entity merge, table analysis, chapter hierarchy, MoSPI patterns |
| **Pass 3** | Qwen-VL (chunked) | Question + binding extraction | Questions per section, entity binding + AnswerStructure |
| **Pass 4** | Programmatic assembly | Enterprise AST construction | TopicNode → QuestionNode → AnswerStructure → AnswerComponent |
| **Pass 5** | Gemini (optional) | Enhancement | Entity classification, alias generation, blueprint validation |

### Key Extraction Principles

1. **Extract ENTITIES + SEMANTIC CONTEXT + STRUCTURE — NOT text/values**
2. **pdfplumber table headers = gold standard entity source** (not VLM output)
3. **Per-page UNIQUE context scripts** (position-aware, entity-carrying)
4. **Fully offline** without Gemini (LLM disabled mode supported)

### Model Configuration

```
LAYOUTLM_ENDPOINT        = http://localhost:8001
SGLANG_ENDPOINT          = http://localhost:8002
SGLANG_MODEL             = Qwen/Qwen2.5-VL-3B-Instruct-AWQ
VLM_PROVIDER             = qwen | gemini | groq
REASONING_PROVIDER       = qwen | gemini | groq
```

**Task-Specific Tuning:**

| Task | Max Tokens | Temperature | Purpose |
|------|-----------|-------------|---------|
| entity_extraction | 256 | 0.1 | Precise entity identification |
| question_generation | 600 | 0.15 | Generate analytical questions |
| entity_binding | 384 | 0.1 | Bind entities to columns |
| toc_extraction | 1000 | 0.1 | Table of contents parsing |
| gap_fill | 1000 | 0.2 | Fill missing structure |
| fact_extraction | 1200 | 0.15 | Extract statistical facts |
| semantic_fallback | 2000 | 0.2 | Fallback for complex pages |
| entity_classification | 600 | 0.1 | Classify entity types |

### LLM Routing

**File:** `report_builder/llm_router.py`

- 8 Groq API keys in round-robin rotation for high-volume tasks
- Model: `llama-4-scout-17b-16e-instruct` (Groq) for vision tasks
- max_output: 8000 tokens
- Per-task provider overrides via environment variables

### Extraction Output: Enterprise AST

The pipeline produces an **Enterprise AST** with an embedded **Blueprint** subtree:

```json
{
  "documentId": "...",
  "chapters": [...],
  "entityGraph": {...},
  "blueprint": {
    "entities": [
      {
        "entityId": "ent_001",
        "canonicalName": "Labour Force Participation Rate",
        "entityType": "measure",
        "aliases": ["LFPR", "lfpr_ps_ss"],
        "unit": "percent",
        "source": "table_header"
      }
    ],
    "topics": [
      {
        "topicId": "topic_001",
        "title": "Employment Trends",
        "questions": [
          {
            "questionId": "q_001",
            "questionText": "How does LFPR vary across states?",
            "questionType": "comparison",
            "requiredEntities": [
              {"entityId": "ent_001", "role": "measure", "required": true},
              {"entityId": "ent_002", "role": "grouping", "required": true}
            ],
            "analyticsSpec": {
              "operation": "group_aggregate",
              "measure": {"entityRef": "ent_001"},
              "groupBy": [{"entityRef": "ent_002"}]
            },
            "answerStructure": {
              "components": [
                {"kind": "table", "columns": ["State", "LFPR"]},
                {"kind": "chart", "chartType": "bar"}
              ]
            }
          }
        ]
      }
    ]
  }
}
```

### Entity Filters (Garbage Rejection)

The extraction pipeline applies comprehensive filters to reject invalid entities:

- `instructional_phrase` — rejects instructional text misidentified as entities
- `incomplete_paren` — rejects text with unbalanced parentheses
- `section_title_pattern` — rejects section/chapter titles
- `too_long` — rejects strings > 100 characters
- `all_numeric` — rejects pure numbers
- `unicode_garbage` — rejects corrupted Unicode sequences

### Checkpoint Store

**File:** `report_builder/checkpoint_store.py`

- `mode="fresh"` — for new uploads (clears stale cache)
- `mode="resume"` — for midway breaks (reuse existing passes)
- Dynamic `config_hash` from source code hash (invalidates on pipeline changes)

---

## Binding Phase Architecture

### The Contract Compiler Path

```
BlueprintQA (gate)
  → S0: Dataset profiling (DatasetAST)
    → S1: Resolver proposals with evidence/risks
      → S2: Human confirmation (state machine)
        → S3: Question binding (role resolution)
          → S3 Plan Compiler (QuestionExecutionPlan[])
            → S3.5: Readiness gate (severity-validated)
              → Freeze Store (versioned persistence)
                → S4 Handoff (ExecutionBundle)
```

### Phase Details

#### S0 — Dataset Profiling

**Input:** Raw CSV upload  
**Output:** `DatasetAST`

Profiles every column:
- `name`, `dtype` (string/int/float/bool/date)
- `role` (dimension/measure/time/id/metadata)
- `cardinality` (distinct value count)
- `sampleValues` (representative values for UI)
- `unit` (percent/MT/crore/per_1000/index/ratio)
- `nullPct`, `minValue`, `maxValue`

Detects column groups (wide tables):
- `measureGroup` — e.g., "LFPR_Male", "LFPR_Female" (stem="LFPR")
- `periodGroup` — e.g., "2022_23", "2023_24", "2024_25" (stem=year pattern)

Computes `signature = hash(sorted "name:dtype")` for cache identity.

#### S1 — Entity Resolution

**File:** `report_builder/binding/resolver.py`  
**Input:** Blueprint entities + DatasetAST  
**Output:** `EntityBinding[]` with evidence and risks

**Cascade scoring:**
1. **Exact name match** → confidence 0.98+, method="exact"
2. **Alias match** → confidence 0.88+, method="alias"
3. **Synonym/token match** (via ColumnSynonymKG) → confidence 0.60-0.87, method="synonym"
4. **Embedding match** (if available) → confidence 0.60+, method="embedding"

**Cardinality classification:**
- `oneToOne` — single column binding
- `memberSet` — dimension realized as wide columns (e.g., Gender → LFPR_Male, LFPR_Female)
- `timeSeries` — realized as period columns
- `composite` — measure realized as sum/pick of multiple columns

**Evidence signals (per binding):**

| Signal | Score | When |
|--------|-------|------|
| `exact_name` | 0.98 | Column name matches entity name exactly |
| `alias` | 0.88+ | Column name matches one of entity's aliases |
| `synonym` | 0.60-0.85 | Matched via ColumnSynonymKG |
| `embedding` | 0.60+ | Semantic similarity match |
| `role_compatibility` | 1.0 / 0.3 | Entity type matches/mismatches column role |
| `unit` | 0.8 | Column has an informative unit |
| `group_match` | 0.9 | Entity maps to a column group |

**Risk codes:**

| Code | Severity | Condition |
|------|----------|-----------|
| `TYPE_MISMATCH` | warn | Entity type ≠ column role |
| `LOW_CONFIDENCE` | warn | Confidence < 0.60 |
| `WEAK_ALIAS_ONLY` | warn | Only synonym/token match (no exact/alias) |
| `AMBIGUOUS_ALTERNATIVES` | warn | Top 2 candidates within 0.10 confidence |

#### S2 — Human Confirmation

**File:** `report_builder/binding/review.py`

**State machine:**
```
proposed    ──confirm──→  confirmed
            ──override─→  overridden (human supplies new columns)
            ──reject───→  rejected
unresolved  ──map──────→  overridden (human supplies columns for unresolved entity)
```

**Key properties:**
- Nothing is auto-accepted — S1 proposes, S2 confirms
- Deterministic + offline — filesystem-backed, no DB required
- Cache by signature — same dataset shape reuses saved decisions
- Only surfaces deltas (new/unresolved) on re-runs

**Persistence:**
- `ReviewRecord` stored at `storage/bindings/{stash_dir}/review.json`
- Confirmations cached per `(templateId, signature)` pair
- Orchestrator co-locates: `datasetAST.json`, `blueprint.json`, CSV copy

#### S3 — Question Binding

**File:** `report_builder/binding/question_binder.py`

**Input:** Blueprint questions + confirmed EntityBindings + DatasetAST  
**Output:** `QuestionBinding[]`

Per-question resolution:
- Maps `requiredEntities[].entityId` → confirmed EntityBinding
- Classifies into roles: `measures`, `dimensions`, `filters`, `time`
- Resolves filter values against actual column distinct values
- Proposes time periods from time column's distinct values

**Status determination:**
- `executable` — all required entities resolved
- `blocked` — a required non-time entity is unresolved
- `degraded` — time required but no time column (snapshot mode), or filter value not found (widened)

#### S3 Plan Compiler

**File:** `report_builder/binding/question_binder.py` (function `compile_execution_plans`)

**Input:** Blueprint + QuestionBindings + DatasetAST  
**Output:** `QuestionExecutionPlan[]`

For each non-blocked question:
1. **Resolves analyticsSpec** — converts entity references to actual column names
2. **Infers formulaSpec** — CONSERVATIVE formula type detection
3. **Infers normalizationPlan** — detects wide tables needing melt
4. **Attaches sourceAnalyticsSpec** — raw blueprint spec for audit trail
5. **Builds lineage** — question → entities → columns → source

**Formula inference rules (MoSPI-safe defaults to DIRECT):**

| Trigger | Formula Type | Condition |
|---------|-------------|-----------|
| Operation = "growth" | GROWTH | Explicit in blueprint |
| Operation = "share" | SHARE | Explicit in blueprint |
| Text contains "growth rate", "year-over-year" | GROWTH | Strong keyword signal |
| Text contains "share of", "proportion of" | SHARE | Must be explicit share language |
| Text contains "distribution of" | **DIRECT** | Distribution = grouped values, NOT share |
| Text contains "per 1000", "rate per" | RATE | Explicit rate calculation |
| Default (everything else) | **DIRECT** | Safe for MoSPI — no derivation |

**Resolved analyticsSpec format (what S4 receives):**
```json
{
  "operation": "group_aggregate",
  "measure": {"column": "LFPR_ps_ss", "agg": "reported_value", "unit": "percent"},
  "groupBy": [{"column": "Sector"}],
  "filters": [{"column": "Gender", "op": "eq", "value": "Female"}],
  "time": {"column": "Year", "periods": {"current": "2024-25", "prior": "2023-24"}},
  "sort": {"by": "measure", "order": "desc"},
  "topN": null
}
```

**sourceAnalyticsSpec (raw blueprint — NOT for execution):**
```json
{
  "operation": "group_aggregate",
  "measure": {"entityRef": "ent_lfpr"},
  "groupBy": [{"entityRef": "ent_sector"}]
}
```

#### S3.5 — Readiness Gate

**File:** `report_builder/binding/readiness_gate.py`

**Input:** `QuestionExecutionPlan[]` + DatasetAST  
**Output:** `ExecutionReadinessReport`

Three-level validation with **severity-controlled outcomes**:

| Level | What it checks | Failure severity |
|-------|---------------|-----------------|
| **Technical** | Columns exist, formula columns in dataset | `error` → BLOCKED |
| **Statistical** | Unit/formula safety, denominator existence | `error` or `warn` |
| **Evidence** | Lineage completeness, source traceability | `info` → no impact |

**Severity → Plan Status → Bundle Status:**

```
severity = error  →  plan = BLOCKED    →  bundle = NOT_READY
severity = warn   →  plan = DEGRADED   →  bundle = DEGRADED
severity = info   →  plan = unchanged  →  bundle = READY (with notes)
```

**Critical checks:**

| Code | Level | Severity | Condition |
|------|-------|----------|-----------|
| `MEASURE_COLUMN_MISSING` | technical | error | Measure column not in dataset |
| `DIMENSION_COLUMN_MISSING` | technical | error | Dimension column not in dataset |
| `FILTER_COLUMN_MISSING` | technical | error | Filter column not in dataset |
| `FORMULA_NUMERATOR_MISSING` | technical | error | Formula numerator not in dataset |
| `FORMULA_DENOMINATOR_MISSING` | technical | error | Formula denominator not in dataset |
| `FORMULA_MISSING_DENOMINATOR` | statistical | **error** | SHARE/RATE/RATIO has no denominator specified |
| `CAGR_MISSING_TIME_WINDOW` | statistical | **error** | CAGR without start/end periods |
| `INDEX_MISSING_BASE` | statistical | **error** | INDEX without baseValue |
| `RATE_SUMMED` | statistical | warn | Percent/rate column aggregated with sum |
| `GROWTH_MISSING_PERIODS` | statistical | warn | GROWTH without both current+prior |
| `CHART_MISSING_DIMENSION` | statistical | warn | Chart output but no dimension resolved |
| `NORMALIZATION_INCOMPLETE` | technical | warn | WIDE_TO_LONG without idVars |
| `DERIVE_MISSING_EXPRESSION` | technical | error | DERIVE_COLUMN without expression |
| `JOIN_MISSING_KEY` | technical | error | JOIN/UNION without joinKey |
| `LOW_CARDINALITY_GROUPBY` | statistical | info | Dimension cardinality < 2 |
| `LINEAGE_MISSING_COLUMNS` | evidence | info | No source columns in lineage |
| `LINEAGE_MISSING_QUESTION` | evidence | info | No source question in lineage |

#### Blueprint QA Gate

**File:** `report_builder/binding/blueprint_qa.py`

Two gates run during `/start` before binding begins:

1. **`validate_blueprint_qa(blueprint)`** — Structural validation
   - Checks: entities exist, questions reference valid entity IDs, analyticsSpec present
   - Entity ref validation: `ent_` prefix does NOT bypass existence check
   - Result: `VALID`, `VALID_WITH_WARNINGS`, or `INVALID`
   - `INVALID` → HTTP 422 (blocks binding start)

2. **`validate_statistical_concepts(blueprint)`** — Statistical concept validation
   - Reads both `topics[].questions[]` and top-level `questions[]`
   - Validates: entity types match roles, measure entities reference valid columns
   - Result: warnings about potential statistical misuse

---

## Data Models & Contracts

### Core Binding Models (`report_builder/binding/schema.py`)

**Controlled vocabularies:**
```python
COLUMN_ROLES     = ("dimension", "measure", "time", "id", "metadata")
CARDINALITIES    = ("oneToOne", "memberSet", "composite", "timeSeries")
COMBINE_OPS      = ("none", "sum", "mean", "min", "max", "pick")
BINDING_METHODS  = ("exact", "alias", "glossary", "synonym", "embedding", "manual")
BINDING_STATUSES = ("proposed", "confirmed", "overridden", "rejected", "unresolved")
QUESTION_STATUSES = ("executable", "blocked", "degraded")
```

### Execution Contracts (`report_builder/binding/execution_contracts.py`)

**Contract version:** `binding.executionBundle.v1`

| Model | Purpose |
|-------|---------|
| `ExecutionBundle` | THE immutable handoff artifact (S3 → S4) |
| `QuestionExecutionPlan` | One fully-specified execution instruction per question |
| `ExecutionReadinessReport` | 3-level readiness assessment |
| `ReadinessCheck` | One check result (level + severity + code + recommendedAction) |
| `NormalizationPlan` | How raw data must be reshaped before execution |
| `FormulaSpec` | How a derived metric is computed |
| `StatisticalContext` | MoSPI-specific metadata (geography, time, units, sources) |
| `LineageRef` | Provenance trace from question back to source |

**Normalization types:**
```python
NORMALIZATION_TYPES = ("NONE", "WIDE_TO_LONG", "PIVOT", "JOIN", "UNION", "FILTER_ROWS", "DERIVE_COLUMN")
```

**Formula types:**
```python
FORMULA_TYPES = ("DIRECT", "SHARE", "RATE", "GROWTH", "CAGR", "INDEX", "RATIO", "DIFFERENCE")
```

**Bundle statuses:**
```python
BUNDLE_STATUSES = ("READY", "NOT_READY", "DEGRADED")
```

### QuestionExecutionPlan Structure

```json
{
  "planId": "plan_q_001",
  "questionId": "q_001",
  "questionText": "How does LFPR vary across states for females?",
  "status": "EXECUTABLE",
  
  "analyticsSpec": {
    "operation": "group_aggregate",
    "measure": {"column": "LFPR_ps_ss", "agg": "reported_value", "unit": "percent"},
    "groupBy": [{"column": "State_UT"}],
    "filters": [{"column": "Gender", "op": "eq", "value": "Female"}],
    "sort": {"by": "measure", "order": "desc"}
  },
  
  "sourceAnalyticsSpec": {
    "operation": "group_aggregate",
    "measure": {"entityRef": "ent_lfpr"},
    "groupBy": [{"entityRef": "ent_state"}],
    "filters": [{"entityRef": "ent_gender", "valueFrom": "defaultMember"}]
  },
  
  "resolvedRoles": {
    "measures": ["LFPR_ps_ss"],
    "dimensions": ["State_UT"],
    "filters": [{"column": "Gender", "op": "eq", "value": "Female", "filterApplied": true}],
    "time": {"column": null, "periods": {}, "timeResolved": false}
  },
  
  "formulaSpec": {
    "type": "DIRECT"
  },
  
  "normalizationPlan": {
    "type": "NONE"
  },
  
  "outputContract": {
    "components": [
      {"kind": "table", "columns": ["State_UT", "LFPR_ps_ss"]},
      {"kind": "chart", "chartType": "bar"}
    ]
  },
  
  "lineage": {
    "sourceQuestionId": "q_001",
    "sourceEntityIds": ["ent_lfpr", "ent_state", "ent_gender"],
    "sourceColumnIds": ["LFPR_ps_ss", "State_UT", "Gender"]
  },
  
  "evidenceRequirements": {
    "returnRowIds": true,
    "returnComputedValues": true,
    "traceToSource": true
  },
  
  "diagnostics": []
}
```

### ExecutionBundle Structure

```json
{
  "contractVersion": "binding.executionBundle.v1",
  "templateId": "plfs_2024",
  "datasetId": "ds_plfs_annual",
  "bindingAstId": "bind_plfs_2024_a1b2c3d4e5f6",
  "status": "READY",
  
  "datasetAst": { "...DatasetAST..." },
  "bindingAst": { "...BindingAST..." },
  
  "statisticalContext": {
    "geographyLevel": "state_ut",
    "timeCoverage": ["2023-24", "2024-25"],
    "unitRegistry": {"LFPR_ps_ss": "percent", "WPR_ps_ss": "percent"},
    "sourceNotes": ["PLFS Annual Report 2024-25"],
    "estimateStatus": "provisional",
    "surveyRound": "PLFS Annual 2024-25"
  },
  
  "plans": [ "...QuestionExecutionPlan[]..." ],
  "blockedQuestions": [
    {"questionId": "q_005", "reason": "Required entity 'ent_rural' unresolved", "unresolvedEntities": ["ent_rural"]}
  ],
  
  "readinessReport": {
    "executableCount": 8,
    "degradedCount": 1,
    "blockedCount": 1,
    "checks": ["...ReadinessCheck[]..."],
    "errors": [],
    "warnings": ["Column 'UR' (unit=percent) should not be summed"],
    "status": "DEGRADED"
  },
  
  "dataframeRef": {"type": "csv", "path": "storage/bindings/plfs__abc123/data.csv"},
  "lineageIndex": {"q_001": {"sourceQuestionId": "q_001", "sourceColumnIds": ["LFPR_ps_ss", "State_UT"]}},
  "frozenAt": "2026-06-10T14:30:00+00:00"
}
```

---

## Severity & Status Control

The readiness gate enforces a strict severity hierarchy that controls plan status and bundle status:

```
┌─────────────────────────────────────────────────────────────┐
│  CHECK SEVERITY    →    PLAN STATUS    →    BUNDLE STATUS    │
├─────────────────────────────────────────────────────────────┤
│  severity="error"  →    BLOCKED        →    NOT_READY        │
│  severity="warn"   →    DEGRADED       →    DEGRADED         │
│  severity="info"   →    unchanged      →    READY            │
└─────────────────────────────────────────────────────────────┘
```

**Why this matters for MoSPI:**
- A SHARE formula without a denominator is **not a warning** — it's a mathematical impossibility
- A percent column summed is concerning but S4 can still execute with a warning
- Missing lineage is informational — doesn't prevent execution

**ReadinessCheck fields:**
```python
@dataclass
class ReadinessCheck:
    level: str = "technical"       # technical | statistical | evidence
    severity: str = "error"        # error | warn | info (controls status)
    passed: bool = True
    code: str = ""                 # machine-readable code
    message: str = ""              # human-readable explanation
    planId: str = ""               # which plan this affects
    recommendedAction: str = ""    # what to do about it
```

---

## Freeze & Versioning

**File:** `report_builder/binding/freeze_store.py`

### Storage Layout

```
storage/bindings/{template_id}__{signature}/
  ├── v1.bundle.json      ← frozen ExecutionBundle (version 1)
  ├── v1.binding.json     ← frozen BindingAST (version 1)
  ├── v2.bundle.json      ← frozen ExecutionBundle (version 2, after changes)
  ├── v2.binding.json     ← frozen BindingAST (version 2)
  └── latest.json         ← pointer: {version, bindingAstId, frozenAt, contentHash}
```

### Freeze Semantics

1. **Idempotent:** Same content → same version returned (no duplicate writes)
2. **Versioned:** Changed confirmations → new version number → new frozen artifact
3. **Content-addressed:** Uses SHA-256 of bundle content (excluding timestamp) to detect changes
4. **Reproducible:** Same frozen artifact returned across repeated calls (stable identity)

### API

```python
# Freeze (called automatically by factory)
freeze_info = freeze_bundle(bundle)
# Returns: {"version": 1, "bindingAstId": "...", "frozenAt": "...", "path": "...", "isNew": True/False}

# Load a specific version (for S4/S5/S6 reproducibility)
bundle = load_frozen_bundle(template_id, signature, version=None)  # None = latest

# Check freeze metadata without loading full bundle
info = get_freeze_info(template_id, signature)
```

### Integration with Factory

The `build_execution_bundle()` factory automatically freezes after every build:
- If content unchanged: returns existing version (no disk write)
- If content changed: writes new versioned artifact
- Freeze failure is non-fatal (logged warning, execution continues)

---

## API Surface

**File:** `api/report_builder_api/binding_phase_api.py`  
**Prefix:** `/report-builder/binding-phase`

### Endpoints

| Method | Endpoint | Purpose | Gate |
|--------|----------|---------|------|
| POST | `/start` | Begin binding session (S0+S1) | BlueprintQA + StatisticalQA |
| GET | `/{template_id}/{signature}/proposals` | View S1 proposals | — |
| POST | `/{template_id}/{signature}/confirm` | Record human decision | — |
| GET | `/{template_id}/{signature}` | View full review record | — |
| POST | `/{template_id}/{signature}/finalize` | Apply confirmations (S3+B6) | Coverage gate |
| GET | `/{template_id}/{signature}/execution-ready` | **S4 Handoff** | Readiness gate |

### Lifecycle

```
1. POST /start
   ├── Validate blueprint (BlueprintQA → 422 if INVALID)
   ├── Profile dataset → DatasetAST (S0)
   ├── Resolve entities → EntityBinding[] (S1)
   └── Return: proposals + evidence + risks + QA results

2. POST /confirm × N (per entity)
   ├── Record: confirm | override | reject
   └── Human sees: evidence, risks, alternatives

3. POST /finalize
   ├── Apply all confirmations to BindingAST
   ├── Bind questions → QuestionBinding[] (S3)
   ├── Compute coverage report (B6)
   └── Return: coverage + question_bindings + errors

4. GET /execution-ready
   ├── Build ExecutionBundle (canonical factory)
   │   ├── S3 Plan Compiler → QuestionExecutionPlan[]
   │   ├── S3.5 Readiness Gate → severity validation
   │   └── Freeze Store → versioned persistence
   └── Return: complete ExecutionBundle for S4
```

### Blueprint Resolution Priority

1. Explicit uploaded file (highest priority)
2. DB-stored blueprint (if `template_id` is numeric)
3. Bundled gold PLFS template (zero-config demo)

---

## End-to-End Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  MoSPI PDF                                                                  │
│  (e.g., PLFS Annual Report 2024-25)                                        │
│                                                                             │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   EXTRACTION PIPELINE    │
                    │                         │
                    │  Pass 0: Rasterize      │
                    │  Pass 1: LayoutLMv3     │
                    │  Pass 2: Qwen-VL        │
                    │  Pass 2.5: KG Assembly  │
                    │  Pass 3: Questions      │
                    │  Pass 4: AST Build      │
                    │  Pass 5: Enhancement    │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   Enterprise AST         │
                    │   + Blueprint            │
                    │     (entities,           │
                    │      topics,             │
                    │      questions,          │
                    │      analyticsSpecs)     │
                    └────────────┬────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        │
┌──────────────┐    ┌────────────────────┐               │
│  CSV Dataset  │    │     Blueprint       │               │
│  (uploaded)   │    │  (from extraction)  │               │
└──────┬───────┘    └─────────┬──────────┘               │
       │                      │                           │
       └──────────┬───────────┘                           │
                  │                                       │
     ┌────────────▼────────────┐                          │
     │  S0: PROFILE DATASET    │                          │
     │  → DatasetAST           │                          │
     │  (columns, groups,      │                          │
     │   reshape recipes)      │                          │
     └────────────┬────────────┘                          │
                  │                                       │
     ┌────────────▼────────────┐                          │
     │  BlueprintQA GATE       │                          │
     │  → VALID / INVALID      │                          │
     │  (entity refs valid?    │                          │
     │   analyticsSpec ok?)    │                          │
     └────────────┬────────────┘                          │
                  │ (422 if INVALID)                       │
                  │                                       │
     ┌────────────▼────────────┐                          │
     │  S1: RESOLVE ENTITIES   │                          │
     │  → EntityBinding[]      │                          │
     │  (cascade scoring,      │                          │
     │   evidence, risks)      │                          │
     └────────────┬────────────┘                          │
                  │                                       │
     ┌────────────▼────────────┐                          │
     │  S2: HUMAN CONFIRM      │◄─── Dashboard UI         │
     │  → confirm/override/    │     (evidence panel,     │
     │    reject per entity    │      risk badges,        │
     │                         │      alternatives)       │
     └────────────┬────────────┘                          │
                  │                                       │
     ┌────────────▼────────────┐                          │
     │  S3: QUESTION BINDING   │                          │
     │  → QuestionBinding[]    │                          │
     │  (measures, dims,       │                          │
     │   filters, time)        │                          │
     └────────────┬────────────┘                          │
                  │                                       │
     ┌────────────▼────────────┐                          │
     │  S3 PLAN COMPILER       │                          │
     │  → QuestionExecPlan[]   │                          │
     │  (resolved analytics,   │                          │
     │   formula, norm,        │                          │
     │   sourceAnalyticsSpec)  │                          │
     └────────────┬────────────┘                          │
                  │                                       │
     ┌────────────▼────────────┐                          │
     │  S3.5: READINESS GATE   │                          │
     │  → severity validation  │                          │
     │  error → BLOCKED        │                          │
     │  warn  → DEGRADED       │                          │
     │  info  → READY          │                          │
     └────────────┬────────────┘                          │
                  │                                       │
     ┌────────────▼────────────┐                          │
     │  FREEZE STORE           │                          │
     │  → v{N}.bundle.json     │                          │
     │  (idempotent,           │                          │
     │   content-addressed)    │                          │
     └────────────┬────────────┘                          │
                  │                                       │
     ┌────────────▼────────────┐                          │
     │  EXECUTION BUNDLE       │──────────────────────────┘
     │  → S4 Handoff           │
     │                         │
     │  contractVersion        │
     │  plans[]                │
     │  statisticalContext     │
     │  readinessReport        │
     │  lineageIndex           │
     │  frozenAt               │
     └─────────────────────────┘
                  │
                  ▼
     ┌─────────────────────────┐
     │  S4: ANALYTICS ENGINE   │
     │  (executes plans,       │
     │   produces results)     │
     │                         │
     │  S5: EVIDENCE ASSEMBLY  │
     │  (uses lineageIndex)    │
     │                         │
     │  S6: REPORT GENERATION  │
     │  (final report output)  │
     └─────────────────────────┘
```

---

## File Map

| File | Phase | Purpose |
|------|-------|---------|
| `report_builder/extraction_pipeline.py` | Extraction | Multi-pass PDF → AST pipeline |
| `report_builder/llm_router.py` | Extraction | LLM routing with 8-key Groq rotation |
| `report_builder/checkpoint_store.py` | Extraction | Cache/resume for extraction passes |
| `report_builder/binding/schema.py` | Binding | Core data models (DatasetAST, EntityBinding, etc.) |
| `report_builder/binding/resolver.py` | S1 | Entity→column cascade resolution |
| `report_builder/binding/review.py` | S2 | Human confirm state machine |
| `report_builder/binding/question_binder.py` | S3 | Question role resolution + plan compilation |
| `report_builder/binding/readiness_gate.py` | S3.5 | Severity-controlled validation gate |
| `report_builder/binding/execution_contracts.py` | Contracts | ExecutionBundle + plan + readiness models |
| `report_builder/binding/execution_bundle_factory.py` | Factory | Single canonical bundle builder |
| `report_builder/binding/freeze_store.py` | Persistence | File-backed versioned freeze |
| `report_builder/binding/blueprint_qa.py` | QA Gate | Blueprint structural + statistical validation |
| `api/report_builder_api/binding_phase_api.py` | API | REST endpoints (thin wrapper) |
| `deep_bi/column_synonym_kg.py` | S1 Support | Domain-aware synonym knowledge graph |
| `tests/test_binding_contracts.py` | Testing | 21 regression tests for contract rules |

---

## Key Design Decisions

### 1. Contract Compiler, Not Resolver

The binding phase is **not** a fuzzy matching system. It is a compiler that transforms:
```
Template Blueprint + Dataset(s) → immutable BindingAST + validated QuestionExecutionPlan[] + ExecutionBundle
```

### 2. Severity Over Level

Readiness check `level` (technical/statistical/evidence) describes WHAT failed. `severity` (error/warn/info) describes HOW BADLY it failed and controls the system's response. A statistical check can be severity=error (SHARE without denominator) or severity=warn (rate summed).

### 3. DIRECT as Safe Default

For MoSPI data, the safest default formula is DIRECT (use value as-is). "Distribution of X by Y" means grouped values, NOT percentage share. Only explicit keywords like "share of", "proportion of" trigger SHARE inference.

### 4. Human-in-the-Loop is Non-Negotiable

S1 proposes, S2 confirms. No auto-acceptance. Evidence and risks are surfaced to help humans make informed decisions, but the system never silently accepts a low-confidence binding.

### 5. Immutable Frozen Artifacts

Once frozen, a bundle cannot change. Same content → same version. Changed confirmations → new version. S4/S5/S6 always reference a specific frozen version for reproducibility.

### 6. sourceAnalyticsSpec vs analyticsSpec

Plans carry TWO specs:
- `analyticsSpec` — RESOLVED (actual column names). S4 executes this.
- `sourceAnalyticsSpec` — RAW blueprint (entity references). For audit/traceability only.

---

## Regression Test Coverage

**File:** `tests/test_binding_contracts.py` — 21 tests

| Test Class | Tests | What It Covers |
|-----------|-------|----------------|
| `TestShareMissingDenominator` | 4 | SHARE/RATE/RATIO block without denominator; pass with denominator |
| `TestDistributionIsNotShare` | 2 | Distribution → DIRECT; explicit share keywords → SHARE |
| `TestGrowthUncertainDegraded` | 1 | GROWTH without periods → DEGRADED |
| `TestBlueprintQAEntityRef` | 2 | Missing entity refs caught; valid refs pass |
| `TestResolverEvidence` | 2 | Evidence populated on match; TYPE_MISMATCH risk detected |
| `TestBundleRoundTrip` | 2 | Full bundle + ReadinessCheck survive to_dict/from_dict |
| `TestFreezeIdempotent` | 3 | Idempotent freeze; changed content → new version; load works |
| `TestSeverityControlsStatus` | 3 | error→NOT_READY; warn→DEGRADED; info→READY |
| `TestCAGRIndexBlocking` | 2 | CAGR/INDEX block without required params |
