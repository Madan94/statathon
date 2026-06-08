# Migration Plan — Current Architecture → Gold-Standard 3-File Design

**Goal:** make the pipeline emit the three [gold-standard](gold_standard/README.md) files — value-free
① `template.ast.json`, value-free ② `template.blueprint.json`, and a fully-traceable ③
`report.output.ast.json` — while squeezing maximum quality out of the **local Qwen** model and
keeping model choice a **one-line `.env` switch**.

> Scope of THIS plan = **extraction half** (PDF → ①②). The binder half (①②+dataset → ③) is
> specced in [README_BINDER_ARCHITECTURE.md](README_BINDER_ARCHITECTURE.md); migration steps for it
> are listed in §7 but executed after extraction lands.

---

## 1. Environment reality (measured, not assumed)

| Layer | What runs | Where | Hard limits |
|-------|-----------|-------|-------------|
| Layout | LayoutLMv3-large | `docker/Dockerfile.layoutlm` :8001 (CPU) | ~4 GB RAM cap |
| Vision+Text | **Qwen2.5-VL-3B-Instruct-AWQ** on **vLLM** | `docker/Dockerfile.sglang` :8002 (GPU) | see below |
| Router | `report_builder/llm_router.py` | in-process | — |
| Orchestrator | `report_builder/extraction_pipeline.py` | in-process | — |

**Qwen serving budget (RTX 4050, 6 GB) — from `sglang-entrypoint.sh`:**

```
--max-model-len 2048          ← TOTAL prompt+output tokens. THE binding constraint.
--mm-processor-kwargs max_pixels=360448   ← ~600×600 px/image (≈460 vision tokens)
--max-num-seqs 1              ← no batching; calls are serialized
--enforce-eager               ← no CUDA graphs (saves VRAM, slower)
--gpu-memory-utilization 0.80 ← 4.8 GB budget; weights 3.32 GB + encoder ~0.1 GB + KV ~0.1 GB
```

**Consequences that shape every design decision below:**
1. **2048 tokens is the wall.** A page image eats ~460; that leaves ~1500 for prompt+JSON out.
   → Prompts must be short; outputs must be small, chunked, schema-bounded.
2. **One sequence at a time.** Throughput = latency-bound. → Minimise round-trips; never loop
   the VLM per-entity when one structured call can return all entities for a region.
3. **Vision is low-res.** ~600×600 → tiny table text is lost. → Tile large tables; lean on
   pdfplumber for text, use the VLM for *structure/semantics*, not OCR of fine print.
4. **3B is weak at long reasoning.** → Push reasoning to validators/heuristics in Python; use the
   VLM for perception + short classification, escalate hard cases to a bigger model via env.

Scale path (no code change): `VLLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct-AWQ` on an 8 GB+ GPU.

---

## 2. Model selection — make "use another model" a one-line switch

### 2.1 What already exists (good — keep it)

`llm_router.py` is the single choke point. Every call is `llm_text_call(task=…)` /
`llm_vision_call(task=…)`. Provider resolves by priority:

```
PROVIDER_<TASK>   →   VLM_PROVIDER (vision) / REASONING_PROVIDER (text)   →   "qwen"
```

Implemented providers today: **qwen** (vLLM OpenAI API), **gemini** (google-genai), **groq**.
Per-task overrides already wired: `PROVIDER_ENTITY_EXTRACTION`, `PROVIDER_QUESTION_GENERATION`,
`PROVIDER_ENTITY_BINDING`, `PROVIDER_TOC_EXTRACTION`, `PROVIDER_GAP_FILL`, `PROVIDER_FACT_EXTRACTION`,
`PROVIDER_SEMANTIC_FALLBACK`. Token/temp per task already env-driven (`_T` in `extraction_pipeline.py`).

### 2.2 The one gap → add a generic `openai` provider

`.env.example` already lists `OPENAI_API_KEY` and `openai` as a per-role option, but
`llm_router.py` has **no `openai` backend**. Adding it unlocks, through a single provider, **any
OpenAI-compatible endpoint**: OpenAI, OpenRouter (100+ models), Ollama, LM Studio, Together,
DeepSeek, Mistral, or a second vLLM. This is the highest-leverage, lowest-risk change.

