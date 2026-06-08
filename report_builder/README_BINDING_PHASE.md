# Binding Phase — Dataset ⇄ Template Binding (Implementation Architecture)

> **Status:** Implementation reference for the **binding phase** (`report_builder/binding/`).
> This is the runtime that connects a **value-free template blueprint** to a **new
> dataset** by resolving **every entity to a dataset column for every question**,
> with **human confirmation of every binding**.
>
> **Scope of THIS phase:** `S0 Profile → S1 Resolve → S2 Confirm → S3 Question-resolve`,
> emitting **`datasetAST` + `bindingAST` + a coverage report**. BI execution (S4) and
> slot-fill/render (S5/S6) are a **defined downstream contract**, deferred for now.
>
> Companion docs: [`README_TEMPLATE_EXTRACTION.md`](README_TEMPLATE_EXTRACTION.md) (R1 — produces the
> template) · [`README_BINDER_ARCHITECTURE.md`](README_BINDER_ARCHITECTURE.md) (R2 — the full S0–S6 vision).

---

## Table of Contents

1. [TL;DR](#1-tldr)
2. [Where binding sits](#2-where-binding-sits)
3. [Inputs & outputs](#3-inputs--outputs)
4. [The binder pipeline (S0 → S3)](#4-the-binder-pipeline-s0--s3)
5. [S0 — Profile the dataset](#5-s0--profile-the-dataset)
6. [S1 — Resolve entity ⇄ column](#6-s1--resolve-entity--column)
7. [One entity ⇄ many columns (cardinality)](#7-one-entity--many-columns-cardinality)
8. [S2 — Confirm every binding](#8-s2--confirm-every-binding)
9. [S3 — Resolve questions](#9-s3--resolve-questions)
10. [The two new artifacts](#10-the-two-new-artifacts-datasetast--bindingast)
11. [Offline-first behavior](#11-offline-first-behavior)
12. [Current vs Needed](#12-current-vs-needed)
13. [Reuse map](#13-reuse-map)
14. [Package layout & phases](#14-package-layout--phases)
15. [Locked decisions](#15-locked-decisions-33)

---

## 1. TL;DR

A template is **value-free** — it knows *what to compute* (`ent_wpr`, grouped by
`ent_sector`) but not *which dataset column* holds it. The **binder** closes that
gap for a specific dataset, under human supervision.

```
 ② template.blueprint.json          📊 new dataset (CSV / DataFrame)
   entities[ ent_wpr, ent_sector ]    [ wpr_pct, sector, state, period, … ]
   questions[].requiredEntities         │
        refs:{} ← EMPTY                  │
            └──────────────┬─────────────┘
                           ▼
            ┌──────────────────────────────────────┐
            │   BINDER   entity ⇄ column for ALL Q   │
            │   propose → HUMAN CONFIRM → resolve     │
            └──────────────────────────────────────┘
                           ▼
       datasetAST  +  bindingAST  +  coverage report
       (every question marked executable | blocked | degraded)
```

**The rule:** nothing is auto-accepted. Every entity→column link is **proposed**
with ranked alternatives, and a human **confirms / overrides / rejects** it. The
binder runs **fully offline** (no embeddings, no LLM) when `LLM_DISABLED=1`.

---

## 2. Where binding sits

```
  legacy PDF ──►[ EXTRACTION (R1) ]──► ① template.ast.json   (skeleton, value-free)
                                       ② template.blueprint.json (brain, value-free)
                                                │
  new dataset ──────────────────────────────────┤
                                                ▼
                            ┌──────────────────────────────────┐
                            │   BINDING PHASE  (this doc)        │
                            │   S0 Profile · S1 Resolve ·        │
                            │   S2 Confirm · S3 Question-resolve │
                            └──────────────────────────────────┘
                                                │
                          datasetAST + bindingAST + coverage report
                                                │
                            ┌─────────────── DEFERRED ───────────────┐
                            │ S4 Execute BI · S5 Fill slots · S6 Render│
                            │ → ③ report.output.ast.json + PDF + preview│
                            └──────────────────────────────────────────┘
```

This phase **stops** at a confirmed, resolved `bindingAST`. It produces no
numbers and no prose — it produces the **map** that the (later) BI executor uses
to fill the report.

---

## 3. Inputs & outputs

| | Artifact | Notes |
|---|----------|-------|
| **In** | `② template.blueprint.json` | The analytic brain. Primary = the clean `report_builder/gold_standard/` blueprint; real `outputs/<doc>/` blueprint slots in once extraction finetuning lands. |
| **In** | `① template.ast.json` *(optional here)* | Carried through for the deferred S5/S6; not required to produce `bindingAST`. |
| **In** | **dataset** | A `DataFrame`, an uploaded `dataset_id`, or a CSV path — one thin adapter, core takes a DataFrame. **One report = one dataset** (multi-dataset later). |
| **Out** | **`datasetAST`** | The profiled, self-describing dataset (roles, units, cardinality, wide-groups, reshape recipes). |
| **Out** | **`bindingAST`** | The core artifact: `entityBindings[]` (proposed→confirmed) + `questionBindings[]` (resolvedRoles + status). |
| **Out** | **coverage report** | Structured JSON + markdown digest; severities `error \| warn \| info`. |

---

## 4. The binder pipeline (S0 → S3)

```
 ② blueprint ─┐                         📊 dataset (df | dataset_id | path)
 ① ast (opt) ─┼──────────────────────────────────┘
              │                                    │
  ┌───────────┴────────────────────────────────────┴──────────────────────────┐
  │ S0 PROFILE        profiler.py            df → datasetAST                     │
  │   per-col: dtype · role(dim/measure/time/id/metadata) · cardinality ·       │
  │   sampleValues · unit · min/max · nullPct                                   │
  │   + detect WIDE column-groups (shared stem) → columnGroups[] + reshape[]    │
  ├──────────────────────────────────────────────────────────────────────────────┤
  │ S1 RESOLVE        resolver.py            entity ⇄ column(s) → PROPOSED        │
  │   cascade: exact → alias → glossary → synonymKG → embedding(provider)        │
  │   cardinality: oneToOne | memberSet | composite | timeSeries                 │
  │   soft type-penalty · keep top-3 alternatives[]                              │
  ├──────────────────────────────────────────────────────────────────────────────┤
  │ S2 CONFIRM ★      review.py              proposed → confirmed|overridden|…    │
  │   dashboard (REST) + headless JSON file · override→ANY col + warn            │
  │   cache by signature hash(name:dtype) · re-run asks only deltas              │
  ├──────────────────────────────────────────────────────────────────────────────┤
  │ S3 QUESTION       question_binder.py     requiredEntities(role) → columns     │
  │   filter values codes⇄labels (value_resolver.py)                            │
  │   period roles + time-column (HUMAN-verified) · snapshot when absent         │
  │   degrade(snapshot/widen)+flag · BLOCK missing-required (+ inline map)        │
  └──────────────────────────────────────────────────────────────────────────────┘
                           ▼
        datasetAST + bindingAST + coverage report   ──►  [ deferred: S4 → ③ ]
```

---

## 5. S0 — Profile the dataset

`binding/profiler.py` turns a DataFrame into a **`datasetAST`**. It reuses the
low-level math in `profiling/dataset_intel.py` + `analytics/distribution.py`,
then adds the things the binder needs: **role**, **unit**, **archetype**, and
**wide column-groups**.

### Column-role inference (deterministic, offline, explainable)

```
 column                  signal                                  → role
 ───────────────────────────────────────────────────────────────────────
 Site_ID                 name ~ /_id|code$/  &  ~unique          → id
 survey_year / period    name ~ /year|date|period|round/ | dt    → time
 State, Resource_Category low-card categorical                   → dimension
 Unit_of_Measure         describes another column (units)        → metadata
 Proved_Reserves         numeric & not id/time                   → measure
 Potential_Capacity_MW   numeric; unit "MW" parsed from name     → measure
```

> The energy CSV has **no** time column — that's a real, supported case (see S3).

### Wide column-group detection

Government tables are often **wide**. S0 flags groups that share a stem so S1 can
treat them as one concept:

```
 Proved_Reserves · Indicated_Reserves · Inferred_Reserves · Total_Reserves
        └──────────── shared stem "_Reserves" ───────────┘   → measureGroup

 WPR_2023_24 · WPR_2024_25                                    → periodGroup
        └─ shared stem "WPR_" + period suffix ─┘
```

These become `datasetAST.columnGroups[]`, each with a **`reshape` recipe** (a
lazy melt — see §7). The original wide DataFrame is never mutated.

---

## 6. S1 — Resolve entity ⇄ column

`binding/resolver.py` runs a **cascade**, stopping at the first confident hit but
**always** keeping ranked `alternatives[]` for the confirm UI.

```
 entity (name, type, aliases, unit, valueDomain)     column (name, dtype, role, samples)
        │                                                   │
        ▼                  CASCADE (stop at first ≥ thr)    ▼
   ┌──────────────────────────────────────────────────────────┐
   │ 1 exact      normalized name == column            1.00    │
   │ 2 alias      alias / abbrev expansion match       ~0.92   │
   │ 3 glossary   glossary term → column pattern       ~0.85   │
   │ 4 synonymKG  ColumnSynonymKG concept ↔ column     ~0.70   │  ← offline stops here
   │ 5 embedding  cosine(name, column) — provider       ~       │  ← online enhancement
   └──────────────────────────────────────────────────────────┘
        │
        ▼  { columns[], cardinality, confidence, method, alternatives[] }   status = PROPOSED
```

**Soft type-compatibility gate (never hides a candidate).** A `measure` entity
*should* bind to a numeric column; a mismatch only **lowers** confidence — the
candidate still appears in `alternatives[]` so the human can pick it if role
inference was wrong.

```
 measure  ⇄ numeric      ✓ full score
 dimension⇄ categorical  ✓ full score
 time     ⇄ date/period  ✓ full score
 measure  ⇄ text         ⚠ penalized, still shown
```

**Propose-only.** Confidence **orders** candidates; it never **auto-accepts**.
Top-1 is `status: proposed`, top-3 kept as `alternatives[]`.

---

## 7. One entity ⇄ many columns (cardinality)

A strict 1↔1 model can't describe real data. Every `entityBinding` carries a
**`cardinality`** so the binder expresses the common wide-data shapes:

```
 cardinality   meaning                          energy-CSV example
 ─────────────────────────────────────────────────────────────────────────────
 oneToOne      one entity → one column          ent_wpr        ⇄ wpr_pct
 memberSet     a DIMENSION whose members        ent_reserve_type ⇄
               ARE columns                         Proved_Reserves    → "Proved"
                                                    Indicated_Reserves → "Indicated"
                                                    Inferred_Reserves  → "Inferred"
 composite     a MEASURE assembled from         ent_total_reserves ⇄
               several columns (+combine)           Total_Reserves            (explicit)
                                                 … or sum(Proved,Indicated,Inferred)
 timeSeries    a TIME role encoded as           ent_period ⇄
               period-suffixed columns              WPR_2023_24 → 2023-24
                                                    WPR_2024_25 → 2024-25
```

Schema fields: `cardinality`, `columns[]` (with optional `memberLabel` / `period`),
and `combine: none | sum | mean | min | max | pick`.

### How it flows

```
 S0  detect wide group  Proved/Indicated/Inferred/Total_Reserves
        → columnGroups[ {stem:"_Reserves", members:[…], kind:measureGroup} ]
 S1  classify cardinality
        ent_reserve_type (dim)  + measureGroup stem  → memberSet
        ent_total_reserves(msr) + "Total" present    → composite(combine=pick→Total)
        ent_period (time)       + periodGroup        → timeSeries
        else                                          → oneToOne
 S2  human confirms cardinality + columns + combine (can switch Total ↔ sum(parts))
 S3  a question grouping BY ent_reserve_type triggers the recorded reshape:
        melt the group → long "Reserve_Type" + "value" (scoped copy, lazy)
```

### memberSet member labels
Derived from the **differing stem**, cleaned + title-cased, and **editable** in
the UI: `Proved_Reserves → "Proved"`, `Potential_Capacity_MW → "Potential Capacity"`.

### composite defaults & sanity-check
When **both** a total column and its parts exist, the binder **proposes the
explicit `Total_Reserves`** (offers `sum(parts)` as the alternative) and
**cross-checks** them — if `sum(parts)` disagrees with `Total` beyond tolerance,
it raises a non-blocking `warn` in coverage (catches wrong groupings early).

### wide → long reshape (lazy)
A confirmed `memberSet`/`timeSeries` implies a melt. It is applied **lazily, on a
per-question scoped copy** — the original wide DataFrame is preserved so `oneToOne`
questions still see the wide columns. `datasetAST.reshape[]` stores the recipe.

```
 WIDE (kept)                          LONG (scoped, only when a Q needs it)
 State Proved Indicated Inferred  →   State  Reserve_Type  value
 Jhar.  671    329       98            Jhar.  Proved        671
                                       Jhar.  Indicated     329
                                       Jhar.  Inferred       98
```

---

## 8. S2 — Confirm every binding

The **hard requirement**: no silent auto-accept. `binding/review.py` is a state
machine over each binding.

```
 ┌─ Binding Review (dashboard OR headless JSON) ───────────────────────────────┐
 │ Entity: Reserve Type   (dimension)                cardinality: memberSet     │
 │ Proposed columns →  Proved_Reserves "Proved" · Indicated_Reserves "Indicated"│
 │                     Inferred_Reserves "Inferred"           confidence 0.78    │
 │ Samples:  671, 329, 98, 1098 …                                              │
 │ Alternatives:  Total_Reserves (0.55)                                        │
 │   [ Confirm ]   [ Override ▼ any column ]   [ Reject ]                       │
 └──────────────────────────────────────────────────────────────────────────────┘

 status:  proposed ──► confirmed | overridden(cols) | rejected | unresolved
```

- **Two surfaces, one contract.** Interactive **dashboard** via FastAPI REST
  (`GET proposals` / `POST confirm`) **and** a **headless JSON** path
  (`proposals.json` → `confirmations.json`, or `--accept-proposed` for CI). Both
  read/write the same `bindingAST` fragments — so offline/air-gapped runs confirm
  too.
- **Override freedom.** The user may bind to **any** dataset column; a
  type-mismatch only shows a **non-blocking warning** (records `method: manual`,
  `status: overridden`).
- **Cache & deltas.** Confirmed bindings are cached keyed by
  **`signature = hash(sorted(name:dtype))`**. A re-run with the same schema reuses
  the cache and **asks only about deltas** (new/renamed columns + previously
  unresolved/rejected entities). Row-level data churn does **not** trigger
  re-confirmation.
- **Persistence.** File-first at `storage/bindings/<templateId>__<sig>.json`
  (works offline) + an optional DB row to index it for the dashboard.

---

## 9. S3 — Resolve questions

`binding/question_binder.py` turns confirmed columns into **per-question
executability**, reusing `binding/value_resolver.py` for filter values.

```
 QuestionNode (analyticsSpec + requiredEntities roles)
   │  resolvedRoles ← confirmed columns by role (measure / grouping / filter / time)
   │  filter VALUES  ← value cascade: exact → normalize → synonym(Rural↔R) → fuzzy → confirm
   │  PERIOD roles   ← time column (HUMAN-picked) → current=latest, prior=prev, delta=diff
   ▼
 status?
   ├ executable  all required roles resolved
   ├ degraded    ran, but a soft fallback was applied (snapshot / widened filter) + flag
   └ blocked     a REQUIRED entity is unbound → coverage report + inline manual-map to un-block
```

### Filter values: codes ⇄ labels
```
 blueprint member   dataset values            resolution
 "Rural"            "Rural" | "R" | 1 | rural  exact → case/space-norm → synonym(R) → fuzzy → confirm
 "Karnataka"        "KA" | 29 | "Karnataka "   …unmatched values surface in the confirm UI
```

### Period roles — human-verified
The binder **proposes** the time column + resolved periods, but the human
**selects/confirms the time column from the available columns** and verifies the
mapping. `current = latest distinct`, `prior = previous`, `delta = current − prior`
— uniform across calendar / fiscal / survey-round (just ordering distinct values).

### No time column (the energy case) — degrade, then verify
```
 question needs: time(current)     dataset time columns: NONE
   → run as single-period SNAPSHOT (drop period filter/compare)
   → flag timeResolved:false        → HUMAN verifies (accept snapshot OR designate a column)
```

### Missing required vs missing default
```
 REQUIRED entity unbound      → BLOCK the question (+ inline manual map to un-block)   [error]
 filter default member absent → WIDEN (compute unfiltered) + flag filterApplied:false  [warn]
```

Nothing is ever silently dropped — every degradation/blockage is recorded in the
coverage report with a severity.

---

## 10. The two new artifacts (`datasetAST` + `bindingAST`)

### `datasetAST` — the profiled, self-describing dataset
```jsonc
{
  "datasetId": "energy_2025", "sourceFile": "unified_energy_reserves_dataset.csv",
  "rowCount": 1000, "archetype": "energy",
  "columns": [
    {"name":"State","dtype":"string","role":"dimension","cardinality":28,
     "sampleValues":["Jharkhand","Odisha"],"unit":null,"nullPct":0.0},
    {"name":"Proved_Reserves","dtype":"int","role":"measure",
     "min":0,"max":2945,"unit":"Billion Tonnes","nullPct":0.0},
    {"name":"Potential_Capacity_MW","dtype":"int","role":"measure","unit":"MW"}
  ],
  "columnGroups": [
    {"stem":"_Reserves","kind":"measureGroup",
     "members":["Proved_Reserves","Indicated_Reserves","Inferred_Reserves","Total_Reserves"]}
  ],
  "reshape": [
    {"groupStem":"_Reserves","kind":"melt","idVars":["State","Resource_Category"],
     "valueVar":"value","memberVar":"Reserve_Type"}
  ]
}
```

### `bindingAST` — the core artifact
```jsonc
{
  "templateId":"tpl_plfs_annual_v1", "datasetId":"energy_2025",
  "datasetSignature":"a1b2c3…",
  "entityBindings": [
    {"entityId":"ent_total_reserves","entityName":"Total Reserves","entityType":"measure",
     "cardinality":"composite","columns":[{"column":"Total_Reserves"}],"combine":"pick",
     "confidence":0.93,"method":"alias","status":"confirmed",
     "alternatives":[{"column":"Proved_Reserves","confidence":0.41,"method":"synonym"}]},
    {"entityId":"ent_reserve_type","entityName":"Reserve Type","entityType":"dimension",
     "cardinality":"memberSet",
     "columns":[{"column":"Proved_Reserves","memberLabel":"Proved"},
                {"column":"Indicated_Reserves","memberLabel":"Indicated"},
                {"column":"Inferred_Reserves","memberLabel":"Inferred"}],
     "combine":"none","confidence":0.78,"method":"synonym","status":"proposed","alternatives":[]}
  ],
  "questionBindings": [
    {"questionId":"q_01","status":"degraded",
     "resolvedRoles":{
        "measures":["Total_Reserves"],"dimensions":["State"],
        "filters":[{"column":"Resource_Category","op":"eq","value":"Coal","filterApplied":true}],
        "time":{"column":null,"periods":{"current":null,"prior":null},"timeResolved":false}},
     "unresolvedEntities":[],"notes":["no time column → single-period snapshot"]}
  ],
  "coverage": {
    "entities":{"bound":2,"pending":1,"unresolved":0},
    "questions":{"executable":3,"blocked":1,"degraded":1},
    "issues":[{"severity":"warn","code":"TIME_SNAPSHOT","questionId":"q_01",
               "message":"No time column; ran as snapshot."}]
  }
}
```

---

## 11. Offline-first behavior

The binder honors the same `LLM_DISABLED` switch as extraction. Offline, the
**embedding stage is skipped** and the cascade uses stages 1–4 only — still
producing a **complete `bindingAST`** that the human confirms.

```
 ONLINE   exact → alias → glossary → synonymKG → EMBEDDING(Gemini→BGE-M3) → confirm
 OFFLINE  exact → alias → glossary → synonymKG → [skipped]                → confirm
```

- **Embedding provider abstraction:** try Gemini `gemini-embedding-001`
  (corp-net) → BGE-M3 (local laptop) → skip. Best-available wins.
- `scripts/simulate_binding_offline.py` runs the whole phase with `LLM_DISABLED=1`
  and `--accept-proposed`, verifying a complete `bindingAST` + coverage with no
  network.

---

## 12. Current vs Needed

```
ENTITY ↔ COLUMN
  current:  TemplateBinder auto-accepts ≥0.90, rest "pending"; 1↔1 only; no UI; no cache
  needed:   propose → CONFIRM every; 1↔many (memberSet/composite/timeSeries);
            alternatives+samples; cache by (templateId + name:dtype signature)

DATASET PROFILE
  current:  api dataset_profiler (dtype/cardinality/samples) — no role, no unit, no wide-groups
  needed:   binding/profiler.py → datasetAST with role + unit + archetype + columnGroups + reshape

FILTER VALUES
  current:  none (codes vs labels unhandled)
  needed:   value cascade exact→normalize→synonym(Rural↔R)→fuzzy→confirm unmatched

TIME / PERIODS
  current:  none (periods were hardcoded years in the legacy instance)
  needed:   human-verified time-column pick; current/prior/delta; snapshot when absent + flag

COVERAGE / SAFETY
  current:  silent fallbacks; partial binding tolerated
  needed:   strict — block missing-required (inline manual-map to un-block);
            structured coverage + severities; nothing dropped silently

OFFLINE
  current:  binder path assumes embeddings/online
  needed:   first-class LLM_DISABLED — cascade stages 1–4 + human confirm, complete bindingAST
```

---

## 13. Reuse map

| Stage | Reuse | Location |
|-------|-------|----------|
| S0 profile | column profiles, dtype/cardinality, distribution | `profiling/dataset_intel.py`, `analytics/distribution.py` |
| S0 ingest | schema inference, file loading | `core/ingestion.py`, `api/services/dataset_profiler.py` |
| S1 cascade | `ColumnResolver` (exact→alias→glossary→fuzzy→synonym) | `template_engine/binder/column_resolver.py` |
| S1 binder | `TemplateBinder`, `DatasetSchema` | `template_engine/binder/template_binder.py` |
| S1 synonyms / values | `ColumnSynonymKG` (has an **energy** domain already) | `deep_bi/column_synonym_kg.py` |
| S1 embedding | provider abstraction + `llm_disabled()` | `report_builder/llm_router.py` |
| schema | dataclass + `to_dict`/`from_dict` conventions | `ast_core/schema.py` |

---

## 14. Package layout & phases

```
report_builder/binding/
├── __init__.py
├── schema.py          B0  DatasetAST · BindingAST · CoverageReport (+ to_dict/from_dict)
├── profiler.py        S0  DataFrame → datasetAST (roles + units + wide-groups + reshape)
├── resolver.py        S1  entity ⇄ column cascade + cardinality + embedding provider
├── value_resolver.py  S3  filter VALUE cascade (codes ⇄ labels)
├── question_binder.py S3  requiredEntities/roles → resolvedRoles; period/time; degrade/block
├── review.py          S2  proposed→confirmed state machine + cache + proposals/confirmations
└── report.py          coverage report (structured JSON + markdown digest)

api/…                  B5  REST: GET /bindings/{sig}/proposals · POST /bindings/{sig}/confirm
storage/bindings/      B5  <templateId>__<signature>.json  (file-first cache)
scripts/run_binding.py            B7  CLI entry
scripts/simulate_binding_offline.py B7  offline e2e (LLM_DISABLED=1, --accept-proposed)
tests/test_binding_*.py           B7  unit + golden e2e (synthetic PLFS) + energy smoke
```

> **Schema location:** the binding subtrees live in `report_builder/binding/schema.py`
> (self-contained, independently testable) rather than bloating the 600-line
> `ast_core/schema.py`. When the deferred S5/S6 merge `datasetAST`/`bindingAST`
> into ③, they import from here.

### Phases (each independently verifiable)

| Phase | Delivers | Depends on |
|-------|----------|-----------|
| **B0** | `schema.py` — DatasetAST/BindingAST/Coverage models | — |
| **B1** | `profiler.py` (S0) — roles + units + wide-groups | B0 |
| **B2** | `resolver.py` (S1) — cascade + cardinality + alternatives | B0, B1 |
| **B3** | `value_resolver.py` + `question_binder.py` (S3) | B2 |
| **B4** | `review.py` (S2) — confirm state machine + cache | B2 |
| **B5** | API REST endpoints + `storage/bindings/` persistence | B4 |
| **B6** | `report.py` — coverage report | B3 |
| **B7** | CLI + offline sim + golden tests | B1–B6 |

---

## 15. Locked decisions (33)

**Inputs & scope:** gold blueprint first · DataFrame-core adapter (df/dataset_id/path) ·
raw CSV → S0 profiler · **offline-first** binder · BI/render **deferred**.

**S0 profile:** new `profiler.py` reusing low-level math · deterministic role rules ·
wide measure/period group detection + lazy reshape recipe.

**S1 resolve:** cascade exact→alias→glossary→synonymKG→embedding · embedding **provider
abstraction** (Gemini→BGE-M3→skip) · **soft** type-penalty (never hide) · **propose-only**,
top-3 alternatives · 1↔many via **cardinality** (oneToOne/memberSet/composite/timeSeries)
+ combine.

**S2 confirm:** dashboard **+ headless JSON** · cache `hash(name:dtype)` · REST contract ·
override→**any column** + warn · **ask only deltas** · file-first persistence.

**S3 questions:** filter value cascade (codes⇄labels) · **human-verified** time-column +
periods · **snapshot** when no time col + flag · **block** missing-required (+ inline map) ·
widen-on-missing-default + flag.

**1↔many detail:** composite prefers explicit **Total** (sum as alt) · cross-check sum vs
total → **warn** · member labels from stem (editable) · reshape **lazy per-question**.

**Outputs:** ③ JSON + coverage **first** · adaptive evidence · central en-IN formatter ·
structured coverage + severities + markdown · golden e2e = **synthetic PLFS CSV** + gold
blueprint · energy CSV = 2nd-archetype smoke test.

---

*End of binding-phase architecture. Implementation lives in `report_builder/binding/`.*
