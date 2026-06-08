# Template Extraction — Architecture & Enrichment Guide (R1)

> **Status:** Reference document (agent-mode knowledge dump). Finetuning of the
> extraction passes is **ongoing** — treat the JSON under `outputs/` as *noisy*,
> not as the contract. This README captures **what exists today**, **what the
> enhanced "gold" template must contain**, and **how each pass should be
> completed/enriched** to emit it.
>
> Companion doc: [`README_BINDER_ARCHITECTURE.md`](README_BINDER_ARCHITECTURE.md) (R2) — the
> runtime that consumes these templates + a dataset and produces the filled report.

---

## 0. TL;DR

Template extraction turns a **legacy MoSPI/NSSO statistical PDF** into a
**reusable, value-free template** that can later regenerate the same report on a
**new dataset**. It is the first half of the system:

```
   legacy PDF ──► [ TEMPLATE EXTRACTION ]  ──►  template.ast.json     (render skeleton, value-free)
                  (this document, R1)            template.blueprint.json (analytic brain, value-free)
                                                          │
   new dataset ──────────────────────────────────────────┼──► [ BINDER ] ──► report.output.ast.json + PDF
                                                          (R2)                  (values + provenance live ONLY here)
```

**The golden rule:** a template stores **structure, labels, entities, and the
recipe** — never **values, prose, or meaning** derived from the original data.

---

## 1. The three-file model (why extraction outputs two files)

The system separates a **template** (authored once per report type) from an
**instance** (generated each run). Three artifacts:

| # | File | Authored / Generated | Contains | NEVER contains |
|---|------|----------------------|----------|----------------|
| ① | `template.ast.json` | **Extraction output** (authored once) | Render skeleton: layout, geometry, style, semantic hierarchy, **empty slots** (table columns w/ no rows, content slots w/ `biQuery`/`templateQuestion`, chart specs w/ no series, metric slots) | data rows, prose, computed values |
| ② | `template.blueprint.json` | **Extraction output** (authored once) | Analytic brain: typed entities, glossary, topics→questions→`analyticsSpec`, answer structures w/ refs into ①, palette, renderProfile | data values, canned MoSPI sentences |
| ③ | `report.output.ast.json` | **Binder output** (per run) | ① cloned + slots filled by BI + `datasetAST` + `bindingAST` + `evidenceAST` | — (this is where values are *supposed* to live) |

> Today the pipeline emits a single combined `enterprise_ast.json` (which holds
> `tableAST`, `semanticAST`, etc.) **plus** a `blueprint.json`. Conceptually
> `enterprise_ast.json` ≈ ① and `blueprint.json` ≈ ②. The enrichment work is to
> make ① genuinely value-free + render-complete, and ② genuinely
> analytic-complete.

---

## 2. Where extraction sits in the codebase

```
report_builder/
├── extraction_pipeline.py   ◄── THE pipeline (Pass 0→5). ~4000 lines. START HERE.
├── chunking.py              late-chunking ToC + per-page context scripts (Pass 2.5 helper)
├── gemini_enrichment.py     optional Pass 5 (semantic hierarchy, entities, facts, questions)
├── blueprint.py             ColPali+SGLang template compile (alt/legacy path)
├── entity_engine.py         entity + slot extraction from an assembled AST
├── knowledge_graph.py       RDF/Neo4j export (orthogonal to template extraction)
├── ast_schema.py            Enterprise AST Pydantic model (14 subtrees)
└── mospi_question_archetypes.json   domain → question archetypes (fallback Q source)

ast_core/
└── schema.py                TemplateBlueprintAST · TopicNode · QuestionNode ·
                             AnswerStructure · AnswerComponent · TemplateEntity
services/layoutlm/main.py    LayoutLMv3 microservice (Pass 1, CPU, :8001)
docker/Dockerfile.sglang     Qwen2.5-VL container (Pass 2 & 3, GPU, :8002)
```