```python
# report_builder/llm_router.py  — new backend
def _call_openai(prompt, image_bytes, max_tokens, temperature):
    base = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    key  = os.getenv("OPENAI_API_KEY") or ""
    model = (os.getenv("OPENAI_VISION_MODEL") if image_bytes else os.getenv("OPENAI_MODEL")) or "gpt-4o-mini"
    if not key and "api.openai.com" in base:        # local servers (ollama) need no key
        return None
    # build OpenAI chat payload (image as data: URL when present) → POST {base}/chat/completions
    ...
```

Wire-up = 3 tiny edits: add `OPENAI_*` to the docstring, add `if provider == "openai": return
_call_openai(...)` in both `llm_text_call`/`llm_vision_call`, add `openai` branch to
`is_provider_available` (key OR localhost base reachable).

### 2.3 Resulting switchboard (examples — all `.env`, zero code)

```
# Everything local Qwen (default, offline):
VLM_PROVIDER=qwen           REASONING_PROVIDER=qwen

# Qwen sees, Gemini reasons (recommended on corp net):
VLM_PROVIDER=qwen           REASONING_PROVIDER=gemini

# Any OpenAI-compatible cloud for reasoning, Qwen for vision:
REASONING_PROVIDER=openai   OPENAI_BASE_URL=https://openrouter.ai/api/v1  OPENAI_MODEL=deepseek/deepseek-chat

# Local Ollama for reasoning (no key, no internet):
REASONING_PROVIDER=openai   OPENAI_BASE_URL=http://localhost:11434/v1     OPENAI_MODEL=qwen2.5:7b

# Escalate ONLY the hard question-gen task to a big model, keep the rest on Qwen:
PROVIDER_QUESTION_GENERATION=openai
```

**Best practice:** keep the *default* fully local (`qwen`) so the pipeline runs offline; treat cloud
models as opt-in escalation for specific tasks via `PROVIDER_*`, never as a hard dependency.

### 2.4 Best model per pipeline part (local-first, RTX 4050 6 GB / 24 GB RAM)

The pipeline has exactly **two model jobs**: **(V) perception** = image+text (pass 2 entities,
pass 3 question-gen); **(R) reasoning** = text-only (binding, ToC, gap-fill, fact, `analyticsSpec`).

**Local candidates that actually fit 6 GB VRAM (or run on 24 GB RAM via Ollama):**

| Model | Modality | 4-bit size | Fits 4050? | Doc/table quality | Reasoning/JSON | Notes |
|-------|----------|-----------|------------|-------------------|----------------|-------|
| **Qwen2.5-VL-3B-AWQ** *(current)* | V+R | ~2.5 GB (GPU) | ✅ vLLM | **Best-in-class for size** on dense tables/OCR | OK (short) | the right default for **V** |
| Qwen2.5-VL-7B-AWQ | V+R | ~4.65 GB | ⚠️ peak >6 GB (Marlin repack) | Excellent | Good | only on 8 GB+ GPU |
| **Gemma 3 4B-it** | V+R | ~3 GB (Ollama `gemma3:4b`) | ✅ (GPU+RAM) | Good general, **weaker on dense gov tables** | **Strong for size** | great single-model for **R**, decent **V** |
| Qwen2.5-7B-Instruct | R only | ~4.7 GB (Ollama `qwen2.5:7b`) | ✅ via RAM | — | **Best local R**, clean JSON | uses your 24 GB RAM headroom |
| Phi-3.5-mini (3.8B) | R only | ~2.5 GB | ✅ | — | Strong reasoning, terse | good lightweight **R** |
| Llama 3.2 3B | R only | ~2 GB | ✅ | — | OK | fast fallback |

**Cloud (opt-in via `PROVIDER_*`, when a page/spec is too hard for 3B):**

