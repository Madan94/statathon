# BharatStat V2 — Template Extraction: Complete Setup & Run Guide

> **What this guide covers:** how to set up the project from scratch, how to run
> the full pipeline to **extract a value-free template** from a legacy MoSPI/NSSO
> PDF, and **every operating mode** — controlled entirely through the `.env` file.
>
> **Audience:** anyone receiving this repo through a secure channel who needs to
> stand it up and produce a template, with or without a GPU, with or without API
> keys, online or fully air-gapped.

---

## Table of Contents

1. [What "template extraction" produces](#1-what-template-extraction-produces)
2. [Prerequisites](#2-prerequisites)
3. [One-time setup](#3-one-time-setup)
4. [The `.env` file — the single control panel](#4-the-env-file--the-single-control-panel)
5. [The four operating modes (detailed)](#5-the-four-operating-modes-detailed)
   - [Mode A — Fully Offline / Air-Gapped](#mode-a--fully-offline--air-gapped-no-key-no-gpu-no-network)
   - [Mode B — Local GPU](#mode-b--local-gpu-qwen-vllm--layoutlm)
   - [Mode C — Cloud API](#mode-c--cloud-api-gemini--groq--openai--openrouter--ollama)
   - [Mode D — Hybrid / Per-task routing](#mode-d--hybrid--per-task-routing-recommended-for-quality)
6. [Quality levers (apply to any online mode)](#6-quality-levers-apply-to-any-online-mode)
7. [How to run extraction (3 ways)](#7-how-to-run-extraction-3-ways)
8. [Understanding the output files](#8-understanding-the-output-files)
9. [Full environment-variable reference](#9-full-environment-variable-reference)
10. [Verification & tests](#10-verification--tests)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. What "template extraction" produces

Template extraction turns a **legacy statistical PDF** into a **reusable,
value-free template** that can later regenerate the same report on a *new*
dataset. It always emits a **3-file value-free model**:

| # | File | Role | Contains | NEVER contains |
|---|------|------|----------|----------------|
| ① | `template.ast.json` | Render skeleton | Layout, geometry, style, section hierarchy, **empty slots** (table columns with no rows, content slots with `biQuery`/`templateQuestion`, chart specs with no series) | data rows, prose, computed values |
| ② | `template.blueprint.json` | Analytic brain | Typed entities, glossary, palette, topics → questions → `analyticsSpec`, answer structures | data values, canned sentences |
| ③ | `report.output.ast.json` | Filled instance (produced later by the **binder**, not by extraction) | ① cloned + slots filled by BI + dataset/binding/evidence | — values live **only** here |

**The golden rule:** a template stores *structure, labels, entities, and the
recipe* — never *values or prose* derived from the original data. Extraction
produces ① and ②. The binder (separate run) produces ③.

Outputs are written to:

```
outputs/<sanitised-doc-title>/template.ast.json
outputs/<sanitised-doc-title>/template.blueprint.json
```

---

## 2. Prerequisites

| Need | Minimum | Notes |
|------|---------|-------|
| **Python** | 3.12+ (3.13 OK) | Add to PATH on Windows. |
| **Poppler** | 24.x+ | For `pdf2image` rasterization. Optional — pipeline falls back to `pdfplumber`. Extract to `C:\poppler`, add `C:\poppler\Library\bin` to PATH (or set `POPPLER_PATH`). |
| **GPU (NVIDIA)** | only for Mode B | 6 GB VRAM → Qwen2.5-VL-3B-AWQ; 8 GB+ → 7B. Not needed for Mode A/C. |
| **Docker Desktop** | only for Mode B local servers | Runs LayoutLM (:8001) + vLLM (:8002) + Neo4j + Redis. Not needed for Mode A. |
| **API key** | only for Mode C/D cloud | Gemini / Groq / OpenAI. Not needed for Mode A/B. |

> **The fastest path** (Mode A, offline) needs **only Python + the pip
> dependencies** — no GPU, no Docker, no keys.

---

## 3. One-time setup

All commands are **PowerShell**, run from the repo root
(`...\statathon`).

### 3.1 Create and activate a virtual environment

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
& .\.venv\Scripts\Activate.ps1
```

### 3.2 Install dependencies

**Windows (recommended — uses binary wheels):**

```powershell
pip install -r requirements-windows.txt
```

**Linux / GPU host:**

```bash
pip install -r requirements.txt
```

> **Corporate network / SSL inspection:** if pip fails on certificates, add
> `--trusted-host pypi.org --trusted-host files.pythonhosted.org`. The runtime
> itself injects the OS trust store via `truststore` so HTTPS calls work behind a
> corporate proxy.

### 3.3 Create your `.env`

```powershell
Copy-Item .env.example .env
```

`.env.example` is the **single source of truth** — every variable the code reads
is documented there. The next section explains how to drive the modes. For a
first offline smoke-test you don't need to edit anything except optionally
setting `LLM_DISABLED=1` (or just use the offline simulation script, which sets
it for you).

---

## 4. The `.env` file — the single control panel

Everything about *how* the pipeline runs is controlled by environment variables.
There are **four switch groups** that matter for extraction:

```
┌─ 1. ON/OFF master switch ───────────────────────────────────────────────┐
│ LLM_DISABLED            blank = online   |   1 = fully offline           │
└──────────────────────────────────────────────────────────────────────────┘
┌─ 2. Provider routing (when online) ─────────────────────────────────────┐
│ VLM_PROVIDER            qwen | gemini | groq | openai   (vision tasks)   │
│ REASONING_PROVIDER      qwen | gemini | groq | openai   (text/reasoning) │
│ PROVIDER_<TASK>         per-task override (optional, see §9)             │
└──────────────────────────────────────────────────────────────────────────┘
┌─ 3. Quality levers (Qwen path) ─────────────────────────────────────────┐
│ GUIDED_JSON             1 = schema-constrained decoding (default ON)     │
│ SELF_CONSISTENCY        1 = confidence-gated 2-pass (default ON)         │
└──────────────────────────────────────────────────────────────────────────┘
┌─ 4. Output shape ───────────────────────────────────────────────────────┐
│ EXTRACTION_EMIT_LEGACY  blank = only the 3-file model  |  1 = also emit  │
│                         legacy enterprise_ast.json + blueprint.json      │
└──────────────────────────────────────────────────────────────────────────┘
```

**Precedence for provider selection** (first match wins):

```
PROVIDER_<TASK>   →   VLM_PROVIDER / REASONING_PROVIDER   →   qwen (default)
```

…but if `LLM_DISABLED=1`, **all of the above is bypassed** — every model call is
skipped and the deterministic path runs.

---

## 5. The four operating modes (detailed)

The same pipeline runs in every mode. What changes is *which steps call a model*
and *which fall back to deterministic logic*. Here is the pass map and where each
mode plugs in:

```
 Pass 0  Rasterize (pdf2image → PNG, pdfplumber → text/tables)   ← always deterministic
 Pass 1  Layout detection (LayoutLMv3 :8001)                     ← skipped offline → pdfplumber
 Pass 2  Entity + structure (VLM)                                ← skipped offline → programmatic
 Pass 2.5 Document knowledge graph                               ← always deterministic
 Pass 2.6 Entity classification                                  ← deterministic (+ optional Gemini)
 Pass 2.7 Entity enrichment (units/format/glossary/palette)      ← always deterministic
 Pass 3  Two-loop questions + bindings (VLM)                     ← skipped offline → archetypes
 Pass 4  AST + blueprint assembly                                ← always deterministic
 Pass 5  Gemini enhancement                                      ← skipped offline / keyless
 Emit    template.ast.json + template.blueprint.json             ← always
```

---

### Mode A — Fully Offline / Air-Gapped (no key, no GPU, no network)

**When to use:** air-gapped deployments, GPU-less CI, reproducible
demonstrations, validating the structure end-to-end, or any machine that can't
reach a model server.

**What it does:** sets the master switch `LLM_DISABLED=1`. Every
`llm_text_call` / `llm_vision_call` returns `None` immediately, LayoutLM is
skipped (Pass 1 returns `None`), Gemini enrichment is skipped, and the pipeline
runs **fully deterministically** on `pdfplumber` + the programmatic fallbacks.
You still get a valid, well-formed, value-free 3-file template.

**What is skipped vs. what still runs:**

| Step | Offline behaviour |
|------|-------------------|
| Pass 1 LayoutLM | **Skipped** → layout derived from `pdfplumber` text/words |
| Pass 2 VLM entities | **Skipped** → entities harvested from table headers + headings |
| Pass 3 VLM questions | **Skipped** → questions generated from archetypes + table structure |
| Pass 5 Gemini | **Skipped** |
| Pass 0 / 2.5 / 2.6 / 2.7 / 4 / Emit | **Run normally** (all deterministic) |

**`.env` configuration:**

```env
LLM_DISABLED=1
# Everything else is ignored in this mode. No API keys needed.
# (Optional) also emit the legacy blended files:
# EXTRACTION_EMIT_LEGACY=1
```

**Run it (one command — the harness sets `LLM_DISABLED` for you):**

```powershell
$env:PYTHONPATH = (Get-Location).Path
& .\.venv\Scripts\python.exe scripts\simulate_offline.py
# or point at any PDF:
& .\.venv\Scripts\python.exe scripts\simulate_offline.py "test_data\Stat reports.pdf"
```

Exit code `0` + `SIMULATION PASSED` means the offline 3-file model was produced
and verified (≥1 topic/entity/question, valid `questionType`, `analyticsSpec`
present, value-free invariant holds, trace confirms LayoutLM + VLM were skipped).

**Trade-offs:** question/entity richness is lower than the model-assisted modes
(borderless or image-only tables degrade gracefully and may be flagged
`needsReview`), but the output is deterministic, fast, and contains zero data
values. This is the **safe baseline**.

---

### Mode B — Local GPU (Qwen vLLM + LayoutLM)

**When to use:** you have an NVIDIA GPU and want the **highest-quality fully
local** extraction with **no cloud calls and no API keys**.

**What it does:** runs LayoutLMv3 on `:8001` and Qwen2.5-VL on `:8002` (via
Docker). Vision **and** reasoning tasks both route to `qwen`. The quality levers
(`GUIDED_JSON`, `SELF_CONSISTENCY`) apply here and are ON by default.

**Start the local servers (Docker):**

```powershell
# From repo root — starts Neo4j + Redis (always) and LayoutLM + vLLM (gpu profile)
docker compose --profile gpu up -d
```

| Container | Port | GPU | Purpose |
|-----------|------|-----|---------|
| `layoutlm` | 8001 | No (CPU) | Pass 1 layout regions |
| `sglang` (vLLM) | 8002 | **Yes** | Pass 2 & 3 vision/reasoning |
| `neo4j` | 7474 / 7687 | No | Knowledge graph (optional) |
| `redis` | 6379 | No | Cache/queues |

> First boot downloads the model weights into `./model/cache` (shared by all
> containers, so it happens once). 6 GB VRAM → keep the default 3B model; 8 GB+ →
> set `VLLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct-AWQ` (compose) or
> `SGLANG_MODEL=...` (`.env`).

**`.env` configuration:**

```env
LLM_DISABLED=
VLM_PROVIDER=qwen
REASONING_PROVIDER=qwen

SGLANG_ENDPOINT=http://localhost:8002
SGLANG_MODEL=Qwen/Qwen2.5-VL-3B-Instruct-AWQ
LAYOUTLM_ENDPOINT=http://localhost:8001

# Quality levers (default ON — keep them on for the 3B model):
GUIDED_JSON=1
SELF_CONSISTENCY=1
SELF_CONSISTENCY_THRESHOLD=0.6

# No API keys required in this mode.
```

**Run it:** see [§7](#7-how-to-run-extraction-3-ways). The pipeline pre-flights
the Qwen server; if it's unreachable it **degrades gracefully** to the same
fallbacks as Mode A (so a partial server outage never crashes a run).

**Trade-offs:** best local quality and full privacy, at the cost of a GPU and the
first-boot model download.

---

### Mode C — Cloud API (Gemini / Groq / OpenAI / OpenRouter / Ollama)

**When to use:** no local GPU, but you *do* have an API key (or a local
OpenAI-compatible server like Ollama / LM Studio). Highest quality with zero GPU
setup.

**What it does:** routes vision and/or reasoning tasks to a hosted provider.
`openai` is a **generic OpenAI-compatible** client — point `OPENAI_BASE_URL` at
any compatible server (OpenRouter, Together, DeepSeek, Ollama, LM Studio, vLLM).

**`.env` configuration — pick ONE provider family:**

<details>
<summary><b>Gemini</b></summary>

```env
LLM_DISABLED=
VLM_PROVIDER=gemini
REASONING_PROVIDER=gemini
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-2.5-flash
```
</details>

<details>
<summary><b>Groq</b></summary>

```env
LLM_DISABLED=
VLM_PROVIDER=groq
REASONING_PROVIDER=groq
GROQ_API_KEY=your-key
GROQ_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
GROQ_VISION_MODEL=meta-llama/llama-4-maverick-17b-128e-instruct
```
</details>

<details>
<summary><b>OpenAI</b></summary>

```env
LLM_DISABLED=
VLM_PROVIDER=openai
REASONING_PROVIDER=openai
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_VISION_MODEL=gpt-4o-mini
```
</details>

<details>
<summary><b>OpenRouter (no GPU, one key, many models)</b></summary>

```env
LLM_DISABLED=
VLM_PROVIDER=openai
REASONING_PROVIDER=openai
OPENAI_API_KEY=your-openrouter-key
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=deepseek/deepseek-chat
```
</details>

<details>
<summary><b>Ollama (local, OpenAI-compatible, no key)</b></summary>

```env
LLM_DISABLED=
VLM_PROVIDER=openai
REASONING_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=qwen2.5:7b
# OPENAI_API_KEY left blank — Ollama needs none
```
</details>

> **Note:** `GUIDED_JSON` / `SELF_CONSISTENCY` are **Qwen-path features**. On
> other providers the `schema=` hint is ignored (the call still works), so leave
> the levers at their defaults.

**Trade-offs:** simplest setup, strong quality, but sends page text/images to a
third party — **do not use in air-gapped contexts** (use Mode A or B instead).

---

### Mode D — Hybrid / Per-task routing (recommended for quality)

**When to use:** you want the **best mix** — e.g. local Qwen for vision (cheap,
private) but a strong cloud model for *reasoning only*, or you want to send one
specific task to a different provider.

**Global hybrid example** (Qwen vision + Gemini reasoning):

```env
LLM_DISABLED=
VLM_PROVIDER=qwen          # all vision tasks → local Qwen
REASONING_PROVIDER=gemini  # all text/reasoning → Gemini
GEMINI_API_KEY=your-key
```

**Per-task overrides** (highest precedence; leave blank to inherit the globals).
Each maps to one extraction task:

```env
PROVIDER_ENTITY_EXTRACTION=      # Pass 2 — entities from page images (vision)
PROVIDER_QUESTION_GENERATION=    # Pass 3 — analytical questions (vision/reasoning)
PROVIDER_ENTITY_BINDING=         # Pass 3 — bind entities to questions
PROVIDER_TOC_EXTRACTION=         # table-of-contents reconstruction
PROVIDER_GAP_FILL=               # fill chapters that produced no questions
PROVIDER_FACT_EXTRACTION=        # fact harvesting
PROVIDER_SEMANTIC_FALLBACK=      # last-resort semantic recovery
```

Example — keep everything local, but route only question generation to Groq:

```env
VLM_PROVIDER=qwen
REASONING_PROVIDER=qwen
PROVIDER_QUESTION_GENERATION=groq
GROQ_API_KEY=your-key
```

**Trade-offs:** maximum control and the best cost/quality balance, at the cost of
a more complex `.env`. Every override still degrades gracefully if its provider
is unavailable.

---

## 6. Quality levers (apply to any online mode)

These harden the **Qwen** path specifically (most impactful on the small 3B
model). Both default **ON**; turn off only if your backend lacks support.

| Variable | Default | What it does |
|----------|---------|--------------|
| `GUIDED_JSON` | `1` | Sends vLLM `guided_json` schema-constrained decoding so the model can only emit JSON matching the expected shape/enums. Large quality win. Set `0` for backends without vLLM structured outputs. |
| `GUIDED_JSON_BACKEND` | `outlines` | The vLLM structured-decoding backend. |
| `SELF_CONSISTENCY` | `1` | Confidence-gated 2-pass re-sampling: a second pass is sampled **only** when the first self-reports confidence below the threshold, then the higher-confidence result wins. Cheap because the local vLLM serializes (`--max-num-seqs 1`). |
| `SELF_CONSISTENCY_THRESHOLD` | `0.6` | Confidence below this triggers the resample. |

> In **Mode A (offline)** these do nothing (no model calls). In **Mode C** on
> non-Qwen providers the schema hint is ignored.

---

## 7. How to run extraction (3 ways)

All three call the same entry point:
`run_extraction_pipeline(pdf_path, doc_title, source_hash, progress_callback)`
in `report_builder/extraction_pipeline.py`, and always write
`outputs/<doc_title>/template.ast.json` + `template.blueprint.json`.

### 7.1 Offline simulation harness (Mode A — easiest)

Forces `LLM_DISABLED=1`, runs end-to-end, and **verifies** the output:

```powershell
$env:PYTHONPATH = (Get-Location).Path
& .\.venv\Scripts\python.exe scripts\simulate_offline.py "test_data\Stat reports.pdf"
```

### 7.2 The pipeline runner script (any mode)

`scripts/run_pipeline.py` reads its input from environment variables and honours
whatever mode your `.env` selects:

```powershell
$env:PYTHONPATH = (Get-Location).Path
$env:PDF_INPUT_PATH = "test_data\Stat reports.pdf"
$env:TEMPLATE_NAME  = "Stat reports"
$env:OUTPUT_DIR     = "outputs"
$env:EXTRACTION_PIPELINE = "v2"
& .\.venv\Scripts\python.exe scripts\run_pipeline.py
```

### 7.3 Direct Python (full control)

```powershell
$env:PYTHONPATH = (Get-Location).Path
& .\.venv\Scripts\python.exe -c "import os, hashlib; from pathlib import Path; from report_builder.extraction_pipeline import run_extraction_pipeline; p = Path('test_data/Stat reports.pdf'); run_extraction_pipeline(pdf_path=p, doc_title='Stat reports', source_hash=hashlib.sha256(p.read_bytes()).hexdigest())"
```

To force offline for any of these, set `$env:LLM_DISABLED = "1"` first.

> The pipeline accepts a `progress_callback(stage, pct, data)` you can pass when
> calling it from your own code (the API server uses it to stream progress).

---

## 8. Understanding the output files

After a run, look in `outputs/<doc_title>/`:

### ① `template.ast.json` — the render skeleton (value-free)

The Enterprise AST subtrees (layout, geometry, content, tables, charts, semantic
hierarchy) **with all data stripped**: table rows emptied (columns + column
groups kept), paragraph content emptied (but `biQuery` / `templateQuestion`
kept), chart series emptied (type / palette kept). Static labels — section
titles, column headers, units, footnotes, header/footer — are **kept**.

### ② `template.blueprint.json` — the analytic brain (value-free)

```jsonc
{
  "templateMeta": { ... },
  "entities":  [ { "entityId", "name", "canonicalName", "entityType",
                   "aliases", "unit", "dtypeHint", "valueDomain",
                   "defaultFormat", "glossaryRef" } ],
  "glossary":  [ { "term", "definition", "unit" } ],
  "palette":   { "paletteId": "mospi_default", ... },
  "topics":    [ { "topicId", "title", "questions": [ {
                   "questionId", "intent",            // real NL question
                   "questionType",                    // single enum
                   "requiredEntities": [ { "entityId", "role" } ],
                   "analyticsSpec": { "operation", "metric",
                                      "groupBy", "agg", "filters",
                                      "sort", "topN" },   // executable BI contract
                   "answerStructure": { ... } } ] } ],
  "tableTemplates":  [ ... ],   // columnGroups + per-column role/unit/format
  "entitiesRejected":[ ... ]    // quarantined noisy candidates (audit trail)
}
```

`questionType` is always one of: `comparison`, `trend`, `ranking`,
`distribution`, `composition`, `correlation`, `describe`.

### (optional) Legacy files

If `EXTRACTION_EMIT_LEGACY=1`, the run **also** writes the older blended
`enterprise_ast.json` + `blueprint.json` alongside the canonical pair (for tools
still expecting the old shape). Off by default.

---

## 9. Full environment-variable reference

Only the variables that affect **template extraction** are listed here. The full
set (auth, DB, SMTP, frontend, etc.) lives in `.env.example`.

### Master switch & output

| Variable | Values | Default | Effect |
|----------|--------|---------|--------|
| `LLM_DISABLED` | blank / `1` | blank | `1` = fully offline: skip every LLM/VLM/LayoutLM call. |
| `EXTRACTION_EMIT_LEGACY` | blank / `1` | blank | `1` = also emit legacy `enterprise_ast.json` + `blueprint.json`. |
| `EXTRACTION_PIPELINE` | `v1` / `v2` | `v2` | `v2` = LayoutLM + Qwen multi-pass (use this). |

### Provider routing (online)

| Variable | Values | Default | Effect |
|----------|--------|---------|--------|
| `VLM_PROVIDER` | `qwen`/`gemini`/`groq`/`openai` | `qwen` | Provider for all **vision** tasks. |
| `REASONING_PROVIDER` | `qwen`/`gemini`/`groq`/`openai` | `qwen` | Provider for all **text/reasoning** tasks. |
| `PROVIDER_ENTITY_EXTRACTION` | provider | blank | Override Pass 2 entity extraction. |
| `PROVIDER_QUESTION_GENERATION` | provider | blank | Override Pass 3 question generation. |
| `PROVIDER_ENTITY_BINDING` | provider | blank | Override Pass 3 entity binding. |
| `PROVIDER_TOC_EXTRACTION` | provider | blank | Override ToC reconstruction. |
| `PROVIDER_GAP_FILL` | provider | blank | Override question gap-fill. |
| `PROVIDER_FACT_EXTRACTION` | provider | blank | Override fact extraction. |
| `PROVIDER_SEMANTIC_FALLBACK` | provider | blank | Override semantic fallback. |
| `VLM_MAX_CONSECUTIVE_FAIL` | int | `3` | Give up on the VLM after N consecutive failures → fallbacks. |

### Provider credentials / models

| Variable | For | Notes |
|----------|-----|-------|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Gemini | Either is accepted. |
| `GROQ_API_KEY` | Groq | |
| `OPENAI_API_KEY` | OpenAI | Only required for `api.openai.com`. |
| `OPENAI_BASE_URL` | OpenAI-compatible | Point at OpenRouter/Ollama/LM Studio/vLLM. |
| `OPENAI_MODEL` / `OPENAI_VISION_MODEL` | OpenAI-compatible | Model IDs. |
| `GEMINI_MODEL` / `GROQ_MODEL` / `GROQ_VISION_MODEL` | resp. | Model IDs. |

### Local servers (Mode B)

| Variable | Default | Effect |
|----------|---------|--------|
| `SGLANG_ENDPOINT` | `http://localhost:8002` | vLLM/Qwen server URL. |
| `SGLANG_MODEL` | `Qwen/Qwen2.5-VL-3B-Instruct-AWQ` | 3B (6 GB) or 7B (8 GB+). |
| `SGLANG_TIMEOUT` | `300` | Seconds. |
| `LAYOUTLM_ENDPOINT` | `http://localhost:8001` | LayoutLMv3 server URL. |
| `LAYOUTLM_TIMEOUT` | `300` | Seconds. |

### Quality levers (Qwen path)

| Variable | Default | Effect |
|----------|---------|--------|
| `GUIDED_JSON` | `1` | Schema-constrained decoding on/off. |
| `GUIDED_JSON_BACKEND` | `outlines` | vLLM structured-decoding backend. |
| `SELF_CONSISTENCY` | `1` | Confidence-gated 2-pass on/off. |
| `SELF_CONSISTENCY_THRESHOLD` | `0.6` | Resample below this confidence. |

### PDF / image processing

| Variable | Default | Effect |
|----------|---------|--------|
| `PDF_DPI` | `150` | Rasterization DPI. |
| `VLM_MAX_IMAGE_DIM` | `800` | Max image edge sent to the VLM. |
| `POPPLER_PATH` | blank | Poppler `bin` dir (Windows). Blank → rely on PATH / pdfplumber. |
| `TESSERACT_CMD` | blank | Optional OCR binary. |

> Document-type caps (`STAT_*`, `PIB_*`) and quality thresholds (`ENTITY_*`,
> `INFERENCE_*`, `CHAPTER_*`) tune entity/question/table limits per document type.
> Defaults are sensible; see `.env.example` §12–§13 to adjust.

---

## 10. Verification & tests

**Run the offline simulation** (proves the whole pipeline + 3-file model end to
end without any servers):

```powershell
$env:PYTHONPATH = (Get-Location).Path
& .\.venv\Scripts\python.exe scripts\simulate_offline.py
```

**Run the unit test suites** (structure, hygiene, headers, questions,
enrichment, max-Qwen, offline switch):

```powershell
& .\.venv\Scripts\python.exe -m pytest `
  tests\test_template_emit.py `
  tests\test_entity_hygiene.py `
  tests\test_header_repair.py `
  tests\test_question_gen.py `
  tests\test_entity_enrichment.py `
  tests\test_max_qwen.py `
  tests\test_offline_mode.py -q
```

A green suite + `SIMULATION PASSED` (exit `0`) confirms the install and all modes
are wired correctly.

> **PowerShell tip:** piping Python's stderr through `Select-Object` can make
> `$LASTEXITCODE` read `1` even on success. To get the true exit code, redirect
> with `*> run.log` and then inspect `$LASTEXITCODE`.

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `No PDF found to simulate with` | No input PDF | Pass a path: `simulate_offline.py "path\to\file.pdf"`. |
| `ModuleNotFoundError: report_builder` | `PYTHONPATH` not set | `$env:PYTHONPATH = (Get-Location).Path` before running. |
| pip TLS/cert errors | Corporate SSL inspection | Add `--trusted-host pypi.org --trusted-host files.pythonhosted.org`. |
| `pdf2image` / Poppler errors | Poppler not installed | Install Poppler + set `POPPLER_PATH`, or ignore — `pdfplumber` fallback runs. |
| Pipeline "LayoutLM unavailable" warning | `:8001` not running | Expected in Mode A/C. Start Docker for Mode B, or ignore (fallback runs). |
| Qwen calls all fail | `:8002` down / wrong `SGLANG_ENDPOINT` | Start `docker compose --profile gpu up -d`, or switch to Mode A/C. |
| Few/low-quality questions offline | No model available | Expected — Mode A is deterministic and conservative. Use Mode B/C/D for richer output. |
| Cloud calls rejected | Missing/!invalid key | Set the right `*_API_KEY`; confirm with the provider. |
| Output has data values in it | Should never happen | The emit step asserts the value-free invariant; re-run `simulate_offline.py` which checks it and report if it fails. |

---

### Quick mode picker

```
Need air-gapped / no GPU / no key?      → Mode A   (LLM_DISABLED=1)
Have an NVIDIA GPU, want full privacy?   → Mode B   (qwen + Docker servers)
No GPU but have an API key?              → Mode C   (gemini | groq | openai)
Want best cost/quality mix?              → Mode D   (qwen vision + cloud reasoning)
```

For the locked design decisions and pass-by-pass internals, see
`report_builder/PLAN_MIGRATION.md` and
`report_builder/README_TEMPLATE_EXTRACTION.md`.
</content>
</invoke>