Entry point: `run_extraction_pipeline(pdf_path, doc_title, source_hash, …)` at
[`extraction_pipeline.py`](extraction_pipeline.py) line ~3596.

---

## 3. The 7-pass pipeline — what each pass does TODAY

```
 ┌─ Pass 0 ──────────── PDF Rasterization ────────────────────────────────────┐
 │ pass0_rasterize(pdf)                                                         │
 │ pdf2image 150dpi → page PNGs   +   pdfplumber → raw_text, words(+size),      │
 │ tables (extract_tables), headings.   OUT: (page_images[], page_texts[])      │
 └──────────────────────────────────────────────────────────────────────────────┘
                                    │
 ┌─ Pass 1 ──────────── Layout Detection (LayoutLMv3, CPU :8001) ──────────────┐
 │ pass1_layout_detection(pdf) → per-page regions [{type,bbox,text}]            │
 │ type ∈ title|text|heading|table|figure|caption|list.  Graceful: falls back  │
 │ to _fallback_layout_from_text() if service down.                            │
 └──────────────────────────────────────────────────────────────────────────────┘
                                    │
 ┌─ Pass 2 ──────────── Entity + Structure (Qwen2.5-VL, GPU :8002) ────────────┐
 │ pass2_entity_structure_extraction(images, layout, texts)                    │
 │ Per page, 50–150 tokens: ENTITIES + structure_type + chart_types + table-   │
 │ title/section-heading.  NOT values, NOT prose.  Provider-pluggable.          │
 └──────────────────────────────────────────────────────────────────────────────┘
                                    │
 ┌─ Pass 2.5 ─────────── Document Knowledge Graph (PROGRAMMATIC, no LLM) ───────┐
 │ pass2_5_document_knowledge_graph(entity_pages, layout, texts, toc)          │
 │  1. Entity collection — 4 prioritized sources:                              │
 │       P0 pdfplumber table headers (gold)  P1 LayoutLM headings/captions     │
 │       P1b VLM table_title/section_heading  P2 VLM entities (filtered)        │
 │  2. Table structure: _merge_multirow_headers() → columns/dims/measures/      │
 │     breakdowns/layout                                                        │
 │  3. Chapter hierarchy from hybrid ToC (_extract_toc_hybrid)                  │
 │  4. Entity co-occurrence + prefix relationships                             │
 │  5. per_page_context_scripts[] (late chunking — position + entities)        │
 │  6. section_patterns[] (executive_summary, trend_analysis, …)               │
 │  7. numbered sections + pre-generated fallback questions                    │
 │  OUT: document_map{chapters, all_entities, table_structures,                │
 │       per_page_context_scripts, section_patterns, …}                        │
 └──────────────────────────────────────────────────────────────────────────────┘
                                    │
 ┌─ Pass 2.6 ─────────── Entity Type Classification ───────────────────────────┐
 │ pass2_6_entity_classification(document_map)                                 │
 │ keyword sets (_MOSPI_MEASURE/DIMENSION/METADATA_KEYWORDS) + table-structure  │
 │ lookup + source heuristic → entityType_hint ∈ dimension|measure|filter|      │
 │ metadata.  Optional Gemini batch for ambiguous ones.                         │
 └──────────────────────────────────────────────────────────────────────────────┘
                                    │
 ┌─ Pass 3 ─────────── Two-Loop AST Building (Qwen-VL, GPU) ────────────────────┐
 │ pass3_two_loop_ast_building(document_map, page_texts, …)                    │
 │  LOOP 1 (per chapter, 1 call): → raw questions                              │
 │     {questionId sp01_q01, intent, questionType, page, sourceHeading}        │
 │     dedup by normalized intent.  questionType ∈ comparison|trend|ranking|    │
 │     distribution|describe                                                    │
 │  LOOP 2 (per question): → {requiredEntities[{entityRef,role}],              │
 │     answerStructure{layoutType, components[{type,renderOrder}]},             │
 │     inferenceConfidence}                                                     │
 │  Topic assignment: narrowest chapter whose pageRange ∋ q.page               │
 │  Fallbacks: provider down → _programmatic_question_fallback();              │
 │             L2 fails → _default_question_binding()                          │
 └──────────────────────────────────────────────────────────────────────────────┘
                                    │
 ┌─ Pass 4 ─────────── AST Assembly + Embedded Blueprint (PROGRAMMATIC) ────────┐
 │ pass4_assemble_ast(...)  → Enterprise AST (14 subtrees) with:               │
 │   layoutAST/geometryAST (Pass 1) · contentAST (pdfplumber+LayoutLM) ·        │
 │   tableAST STRUCTURE-ONLY (Pass 2.5, no values) · semanticAST (chapters) ·   │
 │   entityGraph (all_entities) · blueprint{topics, entities, tableStructures,  │
 │   documentMap}                                                              │
 └──────────────────────────────────────────────────────────────────────────────┘
                                    │
 ┌─ Pass 5 ─────────── Optional Gemini Enhancement (online) ───────────────────┐
 │ gemini_enrichment.py + _gemini_* : semantic hierarchy (if <3 chapters),     │
 │ entities (if <5), facts, gap-fill questions, semantic fallback.  Best-effort.│
 └──────────────────────────────────────────────────────────────────────────────┘
```