| Model | Modality | Use for | Why |
|-------|----------|---------|-----|
| Gemini 2.5 Flash | V+R | hard pages, `analyticsSpec` | works on corp net, cheap, strong vision |
| gpt-4o-mini (`openai`) | V+R | escalation either job | cheapest strong multimodal |
| DeepSeek-chat (`openai`→OpenRouter) | R | reasoning escalation | very strong/cheap text |

**Recommended assignment (default = fully local & offline):**

```
(V) perception   →  Qwen2.5-VL-3B-AWQ   (vLLM :8002)        ← keep; best tables-for-6GB
                    escalate hard pages →  Gemini 2.5 Flash   (PROVIDER_ENTITY_EXTRACTION=gemini)
(R) reasoning    →  Qwen2.5-7B-Instruct (Ollama, uses RAM)   ← upgrade from 3B for binding/specs
   binding/spec  →  or Gemma 3 4B (gemma3:4b) if you want one model for everything
                    escalate →  Gemini 2.5 Flash / DeepSeek (PROVIDER_GAP_FILL=openai …)
```

**Qwen-VL-3B-AWQ vs Gemma 3 4B vs Gemini 2.5 Flash — when to pick which:**

```
                 Qwen2.5-VL-3B-AWQ     Gemma 3 4B           Gemini 2.5 Flash
 vision tables   ████████ best/6GB     █████ ok             ████████ excellent
 reasoning/JSON  █████ ok              ███████ strong       ████████ excellent
 VRAM @ 4050     ████████ 2.5GB fits   ███████ ~3GB fits    — (cloud)
 offline         ✅                    ✅                    ❌ needs net
 cost            free                  free                 ~free tier / cheap
 corp-net SSL    ✅ local              ✅ local              ✅ works
 → pick for      VISION default        local REASONING /    hard-case ESCALATION
                                       single-model setup    (both jobs)
```

**Easy local switching via Ollama (one provider, swap model in `.env`):**

```bash
# one-time
ollama pull qwen2.5:7b      # best local reasoning
ollama pull gemma3:4b       # multimodal, lighter
# .env — switch reasoning to local Ollama, no key, fully offline:
REASONING_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=qwen2.5:7b     # ← change this one line to swap models
# keep vision on the vision-tuned server:
VLM_PROVIDER=qwen           # Qwen2.5-VL-3B-AWQ on vLLM :8002
```

> Note: Ollama serves an OpenAI-compatible API, so it rides the **same `openai` provider** from §2.2
> — no new code per model. Gemma 3 4B (`gemma3:4b`) is multimodal, so you *can* also set
> `VLM_PROVIDER=openai OPENAI_VISION_MODEL=gemma3:4b` for an all-Ollama setup, but Qwen2.5-VL-3B
> stays the recommended **vision** model because it is markedly better on dense Indian-gov tables.

### 2.5 Ready-made `.env` presets (one-toggle switching)

Copy ONE block into `.env`. This is the "easy switch for convenience" — the **recommended default is
HYBRID-CORP**; everything else is a drop-in swap with no code change.

```bash
# ══ PRESET 1 · LOCAL-OFFLINE ══ all Qwen, zero network (air-gapped / corp-SSL safe)
VLM_PROVIDER=qwen
REASONING_PROVIDER=qwen

# ══ PRESET 2 · HYBRID-CORP (RECOMMENDED) ══ Qwen sees, Gemini reasons
VLM_PROVIDER=qwen
REASONING_PROVIDER=gemini
GEMINI_API_KEY=...

# ══ PRESET 3 · LOCAL-OLLAMA ══ Qwen vision + stronger local reasoning, still offline
VLM_PROVIDER=qwen
REASONING_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=qwen2.5:7b          # ← swap to gemma3:4b / phi3.5 / llama3.1:8b in one line

# ══ PRESET 4 · ESCALATE-HARD ══ local default, cloud ONLY for the 2 hardest tasks
VLM_PROVIDER=qwen
REASONING_PROVIDER=qwen
PROVIDER_ENTITY_EXTRACTION=gemini            # hard pages only
PROVIDER_GAP_FILL=openai                      # hard reasoning only
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=deepseek/deepseek-chat
```

