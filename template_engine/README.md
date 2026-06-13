# Template Engine — Production Configuration & Architecture

> **Version:** 7-Phase Complete (Steps 1–46)  
> **Branch:** `feature/rev-template`  
> **Tests:** 324+ passing | 0 failures  
> **Python:** 3.11 · 3.12 · 3.13 | **GPU:** 6GB VRAM (sequential sharing)

---

## Table of Contents

1. [Complete Build Overview](#complete-build-overview)
2. [Full Project Structure](#full-project-structure)
3. [Architecture Diagram](#architecture-diagram)
4. [Quick Start — Real-Time Setup](#quick-start--real-time-setup)
5. [Full Configuration Reference](#full-configuration-reference)
6. [Feature Toggles & Impact Matrix](#feature-toggles--impact-matrix)
7. [Module Reference](#module-reference)
8. [API Reference](#api-reference)
9. [GPU & Docker Setup](#gpu--docker-setup)
10. [Testing](#testing)
11. [Troubleshooting](#troubleshooting)

---

## Complete Build Overview

The Template Engine is a **46-step, 7-phase** system that transforms legacy PDF reports (MoSPI/PLFS quarterly publications) into reusable analytical templates, then generates new publication-grade reports by binding those templates to live datasets.

### End-to-End Pipeline

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          TEMPLATE ENGINE PIPELINE                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────┐    ┌──────────────┐    ┌────────────────┐    ┌──────────────┐  │
│  │ PDF In  │───▶│  VLM Parse   │───▶│ Entity Extract │───▶│  Inference   │  │
│  │ (PLFS)  │    │  (ColPali or │    │  + Dedup +     │    │  Cascade     │  │
│  └─────────┘    │  pdfplumber) │    │  Classifier    │    │  (Questions) │  │
│                 └──────────────┘    └────────────────┘    └──────┬───────┘  │
│                                                                   │          │
│                         TEMPLATE STORED IN DB ◀──────────────────┘          │
│                                   │                                          │
│  ┌──────────┐    ┌─────────────┐  │  ┌──────────────────────────────────┐   │
│  │ Dataset  │───▶│   Binder    │◀─┘  │   Orchestrator (Async Topics)    │   │
│  │ (CSV/DB) │    │  5-stage    │────▶│  Planner → Scribe → Verifier     │   │
│  └──────────┘    │  Resolver   │     │  ConsensusRepair + Citations      │   │
│                  └─────────────┘     └──────────────┬───────────────────┘   │
│                                                      │                       │
│  ┌─────────────────────────────────────────────────┐│                       │
│  │  OUTPUT LAYER                                   ││                       │
│  │  LaTeX Renderer ──▶ lualatex ──▶ PDF            ││                       │
│  │  Pandoc ──▶ HTML Preview                        ││                       │
│  │  SSE Stream ──▶ Dashboard real-time progress   ◀┘│                       │
│  └─────────────────────────────────────────────────┘                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Phase Summary

| Phase | Steps | Theme | Key Deliverables |
|-------|-------|-------|-----------------|
| **1** | 1–8 | Foundation | `PipelineConfig`, `CheckpointBackend`, `LLMRouter`, domain tolerances, entity dedup, error recovery, SGLang 3-call decomposition, soft constraints |
| **2** | 9–16 | PLFS | PLFS glossary (50+ terms), statement parser, hierarchical tables, Camelot, table merger, ColPali fine-tune, VLM-direct inferrer, synthetic tests |
| **3** | 17–24 | Report Gen | `TemplateBinder`, 5-stage `ColumnResolver`, orchestrator, LaTeX renderer, consensus repair, citation manager, priority extraction, template cache |
| **4** | 25–29 | Observability | OTel + Langfuse + Phoenix tracing, Qdrant LTM (3 collections), scribe learning, PLFS style rules, adaptive retry |
| **5** | 30–35 | Dashboard | SSE progress streaming, entity binding API, `ReportProgressStream.tsx`, `EntityBindingPanel.tsx`, HTML preview endpoint |
| **6** | 36–40 | Quality | PLFS integration tests, report-gen tests, LLM provider tests, checkpoint resume tests, benchmark suite |
| **7** | 41–46 | Deploy | GPU Docker Compose (6GB VRAM), `.env.example`, docs, CI pipeline, requirements, e2e |

---

## Full Project Structure

```
statathon/
├── .env                              # Active secrets (git-ignored)
├── .env.example                      # All env vars with defaults ← START HERE
├── .github/
│   └── workflows/
│       └── template-engine-ci.yml   # CI: test matrix (3.11/3.12/3.13) + lint
├── docker-compose.yml               # Standard services (API, Dashboard, Neo4j, Redis)
├── docker-compose.gpu.yml           # GPU services: ColPali + SGLang (sequential)
├── pyproject.toml                   # Build metadata
├── requirements.txt                 # Python deps (observability deps commented optional)
├── requirements-windows.txt         # Windows-specific overrides
│
├── template_engine/                 ◀ CORE PACKAGE
│   ├── __init__.py                  # Public API: compile_template, run_extraction_pipeline
│   ├── pipeline.py                  # run_extraction_pipeline() entry point
│   ├── config.py                    # PipelineConfig — ALL tuneable env-var thresholds
│   │
│   ├── ast/                         # PDF → AST compilation
│   │   ├── ast_builder.py           # compile_template(): TemplateAST builder
│   │   ├── section_classifier.py    # classify_heading(): canonical section taxonomy
│   │   └── template_serializer.py   # JSON ↔ TemplateAST + load_default_mospi()
│   │
│   ├── ingestion/                   # PDF loading & fingerprinting
│   │   ├── pdf_loader.py            # Multi-backend: ColPali → pdfplumber → PyMuPDF
│   │   ├── pdf_hasher.py            # SHA-256 audit fingerprint
│   │   └── spatial_extractor.py    # Region classification from raw PDF
│   │
│   ├── vlm/                         # Vision-Language Model clients
│   │   ├── client.py               # VLMClient ABC + VLMClientFactory (env-driven)
│   │   ├── colpali_client.py       # HTTP client to ColPali microservice
│   │   ├── pdfplumber_adapter.py   # Lattice mode / merged-cell fallback
│   │   ├── mock_client.py          # Fixture-based dev client (no GPU needed)
│   │   └── schemas.py              # VLMPageResult, VLMRegion, HierarchicalTable
│   │
│   ├── extraction/                  # Entity extraction from VLM output
│   │   ├── entity_extractor.py     # extract_entities(): raw → TemplateEntity[]
│   │   ├── entity_classifier.py    # classify_entity_type(): METRIC/DEMOGRAPHIC/etc
│   │   ├── entity_deduplicator.py  # deduplicate_entities(): scoped + cross-ref
│   │   ├── plfs_parser.py          # Statement N.M → entities + questions (PLFS-specific)
│   │   └── table_merger.py         # Cross-page table continuation merging
│   │
│   ├── inference/                   # Question inference from extracted entities
│   │   ├── question_inferrer.py    # Multi-cascade: VLM-direct → pattern → hybrid → stub
│   │   ├── plfs_style_engine.py    # PLFS narrative style: format_value, select_pattern
│   │   └── patterns/
│   │       ├── plfs_glossary.json  # 50+ abbreviations (LFPR, WPR, UR, CWS, UPSS...)
│   │       ├── plfs_style_rules.json # Sentence patterns, precision rules, hedging
│   │       └── mospi_patterns.json  # MoSPI publication-specific patterns
│   │
│   ├── config/                      # Domain-specific configuration files
│   │   └── domain_tolerance.json   # Per-domain verifier tolerance overrides
│   │
│   ├── generation/                  # Grammar-constrained generation
│   │   ├── sglang_client.py        # SGLangClient: 3-call decomposed generation
│   │   └── ast_assembler.py        # Assembles partial outputs into TemplateAST
│   │
│   ├── binder/                      # Template → dataset binding
│   │   ├── template_binder.py      # TemplateBinder: full binding workflow
│   │   └── column_resolver.py      # 5-stage cascade resolver (exact→alias→fuzzy→KG)
│   │
│   ├── render/                      # Report output rendering
│   │   ├── latex_renderer.py       # Jinja2 → .tex → lualatex → PDF
│   │   └── citation_manager.py     # Inline [n] citations + appendix generation
│   │
│   ├── review/                      # Template quality review
│   │   └── reviewer.py             # TemplateReviewer: min thresholds + quality checks
│   │
│   ├── llm/                         # Multi-provider LLM routing
│   │   └── router.py               # LLMRouter: per-role provider + rate limiting
│   │
│   ├── storage/                     # Persistence layer
│   │   ├── checkpoint.py           # FileCheckpoint + DBCheckpoint + get_checkpoint_backend()
│   │   ├── template_cache.py       # TemplateCache: L1 hash + L2 structural (3x speedup)
│   │   ├── ltm_store.py            # LTMStore: Qdrant (corrections, styles, bindings)
│   │   └── template_repository.py  # DB CRUD for TemplateAST entities
│   │
│   └── observability/               # Distributed tracing
│       ├── tracing.py              # OTel + Arize Phoenix + Langfuse init/spans
│       └── llm_tracing.py          # llm_span(): per-call token + latency spans
│
├── agents/                          ◀ AI AGENT PIPELINE
│   ├── planner_agent.py            # PlannerAgent: selects analytics approach per topic
│   ├── scribe_agent.py             # ScribeAgent: narrative generation + LTM integration
│   ├── verifier_agent.py           # VerifierAgent: numeric claim verification ±tolerance
│   ├── consensus_engine.py         # ConsensusEngine: ROUNDING/HALLUCINATION/STALE/LOGIC repair
│   ├── analytics_agent.py          # AnalyticsAgent: statistical computations
│   ├── retrieval_agent.py          # RetrievalAgent: fact lookup from dataset
│   └── deep_agent.py               # DeepAgent: deep BI reasoning chain
│
├── report_builder/                  ◀ REPORT ORCHESTRATION
│   ├── orchestrator.py             # ReportOrchestrator: parallel topic pipeline
│   ├── blueprint.py                # Blueprint schema for report structure
│   ├── pipeline.py                 # Pipeline runner (Planner→Scribe→Verify→Repair)
│   ├── kernel.py                   # Execution kernel
│   ├── memory.py                   # Working memory for in-progress reports
│   ├── knowledge_graph.py          # Local KG for entity relationships
│   ├── exporter.py                 # Export to various formats
│   ├── filter_engine.py            # Data filtering before generation
│   ├── firewall.py                 # Safety/content guardrails
│   └── agui.py                     # AG-UI protocol adapter
│
├── api/                             ◀ FASTAPI BACKEND
│   ├── main.py                     # App factory: all routers registered here
│   ├── deps.py                     # FastAPI dependency injection
│   └── report_builder_api/
│       ├── routes.py               # /generate /jobs /download /preview
│       ├── progress_sse.py         # SSE streaming: ProgressBus pub/sub
│       ├── entity_binding_api.py   # Binding CRUD: /resolve /override /accept /reject
│       ├── schemas.py              # Pydantic request/response models
│       ├── template_validation.py  # Template pre-flight validation
│       ├── delivery.py             # Email/webhook delivery adapter
│       └── access.py               # Job ownership access control
│
├── dashboard/                       ◀ NEXT.JS FRONTEND
│   ├── app/
│   │   └── report-builder/         # Report builder pages
│   └── components/
│       └── report-builder/
│           ├── ReportProgressStream.tsx  # SSE client → real-time progress bar
│           ├── EntityBindingPanel.tsx    # Binding table + approve/reject UI
│           ├── WizardStepper.tsx        # Multi-step wizard
│           ├── DeliveryPanel.tsx        # Delivery channel config
│           └── BlockMappingTable.tsx    # Block layout mapping
│
├── tests/
│   └── test_template_engine/        ◀ TEST SUITE (324+ tests)
│       ├── test_phase3.py           # Binder, resolver, orchestrator, LaTeX, citations (34)
│       ├── test_phase4_5.py         # LLM tracing, LTM, PLFS style, SSE, binding (40)
│       ├── test_phase6_integration.py # Integration + benchmarks (17)
│       ├── test_extraction.py       # Entity extraction unit tests
│       ├── test_inference.py        # Question inference tests
│       ├── test_observability.py    # Tracing backend tests
│       ├── test_plfs.py             # PLFS parser + glossary tests
│       ├── test_schema.py           # TemplateAST schema validation
│       ├── test_vlm_clients.py      # VLM client contract tests
│       ├── test_pipeline_e2e.py     # Full pipeline e2e tests
│       └── ...                      # 6 more test modules
│
└── docs/                            ◀ SUPPLEMENTARY DOCS
    └── images/                      # Architecture diagrams
```

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           COMPONENT DEPENDENCIES                              │
│                                                                               │
│   template_engine/config.py  ◀────── ALL modules import PipelineConfig       │
│          │                                                                    │
│    ┌─────┴──────┬─────────┬─────────┬─────────┬────────┐                    │
│    │            │         │         │         │        │                     │
│   vlm/      ingestion/ extraction/ binder/  render/  llm/                   │
│    │            │         │         │         │        │                     │
│    └─────┬──────┴─────────┘         │         │        │                     │
│          │  pipeline.py             │         │        │                     │
│          │  (ExtractionResult)      │         │        │                     │
│          ▼                          ▼         │        │                     │
│      inference/            storage/           │        │                     │
│      question_inferrer    checkpoint          │        │                     │
│      plfs_style_engine    template_cache      │        │                     │
│                           ltm_store           │        │                     │
│                                │              │        │                     │
│                                └──────────────┘        │                     │
│                                                         │                    │
│   agents/  ◀──────────────────────────────────────────-┘                    │
│   scribe → verifier → consensus_engine                                       │
│                                                                               │
│   report_builder/orchestrator  ◀──── agents/ + binder/ + render/            │
│          │                                                                    │
│   api/report_builder_api  ◀───────── orchestrator + storage + SSE            │
│          │                                                                    │
│   dashboard/ ◀────────────────────── api/ (SSE + REST)                       │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start — Real-Time Setup

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Tested on 3.13 |
| PostgreSQL | 14+ | SQLite works for dev |
| Redis | 7+ | Optional — distributed cache |
| LuaLaTeX | any | `texlive-luatex` — for PDF output |
| Pandoc | 3+ | For HTML preview |
| NVIDIA GPU | 6GB+ VRAM | Optional — ColPali + SGLang |
| Node.js | 18+ | Dashboard |

### Step 1 — Clone and Install

```bash
git clone <repo> && cd statathon
git checkout feature/rev-template

# Python env
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
# Windows (specific wheels):
pip install -r requirements-windows.txt
```

### Step 2 — Configure Environment

```bash
cp .env.example .env
# Open .env and set the values below
```

### Step 3 — Minimum Viable Config (No GPU)

```bash
# .env — paste these to get started immediately
DATABASE_URL=sqlite:///./statathon.db
DEFAULT_LLM_PROVIDER=gemini
DEFAULT_LLM_API_KEY=your-gemini-api-key
DEFAULT_LLM_MODEL=gemini-2.0-flash

# Keep these OFF for first run
CHECKPOINT_ENABLED=false
TRACING_ENABLED=0
# Leave QDRANT_URL empty to disable LTM
QDRANT_URL=
```

### Step 4 — Start Services

```bash
# Terminal 1 — API (hot reload)
cd api
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Dashboard
cd dashboard
npm install
npm run dev
# Open http://localhost:3000
```

### Step 5 — Verify API is Alive

```bash
curl http://localhost:8000/health
# {"status": "ok", "version": "..."}
```

### Step 6 — Generate Your First Report

```bash
# Upload a PLFS PDF → extract template
curl -X POST http://localhost:8000/report-builder/templates/upload \
  -F "file=@your-plfs-report.pdf" \
  -F "name=PLFS-2024-Q1"

# Trigger report generation
curl -X POST http://localhost:8000/report-builder/generate \
  -H "Content-Type: application/json" \
  -d '{"analysis_id": 1}'
# Returns: {"job_id": "abc123", "status": "queued"}

# Stream real-time progress
curl -N http://localhost:8000/report-builder/jobs/abc123/progress/stream

# Download PDF
curl -o report.pdf http://localhost:8000/report-builder/jobs/abc123/download
```

---

## Full Configuration Reference

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./statathon.db` | SQLAlchemy connection string |

```bash
# Development
DATABASE_URL=sqlite:///./statathon.db

# Production
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/statathon
```

---

### LLM Provider — Per-Role Routing

Each agent role can use a different provider. If a role-specific key is absent, `DEFAULT_*` is used.

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_LLM_PROVIDER` | `gemini` | Fallback for all roles |
| `DEFAULT_LLM_API_KEY` | — | API key for default provider |
| `DEFAULT_LLM_MODEL` | `gemini-2.0-flash` | Default model |
| `SCRIBE_PROVIDER` | (default) | Narrative generation |
| `SCRIBE_API_KEY` | (default) | Scribe API key |
| `SCRIBE_MODEL` | (default) | Scribe model |
| `VERIFIER_PROVIDER` | (default) | Claim verification |
| `VERIFIER_MODEL` | (default) | Verifier model |
| `PLANNER_PROVIDER` | (default) | Analytics planning |
| `PLANNER_MODEL` | (default) | Planner model |
| `INFERRER_PROVIDER` | (default) | Question inference |
| `INFERRER_MODEL` | (default) | Inferrer model |
| `ENRICHER_PROVIDER` | (default) | Enrichment pass |
| `GROQ_RPM` | `30` | Groq rate limit (req/min) |
| `GEMINI_RPM` | `60` | Gemini rate limit |
| `OPENAI_RPM` | `60` | OpenAI rate limit |

**Recommended production split:**
```bash
SCRIBE_PROVIDER=gemini
SCRIBE_MODEL=gemini-2.0-flash        # Best prose, long-context

VERIFIER_PROVIDER=groq
VERIFIER_MODEL=llama-3.1-8b-instant  # Fastest verification (<100ms)

PLANNER_PROVIDER=groq
PLANNER_MODEL=llama-3.1-8b-instant   # Fast planning decisions

INFERRER_PROVIDER=gemini
INFERRER_MODEL=gemini-2.5-flash      # Best extraction accuracy
```

---

### VLM / ColPali

| Variable | Default | Description |
|----------|---------|-------------|
| `VLM_BACKEND` | `` (auto) | Force backend: `colpali`, `pdfplumber`, `mock` |
| `COLPALI_ENDPOINT` | `http://localhost:8080` | ColPali microservice URL |
| `VLM_PAGE_TIMEOUT` | `60.0` | Seconds per page |
| `VLM_MAX_RETRIES` | `2` | Retries on parse failure |

**Auto-detection order:** ColPali endpoint reachable → pdfplumber → mock (tests).

---

### SGLang (Local LLM)

| Variable | Default | Description |
|----------|---------|-------------|
| `SGLANG_BACKEND` | `` (auto) | Force: `sglang`, `cloud` |
| `SGLANG_ENDPOINT` | `http://localhost:30000` | SGLang server URL |
| `SGLANG_MODEL` | `default` | Model name |
| `SGLANG_TIMEOUT` | `300.0` | Generation timeout (s) |
| `SGLANG_MAX_TOKENS` | `8192` | Max output tokens |
| `SGLANG_TEMPERATURE` | `0.1` | Generation temperature |
| `SGLANG_DECOMPOSED` | `true` | 3-call decomposed generation |

When `SGLANG_ENDPOINT` is unreachable, the system **automatically falls back** to cloud LLMs — no config change needed.

---

### Checkpointing

| Variable | Default | Description |
|----------|---------|-------------|
| `CHECKPOINT_ENABLED` | `false` | Master toggle |
| `CHECKPOINT_BACKEND` | `auto` | `auto` · `file` · `db` |
| `CHECKPOINT_DIR` | `./checkpoints` | File backend directory |

**Toggle impact:**

| Setting | Behaviour | Recommended for |
|---------|-----------|----------------|
| `false` | No caching — always fresh | **Development, CI, debugging** |
| `true` + `auto` | File if no DB, else Postgres | Single-server staging |
| `true` + `file` | JSON files in CHECKPOINT_DIR | Any single-process deploy |
| `true` + `db` | PostgreSQL — survives restarts | **Multi-worker production** |

> ⚠️ **Warning:** Never enable checkpoints in development. Stale checkpoints will serve old data after code changes and produce confusing test failures.

---

### Observability (3 Independent Layers)

| Variable | Default | Layer | Description |
|----------|---------|-------|-------------|
| `TRACING_ENABLED` | `0` | All | Kill switch — `0` disables everything |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | Layer 1 | OpenTelemetry collector (Jaeger/Grafana) |
| `OTEL_SERVICE_NAME` | `template-engine` | Layer 1 | Service name in traces |
| `PHOENIX_COLLECTOR_ENDPOINT` | — | Layer 2 | Arize Phoenix LLM analysis UI |
| `LANGFUSE_PUBLIC_KEY` | — | Layer 3 | Langfuse prompt/cost tracking |
| `LANGFUSE_SECRET_KEY` | — | Layer 3 | Langfuse secret |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Layer 3 | Self-hosted Langfuse |

**Impact per configuration:**

| Config | Overhead | What you see |
|--------|----------|-------------|
| All disabled | **0ms** | Nothing — use for dev/CI |
| OTel only | ~2ms/span | Span traces in Jaeger/Grafana |
| Langfuse only | ~5ms/call | Cost per call, prompt versions, latency |
| Phoenix only | ~3ms/call | Embedding drift, hallucination detection |
| All three | ~10ms/call | Full production observability stack |

**Environment setups:**
```bash
# Development — zero overhead
TRACING_ENABLED=0

# Staging — cost tracking only
TRACING_ENABLED=1
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...

# Production — full stack
TRACING_ENABLED=1
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
PHOENIX_COLLECTOR_ENDPOINT=http://phoenix:6006
```

---

### Long-Term Memory (LTM)

LTM lets the system **learn from corrections** — narratives improve over time.

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_URL` | — | Qdrant Cloud / self-hosted endpoint |
| `QDRANT_API_KEY` | — | Qdrant API key |
| `LTM_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |

**Toggle impact:**

| Setting | Scribe behaviour | Improvement over time |
|---------|-----------------|----------------------|
| `QDRANT_URL` empty | Rules-only generation | No — static |
| `QDRANT_URL` set | Queries 3 collections before writing | Yes — learns corrections, styles, bindings |

**What is stored (3 Qdrant collections):**

| Collection | Content | Used by |
|------------|---------|---------|
| `plfs_corrections` | Original → corrected narrative pairs | ScribeAgent (inject corrections as reflections) |
| `plfs_styles` | Proven sentence patterns from accepted reports | ScribeAgent (style hints) |
| `entity_bindings` | Historical entity→column binding decisions | ColumnResolver (cold-start acceleration) |

**Free tier setup (Qdrant Cloud — 1GB free):**
```bash
QDRANT_URL=https://your-cluster.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=your-api-key
LTM_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

---

### Entity & Inference Thresholds

| Variable | Default | Description |
|----------|---------|-------------|
| `ENTITY_SIMILARITY_THRESHOLD` | `0.85` | Fuzzy dedup threshold |
| `ENTITY_MIN_LENGTH` | `2` | Min entity name chars |
| `ENTITY_MAX_LENGTH` | `80` | Max entity name chars |
| `ENTITY_CONFIDENCE_BOOST` | `0.05` | Confidence boost per corroborating source |
| `ENTITY_MAX_BOOST` | `0.15` | Cap on confidence boost |
| `INFERENCE_CONFIDENCE_THRESHOLD` | `0.30` | Min to accept any question |
| `INFERENCE_VLM_MIN_CONF` | `0.85` | VLM-direct cascade minimum |
| `INFERENCE_PATTERN_MIN_CONF` | `0.65` | Pattern cascade minimum |
| `INFERENCE_HYBRID_MIN_CONF` | `0.60` | Hybrid cascade minimum |
| `VERIFIER_DEFAULT_TOLERANCE` | `0.05` | ±5% claim tolerance |
| `VERIFIER_DOMAIN_TOLERANCE_PATH` | — | JSON file for domain overrides |

---

### Report Generation & Rendering

| Variable | Default | Description |
|----------|---------|-------------|
| `LATEX_ENGINE` | `lualatex` | Compiler: `lualatex` · `xelatex` · `pdflatex` |
| `PANDOC_PATH` | `pandoc` | Path to Pandoc binary |
| `OUTPUT_DIR` | `./outputs` | Generated report directory |
| `MAX_PARALLEL_TOPICS` | `4` | Async topic parallelism |

**Engine comparison:**

| Engine | Speed | Unicode | Indian scripts | Recommendation |
|--------|-------|---------|---------------|----------------|
| `lualatex` | Slow (2-pass) | ✅ Full | ✅ Yes | **Use for all PLFS reports** |
| `xelatex` | Medium | ✅ Full | ✅ Yes | Alternative |
| `pdflatex` | Fast | ❌ Limited | ❌ No | English-only, draft mode |

---

## Feature Toggles & Impact Matrix

| Toggle | OFF Behaviour | ON Behaviour | Default | Flip for Production |
|--------|--------------|--------------|---------|---------------------|
| `CHECKPOINT_ENABLED` | Fresh extraction every time (~5 min) | Resume in ~30 sec | `false` | `true` |
| `TRACING_ENABLED` | Zero overhead | +2–10ms/span, full trace | `0` | `1` |
| `QDRANT_URL` (LTM) | Static narratives | Learning + improving output | empty | Set Qdrant URL |
| `COLPALI_ENDPOINT` | pdfplumber fallback | GPU-accelerated visual parsing | localhost | Set GPU host |
| `SGLANG_ENDPOINT` | Cloud LLM fallback | Local 3B model — no API cost | localhost | Set GPU host |
| `VLM_BACKEND=mock` | Always fixture data | N/A | auto | Never in prod |
| `SGLANG_DECOMPOSED` | Single-call generation | 3-call decomposed (more stable) | `true` | Keep `true` |

### Performance Profile by Config

| Profile | DATABASE_URL | LLM | GPU | Cache | Extraction | Generation | $/report |
|---------|-------------|-----|-----|-------|-----------|-----------|---------|
| Dev | SQLite | Gemini only | ❌ | OFF | ~5 min | ~2 min | ~$0.05 |
| Staging | Postgres | Groq + Gemini | ❌ | ON | ~2 min | ~1 min | ~$0.03 |
| Production | Postgres | Groq + Gemini | ✅ | ON | ~30 sec | ~45 sec | ~$0.01 |
| Offline | SQLite | SGLang local | ✅ | ON | ~3 min | ~3 min | $0.00 |

---

## Module Reference

### `template_engine/config.py` — All Thresholds

`PipelineConfig.from_env()` loads every variable from environment at startup. Sub-configs:

| Dataclass | Purpose |
|-----------|---------|
| `VLMConfig` | ColPali endpoint, timeouts, retries |
| `SGLangConfig` | Local LLM endpoint, decomposed mode |
| `EntityConfig` | Dedup thresholds, confidence boosts |
| `InferenceConfig` | Cascade confidence levels |
| `ReviewConfig` | Min topic/question/entity counts |
| `VerifierConfig` | Tolerance cascade (domain → entity-type) |
| `CheckpointConfig` | Backend selection, directory |
| `PipelineConfig` | Aggregates all above |

```python
from template_engine.config import PipelineConfig
cfg = PipelineConfig.from_env()
print(cfg.verifier.get_tolerance("labour", "percentage"))  # e.g. 0.02
```

### `template_engine/llm/router.py` — LLM Router

```python
from template_engine.llm import get_llm_router
router = get_llm_router()
response = await router.complete(role="scribe", prompt="Write about LFPR trends...")
```

Roles: `scribe`, `verifier`, `planner`, `inferrer`, `enricher`  
Providers: `gemini`, `groq`, `openai`, `sglang`

### `template_engine/binder/column_resolver.py` — 5-Stage Cascade

```python
from template_engine.binder import ColumnResolver
resolver = ColumnResolver()
result = resolver.resolve(entity, schema)
# result.confidence ≥ 0.90 → auto-accept
# result.confidence 0.60–0.89 → pending UI review
# result.confidence < 0.60 → unresolved, manual selection
```

### `template_engine/storage/ltm_store.py` — Long-Term Memory

```python
from template_engine.storage import get_ltm_store
store = get_ltm_store()

# Check availability
print(store.is_available)   # False if QDRANT_URL not set

# Store a correction
await store.store_correction(original="...", corrected="...", context={})

# Query before generating
corrections = await store.query_corrections(query_text, limit=5)
```

### `agents/scribe_agent.py` — Learning Scribe

```python
from agents.scribe_agent import ScribeAgent
scribe = ScribeAgent()
narrative = await scribe.generate(block_section="LFPR", facts={...})

# Feed correction back for learning
await scribe.store_correction(original=narrative, corrected="...", context={})
```

### `api/report_builder_api/progress_sse.py` — SSE Bus

```python
from api.report_builder_api.progress_sse import ProgressBus, ProgressEvent
bus = ProgressBus()

# Publisher side (inside _run_job)
await bus.publish(job_id, ProgressEvent(stage="binding", pct=20, message="Resolving..."))

# Subscriber side (SSE endpoint)
async for event in bus.subscribe(job_id):
    yield event.to_sse()
```

---

## API Reference

### Report Generation

| Method | Path | Body / Params | Description |
|--------|------|---------------|-------------|
| `POST` | `/report-builder/generate` | `{"analysis_id": N}` | Queue report generation |
| `GET` | `/report-builder/jobs` | `?analysis_id=N` | List jobs |
| `GET` | `/report-builder/jobs/{id}` | — | Job status + metadata |
| `GET` | `/report-builder/jobs/{id}/canvas` | — | Full BlockCanvas JSON |
| `GET` | `/report-builder/jobs/{id}/preview` | — | HTML preview (no install needed) |
| `GET` | `/report-builder/jobs/{id}/download` | — | PDF binary |

### Progress Streaming (SSE)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/report-builder/jobs/{id}/progress/stream` | EventSource stream |
| `GET` | `/report-builder/jobs/{id}/progress` | Latest snapshot (REST) |

**SSE event schema:**
```
event: progress
data: {"stage": "binding", "pct": 25, "message": "Resolving entity columns..."}

event: progress
data: {"stage": "generating", "pct": 60, "message": "Writing section 3/5..."}

event: complete
data: {"stage": "done", "pct": 100, "message": "Report ready"}

event: error
data: {"stage": "error", "pct": -1, "message": "Verification failed: claim not found"}
```

**Stages in order:** `init(5%)` → `binding(20%)` → `planning(35%)` → `generating(60%)` → `verifying(80%)` → `rendering(90%)` → `done(100%)`

### Entity Binding

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/report-builder/bindings/{job_id}` | All bindings + confidence scores |
| `POST` | `/report-builder/bindings/{job_id}/resolve` | Auto-resolve all pending |
| `PUT` | `/report-builder/bindings/{job_id}/{entity_id}` | Manual override |
| `POST` | `/report-builder/bindings/{job_id}/accept` | Batch accept pending |
| `POST` | `/report-builder/bindings/{job_id}/reject` | Batch reject |

**Confidence colours (Dashboard):** 🟢 ≥90% auto-accepted · 🟡 60–89% pending review · 🔴 <60% unresolved

### Template Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/report-builder/templates/upload` | Upload PDF → extract template |
| `GET` | `/report-builder/templates` | List all templates |
| `GET` | `/report-builder/templates/{id}` | Full TemplateAST JSON |
| `DELETE` | `/report-builder/templates/{id}` | Remove template |

---

## GPU & Docker Setup

### 6GB VRAM Sequential Sharing

ColPali (4–5GB) and SGLang (3–4GB) cannot coexist. The GPU Compose uses sequential containers:

```
Step 1 → colpali container up  → extract all pages → stop (VRAM freed)
Step 2 → sglang container up   → generate AST      → stop (VRAM freed)
Step 3 → API uses cloud LLMs for generation         (no GPU needed)
```

### Commands

```bash
# Full automated pipeline (sequential)
docker compose -f docker-compose.gpu.yml --profile gpu run --rm pipeline

# Manual step-by-step (debugging)
docker compose -f docker-compose.gpu.yml --profile gpu up colpali
# wait for extraction to finish...
docker compose -f docker-compose.gpu.yml --profile gpu stop colpali
docker compose -f docker-compose.gpu.yml --profile gpu up sglang
# wait for generation...
docker compose -f docker-compose.gpu.yml --profile gpu stop sglang

# API + Dashboard only (no GPU)
docker compose up api dashboard neo4j redis
```

### Non-GPU Fallback

```bash
# Leave both empty → automatic fallback
COLPALI_ENDPOINT=          # → uses pdfplumber
SGLANG_ENDPOINT=           # → uses cloud LLMs
DEFAULT_LLM_PROVIDER=gemini
DEFAULT_LLM_API_KEY=your-key
```

---

## Testing

### Test Suite

| File | Coverage | Tests | Runtime |
|------|----------|-------|---------|
| `test_extraction.py` | Entity extraction | ~30 | ~5s |
| `test_inference.py` | Question inference | ~25 | ~5s |
| `test_observability.py` | Tracing backends | ~20 | ~3s |
| `test_plfs.py` | PLFS parser + glossary | ~30 | ~5s |
| `test_schema.py` | TemplateAST schema | ~20 | ~3s |
| `test_vlm_clients.py` | VLM contracts | ~25 | ~5s |
| `test_pipeline_e2e.py` | End-to-end pipeline | ~20 | ~30s |
| `test_phase3.py` | Binder, resolver, LaTeX, citations | **34** | ~13s |
| `test_phase4_5.py` | LLM tracing, LTM, PLFS style, SSE, binding | **40** | ~22s |
| `test_phase6_integration.py` | Integration + benchmarks | **17** | ~17s |
| **Total** | All phases | **324+** | ~17 min |

### Running Tests

```bash
# Fast check — new phases only (~50s)
cd statathon
& "C:\dev\src\cne-platform-venv\Scripts\python.exe" -m pytest \
  tests/test_template_engine/test_phase3.py \
  tests/test_template_engine/test_phase4_5.py \
  tests/test_template_engine/test_phase6_integration.py -q

# Full suite (~17 min, excludes live/GPU tests)
& "C:\dev\src\cne-platform-venv\Scripts\python.exe" -m pytest \
  tests/test_template_engine/ -m "not live" -q

# With coverage
& "C:\dev\src\cne-platform-venv\Scripts\python.exe" -m pytest \
  tests/test_template_engine/ -m "not live" \
  --cov=template_engine --cov=agents --cov-report=term-missing

# Single test class
& "C:\dev\src\cne-platform-venv\Scripts\python.exe" -m pytest \
  tests/test_template_engine/test_phase4_5.py::TestLTMStore -v
```

### Test Markers

| Marker | Meaning |
|--------|---------|
| `not live` | Exclude tests requiring real APIs/GPU (use in CI) |
| `benchmark` | Performance benchmarks — run separately |

### CI Pipeline

`.github/workflows/template-engine-ci.yml` runs on push to `main` or `feature/rev-template`:

1. **Matrix:** Python 3.11, 3.12, 3.13
2. **Tests:** `pytest tests/test_template_engine/ -m "not live"` with coverage
3. **Gate:** Coverage ≥ 70% required
4. **Lint:** `ruff check template_engine/ agents/`

---

## Troubleshooting

### Common Issues

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| Tests fail with "stale value" | Checkpoint enabled in dev | `CHECKPOINT_ENABLED=false` |
| `ModuleNotFoundError: qdrant_client` | Optional dep missing | `pip install qdrant-client` or leave `QDRANT_URL` empty |
| LaTeX build fails | lualatex not installed | `apt install texlive-luatex` or set `LATEX_ENGINE=pdflatex` (English only) |
| SSE connection drops after ~30s | Reverse proxy buffering | Add `X-Accel-Buffering: no` header in nginx |
| All bindings show "unresolved" | No column names passed | POST `{"column_names": [...]}` to `/resolve` or set `dataset_id` |
| LLM rate limited | RPM exceeded | Increase `{PROVIDER}_RPM` or add a second provider with `VERIFIER_PROVIDER=groq` |
| Consensus stuck looping | Max retries too high for low-priority | Priority-based retry (`_PRIORITY_RETRY_MAP`) handles this automatically |
| PDF extraction blank | VLM_BACKEND=colpali but no service | Set `VLM_BACKEND=pdfplumber` or start ColPali with Docker |
| Dashboard SSE not connecting | CORS or wrong port | Ensure `NEXT_PUBLIC_API_URL=http://localhost:8000` in dashboard `.env.local` |

### Debug Snippets

```bash
# Check which LLM provider will be used for each role
python -c "
from template_engine.llm import get_llm_router
r = get_llm_router()
for role in ['scribe','verifier','planner','inferrer']:
    print(role, '->', r.get_provider(role))
"

# Check LTM connectivity
python -c "
from template_engine.storage import get_ltm_store
store = get_ltm_store()
print('LTM available:', store.is_available)
"

# Check checkpoint config
python -c "
from template_engine.config import PipelineConfig
c = PipelineConfig.from_env()
print('Checkpoint enabled:', c.checkpoint.enabled)
print('Backend:', c.checkpoint.backend)
print('Dir:', c.checkpoint.file_dir)
"

# Trace a single LLM call
python -c "
import asyncio
from template_engine.observability.llm_tracing import llm_span
with llm_span('test', model='gemini-2.0-flash') as r:
    r.output = 'hello world'
print(f'Latency: {r.latency_ms:.1f}ms, Tokens: {r.total_tokens}')
"
```


---

## Table of Contents

1. [Complete Build Overview](#complete-build-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Quick Start (Real-Time Setup)](#quick-start-real-time-setup)
4. [Full Configuration Reference](#full-configuration-reference)
5. [Feature Toggles & Impact Matrix](#feature-toggles--impact-matrix)
6. [Module Reference](#module-reference)
7. [API Reference](#api-reference)
8. [GPU & Docker Setup](#gpu--docker-setup)
9. [Testing](#testing)
10. [Troubleshooting](#troubleshooting)

---

## Complete Build Overview

The Template Engine is a **46-step, 7-phase** system that transforms legacy PDF reports (primarily MoSPI/PLFS quarterly publications) into reusable analytical templates, then generates new reports by binding those templates to live datasets.

### What It Does

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TEMPLATE ENGINE PIPELINE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  INPUT                    EXTRACTION                GENERATION              │
│  ─────                    ──────────                ──────────              │
│  Legacy PDF ──→ VLM Parse ──→ Entity Extract ──→ Question Infer            │
│                     │              │                    │                    │
│                     ▼              ▼                    ▼                    │
│              Page Regions    TemplateEntity[]     QuestionNode[]            │
│              + Tables        + Dedup + Scope      + Priority Tag            │
│                                                        │                    │
│  BINDING                    REPORT GEN                 │                    │
│  ───────                    ──────────                 │                    │
│  Dataset + Template ──→ Column Resolve ──→ Orchestrator                    │
│                              │                    │                         │
│                              ▼                    ▼                         │
│                         BindingResult      Agent Pipeline                   │
│                         (auto >0.90)       (Planner→Scribe→Verifier)       │
│                              │                    │                         │
│                              ▼                    ▼                         │
│                         UI Approval         Consensus + Citations           │
│                                                   │                         │
│  OUTPUT                                           │                         │
│  ──────                                           ▼                         │
│                                          LaTeX ──→ PDF                      │
│                                          Pandoc ──→ HTML Preview            │
│                                          SSE ──→ Real-time Progress         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Phase Breakdown

| Phase | Steps | Purpose | Key Deliverables |
|-------|-------|---------|-----------------|
| **1** | 1–8 | Foundation Hardening | PipelineConfig, CheckpointBackend, LLM Router, Domain Tolerances, Entity Dedup, Error Recovery, SGLang Decomposition, Soft Constraints |
| **2** | 9–16 | PLFS Specialization | PLFS Glossary, Statement Parser, Hierarchical Tables, Camelot Integration, Table Merger, ColPali Fine-tune, VLM-Direct Inferrer, Synthetic Tests |
| **3** | 17–24 | Report Generation | Template Binder, Column Resolver, Report Orchestrator, LaTeX Renderer, Consensus Repair, Citation Manager, Priority Extraction, Template Cache |
| **4** | 25–29 | Observability & LTM | 3-Layer Tracing, Qdrant LTM, Scribe Learning, PLFS Style Rules, Adaptive Retry |
| **5** | 30–35 | Dashboard & API | SSE Progress, Entity Binding API, Progress Component, Binding UI, Generate Trigger, Preview/Download |
| **6** | 36–40 | Testing & Quality | PLFS Integration, Report Gen Tests, LLM Provider Tests, Checkpoint Tests, Benchmark Suite |
| **7** | 41–46 | Deployment | GPU Docker Compose, .env.example, Documentation, CI Pipeline, Requirements, E2E |

### Data Flow: End-to-End

```
1. Officer uploads legacy PLFS PDF via Dashboard
2. VLM (ColPali) extracts page regions, tables, headings
3. PLFS Parser identifies "Statement N.M" patterns → entities
4. Question Inferrer builds QuestionNode[] with priority tags
5. Template stored in DB (reusable for quarterly reports)
6. Officer selects template + dataset → Generate
7. Column Resolver maps entities to dataset columns (auto + manual)
8. Orchestrator parallelizes per-topic:
   a. PlannerAgent selects analytics approach
   b. ScribeAgent generates grounded narratives (consults LTM)
   c. VerifierAgent checks all numeric claims
   d. ConsensusEngine repairs failures (classified: ROUNDING/HALLUCINATION/STALE/LOGIC)
   e. CitationManager adds evidence markers
9. LaTeX Renderer produces .tex → lualatex → PDF
10. SSE streams real-time progress to Dashboard
11. Officer reviews, corrects → corrections feed back to LTM
```

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                            TEMPLATE ENGINE                            │
├──────────────┬──────────────┬──────────────┬─────────────────────────┤
│  config/     │  extraction/ │  inference/  │  binder/                │
│  config.py   │  plfs_parser │  question_   │  template_binder.py     │
│  (all env    │  table_      │  inferrer.py │  column_resolver.py     │
│   toggles)   │  merger.py   │  plfs_style_ │  (5-stage cascade)      │
│              │  entity_     │  engine.py   │                         │
│              │  dedup.py    │  patterns/   │                         │
├──────────────┼──────────────┼──────────────┼─────────────────────────┤
│  render/     │  storage/    │  observ/     │  llm/                   │
│  latex_      │  checkpoint  │  tracing.py  │  router.py              │
│  renderer.py │  template_   │  llm_        │  providers.py           │
│  citation_   │  cache.py    │  tracing.py  │  (per-role routing)     │
│  manager.py  │  ltm_store   │              │                         │
├──────────────┼──────────────┼──────────────┼─────────────────────────┤
│  agents/                    │  api/                                   │
│  scribe_agent.py            │  progress_sse.py (SSE streaming)       │
│  verifier_agent.py          │  entity_binding_api.py (CRUD)          │
│  consensus_engine.py        │  routes.py (generate/download/preview) │
│  planner_agent.py           │                                        │
└─────────────────────────────┴────────────────────────────────────────┘
```

---

## Quick Start (Real-Time Setup)

### Prerequisites

- Python 3.11+ (tested on 3.13)
- PostgreSQL (or SQLite for dev)
- Redis (optional, for caching)
- LuaLaTeX + Pandoc (for PDF/HTML output)
- GPU with 6GB+ VRAM (optional, for ColPali/SGLang)

### Step 1: Clone and Install

```bash
git clone <repo> && cd statathon
git checkout feature/rev-template
python -m venv .venv && source .venv/bin/activate  # or Windows equivalent
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
cp .env.example .env
# Edit .env with your values (see Configuration Reference below)
```

### Step 3: Minimal Working Setup (No GPU, No Observability)

```bash
# .env — minimum viable config
DATABASE_URL=sqlite:///./statathon.db
DEFAULT_LLM_PROVIDER=gemini
DEFAULT_LLM_API_KEY=your-gemini-api-key
DEFAULT_LLM_MODEL=gemini-2.0-flash
CHECKPOINT_ENABLED=false
TRACING_ENABLED=0
```

### Step 4: Start API + Dashboard

```bash
# Terminal 1: API
cd api && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Dashboard
cd dashboard && npm install && npm run dev
```

### Step 5: Generate a Report

```bash
# Via API (or use Dashboard UI)
curl -X POST http://localhost:8000/report-builder/generate \
  -H "Content-Type: application/json" \
  -d '{"analysis_id": 1}'
```

---

## Full Configuration Reference

### LLM Provider Configuration

The system supports **per-role LLM routing** — each agent can use a different provider/model.

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_LLM_PROVIDER` | `gemini` | Fallback provider for all roles |
| `DEFAULT_LLM_API_KEY` | — | API key for default provider |
| `DEFAULT_LLM_MODEL` | `gemini-2.0-flash` | Default model |
| `SCRIBE_PROVIDER` | (fallback) | Provider for narrative generation |
| `SCRIBE_API_KEY` | (fallback) | API key for Scribe |
| `SCRIBE_MODEL` | (fallback) | Model for Scribe |
| `VERIFIER_PROVIDER` | (fallback) | Provider for claim verification |
| `INFERRER_PROVIDER` | (fallback) | Provider for question inference |
| `PLANNER_PROVIDER` | (fallback) | Provider for analytics planning |
| `ENRICHER_PROVIDER` | (fallback) | Provider for enrichment |
| `GROQ_RPM` | `30` | Groq rate limit (req/min) |
| `GEMINI_RPM` | `60` | Gemini rate limit |
| `OPENAI_RPM` | `60` | OpenAI rate limit |

**Impact of changing:** Switching providers affects latency, cost, and quality. Gemini is fastest for long-form generation. Groq is fastest for short verification. OpenAI is most accurate for complex reasoning.

**Recommended production config:**
```bash
SCRIBE_PROVIDER=gemini          # Best prose quality
SCRIBE_MODEL=gemini-2.0-flash
VERIFIER_PROVIDER=groq          # Fastest verification
VERIFIER_MODEL=llama-3.1-8b-instant
PLANNER_PROVIDER=groq           # Fast planning
PLANNER_MODEL=llama-3.1-8b-instant
INFERRER_PROVIDER=gemini        # Best extraction
INFERRER_MODEL=gemini-2.5-flash
```

---

### Checkpointing Configuration

Checkpoints allow resuming failed extractions without re-processing.

| Variable | Default | Description |
|----------|---------|-------------|
| `CHECKPOINT_ENABLED` | `false` | Master toggle for checkpointing |
| `CHECKPOINT_DIR` | `./checkpoints` | Directory for file-based checkpoints |
| `CHECKPOINT_BACKEND` | `file` | Backend type: `file` or `db` |

**Toggle impact:**

| Setting | Behaviour | When to use |
|---------|-----------|-------------|
| `false` | No caching, always fresh extraction | Development, debugging, testing |
| `true` + `file` | JSON files in CHECKPOINT_DIR | Single-server production |
| `true` + `db` | PostgreSQL storage | Multi-server, HA production |

**⚠️ Important:** Enable checkpoints ONLY in production. During development, stale checkpoints can mask code changes and cause confusing test failures.

---

### Observability Configuration

Three independent layers — enable any combination:

| Variable | Default | Layer | Description |
|----------|---------|-------|-------------|
| `TRACING_ENABLED` | `0` | All | Master kill switch (0 = disabled) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | Layer 1 | OTel collector endpoint |
| `OTEL_SERVICE_NAME` | `template-engine` | Layer 1 | Service name in traces |
| `PHOENIX_COLLECTOR_ENDPOINT` | — | Layer 2 | Arize Phoenix for LLM analysis |
| `LANGFUSE_PUBLIC_KEY` | — | Layer 3 | Langfuse prompt tracking |
| `LANGFUSE_SECRET_KEY` | — | Layer 3 | Langfuse secret |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Layer 3 | Self-hosted Langfuse URL |

**Toggle impact:**

| Configuration | Overhead | Use Case |
|---------------|----------|----------|
| All disabled (`TRACING_ENABLED=0`) | 0ms | Development, CI |
| OTel only | ~2ms/span | Infrastructure monitoring (Jaeger/Grafana) |
| Langfuse only | ~5ms/call | LLM cost tracking, prompt optimization |
| Phoenix only | ~3ms/call | Embedding drift detection |
| All three | ~10ms/call | Full production observability |

**Recommended setup:**
```bash
# Development
TRACING_ENABLED=0

# Staging (cost tracking only)
TRACING_ENABLED=1
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx

# Production (full stack)
TRACING_ENABLED=1
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx
PHOENIX_COLLECTOR_ENDPOINT=http://phoenix:6006
```

---

### Long-Term Memory (LTM) Configuration

LTM enables the system to learn from user corrections and improve over time.

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_URL` | — | Qdrant Cloud endpoint |
| `QDRANT_API_KEY` | — | Qdrant API key |
| `LTM_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| `LTM_ENABLED` | `1` (if QDRANT_URL set) | Override toggle |

**Toggle impact:**

| Setting | Behaviour | Impact |
|---------|-----------|--------|
| Disabled (no QDRANT_URL) | ScribeAgent uses rules only | Consistent but static output |
| Enabled | Queries corrections + styles before generating | Narratives improve over time, adapts to user preferences |

**What LTM stores:**
- `plfs_corrections` — User edits (original→corrected pairs)
- `plfs_styles` — Proven sentence patterns
- `entity_bindings` — Historical entity→column mappings (faster future resolution)

**Free tier setup (Qdrant Cloud):**
```bash
QDRANT_URL=https://your-cluster.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=your-api-key
LTM_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

---

### Report Generation Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LATEX_ENGINE` | `lualatex` | LaTeX compiler (`lualatex`, `xelatex`, `pdflatex`) |
| `PANDOC_PATH` | `pandoc` | Path to Pandoc binary |
| `OUTPUT_DIR` | `./outputs` | Generated report output directory |
| `MAX_PARALLEL_TOPICS` | `4` | Topic-level parallelism |

**Toggle impact:**

| Engine | Speed | Unicode | Fonts | Recommended |
|--------|-------|---------|-------|-------------|
| `lualatex` | Slow (2-pass) | Full | System fonts | Production (Indian scripts) |
| `xelatex` | Medium | Full | System fonts | Alternative |
| `pdflatex` | Fast | Limited | TeX fonts only | English-only reports |

---

### Consensus Engine Configuration

| Variable | Built-in Default | Description |
|----------|-----------------|-------------|
| `MAX_RETRIES` | 3 | Base retry count |
| Priority: `high` | 4 retries | Critical claims get more attempts |
| Priority: `medium` | 3 retries | Standard claims |
| Priority: `low` | 2 retries | Low-priority questions |

**Failure classification impact:**

| Failure Type | Repair Strategy | Description |
|--------------|----------------|-------------|
| `ROUNDING` | Re-round from source | "4.23% was reported as 4.2%" |
| `HALLUCINATION` | Strip claim, regenerate | "Claim not found in facts" |
| `STALE_DATA` | Refresh facts, retry | "Data changed since extraction" |
| `LOGIC` | Full regeneration with guidance | "Conclusion contradicts premises" |

---

### Template Cache Configuration

| Setting | Value | Description |
|---------|-------|-------------|
| L1 Cache | SHA256 hash | Exact page content match → instant reuse |
| L2 Cache | Structural fingerprint | Similar layouts (≥85% match) → skeleton reuse |
| Max entries | 50 | LRU eviction when full |
| Persistence | JSON on disk | Survives restarts |

**Impact:** For quarterly PLFS reports (same structure each quarter), cache provides ~3x speedup on template extraction. Disable for one-off reports by clearing cache.

---

### Entity Binding Configuration

| Setting | Value | Description |
|---------|-------|-------------|
| Auto-accept threshold | `≥0.90` confidence | Binding accepted without user review |
| Pending threshold | `0.60–0.89` | Shown in UI for user approval |
| Unresolved | `<0.60` | Requires manual column selection |

**Resolution cascade (5 stages):**
1. **Exact match** — entity name equals column name (case-insensitive)
2. **Alias match** — PLFS glossary abbreviations (LFPR → labour_force_participation_rate)
3. **Glossary match** — Entity hints + column semantics
4. **Fuzzy match** — SequenceMatcher ratio ≥0.60
5. **Synonym KG** — Deep BI knowledge graph (if available)

---

## Feature Toggles & Impact Matrix

| Toggle | OFF Impact | ON Impact | Recommended |
|--------|-----------|-----------|-------------|
| `CHECKPOINT_ENABLED` | Fresh extraction every time (~5min) | Resume from last checkpoint (~30s) | OFF (dev), ON (prod) |
| `TRACING_ENABLED` | Zero overhead | +10ms/span, full observability | OFF (dev), ON (prod) |
| `LTM_ENABLED` | Static narratives, no learning | Improving output, 100ms/query | OFF (CI), ON (prod) |
| `COLPALI_ENDPOINT` | VLM falls back to pdfplumber | GPU-accelerated page analysis | Required for PLFS PDFs |
| `SGLANG_ENDPOINT` | LLM Router uses cloud APIs | Local 3B model, no API cost | Optional (cost saving) |
| `NEO4J_ENABLED` | No knowledge graph | Entity relationships, cross-refs | Optional |
| `REDIS_URL` | No distributed cache | Shared cache across workers | Multi-worker only |

### Performance Profile by Configuration

| Profile | Config | Extraction Time | Generation Time | Cost/Report |
|---------|--------|----------------|-----------------|-------------|
| **Dev** | SQLite, Gemini only, no cache | ~5 min | ~2 min | ~$0.05 |
| **Staging** | Postgres, Groq+Gemini, cache ON | ~2 min | ~1 min | ~$0.03 |
| **Production** | Postgres, GPU, full stack | ~30 sec | ~45 sec | ~$0.01 |
| **Offline** | SQLite, SGLang local, no API | ~3 min | ~3 min | $0.00 |

---

## Module Reference

### Phase 1: Foundation (`template_engine/config/`, `storage/`, `llm/`)

| Module | File | Purpose |
|--------|------|---------|
| PipelineConfig | `config.py` | All hardcoded values → env-configurable dataclass |
| CheckpointBackend | `storage/checkpoint.py` | File/DB checkpoint save/load/exists |
| LLMRouter | `llm/router.py` | Per-role provider routing + rate limiting |
| DomainTolerance | `config.py` | Verifier tolerance cascade (domain→entity-type) |
| EntityDeduplicator | `extraction/entity_deduplicator.py` | Scoped dedup + cross-refs |
| ErrorRecovery | `pipeline.py` | Partial output on failure, never crash |
| SGLangClient | `generation/sglang_client.py` | Decomposed 3-call generation |
| SoftConstraints | `ast_core/schema.py` | suggested + user + effective constraints |

### Phase 2: PLFS (`template_engine/extraction/`, `inference/`)

| Module | File | Purpose |
|--------|------|---------|
| PLFSGlossary | `inference/patterns/plfs_glossary.json` | 50+ abbreviations, archetypes, hints |
| PLFSParser | `extraction/plfs_parser.py` | Statement N.M → entities + questions |
| HierarchicalTable | `vlm/schemas.py` | headerLevels, spans, mergedCells |
| CamelotAdapter | `vlm/pdfplumber_adapter.py` | Lattice mode for merged cells |
| TableMerger | `extraction/table_merger.py` | Cross-page table continuation |
| QuestionInferrer | `inference/question_inferrer.py` | Multi-cascade with PLFSDirectInferrer |
| PLFSStyleEngine | `inference/plfs_style_engine.py` | Style patterns, precision rules |

### Phase 3: Report Generation (`binder/`, `render/`, `report_builder/`)

| Module | File | Purpose |
|--------|------|---------|
| TemplateBinder | `binder/template_binder.py` | Entity→column binding (auto/manual) |
| ColumnResolver | `binder/column_resolver.py` | 5-stage cascade resolution |
| ReportOrchestrator | `report_builder/orchestrator.py` | Full pipeline, topic parallelism |
| LaTeXRenderer | `render/latex_renderer.py` | Jinja2→.tex→lualatex→PDF |
| CitationManager | `render/citation_manager.py` | Inline [n] markers + appendix |
| ConsensusRepair | `agents/consensus_engine.py` | ROUNDING/HALLUCINATION/STALE/LOGIC |
| PriorityExtraction | `inference/question_inferrer.py` | high/medium/low tagging |
| TemplateCache | `storage/template_cache.py` | L1 hash + L2 structural (3x speedup) |

### Phase 4: Observability & LTM (`observability/`, `storage/`)

| Module | File | Purpose |
|--------|------|---------|
| TracingConfig | `observability/tracing.py` | OTel + Phoenix + Langfuse init |
| LLMTracing | `observability/llm_tracing.py` | Per-call spans with token counts |
| LTMStore | `storage/ltm_store.py` | Qdrant: corrections, styles, bindings |
| ScribeLTM | `agents/scribe_agent.py` | Query LTM before generating |
| PLFSStyleRules | `inference/patterns/plfs_style_rules.json` | 50+ sentence patterns |
| AdaptiveRetry | `agents/consensus_engine.py` | Priority→retry budget mapping |

### Phase 5: Dashboard & API (`api/report_builder_api/`, `dashboard/`)

| Module | File | Purpose |
|--------|------|---------|
| ProgressSSE | `api/report_builder_api/progress_sse.py` | Real-time event streaming |
| EntityBindingAPI | `api/report_builder_api/entity_binding_api.py` | CRUD + resolve + override |
| ProgressComponent | `dashboard/components/report-builder/ReportProgressStream.tsx` | EventSource → progress bar |
| BindingPanel | `dashboard/components/report-builder/EntityBindingPanel.tsx` | Table + edit + accept/reject |
| HTMLPreview | `api/report_builder_api/routes.py` | Canvas→HTML rendering |

---

## API Reference

### Report Generation

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/report-builder/generate` | Trigger report generation | Required |
| `POST` | `/report-builder/coord-generate` | Coordinate-exact generation | Required |
| `GET` | `/report-builder/jobs` | List jobs (filter by analysis_id) | Required |
| `GET` | `/report-builder/jobs/{id}` | Job status | Required |
| `GET` | `/report-builder/jobs/{id}/canvas` | Full BlockCanvas JSON | Required |
| `GET` | `/report-builder/jobs/{id}/preview` | HTML preview | Required |
| `GET` | `/report-builder/jobs/{id}/download` | PDF download | Required |
| `POST` | `/report-builder/jobs/{id}/deliver` | Email/webhook delivery | Required |

### Progress Streaming (SSE)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/report-builder/jobs/{id}/progress/stream` | SSE event stream |
| `GET` | `/report-builder/jobs/{id}/progress` | Latest progress snapshot |

**SSE Event Types:**
```
event: progress
data: {"stage": "binding", "pct": 25, "message": "Resolving entities..."}

event: complete
data: {"stage": "done", "pct": 100, "message": "Done"}

event: error
data: {"stage": "error", "pct": -1, "message": "Verification failed"}
```

### Entity Binding

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/report-builder/bindings/{job_id}` | All bindings for job |
| `POST` | `/report-builder/bindings/{job_id}/resolve` | Auto-resolve cascade |
| `PUT` | `/report-builder/bindings/{job_id}/{entity_id}` | User override |
| `POST` | `/report-builder/bindings/{job_id}/accept` | Batch accept pending |
| `POST` | `/report-builder/bindings/{job_id}/reject` | Batch reject |

### Template Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/report-builder/templates/upload` | Upload PDF → extract template |
| `GET` | `/report-builder/templates` | List templates |
| `GET` | `/report-builder/templates/{id}` | Full AST |
| `DELETE` | `/report-builder/templates/{id}` | Delete template |

---

## GPU & Docker Setup

### 6GB VRAM Sequential Sharing Strategy

ColPali (extraction) and SGLang (generation) cannot share 6GB VRAM simultaneously. The Docker Compose uses sequential containers:

```
Phase 1: ColPali container starts → extracts all pages → stops (releases VRAM)
Phase 2: SGLang container starts → generates AST → stops (releases VRAM)
Phase 3: API generates report using cloud LLMs (no GPU needed)
```

### Docker Compose (GPU)

```bash
# Full sequential pipeline
docker compose -f docker-compose.gpu.yml --profile gpu run --rm pipeline

# Manual control (useful for debugging)
docker compose -f docker-compose.gpu.yml --profile gpu up colpali
docker compose -f docker-compose.gpu.yml --profile gpu stop colpali
docker compose -f docker-compose.gpu.yml --profile gpu up sglang
docker compose -f docker-compose.gpu.yml --profile gpu stop sglang

# API + Dashboard (no GPU needed)
docker compose -f docker-compose.gpu.yml up api dashboard
```

### Non-GPU Fallback

Without GPU, the system uses:
- **pdfplumber** instead of ColPali for page extraction
- **Cloud LLMs** (Gemini/Groq) instead of SGLang for generation
- No model files needed locally

```bash
# .env for non-GPU
COLPALI_ENDPOINT=        # Empty = pdfplumber fallback
SGLANG_ENDPOINT=         # Empty = cloud LLM fallback
DEFAULT_LLM_PROVIDER=gemini
```

---

## Testing

### Test Suite Structure

| File | Phase | Tests | Time |
|------|-------|-------|------|
| `tests/test_template_engine/test_*.py` (P1-2) | 1-2 | 267 | ~16 min |
| `tests/test_template_engine/test_phase3.py` | 3 | 34 | ~13 sec |
| `tests/test_template_engine/test_phase4_5.py` | 4-5 | 40 | ~22 sec |
| `tests/test_template_engine/test_phase6_integration.py` | 6 | 17 | ~17 sec |
| **Total** | All | **324+** | ~17 min |

### Running Tests

```bash
# Quick: New phases only (~50 sec)
pytest tests/test_template_engine/test_phase3.py \
       tests/test_template_engine/test_phase4_5.py \
       tests/test_template_engine/test_phase6_integration.py -q

# Full suite (~17 min)
pytest tests/test_template_engine/ -m "not live" -q

# With coverage
pytest tests/test_template_engine/ -m "not live" \
  --cov=template_engine --cov=agents --cov-report=term-missing

# Single test class
pytest tests/test_template_engine/test_phase4_5.py::TestLTMStore -v
```

### Test Markers

| Marker | Description |
|--------|-------------|
| `not live` | Excludes tests requiring real APIs/GPU |
| `benchmark` | Performance benchmarks only |

---

## Troubleshooting

### Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| Tests fail with stale data | `CHECKPOINT_ENABLED=true` in dev | Set `CHECKPOINT_ENABLED=false` |
| `ModuleNotFoundError: qdrant_client` | LTM deps not installed | `pip install qdrant-client` or set `LTM_ENABLED=0` |
| LaTeX compilation fails | lualatex not installed | `apt install texlive-luatex` or use HTML preview |
| SSE connection drops | Proxy buffering | Set `X-Accel-Buffering: no` in nginx |
| Entity binding all "unresolved" | No columns provided | Pass `column_names` or `dataset_id` to `/resolve` |
| LLM rate limited | RPM exceeded | Increase `{PROVIDER}_RPM` or add fallback provider |
| Consensus stuck in repair loop | Max retries too high for low-priority | Priority system handles this automatically |

### Debug Mode

```bash
# Verbose logging
export LOG_LEVEL=DEBUG

# Trace a specific LLM call
python -c "
from template_engine.observability.llm_tracing import llm_span
with llm_span('test', model='debug') as r:
    r.output = 'hello'
    print(f'Traced: {r.latency_ms:.1f}ms')
"

# Check LTM connectivity
python -c "
from template_engine.storage.ltm_store import get_ltm_store
store = get_ltm_store()
print(f'LTM available: {store.is_available}')
"

# Verify checkpoint config
python -c "
from template_engine.config import get_config
c = get_config()
print(f'Checkpoint: enabled={c.checkpoint.enabled}, dir={c.checkpoint.checkpoint_dir}')
"
```

### CI Pipeline

The GitHub Actions workflow (`.github/workflows/template-engine-ci.yml`) runs:
1. Tests on Python 3.11, 3.12, 3.13
2. Coverage check (≥70% required)
3. Linting via `ruff`

Triggered on pushes to `main` or `feature/rev-template` affecting `template_engine/`, `agents/`, `report_builder/`, or `tests/`.