### Data structures produced today

```jsonc
// entity (document_map.all_entities[i])  →  blueprint.entities[i]
{ "entityId":"ent_001", "name":"LFPR", "entityType":"measure",
  "sourceType":"table_header", "confidence":0.8, "aliases":[], "pageIndex":1,
  "sourceContext":"", "scope":"global", "crossRefs":[] }

// table structure (document_map.table_structures[i]  →  blueprint.tableStructures[i])
{ "tableId":"tbl_1_1", "page":0, "columns":[...], "dimensions":[...],
  "measures":[], "breakdowns":[], "layout":"multi_dimension", "row_count":60 }

// question (Pass 3 → blueprint.topics[t].questions[q])
{ "questionId":"sp01_q01", "intent":"…?", "questionType":"comparison",
  "inferenceMethod":"vlm", "inferenceConfidence":0.8,
  "requiredEntities":[{"entityId":"ent_001","role":"groupBy","confidence":0.7,"bindingMethod":"vlm"}],
  "answerStructure":{"layoutType":"multi-panel","components":[{"componentId":"q1_c1","renderOrder":1,"type":"grouped_bar_chart","constraints":{},"refs":{}}]},
  "pageIndex":0, "sourceHeading":"…", "priority":"high" }
```

---

## 4. Current defects (grounded in the code + real `outputs/`)

These are the concrete reasons the current `outputs/*/blueprint.json` are not yet
usable as a gold template. Each is traced to its source.