Mental model: **global** (`VLM_PROVIDER`/`REASONING_PROVIDER`) sets the baseline; **per-task**
(`PROVIDER_*`) overrides one task; **model name** (`OPENAI_MODEL`, `GEMINI_MODEL`, `SGLANG_MODEL`)
is the last knob. Three layers, all `.env`, no redeploy.

---

## 3. Max-Qwen quality playbook (get gold-grade output from a 3B in 2048 ctx)

| Lever | Why it helps a small VLM | Where it plugs in |
|-------|--------------------------|-------------------|
| **Schema-bounded decoding** (JSON grammar / `guided_json`) | vLLM can constrain output to a JSON schema → no truncated/echoed JSON (kills D3/D4) | per-call `extra_body={"guided_json": schema}` in `_call_qwen_*` |
| **Region tiling** | low-res vision loses small text → crop to one table/figure per call at full budget | new pass 0.5 cropper feeding pass 2 |
| **Short, single-purpose prompts** | 2048 ctx; every example token competes with output | rewrite pass-2/3 prompts; drop in-prompt JSON examples that get echoed |
| **Programmatic validators after every call** | move reasoning out of the model into Python | extend `_is_valid_entity_name`, add header/measure validators, question post-validator |
| **2-pass self-consistency** for low-confidence items only | sample twice, keep agreement; cheap because rare | wrap entity/question calls with a confidence gate |
| **pdfplumber as ground truth for text** | VLM for structure, deterministic text for values | already partly there; formalise as "text-from-plumber, shape-from-VLM" |
| **Confidence + escalation** | when Qwen self-rates low, route that one item to `PROVIDER_*` big model | confidence field already in schema; add threshold + override |

Net rule: **Qwen perceives, Python validates, a big model is the rare tie-breaker.**

---

## 4. Current → Desired architecture

### 4.1 Today (what the code emits)

```
PDF ─▶ pass0 raster ─▶ pass1 LayoutLM ─▶ pass2 Qwen-VL entities ─▶ pass2.5 doc-KG
     ─▶ pass2.6 classify ─▶ pass3 two-loop Q&A ─▶ pass4 assemble ─▶ pass5 Gemini gap-fill
                                                                        │
                                                                        ▼
                              ONE blended AST  (Enterprise_Document_AST.json)
                              ─ mixes structure + extracted values + prose
                              ─ questions are STUBS, entities NOISY, measures EMPTY  (D1–D8)
                              ─ no analyticsSpec, no units/formats, refs:{} unfilled
```

### 4.2 Desired (what we want)

```
PDF ─▶ pass0…pass2.6 (perception, mostly unchanged)
     ─▶ pass3*  REAL questions + analyticsSpec   (rewrite)
     ─▶ pass2.7 ENRICH: units, formats, valueDomain, columnGroups, glossary, palette   (NEW)
     ─▶ pass4*  SPLIT-assemble ──────────────┐
                                              ├─▶ ① template.ast.json     (value-free skeleton)
                                              └─▶ ② template.blueprint.json (value-free brain)
     ─▶ pass5*  Gemini/Qwen polish of ② labels only (no values)

   (later, separate process)
   ①② + dataset ─▶ BINDER ─▶ ③ report.output.ast.json  (the only file with values+prose)
```

**The structural change:** pass4 stops producing one blended AST and instead **emits two value-free
files**; a new **pass 2.7 enrichment** stage adds the analytic metadata the gold ② needs; **pass3 is
rewritten** to stop echoing stub questions and to attach an `analyticsSpec` per question.

### 4.3 Defect → fix → file map

