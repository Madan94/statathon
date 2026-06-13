# Binder Architecture — Dataset ⇄ Template Binding (R2)

> **Status:** Reference document (agent-mode knowledge dump) capturing every
> locked design decision for the **binding phase** and the **gold-standard AST
> design** it produces. Deep refinement happens in **plan mode** next.
>
> Companion doc: [`README_TEMPLATE_EXTRACTION.md`](README_TEMPLATE_EXTRACTION.md) (R1) — produces the
> templates this binder consumes.

---

## 0. TL;DR

The **binder** is the runtime that takes a **value-free template** (① skeleton +
② brain) plus a **new dataset** and produces a **filled, fully-traceable report**
(③) — every table cell, chart slice, metric, and sentence linked back through
*question → BI plan → dataset rows*.

```
 ① template.ast.json ─┐
 ② template.blueprint.json ─┼─► [ BINDER : S0…S6 ] ─► ③ report.output.ast.json ─► PDF + dashboard preview
 📊 new dataset (DataFrame) ─┘                          (+ datasetAST, bindingAST, evidenceAST)
```

**Core mission:** resolve **entities ⇄ dataset columns** for **all** questions,
with **human confirmation of every binding**, then execute BI per question and
fill the template slots.

---

## 1. Template vs Instance (the mental model)

```
        AUTHORED ONCE  (gold, value-free)                 GENERATED EACH RUN
 ┌──────────────────────────────┐ ┌──────────────────────────────┐ ┌─────────────────────────┐
 │ ① template.ast.json          │ │ ② template.blueprint.json    │ │ ③ report.output.ast.json│
 │   RENDER SKELETON            │+│   ANALYTIC BRAIN             │→│   ① cloned + slots       │
 │  layout·geometry·style·      │ │  entities·glossary·questions·│ │   FILLED by BI from new  │
 │  semantic + EMPTY SLOTS      │ │  analyticsSpec·refs→①·       │ │   dataset                │
 │  (cols no rows; biQuery no   │ │  palette·renderProfile       │ │  + datasetAST·bindingAST │
 │   prose; chart spec no       │ │                              │ │  + evidenceAST           │
 │   series; metric no value)   │ │                              │ │  VALUES LIVE ONLY HERE   │
 └──────────────────────────────┘ └──────────────────────────────┘ └─────────────────────────┘
              └───────────── linked by IDs (tableRef · chartRef · contentRef) ──────────┘
```

The legacy root `Enterprise_Document_AST.json` is a **filled instance**
(a photograph). It is the **shape ③ must match** — but a template is the
**negative** that prints a new photo from new data. Values, prose, and meaning
**never** live in ① or ②.

---

## 2. Gold-standard ③ — what the binder must produce

Take the legacy 19-subtree AST as the destination shape, then **add 3 provenance
subtrees** and **augment 4** so every number is auditable.

```
                       LEGACY INSTANCE (today)        ENHANCED ③ (binder target)
──────────────────────────────────────────────────────────────────────────────────
+ datasetAST           ✗                              schema+role+cardinality+samples (BI self-describes)
+ bindingAST           ✗                              entity→column, confidence, method, PROPOSED/CONFIRMED, alternatives[]
+ evidenceAST          ✗                              per number: rowIds[] + computation (row-level audit)
~ analyticsAST         metrics only; aggr/rank/trend=[] + plans[] + executions[] + aggregations/rankings/trends FILLED
~ tableAST             columns + rows                 + columnGroups + per-col unit/format/align + dims/measures/breakdowns
~ chartAST             series{label,value}            + palette + unit + dimension + sourceTableRef + figureRef
~ figureAST            caption/description            + chartRef (figure ↔ chart)
~ components.refs       {}                            FILLED: tableRef/chartRef/contentRef/analyticsRef/evidenceRef
~ metadata             basic                          + locale/numberFormat (en-IN) + unit registry
```

### 2a. `datasetAST` (NEW) — the bound dataset, self-describing
```jsonc
"datasetAST": {
  "datasetId":"plfs_2025", "sourceFile":"…mospi_mock_survey_data.csv",
  "rowCount":5000, "detectedArchetype":"PLFS",
  "columns":[
    {"name":"sector","dtype":"string","role":"dimension","cardinality":2,
     "sampleValues":["Rural","Urban"],"nullPct":0.0},
    {"name":"sal","dtype":"float","role":"measure","min":0,"max":250000,"unit":"INR","nullPct":0.01},
    {"name":"survey_date","dtype":"date","role":"time","cardinality":365}] }
```