| # | Defect | Evidence | Root cause (file/function) |
|---|--------|----------|----------------------------|
| D1 | **Noisy entities** — `"Press Re"`, `":49 AM"`, `"e \| Press Inform"`, URLs, sentence fragments become `entityType:"dimension"` | `outputs/*/blueprint.json` entities | PIB web-export tables leak page chrome through pdfplumber; `_is_website_artifact_table()` exists but isn't applied to **all** entity sources before they reach `all_entities`. `_is_valid_entity_name()` passes multi-word fragments < 80 chars. |
| D2 | **Garbled multi-row headers** — column names split mid-word (`"Press Re"`,`"lease Pag"`) and `measures:[]` always empty | `blueprint.tableStructures[*]` | `_merge_multirow_headers()` qualifier-heuristic (`_HEADER_QUALIFIERS` / len≤12) does not fire on PIB layout; the real header band is fragmented by pdfplumber's column model, so dim/measure split never happens → `measures` stays `[]`. |
| D3 | **Stub questions** — `"intent":"Specific analytical question referencing real entities?"`, all `questionId:"q1"`, duplicated | `outputs/*/blueprint.json` | Comes from fallback/echo: the Pass 3 L1 prompt literally embeds an example `{"intent":"Specific question about this section topic?"}`; when VLM echoes or fails, `_default_question_binding()` / `_programmatic_question_fallback()` stub strings surface. |
| D4 | **`questionType` left as enum string** — `"comparison\|trend\|ranking\|distribution\|describe"` | same | VLM echoed the instruction literal instead of choosing one. No post-validation coerces it to a single enum member. |
| D5 | **Empty `topics[].questions` but huge `entities[]`** | `sanjay_thirtu_ntk` | When topic assignment finds no chapter span containing `q.page`, questions are dropped from topics (see `_unassigned` warning) even though entities persist. |
| D6 | **`refs:{}` always empty** | every component | **By design** at extraction time — refs are filled by the binder (R2). Not a bug, but must be documented so downstream knows. |
| D7 | **No units / formats / valueDomain** | entities | Pass 2.6 only assigns a coarse type; no unit (`%`, `₹`, `Billion Tonnes`), no enum members (Rural/Urban), no number format. |
| D8 | **No `analyticsSpec`** | questions | The executable BI contract does not exist yet — the binder would have to *guess* the plan from fuzzy `intent` text. |

---

## 5. What the ENHANCED gold template must contain (the target)

This is the contract the enriched extraction must emit. Items marked **NEW** do
not exist today.

### ② `template.blueprint.json` (analytic brain)