| ID | Defect (today) | Root cause (function) | Fix | Lands in |
|----|----------------|-----------------------|-----|----------|
| D1 | Noisy entities ("Press Re", URLs) | `_is_valid_entity_name` too lax; web-chrome leaks | blocklist + regex pre-filter; apply `_is_website_artifact_table` to all entity sources | ② entities |
| D2 | `measures: []` on tables | `_merge_multirow_headers` heuristic misses PIB headers | **3 signals:** pdfplumber x-spans + **LayoutLMv3 header-region** + VLM tie-break → `columnGroups`/`measures` | ① columns / ② tableTemplates |
| D3 | Stub questions ("Specific question…?") | pass3 L1 prompt embeds an example the VLM echoes | remove echoed example; schema-bounded decode; post-validator drops template-looking text | ② questions |
| D4 | `questionType` = full enum string | prompt asks for the whole enum | single-value classify + validator | ② questions |
| D5 | Unassigned questions dropped | pass3 assignment loop | keep & route to nearest topic | ② topics |
| D6 | `refs: {}` empty | (by design at extraction) | leave empty in ①② — binder fills in ③ | ③ |
| D7 | No units/formats/valueDomain | nothing computes them | **pass 2.7** infers from headers/aliases/glossary | ② entities, ① columns |
| D8 | No `analyticsSpec` | nothing emits it | infer from `questionType`+roles at pass3; human-review later | ② questions |

**Header repair uses THREE deterministic signals before any VLM call (answers "why LayoutLM?"):**

```
1. pdfplumber  → exact cell x-spans + ruled lines/rects   (great on bordered gov tables)
2. LayoutLMv3  → region typing: marks the TABLE bbox and HEADER-vs-BODY band   (:8001, already running)
                 → works even on BORDERLESS tables where plumber has no lines to read
3. VLM (Qwen)  → semantic tie-break ONLY when 1+2 disagree, on a hi-res crop
```

LayoutLMv3 is already in the pipeline (pass 1) producing region boxes — we just *reuse* its
header/table region labels as a second geometry source. It complements pdfplumber (which needs ruled
lines) by locating the header band on borderless tables; it does **not** reconstruct exact column
spans, so plumber stays primary for x-geometry. This keeps header repair fully **offline + deterministic**,
reserving the 2048-token VLM budget for genuine ambiguity only.

---

## 5. Migration phases

- **P0 — Model switchboard (½ day).** Add `_call_openai` + env + `is_provider_available`; smoke-test
  `REASONING_PROVIDER=openai`. *No behaviour change when unset.*
- **P1 — Value-free split (1–2 days).** pass4 emits ①②; add `valueFree` assert (no numbers/prose in
  ①②). Formalise `clear_prefilled_slots()` as the skeleton-maker.
- **P2 — Entity hygiene D1 (1 day).** blocklist+regex; artifact-table filter everywhere; unit tests on
  the known-noisy outputs.
- **P3 — Header/measure repair D2 (1–2 days).** pdfplumber de-fragmentation; multi-row merge →
  `columnGroups`+`measures`.
- **P4 — Real questions D3/D4/D5 (2 days).** rewrite pass3 prompts; schema-bounded decode;
  post-validator + archetype fallback; keep unassigned.
- **P5 — Enrichment pass 2.7 D7/D8 (2–3 days).** units/formats/valueDomain/glossary/palette/
  `analyticsSpec`; Qwen-first with big-model escalation for ambiguous specs.
- **P6 — Max-Qwen hardening.** guided_json everywhere; tiling; 2-pass self-consistency on low-conf.

Each phase is independently shippable and reversible; gates in §6.

---

## 6. Quality gates (must pass before a phase is "done")

1. **Value-free invariant:** ①② contain no digits-as-values, no sentences (regex + JSON walk).
2. **ID integrity:** every `requiredEntities[].entityId`, `biQuery`, `templateRef` resolves
   (reuse the cross-check script proven on the gold files).
3. **No stubs:** zero questions matching the stub-phrase blocklist; ≥1 real question per topic.
4. **Measure coverage:** ≥90% of numeric table columns have a non-empty `measures`/`unit`.
5. **Golden diff:** extracted ②'s *shape* matches `gold_standard/template.blueprint.json` keys.
6. **Offline default:** whole extraction runs with only `qwen` providers (no network).

---

## 7. Binder follow-on (after extraction lands)

