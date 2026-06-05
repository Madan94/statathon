# Complete Setup & Run Guide — Statathon Platform + Template Engine

This guide covers every step from a clean Windows machine to a fully running system,
including real VLM (ColPali), LLM (SGLang + Gemini), Supabase, R2, and the Next.js
dashboard.

---

## Table of Contents
1. [Prerequisites](#1-prerequisites)
2. [Python Environment](#2-python-environment)
3. [Environment Variables (.env)](#3-environment-variables)
4. [Database — Supabase / Postgres](#4-database--supabase--postgres)
5. [Redis](#5-redis)
6. [Neo4j](#6-neo4j)
7. [ColPali — Vision Model Service](#7-colpali--vision-model-service)
8. [SGLang — Grammar-Constrained LLM Server](#8-sglang--grammar-constrained-llm-server)
9. [FastAPI Backend](#9-fastapi-backend)
10. [Next.js Dashboard](#10-nextjs-dashboard)
11. [Running Tests](#11-running-tests)
12. [Running the Template Engine End-to-End](#12-running-the-template-engine-end-to-end)
13. [Full One-Command Stack Start](#13-full-one-command-stack-start)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Prerequisites

| Tool | Version | Where to get it |
|------|---------|-----------------|
| Python | ≥ 3.11 (3.13 recommended) | https://python.org/downloads |
| pip / uv | latest | `pip install uv` |
| Docker Desktop | ≥ 4.30 | https://docker.com/products/docker-desktop |
| Node.js | ≥ 20 LTS | https://nodejs.org |
| Git | any | https://git-scm.com |
| NVIDIA GPU | CUDA 12+ (for real models) | optional — mock mode works without GPU |
| CUDA Toolkit | 12.x | https://developer.nvidia.com/cuda-downloads |

---

## 2. Python Environment

### Option A — uv (recommended, fast)
```powershell
# Install uv globally
pip install uv

# Create venv + install all deps in one step
cd C:\Users\2504690\syl\statathon
uv venv .venv --python 3.13
.venv\Scripts\Activate.ps1

uv pip install -r requirements-windows.txt
```

### Option B — standard pip
```powershell
cd C:\Users\2504690\syl\statathon
python -m venv .venv
.venv\Scripts\Activate.ps1

pip install -r requirements-windows.txt
```

### Verify
```powershell
python -c "import fastapi, sqlalchemy, pydantic; print('OK')"
python -m pytest --collect-only tests/test_template_engine/ -q 2>&1 | Select-Object -Last 3
```
Expected: `176 passed, 6 skipped` (or similar).

---

## 3. Environment Variables

The `.env` file at the repo root is already configured with your credentials.
The critical variables are:

```ini
# .env  (already present — DO NOT commit to git)
DATABASE_URL=postgresql://postgres.xxx:password@aws.supabase.co:5432/postgres
GEMINI_API_KEY=AIzaSy...
S3_ENDPOINT_URL=https://xxx.r2.cloudflarestorage.com
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
S3_BUCKET=statathon-reports
SECRET_KEY=your-64-char-random-string
REDIS_URL=redis://localhost:6379/0
```

### Enabling real VLM / SGLang
Uncomment (or add) these lines once the services are running:
```ini
VLM_BACKEND=colpali
COLPALI_ENDPOINT=http://localhost:8100
SGLANG_ENDPOINT=http://localhost:30000
```

---

## 4. Database — Supabase / Postgres

### Option A — use hosted Supabase (already configured in .env)
Nothing to install. Your `DATABASE_URL` points to Supabase cloud.

### Option B — local Postgres via Docker
```powershell
docker run -d --name statathon-pg `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=statathon `
  -p 5432:5432 `
  postgres:16
```
Then set `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/statathon`

### Run DB migrations
```powershell
# If using Alembic:
alembic upgrade head

# Or run SQL directly:
psql $env:DATABASE_URL -f scripts/init_db.sql
```

---

## 5. Redis

```powershell
# Via Docker (simplest)
docker run -d --name statathon-redis -p 6379:6379 redis:7-alpine

# Verify
docker exec statathon-redis redis-cli ping
# → PONG
```

Or install Redis natively: https://github.com/microsoftarchive/redis/releases

---

## 6. Neo4j

Used for the knowledge-graph features (column synonym KG, entity graph).

```powershell
docker run -d --name statathon-neo4j `
  -p 7474:7474 -p 7687:7687 `
  -e NEO4J_AUTH=neo4j/statathon123 `
  neo4j:5

# Web UI: http://localhost:7474
```

Add to `.env`:
```ini
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=statathon123
```

---

## 7. ColPali — Vision Model Service

ColPali converts PDF pages to structured JSON (tables, charts, regions, entities).
It requires a GPU; on CPU it will run very slowly.

### Quick start — Docker (recommended)
```powershell
# Pull pre-built image (bharatstat/colpali-service:latest)
docker pull bharatstat/colpali-service:latest

# GPU mode
docker run -d --name colpali --gpus all `
  -p 8100:8100 `
  -e MODEL_ID=vidore/colpali-v1.2 `
  bharatstat/colpali-service:latest

# CPU-only mode (slow but works for testing)
docker run -d --name colpali `
  -p 8100:8100 `
  -e DEVICE=cpu `
  bharatstat/colpali-service:latest
```

### Using docker-compose (includes all services)
```powershell
docker-compose up -d colpali
```

### Verify health
```powershell
Invoke-RestMethod http://localhost:8100/health
# → {"status":"ok","model":"vidore/colpali-v1.2"}
```

### Model download (if running from source)
```powershell
# ColPali model is ~4 GB
pip install colpali-engine
python -c "from colpali_engine.models import ColPali; ColPali.from_pretrained('vidore/colpali-v1.2')"
```

---

## 8. SGLang — Grammar-Constrained LLM Server

SGLang serves the Qwen 2.5 7B model with JSON schema enforcement (grammar-constrained
decoding). It generates the structured AST JSON.

### Install SGLang
```powershell
pip install "sglang[all]>=0.3"
pip install flashinfer -i https://flashinfer.ai/whl/cu121/torch2.4/
```

### Download model (Qwen2.5-7B-Instruct, ~15 GB)
```powershell
pip install huggingface-hub
python -c "
from huggingface_hub import snapshot_download
snapshot_download('Qwen/Qwen2.5-7B-Instruct', local_dir='C:/models/qwen2.5-7b')
"
```

### Start SGLang server
```powershell
# GPU (recommended, uses ~15 GB VRAM)
python -m sglang.launch_server `
  --model-path C:/models/qwen2.5-7b `
  --port 30000 `
  --mem-fraction-static 0.85 `
  --tp 1

# Or smaller model for 8 GB VRAM:
# --model-path Qwen/Qwen2.5-3B-Instruct
```

### Verify
```powershell
Invoke-RestMethod http://localhost:30000/health
# → {"status":"healthy"}
```

---

## 9. FastAPI Backend

```powershell
cd C:\Users\2504690\syl\statathon
.venv\Scripts\Activate.ps1

# Development server (auto-reload)
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Production (4 workers)
uvicorn api.main:app --workers 4 --host 0.0.0.0 --port 8000
```

### Verify
```powershell
Invoke-RestMethod http://localhost:8000/health
# → {"status":"ok"}

# Swagger docs
Start-Process "http://localhost:8000/docs"
```

---

## 10. Next.js Dashboard

```powershell
cd C:\Users\2504690\syl\statathon\dashboard

# Install JS dependencies
npm install

# Development server
npm run dev
# → http://localhost:3000

# Production build
npm run build
npm start
```

The `dashboard/.env.local` is already configured with:
```ini
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 11. Running Tests

### Tier 1 — Unit tests (no external services)
```powershell
cd C:\Users\2504690\syl\statathon
.venv\Scripts\Activate.ps1

# Original 111 tests
python -m pytest tests/test_template_engine/ -q --tb=short -m "not live"

# Enhanced env-aware tests (65 more)
python -m pytest tests/test_template_engine/test_enhanced_with_env.py -q --tb=short -m "not live"

# All together
python -m pytest tests/test_template_engine/ -q --tb=short -m "not live"
# Expected: ~176 passed, 6 skipped
```

### Tier 2 — Live Gemini API
```powershell
# Requires GEMINI_API_KEY in .env (already configured)
python -m pytest tests/test_template_engine/test_enhanced_with_env.py -m live_llm -v --tb=short
```

### Tier 3 — Live ColPali
```powershell
# Requires ColPali Docker running on port 8100
$env:COLPALI_ENDPOINT = "http://localhost:8100"
python -m pytest tests/test_template_engine/test_enhanced_with_env.py -m live_vlm -v --tb=short
```

### Tier 4 — Live SGLang
```powershell
# Requires SGLang server running on port 30000
$env:SGLANG_ENDPOINT = "http://localhost:30000"
python -m pytest tests/test_template_engine/test_enhanced_with_env.py -m live_sglang -v --tb=short
```

### Tier 5 — Live Supabase DB
```powershell
# Requires DATABASE_URL with live Supabase (already in .env)
python -m pytest tests/test_template_engine/test_enhanced_with_env.py -m live_db -v --tb=short
```

### Tier 6 — Live Cloudflare R2
```powershell
# Requires S3 credentials in .env (already configured)
python -m pytest tests/test_template_engine/test_enhanced_with_env.py -m live_s3 -v --tb=short
```

### Full end-to-end verification script
```powershell
python -m pytest tests/verify_full.py -s -q --no-header
# → === ALL VERIFICATION STAGES PASSED ===
```

### All live tests at once (everything running)
```powershell
$env:COLPALI_ENDPOINT = "http://localhost:8100"
$env:SGLANG_ENDPOINT  = "http://localhost:30000"
python -m pytest tests/test_template_engine/ -m live -v --tb=short
```

---

## 12. Running the Template Engine End-to-End

### Option A — Python REPL / script (mock mode, no GPU needed)
```python
from pathlib import Path
from template_engine.pipeline import run_extraction_pipeline

result = run_extraction_pipeline(
    pdf_path=Path("sample_reports/mospi_survey.pdf"),
    template_name="MoSPI Household Expenditure Survey 2024",
    vlm_backend="mock",        # change to "colpali" when Docker is running
    sglang_backend="mock",     # change to "sglang" when server is running
    progress_callback=lambda p: print(f"  [{p.pct_complete:3.0f}%] {p.stage}: {p.message}"),
)

print(f"Success: {result.success}")
print(f"Template ID: {result.ast.templateId}")
print(f"Topics: {len(result.ast.topics)}")
print(f"Questions: {len(result.ast.all_questions())}")
print(f"Entities: {len(result.ast.entities)}")
print(f"Review: {result.review.decision}")
print(f"Hash: {result.source_hash}")

# Export to JSON
import json
with open("outputs/my_template.json", "w") as f:
    json.dump(result.ast.to_dict(), f, indent=2)
```

### Option B — Real models (GPU required)
```python
# Ensure ColPali and SGLang servers are running, then:
result = run_extraction_pipeline(
    pdf_path=Path("your_report.pdf"),
    template_name="My Report",
    vlm_backend="colpali",      # ← real vision model
    sglang_backend="sglang",    # ← real LLM
)
```

### Option C — Via FastAPI endpoint
```powershell
# Upload PDF and extract template
$pdf = "C:\path\to\report.pdf"
$headers = @{"Authorization" = "Bearer $token"}
$form = @{file = Get-Item $pdf; template_name = "My Report"}

Invoke-RestMethod `
  -Uri "http://localhost:8000/api/template/extract" `
  -Method POST `
  -Headers $headers `
  -Form $form
```

---

## 13. Full One-Command Stack Start

A convenience script to start all services:

```powershell
# Start all Docker services defined in docker-compose.yml
cd C:\Users\2504690\syl\statathon
docker-compose up -d

# Start SGLang (GPU, background)
Start-Job -Name sglang -ScriptBlock {
    cd C:\Users\2504690\syl\statathon
    .venv\Scripts\Activate.ps1
    python -m sglang.launch_server `
      --model-path C:/models/qwen2.5-7b `
      --port 30000
}

# Start FastAPI backend
Start-Job -Name api -ScriptBlock {
    cd C:\Users\2504690\syl\statathon
    .venv\Scripts\Activate.ps1
    uvicorn api.main:app --reload --port 8000
}

# Start dashboard
Start-Job -Name dashboard -ScriptBlock {
    cd C:\Users\2504690\syl\statathon\dashboard
    npm run dev
}

Write-Host "Stack starting..."
Write-Host "  API:       http://localhost:8000/docs"
Write-Host "  Dashboard: http://localhost:3000"
Write-Host "  ColPali:   http://localhost:8100/health"
Write-Host "  SGLang:    http://localhost:30000/health"
```

---

## 14. Troubleshooting

### `ModuleNotFoundError: No module named 'template_engine'`
```powershell
# Ensure you're in the repo root and venv is active
cd C:\Users\2504690\syl\statathon
.venv\Scripts\Activate.ps1
# The conftest.py adds repo root to sys.path automatically for pytest
# For scripts, use:
$env:PYTHONPATH = "C:\Users\2504690\syl\statathon"
```

### `google.generativeai` FutureWarning
This is a warning only, not an error. The code falls back gracefully. To suppress:
```powershell
$env:PYTHONWARNINGS = "ignore::FutureWarning"
python -m pytest ...
```

### ColPali returns 404 / not reachable
```powershell
docker ps | Select-String colpali
docker logs colpali --tail 30
# Ensure port 8100 is exposed and not blocked by firewall
```

### SGLang OOM (Out of Memory)
```powershell
# Use a smaller model or reduce memory fraction:
python -m sglang.launch_server `
  --model-path Qwen/Qwen2.5-3B-Instruct `
  --port 30000 `
  --mem-fraction-static 0.70
```

### Supabase connection timeout
```powershell
# Test connection directly:
python -c "
from sqlalchemy import create_engine, text
import os; from dotenv import load_dotenv; load_dotenv()
e = create_engine(os.getenv('DATABASE_URL'))
print(e.connect().execute(text('SELECT 1')).scalar())
"
# → 1
```

### R2/S3 403 Forbidden
- Verify `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in `.env` match your R2 API token
- Ensure the token has `Object Read & Write` permissions on the bucket
- Check `S3_ENDPOINT_URL` ends with `.r2.cloudflarestorage.com` (no trailing slash)

### Next.js `NEXT_PUBLIC_API_URL` not set
```powershell
# dashboard/.env.local must contain:
# NEXT_PUBLIC_API_URL=http://localhost:8000
# Restart `npm run dev` after editing .env.local
```

---

## Quick Reference — Key Commands

```powershell
# Activate venv
.venv\Scripts\Activate.ps1

# Run all unit tests (fast, no external deps)
python -m pytest tests/test_template_engine/ -q -m "not live"

# Run full verification
python -m pytest tests/verify_full.py -s -q

# Run template engine on a PDF (mock mode)
python -c "
from pathlib import Path
from template_engine.pipeline import run_extraction_pipeline
r = run_extraction_pipeline(Path('sample_reports/mospi_survey.pdf'), 'Test', vlm_backend='mock', sglang_backend='mock')
print(r.ast.templateId, r.review.decision)
"

# Start API
uvicorn api.main:app --reload --port 8000

# Start dashboard
cd dashboard; npm run dev

# Start all Docker services
docker-compose up -d
```