```jsonc
{
  "templateMeta": {                                   // NEW
    "templateId":"plfs_annual", "name":"PLFS Annual Report",
    "domain":"PLFS", "reportType":"annual",
    "locale":"en-IN", "currency":"INR", "version":"1.0", "sourceHash":"…" },

  "glossary": [                                       // NEW
    {"term":"LFPR","definition":"Labour Force Participation Rate","unit":"%","formula":"LF/Pop×100"},
    {"term":"WPR","definition":"Worker Population Ratio","unit":"%"} ],

  "palette": {                                        // NEW (registry)
    "reserves":{"Proved":"#1f4e79","Indicated":"#5b9bd5","Inferred":"#bdd7ee"},
    "gender":{"Male":"#1f77b4","Female":"#e377c2"} },

  "entities": [                                       // TemplateEntity ++
    { "entityId":"ent_lfpr", "name":"LFPR", "canonicalName":"labour_force_participation_rate",
      "entityType":"measure",                         // dimension|measure|filter|time|metadata
      "aliases":["Labour Force Participation Rate"],  // NEW richer
      "unit":"%", "dtypeHint":"float",                // NEW
      "valueDomain":[], "defaultFormat":"0.0%",       // NEW
      "glossaryRef":"LFPR", "confidence":0.9 },
    { "entityId":"ent_sector", "name":"Sector", "entityType":"dimension",
      "valueDomain":["Rural","Urban"] },              // NEW — BI filter members
    { "entityId":"ent_period", "name":"Period", "entityType":"time" } ],

  "topics": [ { "topicId":"t_01", "title":"Worker Population Ratio", "questions":[
    { "questionId":"q_03",
      "intent":"How does WPR vary across sector for persons aged 15+?",   // REAL NL
      "questionType":"comparison",                    // SINGLE enum
      "requiredEntities":[
        {"entityId":"ent_wpr","role":"measure"},
        {"entityId":"ent_sector","role":"dimension"}],// roles: measure|dimension|filter|time
      "analyticsSpec": {                              // NEW — executable BI contract
        "operation":"aggregate",                      // rank|aggregate|trend|compare|share|describe
        "metric":"ent_wpr", "groupBy":["ent_sector"], "agg":"mean",
        "filters":[{"entityId":"ent_age","value":"15+"}],
        "timeWindow":"current", "topK":null,
        "allowBIOverride":true },
      "answerStructure": { "layoutType":"split", "components":[
        { "componentId":"q3_c1", "type":"narrative_paragraph", "renderOrder":1,
          "constraints":{"max_words":110},
          "layout":{"region":null,"grid":{"row":0,"col":0,"span":2}},  // NEW preview geometry
          "style":{"styleRef":"s_body"},                               // NEW
          "narrativeTemplate":{"tone":"mospi_official","maxWords":110,  // NEW (LITE, no prose)
                               "mustMention":["ent_wpr","ent_sector"]},
          "outputContract":{"kind":"prose","maxWords":110,"mustMention":["ent_wpr","ent_sector"]}, // NEW
          "refs":{} },                                                  // filled by binder
        { "componentId":"q3_c2", "type":"grouped_bar_chart", "renderOrder":2,
          "constraints":{"chart_type":"bar","paletteRef":"gender","top_k":10,"unit":"%"},
          "outputContract":{"kind":"chart","series":"per_dimension_member"},
          "refs":{} } ] } } ] } ],

  "tableTemplates": [                                 // NEW
    { "tableId":"table_007", "title":"Statewise {measure} ({asOfDate})",
      "columnGroups":[{"label":"Proved","periods":["current","prior"]}],  // multi-row header
      "columns":[
        {"name":"States/UTs","role":"dimension","align":"left"},
        {"name":"Proved·current","role":"measure","unit":"BT","format":"#,##,##0","align":"right"}],
      "dimensions":["States/UTs"], "measures":["Proved","Indicated","Inferred","Total"],
      "breakdowns":[{"measure":"*","by":"period","values":["current","prior"]}],
      "footnotes":["Total may not tally due to rounding"], "styleRef":"s_tbl" } ],

  "figureTemplates": [                                // NEW
    { "figureId":"fig_001","caption":"Fig 1.1 …","chartType":"pie",
      "paletteRef":"reserves","sourceTableRef":"table_007","chartRef":"chart_004" } ],

  "documentMap": { "chapters":[…], "sectionPatterns":[…], "toc":[…] },
  "renderProfile": {                                  // NEW
    "pageSize":"A4","margins":{}, "header":"…","footer":"…", "styles":{}, "paletteRef":"reserves" }
}
```

### ① `template.ast.json` (render skeleton, value-free)

Same 14 subtrees as today **but**: `tableAST.tables[*].rows = []` (columns +
columnGroups kept), `contentAST.paragraphs[*].content = ""` (with `biQuery` +
`templateQuestion` kept), `chartAST.charts[*].series = []` (type/slices/palette
kept), metric slots carry `{name,unit}` but no `value`. Static labels (section
titles, table titles, column headers, footnotes, units, header/footer) are
**kept**; everything data-derived is **dropped**.

---

## 6. Current vs Needed (at a glance)

```
ENTITIES
  current:  name + coarse entityType + confidence; noisy (chrome, fragments, URLs)
  needed:   CLEAN + canonicalName + aliases[] + unit + dtypeHint + valueDomain[] + glossaryRef

QUESTIONS
  current:  stub intent, dup q1, questionType = enum-string, refs:{}
  needed:   real NL intent, unique IDs, SINGLE questionType, requiredEntities roles
            (measure|dimension|filter|time), + analyticsSpec, + narrativeTemplate(lite),
            + per-component outputContract/layout/style

TABLES
  current:  garbled columns (split mid-word), measures:[] always, no formats
  needed:   clean columnGroups (multi-row header) + per-col {role,unit,format,align}
            + dimensions/measures/breakdowns

CHARTS / FIGURES
  current:  chart_types hint only; no palette; no figure↔chart link
  needed:   figureTemplates{chartType,palette,sourceTableRef,chartRef}; chart slice spec

CROSS-CUTTING
  current:  no glossary, no palette registry, no renderProfile, no locale, no period roles
  needed:   glossary + palette + renderProfile + locale en-IN + period params {current,prior,delta}
            + value-free slots (clear_prefilled_slots) preserving biQuery/templateQuestion
```