### 2b. `bindingAST` (NEW) — the core artifact of this phase
```jsonc
"bindingAST": {
  "templateId":"plfs_annual","datasetId":"plfs_2025",
  "entityBindings":[
    {"entityId":"ent_lfpr","entityName":"LFPR","entityType":"measure",
     "column":"lfpr_pct","confidence":0.93,"method":"alias",
     "status":"confirmed",                         // proposed|confirmed|overridden|rejected|unresolved
     "alternatives":[{"column":"wpr_pct","confidence":0.41,"method":"embedding"}],
     "unit":"%"},
    {"entityId":"ent_state","entityName":"State/UT","entityType":"dimension",
     "column":"state_code","confidence":0.88,"method":"glossary","status":"proposed"}],
  "questionBindings":[
    {"questionId":"q_03","status":"executable",     // executable|blocked
     "resolvedRoles":{"measures":["lfpr_pct"],"dimensions":["state_code"],
                      "filters":[{"column":"sector","value":"Rural"}],"time":[]},
     "planRef":"plan_03","executionRef":"exec_03","unresolvedEntities":[],"notes":[]}],
  "coverage":{"entitiesBound":12,"pending":3,"unresolved":1,
              "questionsExecutable":8,"blocked":2} }
```

### 2c. `analyticsAST` (AUGMENT — fill the empty arrays)
```jsonc
"analyticsAST": {
  "plans":[{"planId":"plan_03","questionId":"q_03",
    "steps":[{"op":"aggregate","params":{"by":["state_code"],"metric":"lfpr_pct","fn":"mean"}},
             {"op":"rank","params":{"metric":"lfpr_pct","order":"desc","top_k":10}}]}],
  "executions":[{"executionId":"exec_03","planId":"plan_03",
    "finalTableRef":"table_007","finalChartRef":"chart_004","status":"ok"}],
  "rankings":[{"rankId":"rank_02","questionId":"q_03","metric":"lfpr_pct","order":"desc","topK":10,
    "result":[{"rank":1,"group":"Himachal Pradesh","value":78.4}],
    "sourceColumns":["state_code","lfpr_pct"],"rowIds":[12,45,88]}],
  "aggregations":[ /* … */ ], "trends":[ /* … */ ],
  "metrics":[{"metricId":"m_01","name":"All-India LFPR","value":60.1,"unit":"%","rowIds":[…],"questionId":"q_03"}] }
```

### 2d. `evidenceAST` (NEW) — row-level provenance
```jsonc
"evidenceAST": { "evidence":[
  {"evidenceId":"ev_11","questionId":"q_03","componentId":"q3_c2","kind":"rank",
   "datasetId":"plfs_2025","rowIds":[12,45,88],"columns":["state_code","lfpr_pct"],
   "computation":{"fn":"mean","by":"state_code"},"value":78.4,"confidence":0.93}] }
```
Legacy `factGraph.sourceRefs` points at **PDF pages**; a regenerated report must
point every number at **dataset rows**. The existing `EvidenceLedger` and
`AnalyticsExecutor.row_ids` already produce this — we just persist it.

### 2e. Filled `blueprint` refs
```jsonc
"components":[
  {"componentId":"q3_c1","type":"narrative_paragraph",
   "refs":{"contentRef":"p_041","analyticsRef":"rank_02","evidenceRef":"ev_11"}},
  {"componentId":"q3_c2","type":"grouped_bar_chart",
   "refs":{"chartRef":"chart_004","analyticsRef":"rank_02","evidenceRef":"ev_11",
           "entityRefs":["ent_lfpr","ent_state"]}}]
```

---

## 3. The binder pipeline (S0 → S6)