Per [README_BINDER_ARCHITECTURE.md](README_BINDER_ARCHITECTURE.md) §10: new `report_builder/binding/`
package (profiler → resolver → review → question_binder → executor → filler → assembler), extend
`ast_core/schema.py` with `datasetAST/bindingAST/analyticsAST/evidenceAST`, reuse `TemplateBinder` +
`deep_bi`. Produces ③. Gold target = `gold_standard/report.output.ast.json`.

---

## 8. Locked decisions (from the 22-question extraction loop)

| # | Decision | Choice |
|---|----------|--------|
| Q1 | Template output shape | **Two files** — `template.ast.json` (skeleton) + `template.blueprint.json` (brain) |
| Q2 | Where templates live | **Disk** `storage/templates/<id>/` for dev → **freeze into immutable S3 vault** for prod |
| Q3 | Legacy blended AST | **Keep behind `EXTRACTION_EMIT_LEGACY`** (default OFF) during P1–P5, then drop |
| Q4 | "Value-free" line | **Moderate** — enum members, glossary, aliases, units/formats allowed (schema); measured numbers + prose forbidden |
| Q5 | Model switchboard | **Add `openai` provider now** (default unset); Ollama via `OPENAI_BASE_URL`; presets in §2.5 |
| Q6 | Entity de-noise | **Blocklist + regex** pre-filter (offline); escalate only borderline survivors |
| Q7 | Rejected entities | **Quarantine** to `entitiesRejected[]` (+reason); never silent-delete |
| Q8 | Multi-row headers | **3 signals**: pdfplumber x-spans + **LayoutLMv3 header-region** + VLM tie-break |
| Q9 | columnGroups | **Geometry-span + repetition**; VLM fallback |
| Q10 | Empty-measure tables | **Re-extract once** (hi-res tile) → else keep `needsReview=true`; never silent-drop |
| Q11 | Stub questions | **All three**: de-exemplify prompt + `guided_json` + post-validate & regenerate |
| Q12 | Question source | **Hybrid** — VLM proposes → archetype library normalizes + guarantees ≥1/topic |
| Q13 | `analyticsSpec` | **Deterministic rule table** (questionType→operation) backbone + later human review |
| Q14 | Questions/topic | **Min 1, soft max 5, priority-ranked** |
| Q15 | Unassigned questions | **Route to nearest topic** → else "General"; **never drop** |
| Q16 | Enrichment placement | **New dedicated `pass 2.7`** stage |
| Q17 | Units/formats | **Layered** regex + glossary → VLM fallback |
| Q18 | Dimension members | **Hybrid** — canonical closed low-card dims filled; high-card (State) open |
| Q19 | Glossary & palette | **Both** — canonical MoSPI defaults + doc overrides |
| Q20 | Schema-bounded decode | **Adopt `guided_json` broadly now** (top max-Qwen lever) |
| Q21 | Self-consistency | **Only low-confidence** items (gated; GPU is single-sequence) |
| Q22 | Testing | **Both** — golden-shape diff in CI + one pinned PDF e2e nightly |

### 8.1 New building blocks these decisions introduce

- `report_builder/llm_router.py` → `_call_openai` (Q5) + `.env` presets (§2.5).
- `pass 2.7` enrichment stage (Q16) computing units/format/valueDomain/glossary/palette/`analyticsSpec` (Q13/Q17/Q18/Q19).
- An **archetype question library** (Q12) + **stub post-validator** (Q11) + **analyticsSpec rule table** (Q13).
- An **entity blocklist/regex** + `entitiesRejected[]` (Q6/Q7).
- **Header repair** combining pdfplumber + LayoutLMv3 + VLM (Q8/Q9/Q10).
- **`guided_json` schemas** per structured VLM call (Q20) + **confidence-gated re-sampling** (Q21).
- **`pass4` split-emit** → `template.ast.json` + `template.blueprint.json` (Q1) with a **value-free assert** (Q4) and `EXTRACTION_EMIT_LEGACY` flag (Q3).
- **Golden-shape tests** vs `gold_standard/` (Q22).

All of these fold into the phase plan in §5; nothing in §3–§5 conflicts with the locked choices.