---

## 7. How to complete/enrich each pass (options + tradeoffs)

> Implementation order proposed: **clean first (D1/D2), then enrich (D7/D8), then
> validate (D3/D4/D5)**. Detailed task breakdown belongs in plan mode; this is the
> design menu.

### 7.1 Fix noisy entities (D1) — *pre-filter every entity source*

```
Option A  Hard blocklist + artifact regex BEFORE all_entities
          (apply _WEBSITE_NAV_RE + _is_website_artifact_table to P0/P1/P2 sources)
   + simple, deterministic, fast      − misses novel chrome; needs maintenance
Option B  Score entities by "concept-likeness" (in glossary? in table dim/measure?
          matches measure/dimension keyword? appears on ≥2 pages?) and drop low score
   + generalizes, ranks               − threshold tuning; may drop rare real entities
Option C  Gemini/VLM entity-validation batch (classify real vs chrome)
   + highest precision                − online cost; network (corp SSL handled via truststore)
RECOMMENDED: A (gate) → B (rank) → C (only for the ambiguous middle).
```

### 7.2 Fix multi-row headers + empty measures (D2)

```
Option A  Improve _merge_multirow_headers qualifier detection: detect the header
          BAND (top N rows where cells are non-numeric) and forward-fill spans,
          then dim/measure split = first non-numeric col → dimension, repeated
          prefix+qualifier → measure×breakdown.
   + reuses gold "prefix+qualifier" pattern    − pdfplumber fragmentation still upstream
Option B  Re-extract tables with pdfplumber table_settings tuned per layout
          (lines vs text strategy) + cell de-fragmentation (merge adjacent
          same-row cells whose x-gap < threshold).
   + fixes split-mid-word at the source        − per-document tuning
Option C  Use LayoutLM/VLM table bbox to crop + re-OCR header band only.
   + robust to bad text layer                  − GPU/online, slower
RECOMMENDED: B (de-fragment at source) + A (smarter merge) ; C as fallback.
Also: ALWAYS populate measures by the repeated-prefix rule; never leave [].
```

### 7.3 Real questions, not stubs (D3/D4/D5)

```
- Remove the literal example from the L1 prompt OR make the example domain-true,
  and ADD a post-parse validator that REJECTS any intent containing
  "Specific analytical question" / "this section topic" or a pipe-delimited
  questionType, forcing a regenerate or a programmatic archetype question.
- Coerce questionType to a single enum member (map echo → first listed / infer
  from verbs: "vary/compare"→comparison, "over years"→trend, "highest"→ranking).
- Fix topic assignment so unassigned questions attach to the nearest chapter by
  page distance instead of being dropped (D5).
- Make questionId globally unique at WRITE time (already sp{nn}_q{nn} in L1 — make
  the fallback paths honor it too).
RECOMMENDED: validator + archetype fallback from mospi_question_archetypes.json.
```

### 7.4 Add the enrichment fields (D7/D8) — *new programmatic stage "Pass 2.7" + author-time*

```
unit / dtypeHint / valueDomain:
   - unit: glossary lookup → regex on source context (%, ₹, MW, Billion Tonnes)
   - valueDomain: harvest enum members from table breakdowns + known dimension
     vocab (Rural/Urban, Male/Female, age bands)
analyticsSpec  (DECISION: auto-infer at template-build, THEN human review):
   - operation from questionType (comparison→aggregate/compare, ranking→rank,
     trend→trend, distribution/share→share, describe→describe)
   - metric = requiredEntities role=measure ; groupBy = role=dimension ;
     filters = role=filter (+ valueDomain) ; timeWindow from period roles
glossary / palette / renderProfile:
   - glossary seeded from a MoSPI domain pack + harvested abbreviations "(LFPR)"
   - palette + renderProfile authored per reportType (PLFS/NSSO/HCES/energy)
```