```
 ① template.ast.json    ② template.blueprint.json    📊 new dataset (DataFrame)
        └──────────────────────┬──────────────────────────┘
                               ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ S0  PROFILE          dataset → datasetAST                                 │
 │     per column: dtype · role(dim/measure/time/id) · cardinality ·         │
 │     samples · unit · min/max · null% · archetype(PLFS/NSSO/energy)        │
 ├─────────────────────────────────────────────────────────────────────────┤
 │ S1  RESOLVE          entity ⇆ column  → bindingAST (PROPOSED)             │
 │     cascade: exact → alias → glossary → synonymKG → embedding(BGE-M3/     │
 │     Gemini).  Each entity: best column + confidence + method + alts[]     │
 ├─────────────────────────────────────────────────────────────────────────┤
 │ S2  CONFIRM ★ every binding (HARD REQUIREMENT)                            │
 │     dashboard UI shows: entity │ proposed col │ alternatives │ samples │  │
 │     confidence.  user: confirm / override / reject → status.              │
 │     persist to binding-cache keyed by (templateId + column signature)     │
 ├─────────────────────────────────────────────────────────────────────────┤
 │ S3  QUESTION RESOLVE  requiredEntities(role) → confirmed columns          │
 │     resolve filter VALUES vs valueDomain (Rural/Urban vs codes) ·         │
 │     resolve PERIOD roles (current/prior → dataset max/prev) ·             │
 │     mark each question  executable │ blocked(missing required)            │
 ├─────────────────────────────────────────────────────────────────────────┤
 │ S4  EXECUTE          analyticsSpec → AnalyticsPlan → AnalyticsExecutor    │
 │     (BI override ONLY if spec infeasible — log it) →                      │
 │     analyticsAST(plans/executions/rankings/aggs/trends) + evidenceAST     │
 │     (final_table/chart/metrics + rowIds per number)                       │
 ├─────────────────────────────────────────────────────────────────────────┤
 │ S5  FILL SLOTS       per component, honor outputContract → fill ③         │
 │     table→rows(columnGroups, en-IN) · chart→series+palette ·             │
 │     narrative→≤N words(mustMention, BI/Gemini writes) · metric→{value,unit}│
 │     set refs: tableRef/chartRef/contentRef/analyticsRef/evidenceRef       │
 ├─────────────────────────────────────────────────────────────────────────┤
 │ S6  ASSEMBLE+RENDER  MultiASTBuilder(clone ① + slots + provenance)        │
 │     render (hybrid coords/flow). GATES: all required bound · all          │
 │     executable Q produced output · every number has evidence              │
 └─────────────────────────────────────────────────────────────────────────┘
                               ▼
        ③ report.output.ast.json  +  rendered PDF  +  coverage/binding report
```

---

## 4. S1 — Entity ⇄ column resolution (the heart)

Cascade, stop at first hit ≥ threshold; **always** keep ranked `alternatives[]`
for the confirm UI.

```
 entity (name, type, aliases, unit, valueDomain)            dataset column (name, dtype, role, samples)
        │                                                          │
        ▼                                                          ▼
   ┌──────────────────────────── CASCADE ────────────────────────────┐
   │ 1 exact      name == column (normalized)                  1.00   │
   │ 2 alias      alias/abbrev expansion match                 0.92   │
   │ 3 glossary   glossary term → column pattern               0.85   │
   │ 4 synonymKG  ColumnSynonymKG concept↔column               0.70   │
   │ 5 embedding  cosine(name, column) — BGE-M3 local / Gemini  ~      │
   │ (6 LLM disambig — optional, only for the ambiguous middle)        │
   └──────────────────────────────────────────────────────────────────┘
        │
        ▼  {column, confidence, method, alternatives[]}  status = PROPOSED
```

**Type compatibility gate:** a `measure` entity should bind to a numeric column,
a `dimension` to a low-cardinality categorical, a `time` to a date/period column.
Mismatches are surfaced as low confidence in the confirm UI.

**Embeddings:** BGE-M3 is blocked on the corporate network but **available on the
user's own laptop**; Gemini `gemini-embedding-001` works on the corp net. The
matcher uses whichever provider is available (provider abstraction), and the
cascade degrades gracefully to stages 1–4 if no embedder is present.

---

## 5. S2 — Confirm every binding (hard requirement)

```
 ┌─ Binding Review (dashboard / Next.js) ──────────────────────────────────────┐
 │ Entity: LFPR (measure, unit %)                                              │
 │ Proposed → column  lfpr_pct          confidence 0.93   method alias         │
 │ Samples: 60.1, 58.7, 62.3, …                                               │
 │ Alternatives:  wpr_pct (0.41)   ur_pct (0.22)                              │
 │   [ Confirm ]   [ Override ▼ ]   [ Reject ]                                 │
 └──────────────────────────────────────────────────────────────────────────────┘
```

- Status transitions: `proposed → confirmed | overridden(col) | rejected`.
- **Cache** confirmed bindings keyed by **(templateId + dataset column
  signature)** → re-runs ask only **deltas** (new/changed columns).
