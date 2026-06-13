<div align="center">

# BharatStat

**Turn raw statistical datasets into audit-ready intelligence and publication-grade reports.**

[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?style=flat-square)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Dashboard-Next.js_16-000000?style=flat-square)](https://nextjs.org/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Statathon_Hackathon-f5c518?style=flat-square)](#license)

<br />

<img src="docs/images/header-image1.png" alt="BharatStat platform overview" width="100%" />

<img src="docs/images/header-image2.png" alt="BharatStat platform overview" width="100%" />

</div>

---

## NEW GPU LAPTOP — COMPLETE SETUP GUIDE

> **Everything needed to run the full stack on a fresh Windows machine with NVIDIA GPU (RTX 4050/4060/4070, 6–8 GB VRAM). Docker handles Neo4j, Redis, LayoutLM, and vLLM. API + Dashboard run natively for fast dev.**

### Step 0: Install Prerequisites

| Software | Version | Download | Notes |
|----------|---------|----------|-------|
| **Git** | Latest | https://git-scm.com/download/win | |
| **Python** | 3.12.x | https://www.python.org/downloads/ | Check "Add to PATH" |
| **Node.js** | 20 LTS+ | https://nodejs.org/ | |
| **Docker Desktop** | Latest | https://www.docker.com/products/docker-desktop/ | Enable WSL2 backend + GPU |
| **Poppler** | 24.x+ | https://github.com/osber/poppler-windows/releases | Extract to `C:\poppler` |
| **NVIDIA Driver** | 550+ | https://www.nvidia.com/drivers | Required for GPU containers |

After installing Poppler, add `C:\poppler\Library\bin` to your system PATH.

Docker Desktop GPU setup: Settings → Resources → WSL Integration → enable. Then Settings → Docker Engine → confirm `"default-runtime": "nvidia"` or use `--gpus all`.

### Step 1: Clone & Checkout

```powershell
cd C:\Users\<you>\projects
git clone https://github.com/Madan94/statathon.git
cd statathon
git checkout feature/rev-template
```

### Step 2: Create `.env` (Backend)

Create `statathon/.env`:

```env
# ─── Core ───────────────────────────────────────────
SECRET_KEY=change-me-to-32-chars-minimum-random-string
AUTH_REQUIRED=false
DATABASE_URL=sqlite:///./statathon.db
APP_ENV=development
LOG_LEVEL=INFO

# ─── CORS ──────────────────────────────────────────
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# ─── Storage ───────────────────────────────────────
UPLOAD_STORAGE_PATH=./storage/uploads
REPORT_STORAGE_PATH=./storage/reports
OBJECT_STORAGE_DISABLED=true

# ─── Neo4j (Docker handles this — just set enabled) ──
NEO4J_ENABLED=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=mospi_secure_password

# ─── Redis ─────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ─── Gemini (for report enrichment pass5) ──────────
GOOGLE_API_KEY=your-gemini-api-key-here

# ─── Model cache ──────────────────────────────────
HUGGINGFACE_HUB_CACHE=./model/cache

# ─── Report Builder V2 Pipeline ───────────────────
EXTRACTION_PIPELINE=v2
LAYOUTLM_ENDPOINT=http://localhost:8001
SGLANG_ENDPOINT=http://localhost:8002
SGLANG_MODEL=Qwen/Qwen2.5-VL-3B-Instruct-AWQ
SGLANG_TIMEOUT=120
LAYOUTLM_TIMEOUT=300
POPPLER_PATH=C:/poppler/Library/bin
VLM_MAX_IMAGE_DIM=800
VLM_MAX_CONSECUTIVE_FAIL=3

# ─── Dev auth ─────────────────────────────────────
DEV_AUTH_ENABLED=true
```

### Step 3: Create `dashboard/.env.local`

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
API_INTERNAL_URL=http://localhost:8000
MAIL_INTERNAL_SECRET=any-shared-secret-here
SMTP_DEV_LOG_OTP=true
```

### Step 4: Start Docker Services (Neo4j + Redis + LayoutLM + vLLM)

```powershell
# From repo root — starts Neo4j, Redis (always), LayoutLM + vLLM (gpu profile)
docker compose --profile gpu up -d
```

**What this starts:**

| Container | Image | Port | GPU? | First-boot time |
|-----------|-------|------|------|-----------------|
| `redis` | redis:7-alpine | 6379 | No | ~2s |
| `neo4j` | neo4j:5 | 7474, 7687 | No | ~10s |
| `layoutlm` | Built from Dockerfile.layoutlm | 8001 | No (CPU) | ~2min (downloads LayoutLMv3-large ~1.4GB) |
| `sglang` | Built from Dockerfile.sglang | 8002 | Yes | ~2-5min (downloads Qwen2.5-VL-3B ~2.5GB) |

**First run only**: LayoutLM and vLLM download model weights. These are cached in `./model/cache/` — subsequent starts take ~30s.

```powershell
# Watch vLLM startup (wait for "Uvicorn running on 0.0.0.0:8002")
docker compose logs -f sglang

# In another terminal, watch LayoutLM
docker compose logs -f layoutlm
```

**If images aren't built yet:**

```powershell
# Build images first (only needed once, or after Dockerfile changes)
docker compose --profile gpu build layoutlm sglang
docker compose --profile gpu up -d
```

### Step 5: Verify Docker Services

```powershell
# Redis
docker compose exec redis redis-cli ping
# → PONG

# Neo4j (wait ~15s after start)
curl http://localhost:7474
# → Neo4j browser HTML

# LayoutLM (wait ~2min first time)
curl http://localhost:8001/health
# → {"status":"ok"}

# vLLM (wait ~2-5min first time)
curl http://localhost:8002/v1/models
# → {"data":[{"id":"Qwen/Qwen2.5-VL-3B-Instruct-AWQ",...}]}
```

### Step 6: Start API Backend (Native Python)

```powershell
# New terminal — repo root
cd statathon
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-windows.txt

# Start API
cd api
$env:PYTHONPATH = (Resolve-Path "..").Path
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Verify: http://localhost:8000/health → `{"status":"ok"}`

API docs: http://localhost:8000/docs

### Step 7: Start Dashboard (Native Node.js)

```powershell
# New terminal
cd statathon\dashboard
npm install
npm run dev
```

Open http://localhost:3000

### Step 8: First Run Workflow

1. **Login**: http://localhost:3000/login — with `DEV_AUTH_ENABLED=true`, access without credentials
2. **Upload**: `/upload` → drag a CSV/XLSX (test files in `test_data/`)
3. **Analyze**: Open dataset → "Run Analysis" → 5-step wizard
4. **Report Builder**: `/report-builder` → upload reference PDF → "Extract Template"
5. **Neo4j Browser**: http://localhost:7474 — user: `neo4j`, password: `mospi_secure_password`
6. **Generate Report**: Select ready analysis + template → generate PDF

---

### Docker Compose Profiles

| Command | What starts |
|---------|-------------|
| `docker compose up -d` | Redis + Neo4j only |
| `docker compose --profile gpu up -d` | Redis + Neo4j + LayoutLM + vLLM (GPU) |
| `docker compose --profile full up -d` | Everything including Dashboard container |

### When Do You Need to Rebuild?

| Scenario | Command | Time |
|----------|---------|------|
| **First clone** | `docker compose --profile gpu up -d` | ~5min (builds images + downloads models) |
| **`git pull` with no Dockerfile changes** | `docker compose --profile gpu up -d` | ~30s (reuses cached images + models) |
| **Dockerfile changed** | `docker compose --profile gpu build && docker compose --profile gpu up -d` | ~2-3min (rebuilds only changed layers) |
| **Python code changed (API)** | Just restart uvicorn — `--reload` handles it | Instant |
| **Dashboard code changed** | Auto hot-reload via `npm run dev` | Instant |
| **docker-compose.yml env vars changed** | `docker compose --profile gpu up -d` | ~30s (recreates containers, reuses images) |
| **Model cache exists in `./model/cache/`** | No download needed | ~30s startup |

**Key insight**: Model weights are stored in `./model/cache/` (bind mount, not a Docker volume). This means:
- Models survive `docker compose down`
- Models survive `docker system prune`
- Models are shared between LayoutLM, vLLM, and the API
- Moving to a new machine? Copy `model/cache/` folder to skip downloads

### RTX 4050 (6GB) vs RTX 4070+ (8GB+)

Default is `Qwen2.5-VL-3B-Instruct-AWQ` (fits 6GB). For 8GB+ GPUs:

```powershell
$env:VLLM_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"
docker compose --profile gpu up -d sglang
```

Also update `.env`:
```
SGLANG_MODEL=Qwen/Qwen2.5-VL-7B-Instruct-AWQ
```

### Stopping & Cleanup

```powershell
# Stop all containers (keeps data)
docker compose --profile gpu down

# Stop and remove volumes (deletes Neo4j data, Redis cache)
docker compose --profile gpu down -v

# View running containers
docker compose ps

# View GPU usage
nvidia-smi
```

---

### Troubleshooting

| Problem | Fix |
|---------|-----|
| `pip install` fails on torch | Use `requirements-windows.txt` not `requirements.txt` |
| `pdf2image` fails | Install Poppler, set `POPPLER_PATH` in `.env`, add to system PATH |
| `ModuleNotFoundError: pipelines` | Set `PYTHONPATH` to repo root before running uvicorn |
| vLLM OOM / CUDA crash | Pipeline auto-falls back to pdfplumber + Gemini. No action needed |
| vLLM won't start (CUDA error) | `wsl --shutdown` → restart Docker Desktop → `docker compose --profile gpu up -d sglang` |
| Dashboard 500 on API calls | Check `NEXT_PUBLIC_API_URL=http://localhost:8000` in `dashboard/.env.local` |
| `sentence-transformers` slow first run | Downloads `all-MiniLM-L6-v2` (~80MB) on first analysis |
| Gemini 400 error | Ensure `GOOGLE_API_KEY` is set in `.env` |
| Neo4j "connection refused" | Wait 15s after `docker compose up`, or check `docker compose logs neo4j` |
| Port 8000 in use | Kill other processes: `Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess` |
| LayoutLM timeout | Increase `LAYOUTLM_TIMEOUT=600` in `.env` for large PDFs |
| Docker "no matching manifest" | Ensure Docker Desktop uses Linux containers (not Windows) |

---

### Port Summary

| Port | Service | Source |
|------|---------|--------|
| 3000 | Next.js Dashboard | Native `npm run dev` |
| 8000 | FastAPI Backend | Native `uvicorn` |
| 8001 | LayoutLM (CPU) | Docker |
| 8002 | vLLM Qwen-VL (GPU) | Docker |
| 7474 | Neo4j Browser | Docker |
| 7687 | Neo4j Bolt | Docker |
| 6379 | Redis | Docker |

---

## Table of contents

- [Platform preview](#platform-preview)
- [Overview](#overview)
- [Key capabilities](#key-capabilities)
- [Architecture](#architecture)
- [Technology stack](#technology-stack)
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Development workflow](#development-workflow)
- [API surface](#api-surface)
- [Analysis pipeline](#analysis-pipeline)
- [Report Builder](#report-builder)
- [Authentication & security](#authentication--security)
- [Testing & quality](#testing--quality)
- [Deployment](#deployment)
- [Operations](#operations)
- [Documentation index](#documentation-index)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Government and research teams routinely receive heterogeneous CSV/Excel files: inconsistent column names, missing values, outliers, and weak metadata. BharatStat addresses this with:

1. **Deterministic + ML hybrid semantics** — Sentence-transformer embeddings, MoSPI ontology keywords, dynamic domain clusters, and optional Gemini refinement for ambiguous cases.
2. **Candidate-first quality layer** — Validation rules, anomaly detection, and imputation suggestions are stored as **candidates**; officers approve before anything is applied.
3. **Explainable routing** — Every column mapping records confidence, cluster support, graph consistency, and routing path (schema lock, RapidFuzz, embedding similarity, etc.).
4. **Report generation** — Upload a reference PDF template, extract layout/text/tables, map AST blocks to analysis outputs, and export MoSPI-style PDFs with agent-assisted narrative (Scribe + Verifier).
5. **Audit trail** — Activity feed, tamper-evident report artifacts, normalization versioning, and optional Neo4j knowledge-graph sync.

The system is designed for **officer-in-the-loop** workflows: automation proposes; humans decide.

---

## Key capabilities

| Area | What you get |
|------|----------------|
| **Ingestion** | CSV, XLS, XLSX upload (local disk or S3-compatible presigned URLs) |
| **Profiling** | Row/column health, dtype inference, dataset intelligence profiles |
| **Semantic mapping** | Domain taxonomy, ensemble confidence, per-column overrides |
| **Normalization** | Approved column schema versions drive downstream steps |
| **Phase 3 intel** | Rule validation, IQR/Z-score/isolation outliers, imputation candidates |
| **Clustering** | Hierarchical linkage with dataset-size-aware similarity thresholds |
| **Knowledge graph** | Schema blueprint + optional Neo4j sync |
| **Report Builder** | 6-stage PDF template extraction, block mapping, async generation jobs |
| **Dashboard** | Next.js 16 app — upload, analysis wizard, report preview, activity log |

---

## Architecture

```mermaid
flowchart TB
  subgraph Client["Dashboard (Next.js)"]
    UI[Officer UI]
  end

  subgraph API["FastAPI — BharatStat API"]
    Auth[Auth / OTP / OAuth]
    DS[Datasets]
    AN[Analysis]
    RB[Report Builder]
    DH[Dashboard Activity]
  end

  subgraph Core["Analysis core"]
    ORCH[pipelines/orchestrator]
    SEM[Semantic pipeline]
    P3[Phase 3 — validation / outliers / imputation]
    PROF[profiling / weights]
  end

  subgraph Data["Persistence & storage"]
    PG[(PostgreSQL / SQLite)]
    S3[(S3 / R2 / local uploads)]
    N4J[(Neo4j — optional)]
  end

  subgraph Report["Report engine"]
    AST[Template AST]
    AG[agents — Scribe / Verifier]
    EXP[PDF exporter]
    DUCK[DuckDB analytics]
  end

  UI -->|HTTPS + cookies| API
  Auth --> PG
  DS --> S3
  DS --> ORCH
  AN --> ORCH
  ORCH --> SEM --> P3
  ORCH --> PG
  ORCH --> N4J
  RB --> AST --> AG --> EXP
  RB --> DUCK
  RB --> S3
```

**Request flow (analysis):**

1. Officer uploads a dataset → `POST /datasets/upload` (or presigned URL + register).
2. Officer starts analysis → `POST /analysis/{dataset_id}/analyze-async`.
3. Background runner executes `pipelines/orchestrator.run_pipeline` (ingestion → semantic → phase 3 → persistence).
4. Dashboard polls `GET /analysis/{id}/status` and loads `GET /analysis/{id}/results`.
5. Officer walks the 5-step wizard (summary → normalize → semantic → cluster → schema/KG).
6. Optional: Report Builder consumes a **ready** analysis and generates a PDF job.

---

## Technology stack

| Layer | Technologies |
|-------|----------------|
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS v4, Axios, Sonner |
| **API** | FastAPI, Uvicorn, SQLAlchemy 2, Pydantic v2, python-jose, bcrypt |
| **ML / NLP** | sentence-transformers (`all-MiniLM-L6-v2`), scikit-learn, PyTorch (semantic embeddings) |
| **Data** | pandas, NumPy, SciPy, openpyxl, xlrd, DuckDB adapter (reports) |
| **PDF** | pdfplumber, PyMuPDF, ReportLab |
| **Graph** | Neo4j 5.x (optional), NetworkX |
| **Queue / cache** | Celery, Redis (optional workers) |
| **Object storage** | boto3 — AWS S3, Cloudflare R2, or local paths |
| **Auth** | JWT (httpOnly cookies), OTP email, dev bypass, optional OAuth |

---

## Repository layout

```
statathon/
├── api/                    # FastAPI application (run uvicorn from here)
│   ├── main.py             # App entry, routers, middleware, migrations
│   ├── auth/               # OTP, JWT, CSRF, rate limits
│   ├── dataset_api/        # Upload, profile, effective schema
│   ├── analysis/           # Analysis jobs, results, normalization, KG
│   ├── report_builder_api/ # Template extraction, generation jobs
│   ├── dashboard/          # Aggregated activity feed
│   ├── database/           # SQLAlchemy models & migrations
│   └── services/           # Analysis runner, profiling, persistence
├── dashboard/              # Next.js officer UI
├── agents/                 # Scribe, Verifier, planner, retrieval (reports)
├── pipelines/              # Orchestrator, semantic runner, phase 3
├── model/                  # Semantic mapping, ontology config
├── validation/             # Rule engine, multi-column validators
├── outliers/               # IQR, Z-score, isolation, distribution fit
├── imputation/             # KNN, median, mechanism detection
├── report_builder/         # Template pipeline, firewall, exporter
├── template_engine/        # PDF → AST compilation
├── graph/                  # Neo4j sync & schema bootstrap
├── analytics_engine/       # DuckDB / ClickHouse adapters
├── profiling/              # Dataset & column intelligence
├── docs/                   # Deep-dive guides (env, AWS, report builder)
├── tests/                  # pytest suite
├── docker/                 # API & dashboard Dockerfiles
├── requirements.txt        # Full stack (Linux / GPU-friendly)
└── requirements-windows.txt # Windows-friendly wheels (recommended on Win)
```

---

## Prerequisites

| Requirement | Version / notes |
|-------------|-----------------|
| **Python** | 3.12+ (3.12 recommended; use `requirements-windows.txt` on Windows) |
| **Node.js** | 20+ for the dashboard |
| **Database** | PostgreSQL (production) or SQLite (local hackathon) |
| **Redis** | Optional — only if running Celery workers |
| **Neo4j** | Optional — set `NEO4J_ENABLED=false` to disable KG sync |
| **SMTP** | Required for OTP in production; dev can log OTP to console |

---

## Quick start

### 1. Clone and configure backend

```bash
git clone <repository-url>
cd statathon
python -m venv .venv
```

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-windows.txt
```

**Linux / macOS:**

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Start the API

From the `api/` directory (required for correct import paths):

```bash
cd api
$env:PYTHONPATH = (Resolve-Path "..").Path   
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Verify:

- `GET http://127.0.0.1:8000/health` → `{"status":"ok"}`
- `GET http://127.0.0.1:8000/health/db` → database reachable

Interactive docs: **http://127.0.0.1:8000/docs**

### 3. Start the dashboard

```bash
cd dashboard
cp .env.local.example .env.local
npm install
npm run dev
```

Open **http://localhost:3000**. Sign in with dev credentials from `.env` or complete OTP flow if SMTP is configured.

### 4. Run a sample analysis

1. Go to **Upload** → drop a CSV/XLSX (see `test_data/` for MoSPI-style samples).
2. Open the dataset → **Run analysis**.
3. Open the analysis workspace → complete steps 1–5.
4. Optional: **Report Builder** → pick a ready analysis → extract or clone a template → generate PDF.

---

## Configuration

Environment variables are loaded from **repo root `.env`** when the API starts from `api/`. The dashboard uses `dashboard/.env.local`.

### Essential variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | JWT signing secret (≥32 chars when `AUTH_REQUIRED=true`) |
| `DATABASE_URL` | SQLAlchemy URL (`sqlite:///./statathon.db` or Postgres) |
| `AUTH_REQUIRED` | Enforce authentication (`true` in production) |
| `CORS_ORIGINS` | Comma-separated dashboard origins |
| `UPLOAD_STORAGE_PATH` | Local upload directory (default `./storage/uploads`) |
| `REPORT_STORAGE_PATH` | Generated PDFs and vault JSON |
| `NEO4J_ENABLED` | `true` / `false` — disable if no graph DB |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | Bolt connection when enabled |
| `HUGGINGFACE_HUB_CACHE` | Model cache dir (default `./model/cache`) |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Optional semantic ambiguity refinement |
| `STORAGE_PROVIDER`, `S3_*` | Presigned uploads (R2/AWS); use `OBJECT_STORAGE_DISABLED=true` locally |

### Dashboard variables

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Backend base URL (default `http://localhost:8000`) |
| `MAIL_INTERNAL_SECRET` | Shared secret for internal report-email route |
| `SMTP_*` | Nodemailer OTP and report delivery |

**Full reference:** [docs/ENV_SETUP_STEP_BY_STEP.md](docs/ENV_SETUP_STEP_BY_STEP.md)

---

## Development workflow

| Task | Command |
|------|---------|
| API (hot reload) | `cd api && python -m uvicorn main:app --reload --port 8000` |
| Dashboard | `cd dashboard && npm run dev` |
| Lint (frontend) | `cd dashboard && npm run lint` |
| Tests | `python -m pytest tests -v --tb=short` (from repo root) |
| Semantic benchmark | `python scripts/benchmark_semantic_e2e.py` (see testing guide) |

**Import path note:** Always run Uvicorn with `api/` as the working directory so `main:app` resolves and repo-root packages (`pipelines/`, `model/`) import correctly.

On first semantic run, **sentence-transformers** downloads `all-MiniLM-L6-v2` into `HUGGINGFACE_HUB_CACHE` (or `api/model/cache` depending on cwd). Allow a few minutes on a cold start.

---

## API surface

Base URL: `http://localhost:8000` (development)

| Router | Prefix | Responsibility |
|--------|--------|----------------|
| Auth | `/auth` | Login, OTP, refresh, `/me`, CSRF token |
| OAuth | `/auth/oauth` | Optional social login |
| Datasets | `/datasets` | Upload, presigned URL, profile, effective schema |
| Analysis | `/analysis` | Start job, status, results, normalization, domains, clusters, KG |
| Reports | `/reports` | Legacy ingestion PDFs and downloads |
| Report Builder | `/report-builder` | Template extract (async), generate jobs, ready analyses |
| Dashboard | `/dashboard` | Activity feed aggregation |

**Health:**

- `GET /health` — process alive
- `GET /health/db` — SQL connectivity

OpenAPI: `/docs` and `/redoc`

---

## Analysis pipeline

The orchestrator (`pipelines/orchestrator.py`) runs after upload registration:

| Stage | Module | Output |
|-------|--------|--------|
| **Ingestion** | `core/ingestion` | DataFrame, schema, health summary |
| **Profiling** | `profiling/` | Column & dataset intelligence profiles |
| **Semantic** | `pipelines/semantic_runner` | Domain mappings, dynamic clusters, confidence |
| **Phase 3** | `pipelines/phase3_pipeline` | Validation candidates, anomalies, imputation candidates |
| **Persistence** | `api/services/*_persistence_service` | SQL tables + API payload |
| **KG sync** | `graph/neo4j_sync` | Optional graph write |

**Dashboard wizard (5 steps):**

1. **Summary** — health KPIs and pipeline overview  
2. **Normalize** — approve/reject column transformations; versioned effective schema  
3. **Semantic** — domain registry, routing paths, officer overrides  
4. **Cluster** — linkage clusters and cohesion metrics  
5. **Schema & KG** — blueprint preview and knowledge-graph export  

Phase 3 follows a **detect → explain → store → decide** model; see [docs/PHASE3_PIPELINE.md](docs/PHASE3_PIPELINE.md).

---

## Report Builder

Production flow for template-based PDF generation:

1. Select a **ready** analysis (`GET /report-builder/ready-analyses`).
2. Upload a reference PDF or clone the MoSPI default template.
3. **Extract template (async)** — 6-stage pipeline (`report_builder/blueprint.py`): layout, text pages, tables, images → Template AST.
4. Map AST blocks to analysis data sources (`hints.source`).
5. Apply filters (`report_builder/filter_engine.py`).
6. `POST /report-builder/generate` — background job via `report_builder/pipeline.py` (agents, DuckDB kernel, PDF export).
7. Download or deliver (email / webhook).

Architecture detail: [docs/REPORT_BUILDER_ARCHITECTURE.md](docs/REPORT_BUILDER_ARCHITECTURE.md)

---

## Authentication & security

- **JWT access + refresh** tokens in **httpOnly** cookies when using the dashboard.
- **CSRF** double-submit cookie on mutating requests (`CSRF_ENABLED=true`).
- **Rate limiting** on auth endpoints (`AUTH_RATE_MAX_PER_WINDOW`).
- **Security headers** — `X-Content-Type-Options`, `X-Frame-Options`, HSTS in production.
- **RBAC** — datasets, analyses, templates, and jobs scoped to the authenticated officer (`user_id`).
- **Dev mode** — `DEV_AUTH_ENABLED` seeds a test officer; fixed OTP when SMTP is unavailable.

Never commit `.env` or real secrets. Rotate `SECRET_KEY` and database credentials for production.

---

## Testing & quality

```bash
# From repository root
python -m pytest tests -v --tb=short
```

Coverage highlights:

- Analysis state & API payload serialization  
- Semantic adapter and clustering utilities  
- Dataset profiling and ingestion health  
- Storage key conventions  
- JSON-safe numeric handling  

Semantic accuracy benchmarks and relaxed matching rules: [docs/TESTING_FULL_GUIDE.md](docs/TESTING_FULL_GUIDE.md)

---

## Deployment

| Target | Reference |
|--------|-----------|
| **Docker** | `docker/Dockerfile.api`, `docker/Dockerfile.dashboard`, `docker/Dockerfile.api.fargate` |
| **AWS (Fargate, GPU worker, cutover)** | [docs/deploy/aws/README.md](docs/deploy/aws/README.md) |
| **Object storage (R2)** | [docs/R2_STEP_BY_STEP.md](docs/R2_STEP_BY_STEP.md), [docs/OBJECT_STORAGE.md](docs/OBJECT_STORAGE.md) |

## Operations

| Concern | Action |
|---------|--------|
| **Stuck analyses** | API resets orphaned jobs on startup (`services/analysis_runner`) |
| **Neo4j down** | Set `NEO4J_ENABLED=false` or fix Bolt URI; pipeline still completes |
| **PDF extraction fails** | Ensure `pdfplumber` and `PyMuPDF` installed; check job error in Report Builder UI |
| **Large uploads** | Use presigned `POST /datasets/upload-url` + `register` |
| **Logs** | Uvicorn stdout; request logging middleware in `api/main.py` |

Local artifact paths (gitignored): `storage/uploads/`, `storage/reports/`, `api/storage/` when running from `api/`.

---

## Documentation index

| Document | Topic |
|----------|--------|
| [docs/ENV_SETUP_STEP_BY_STEP.md](docs/ENV_SETUP_STEP_BY_STEP.md) | Every `.env` variable explained |
| [docs/PHASE3_PIPELINE.md](docs/PHASE3_PIPELINE.md) | Validation, outliers, imputation |
| [docs/REPORT_BUILDER_ARCHITECTURE.md](docs/REPORT_BUILDER_ARCHITECTURE.md) | Report engine phases |
| [docs/TESTING_FULL_GUIDE.md](docs/TESTING_FULL_GUIDE.md) | pytest, benchmarks, troubleshooting |
| [docs/SEMANTIC_PLATFORM_INPUTS.md](docs/SEMANTIC_PLATFORM_INPUTS.md) | Semantic layer inputs |
| [docs/OBJECT_STORAGE.md](docs/OBJECT_STORAGE.md) | S3-compatible storage |
| [docs/deploy/aws/README.md](docs/deploy/aws/README.md) | AWS deployment runbooks |
| [dashboard/README.md](dashboard/README.md) | Frontend-specific setup |

---

<p align="center">
  <strong>BharatStat</strong> — from raw tables to trusted insight and publishable reports.
</p>