### 7.5 Make ① genuinely value-free

```
Reuse ast_core/domain_remap.clear_prefilled_slots() to strip rows/prose/series
while preserving columns, biQuery, templateQuestion, chart specs. Formalize this
as the final "templatize" step that splits the assembled AST into ① (skeleton)
and ② (brain).
```

---

## 8. Enrichment flow (target)

```
   Pass 0–2.6 (as today, but with D1/D2 cleaning) 
        │
        ▼
   Pass 3 (questions) + post-validator (D3/D4/D5)  ──► real questions
        │
        ▼
   Pass 2.7 (NEW, programmatic) ENRICH:
        entities  +unit +dtypeHint +valueDomain +canonicalName +glossaryRef
        questions +analyticsSpec(auto-infer) +narrativeTemplate(lite)
        components +outputContract +layout +style
        tables    +columnGroups +per-col format +measures(fixed)
        + glossary + palette + renderProfile + locale + period roles
        │
        ▼
   Pass 4 assemble → ENTERPRISE AST
        │
        ▼
   TEMPLATIZE (clear_prefilled_slots): split → ① template.ast.json + ② template.blueprint.json
        │
        ▼
   (optional) Pass 5 Gemini review of analyticsSpec + glossary + valueDomain
        │
        ▼
   ① + ②  → consumed by BINDER (R2)
```

---

## 9. Function/► reference map (where to work)

| Concern | Function (file: `extraction_pipeline.py`) | Line |
|---------|-------------------------------------------|------|
| Entity validity | `_is_valid_entity_name` | ~390 |
| Multi-row headers | `_merge_multirow_headers` | ~437 |
| Website artifact tables | `_is_website_artifact_table` | ~585 |
| Doc KG / entity collection | `pass2_5_document_knowledge_graph` | ~1595 |
| Entity classification | `pass2_6_entity_classification` | ~832 |
| Entity ref resolution | `_resolve_entity_ref` | ~983 |
| Questions (two-loop) | `pass3_two_loop_ast_building` | ~2347 |
| Default/stub binding | `_default_question_binding` | ~2778 |
| Programmatic Q fallback | `_programmatic_question_fallback` | ~2945 |
| Archetypes | `_load_archetypes` / `mospi_question_archetypes.json` | ~2842 |
| AST assembly + blueprint | `pass4_assemble_ast` | ~3184 |
| Pipeline entry | `run_extraction_pipeline` | ~3596 |
| Gemini enhancement | `_gemini_*`, `gemini_enrichment.py` | ~3876 |
| Value-free templatize | `ast_core/domain_remap.clear_prefilled_slots` | — |
| Schemas | `ast_core/schema.py` (TemplateEntity, QuestionNode, …) | — |

---

## 10. Glossary

| Term | Meaning |
|------|---------|
| **Template** | Value-free, reusable structure+recipe (① + ②) |
| **Instance** | A generated report with real values (③) |
| **Slot** | An empty placeholder in ① filled at bind time (table rows, content, chart series, metric) |
| **Entity** | A data concept (dimension/measure/filter/time/metadata) the report depends on |
| **analyticsSpec** | The executable BI contract per question (operation+metric+groupBy+filters) |
| **valueDomain** | Enum members of a dimension (Rural/Urban) used to resolve filters |
| **columnGroups** | Multi-row header description (e.g. Proved × {current,prior}) |
| **period roles** | `current` / `prior` / `delta` — abstract periods resolved from the new dataset |
| **outputContract** | Per-component spec of WHAT the binder must produce |

---

*End of R1. See [`README_BINDER_ARCHITECTURE.md`](README_BINDER_ARCHITECTURE.md) for the runtime that consumes ① + ②.*