- No silent auto-accept — even high confidence is *proposed* until confirmed
  (the user's explicit rule). A "confirm all high-confidence" convenience action
  is allowed but is still an explicit user action.

---

## 6. S3/S4 — Question resolution & execution

```
QuestionNode (analyticsSpec + requiredEntities roles)
   │  resolvedRoles ← confirmed columns by role (measure/dimension/filter/time)
   │  filter values ← match valueDomain member to dataset value (Rural↔"R"/1)
   │  period roles  ← current=max(period), prior=current-1, delta=current-prior
   ▼
 executable?  ── missing required entity ──► BLOCKED (coverage report; manual map)
   │ yes
   ▼
 analyticsSpec ──► AnalyticsPlan (deep_bi.AnalyticsPlanner)
   │  BI OVERRIDE only if spec infeasible on this dataset (logged)
   ▼
 AnalyticsExecutor.execute(plan, df)
   ──► final_table / final_chart / final_metrics  + row_ids per step
   ──► analyticsAST (plans, executions, rankings, aggregations, trends)
   ──► evidenceAST (rowIds, computation, value, confidence)
```

---

## 7. S5/S6 — Fill slots & assemble

Each component carries an **`outputContract`** (from ②) telling the binder exactly
what to produce:

| Component type | outputContract → produces |
|----------------|---------------------------|
| `data_table` / `cross_tabulation_matrix` | rows matching `columnGroups`, en-IN number format, dims left / measures right |
| `grouped_bar_chart` / `line_chart` / `pie_chart` | `series` per dimension member, palette from registry, unit label |
| `narrative_paragraph` | ≤ `maxWords`, `mustMention[entityIds]` present, tone `mospi_official` — **BI/Gemini writes at render** (no stored prose) |
| `metric_card` | `{value, unit}` formatted |

Assembly uses `ast_core/builder.py` `MultiASTBuilder` (auto IDs + back-refs) to
clone ① and inject filled slots + provenance, then the `ast_core` renderer
produces the PDF. **Hybrid preview**: coordinates preserved for tables/figures,
flow layout for prose.

**Validation gates (S6):** (1) all required entities bound, (2) every executable
question produced output, (3) every number has an `evidenceRef`. Failures →
coverage report, not silent drop.

---

## 8. Locked decisions (this session)

### Gold-standard / template design
- **3-file model** — ① value-free skeleton, ② value-free brain, ③ generated each run (values + provenance ONLY in ③).
- Keep structural labels (titles/headers/footnotes/units/chrome); **drop** all data prose + numbers.
- **Periods parameterized** as roles `{current, prior, delta}` resolved from the new dataset.
- Structure → AST (①); recipe + links → blueprint (②); linked by IDs.
- **Explicit `outputContract`** per component.
- Narrative slots **LITE** `{tone, maxWords, mustMention[entityIds]}` — no stored MoSPI sentences.
- Grouped headers = **columnGroups + breakdowns**; palette = **registry in template**.
- `analyticsSpec` = **explicit spec + BI override** (option C).
- Preview = **hybrid** (coords for tables/figs, flow for prose).

### Binder
- **Bind once globally** (entity→column), apply per-question by role.
- **Confirm every binding** via **dashboard UI** (proposed col + alternatives + samples + confidence).
- **Cache** confirmed bindings keyed by **(templateId + dataset column signature)**; re-run asks only deltas.
- **Missing required entity → BLOCK** that question + coverage report (strict, no silent drop).
- Resolve filter **values** (Rural/Urban vs codes) + **period roles** (current/prior → dataset max/prev); both confirmable.
- **One report = one dataset** first (multi-dataset later).

### Build order & deliverables
- **EXTRACTION FIRST**, then binder (fix/complete/enrich extraction to emit ①②; see R1).
- `analyticsSpec`: **auto-infer at template-build + human review**.
- Output targets: **③ JSON + rendered PDF + dashboard live preview + coverage/binding report**.
- Tests: **unit + golden e2e** (energy CSV + PLFS/MoSPI `test_data/` CSVs).
- Code layout: **new `report_builder/binding/` package** + extend `ast_core/schema.py` with new subtrees.

---

## 9. Reuse map (existing code the binder builds on)

| Stage | Reuse | Location |
|-------|-------|----------|
| S0 profile | dtype/role/cardinality heuristics; archetype detect | `_detect_document_type` (extraction) · new code |
| S1 resolve | `ColumnResolver` (5-stage cascade) + `TemplateBinder` | `template_engine/binder/column_resolver.py`, `template_binder.py` |
| S1 synonyms | `ColumnSynonymKG` | `deep_bi/column_synonym_kg.py` |
| S1 embeddings | BGE-M3 local / Gemini `gemini-embedding-001` | provider abstraction |
| S4 plan/exec | `AnalyticsPlanner` → `AnalyticsExecutor` (row_ids, final_table/chart/metrics) | `deep_bi/analytics_planner.py`, `analytics_executor.py` |
| S4 intent (fallback) | `IntentParser` | `deep_bi/intent_parser.py` |
| S4 evidence | `EvidenceLedger` | `deep_bi/evidence_ledger.py` |
| S5 prose | `prose_from_bi` / Gemini narrate | `ast_core/prose_from_bi.py` |
| S6 assemble | `MultiASTBuilder` | `ast_core/builder.py` |
| S6 render | renderer (ReportLab/coords) | `ast_core/renderer.py` |
| templatize | `clear_prefilled_slots` | `ast_core/domain_remap.py` |

> Note: two report paths exist today — `report_builder/orchestrator.py`
> (blueprint-aware, BI-blind) and `ast_core/coord_deep_bi_orchestrator.py`
> (BI-aware, economics-hardcoded). The new binder **generalizes** the BI wiring of
> the coord path to be **blueprint-driven and domain-agnostic**.

---

## 10. Proposed package layout (to be created in plan/implementation mode)

```
report_builder/binding/
├── __init__.py
├── profiler.py        S0  DataFrame → datasetAST
├── resolver.py        S1  entity ⇄ column cascade (wraps ColumnResolver + embeddings)
├── review.py          S2  proposed→confirmed state machine + binding cache
├── question_binder.py S3  requiredEntities/roles → resolvedRoles; filter+period resolution
├── executor.py        S4  analyticsSpec → AnalyticsPlan → AnalyticsExecutor → analyticsAST+evidenceAST
├── filler.py          S5  outputContract-driven slot fill (table/chart/narrative/metric)
├── assembler.py       S6  MultiASTBuilder clone(①)+slots+provenance → ③ ; validation gates
└── report.py          coverage/binding report (JSON + human-readable)

ast_core/schema.py     +DatasetAST +BindingAST +EvidenceAST ; augment AnalyticsAST/Table/Chart
```

---

## 11. Current vs Needed (binder)

```
ENTITY↔COLUMN
  current:  TemplateBinder auto-accepts ≥0.90, rest "pending"; no confirm UI; no cache
  needed:   EVERY binding proposed→confirmed via dashboard; alternatives+samples; cache by signature

BI EXECUTION
  current:  coord path hardcodes MoSPI economics queries (index_al/inflation_al); ignores blueprint questions
  needed:   per-question analyticsSpec → plan → execute; domain-agnostic; BI override logged

PROVENANCE
  current:  row_ids exist in AnalyticsExecution but are NOT persisted into the AST
  needed:   evidenceAST with rowIds for every number; analyticsAST arrays filled; component refs set

OUTPUT
  current:  orchestrator returns a ReportResult dict (not an AST); coord path renders a PDF
  needed:   ③ report.output.ast.json (gold-shaped) + PDF + dashboard preview + coverage report

REVIEW / SAFETY
  current:  silent fallbacks; partial binding tolerated
  needed:   strict gates — block unresolved questions, surface coverage, no silent drop
```

---

## 12. Open questions for plan mode (deep-think next)

1. Exact `analyticsSpec` schema + the questionType→operation inference table (and how BI-override is detected/logged).
2. `datasetAST` role-inference rules (when is a numeric column a measure vs an ID/code?).
3. Filter-value resolution when the dataset uses codes (state_code 29) vs labels (Karnataka) — mapping source.
4. Period-role resolution policy across archetypes (calendar vs fiscal vs survey round).
5. Binding-cache signature definition (column names only? + dtypes? + samples hash?).
6. Confirm-UI payload contract between Python binder and the Next.js dashboard.
7. Number-format/locale rules (en-IN grouping `1,48,718`; unit placement; % vs ratio).
8. Validation-gate severities (hard-fail vs warn) and the coverage-report schema.
9. Golden-test fixtures: which CSVs + expected ③ snapshots.
10. How ③ feeds the existing renderer vs needing renderer changes for new subtrees.

---

*End of R2. See [`README_TEMPLATE_EXTRACTION.md`](README_TEMPLATE_EXTRACTION.md) for the extraction half that emits ① + ②.*
