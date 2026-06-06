# GPU Laptop Deployment Guide — Enterprise Document AST Pipeline

> **Branch:** `feature/rev-template`  
> **GPU Compatibility:** RTX 4050 (SM89, 6GB) / RTX 3050 (SM86, 6GB)  
> **Last verified:** Phase 2 complete — all 9 checks pass

---

## Architecture Overview

```
┌──────────┐     ┌────────────────┐     ┌──────────────────┐     ┌───────────┐
│ Dashboard │────▶│   API Server   │────▶│  LayoutLMv3 CPU  │     │   Neo4j   │
│ Next.js   │     │  FastAPI:8000  │     │  Layout:8001     │     │  :7687    │
│ :3000     │     └───────┬────────┘     └──────────────────┘     └───────────┘
└──────────┘              │
                          │              ┌──────────────────┐     ┌───────────┐
                          └─────────────▶│  vLLM (Qwen-VL)  │     │   Redis   │
                                         │  Vision:8002 GPU │     │  :6379    │
                                         └──────────────────┘     └───────────┘
```

**Pipeline Flow (V2):**
```
PDF → Rasterize → LayoutLMv3 (layout detection, CPU)
    → Qwen2.5-VL-7B-AWQ (content extraction, GPU)
    → Semantic analysis → AST assembly → Gemini enrichment
    → Enterprise Document AST JSON
```

---

## Prerequisites

### 1. System Requirements
- **Docker Desktop** ≥ 4.25 with WSL2 backend + NVIDIA Container Toolkit
- **NVIDIA Driver** ≥ 535 (check: `nvidia-smi`)
- **Git** for Windows
- **Node.js** ≥ 18 (only if running frontend locally without Docker)
- **Python** 3.11+ (only if running API locally without Docker)

### 2. Verify GPU Access in Docker
```powershell
# Must show your GPU name and VRAM
docker run --rm --gpus all nvidia/cuda:12.1-base nvidia-smi
```

If this fails:
```powershell
# Fix WSL2 GPU passthrough
wsl --shutdown
# Restart Docker Desktop
# Re-run the test
```

### 3. Verify Docker BuildKit
```powershell
# Should output BuildKit version
docker buildx version
```

---

## First-Time Setup

### Step 1: Clone and Checkout

```powershell
cd C:\Users\2504690\syl
git clone <repo-url> statathon   # skip if already cloned
cd statathon
git checkout feature/rev-template
git pull origin feature/rev-template
```

### Step 2: Create Model Cache Directory

```powershell
# This persists model weights across Docker rebuilds
mkdir -p model/cache
mkdir -p outputs
mkdir -p checkpoints
mkdir -p data
```

### Step 3: Configure .env

The `.env` file should already be configured. Verify key settings:

```powershell
# Check critical V2 pipeline vars are set
Select-String -Path .env -Pattern "EXTRACTION_PIPELINE|LAYOUTLM_ENDPOINT|SGLANG_MODEL|PIPELINE_GPU_MODE"
```

Expected output:
```
EXTRACTION_PIPELINE=v2
LAYOUTLM_ENDPOINT=http://localhost:8001
SGLANG_MODEL=Qwen/Qwen2.5-VL-7B-Instruct-AWQ
PIPELINE_GPU_MODE=sequential
```

**POPPLER_PATH** — Update for your machine:
```
# RTX 4050 laptop (Sanjay):
POPPLER_PATH="C:\Users\SANJAY S\Downloads\Release-26.02.0-0\poppler-26.02.0\Library\bin"

# HP Victus (if different path):
POPPLER_PATH="C:\path\to\poppler\bin"
```

> **Note:** POPPLER_PATH is only needed for local (non-Docker) API runs. Inside Docker, poppler is installed via apt in the Dockerfile.

---

## Build All Docker Images (One-Time)

```powershell
# Enable BuildKit for cache mounts
$env:DOCKER_BUILDKIT = 1
$env:COMPOSE_DOCKER_CLI_BUILD = 1

# Build ALL services (including GPU profile)
docker compose -f docker-compose.gpu.yml --profile gpu build
```

**Expected build times (first time):**
| Service | Time | Notes |
|---------|------|-------|
| layoutlm | 3-5 min | Downloads PyTorch CPU (~2GB) |
| sglang | 1-2 min | Base image has vLLM pre-installed |
| api | 2-3 min | Installs all Python deps |
| dashboard | 2-4 min | `npm ci` + Next.js build |
| neo4j | <30s | Pull only |
| redis | <10s | Pull only |

**Subsequent builds:** <30s (only changed layers rebuild)

---

## Running the Full Stack

### Option A: Full Docker Stack (Recommended)

```powershell
# Step 1: Start infrastructure (Redis + Neo4j)
docker compose -f docker-compose.gpu.yml up -d neo4j redis

# Step 2: Start LayoutLM (CPU) — waits for health check
docker compose -f docker-compose.gpu.yml --profile gpu up -d layoutlm

# Step 3: Start vLLM (GPU) — takes 30-180s on first boot (model download)
docker compose -f docker-compose.gpu.yml --profile gpu up -d sglang

# Step 4: Wait for GPU model to be ready
docker compose -f docker-compose.gpu.yml --profile gpu logs -f sglang
# Wait until you see: "Started server process" or health check passes

# Step 5: Start API + Dashboard
docker compose -f docker-compose.gpu.yml up -d api dashboard
```

**Verify everything is running:**
```powershell
docker compose -f docker-compose.gpu.yml --profile gpu ps
```

Expected output:
```
NAME        SERVICE     STATUS          PORTS
layoutlm    layoutlm    Up (healthy)    0.0.0.0:8001->8001/tcp
sglang      sglang      Up (healthy)    0.0.0.0:8002->8002/tcp
api         api         Up              0.0.0.0:8000->8000/tcp
dashboard   dashboard   Up              0.0.0.0:3000->3000/tcp
neo4j       neo4j       Up              0.0.0.0:7474->7474/tcp, 7687/tcp
redis       redis       Up              0.0.0.0:6379->6379/tcp
```

### Option B: Local Frontend + Dockerized Backend

```powershell
# Start backend services in Docker
docker compose -f docker-compose.gpu.yml --profile gpu up -d layoutlm sglang neo4j redis api

# Run frontend locally (faster hot-reload for development)
cd dashboard
npm install
npm run dev
# → Frontend at http://localhost:3000
```

### Option C: Everything Local (No Docker except GPU)

```powershell
# Only GPU model in Docker (no CUDA toolkit needed locally)
docker compose -f docker-compose.gpu.yml --profile gpu up -d sglang

# LayoutLM locally (requires Python 3.11+ with torch)
cd services/layoutlm
pip install -r requirements.txt
python main.py
# → LayoutLM at http://localhost:8001

# API locally
cd ../..
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
# → API at http://localhost:8000

# Frontend locally
cd dashboard
npm run dev
# → Dashboard at http://localhost:3000
```

---

## Running the V2 Pipeline (Process a PDF)

### Via Docker (recommended):
```powershell
# Copy your PDF into the data/ directory
Copy-Item "C:\path\to\your\report.pdf" ./data/input.pdf

# Run the pipeline
docker compose -f docker-compose.gpu.yml --profile gpu run --rm `
    -e PDF_INPUT_PATH=/app/data/input.pdf `
    -e TEMPLATE_NAME="Energy Statistics 2025" `
    pipeline

# Output will be in ./outputs/enterprise_ast_<hash>.json
```

### Via API endpoint:
```powershell
# Upload PDF and trigger extraction
curl -X POST http://localhost:8000/api/v1/templates/compile `
    -F "file=@./data/input.pdf" `
    -F "template_name=Energy Statistics 2025"
```

### Via local script:
```powershell
$env:PDF_INPUT_PATH = "C:\Users\2504690\syl\statathon\data\input.pdf"
$env:TEMPLATE_NAME = "Energy Statistics 2025"
$env:OUTPUT_DIR = "./outputs"
$env:EXTRACTION_PIPELINE = "v2"
C:\dev\src\cne-platform-venv\Scripts\python.exe scripts/run_pipeline.py
```

---

## Verify the Output

```powershell
# Check the generated AST
C:\dev\src\cne-platform-venv\Scripts\python.exe -c "
import json, sys
sys.path.insert(0, '.')
from report_builder.ast_schema import EnterpriseDocumentAST
from pathlib import Path

# Find latest output
outputs = sorted(Path('outputs').glob('enterprise_ast_*.json'), key=lambda p: p.stat().st_mtime)
if not outputs:
    print('No outputs found yet'); sys.exit(1)

latest = outputs[-1]
ast = EnterpriseDocumentAST.model_validate_json(latest.read_text())
s = ast.summary()
print(f'File: {latest.name}')
for k, v in s.items():
    print(f'  {k}: {v}')
"
```

---

## Health Check Endpoints

| Service | URL | Expected |
|---------|-----|----------|
| LayoutLM | http://localhost:8001/health | `{"status":"ok"}` |
| vLLM | http://localhost:8002/health | `{"status":"ok"}` |
| API | http://localhost:8000/docs | Swagger UI |
| Dashboard | http://localhost:3000 | Next.js app |
| Neo4j Browser | http://localhost:7474 | Neo4j UI |

```powershell
# Quick health check all services
@("http://localhost:8001/health", "http://localhost:8002/health", "http://localhost:8000/docs") | ForEach-Object {
    try { 
        $r = Invoke-WebRequest -Uri $_ -TimeoutSec 5 -ErrorAction Stop
        Write-Host "OK  $_ ($($r.StatusCode))"
    } catch { 
        Write-Host "FAIL $_"
    }
}
```

---

## Stopping & Cleanup

```powershell
# Stop everything
docker compose -f docker-compose.gpu.yml --profile gpu down

# Stop but keep volumes (model cache, neo4j data)
docker compose -f docker-compose.gpu.yml --profile gpu down --remove-orphans

# Full cleanup (removes cached models — next start will re-download!)
docker compose -f docker-compose.gpu.yml --profile gpu down -v
```

---

## Troubleshooting

### 1. vLLM OOM (Out of Memory)

**Symptoms:** `sglang` container crashes with CUDA OOM  
**Cause:** Not enough free VRAM (display driver uses ~1.05GB)

```powershell
# Check what's using VRAM
nvidia-smi

# If another process holds VRAM, kill it
# Then restart sglang:
docker compose -f docker-compose.gpu.yml --profile gpu restart sglang
```

**For HP Victus (RTX 3050, tighter VRAM):** Edit `docker/sglang-entrypoint.sh`:
```bash
--gpu-memory-utilization 0.78   # reduced from 0.82
--max-model-len 1024            # reduced from 2048
```

### 2. Model Download Timeout

**Symptoms:** `sglang` stays unhealthy for >5 min  
**Cause:** First-run model download (~3GB) is slow

```powershell
# Check download progress
docker compose -f docker-compose.gpu.yml --profile gpu logs -f sglang

# Pre-download the model (saves time on first docker run):
docker run --rm -v "${PWD}/model/cache:/cache" -e HF_HOME=/cache python:3.11 `
    pip install huggingface_hub && python -c "
from huggingface_hub import snapshot_download
snapshot_download('Qwen/Qwen2.5-VL-7B-Instruct-AWQ', cache_dir='/cache')
"
```

### 3. LayoutLM First-Run Slow

**Symptoms:** `layoutlm` health check fails initially  
**Cause:** First run downloads `microsoft/layoutlmv3-large` (~1.4GB)

```powershell
# Check progress
docker compose -f docker-compose.gpu.yml --profile gpu logs -f layoutlm

# The model is cached in ./model/cache — subsequent starts are instant
```

### 4. Dashboard Build Fails

**Symptoms:** `COPY dashboard/package.json` fails  
**Cause:** Docker context not set to repository root

```powershell
# Verify you're running from the repo root
Get-Location  # should be C:\Users\2504690\syl\statathon

# Build with explicit context
docker build -f docker/Dockerfile.dashboard -t statathon-dashboard .
```

### 5. WSL2 GPU Not Detected

```powershell
# Full reset
wsl --shutdown
# Restart Docker Desktop (Settings → General → "Use WSL2 based engine" checked)
# Verify
docker run --rm --gpus all nvidia/cuda:12.1-base nvidia-smi
```

### 6. Port Conflicts

```powershell
# Check what's using the ports
netstat -ano | Select-String "8000|8001|8002|3000|7687|6379"

# Kill conflicting process
Stop-Process -Id <PID> -Force
```

### 7. Pipeline Checkpoint Resume

If the pipeline crashes mid-way, it saves checkpoints:
```powershell
# Resume from last checkpoint
docker compose -f docker-compose.gpu.yml --profile gpu run --rm `
    -e CHECKPOINT_ENABLED=true `
    pipeline

# Force fresh run (ignore checkpoints)
Remove-Item ./checkpoints/* -Recurse -Force
docker compose -f docker-compose.gpu.yml --profile gpu run --rm pipeline
```

---

## VRAM Budget Reference

| Component | VRAM Usage |
|-----------|-----------|
| NVIDIA display driver | ~1.05 GB |
| Qwen2.5-VL-7B-AWQ weights | ~4.0 GB |
| KV cache (max_model_len=2048) | ~0.5 GB |
| **Total required** | **~5.55 GB** |
| RTX 4050 total | 6.0 GB |
| RTX 3050 total | 6.0 GB |
| **Headroom** | **~0.45 GB** |

> The `--enforce-eager` flag saves ~500MB by disabling CUDA graphs.  
> Sequential mode means LayoutLM (CPU) finishes before vLLM (GPU) needs all VRAM.

---

## Daily Workflow

```powershell
# Morning: Start the stack
cd C:\Users\2504690\syl\statathon
docker compose -f docker-compose.gpu.yml --profile gpu up -d

# Process a PDF
Copy-Item "C:\path\to\report.pdf" ./data/input.pdf
docker compose -f docker-compose.gpu.yml --profile gpu run --rm pipeline

# Evening: Stop (keeps cached models)
docker compose -f docker-compose.gpu.yml --profile gpu down
```

---

## File Reference

| File | Purpose |
|------|---------|
| `docker-compose.gpu.yml` | GPU pipeline orchestration (7 services) |
| `docker-compose.yml` | Non-GPU dev environment (4 services) |
| `docker/Dockerfile.sglang` | vLLM GPU server (Qwen2.5-VL-7B-AWQ) |
| `docker/Dockerfile.layoutlm` | LayoutLMv3 CPU layout detection |
| `docker/Dockerfile.api` | FastAPI server + pipeline runner |
| `docker/Dockerfile.dashboard` | Next.js standalone build |
| `docker/sglang-entrypoint.sh` | vLLM startup with VRAM diagnostics |
| `scripts/run_pipeline.py` | Pipeline entry point (V1/V2 routing) |
| `report_builder/extraction_pipeline.py` | V2 5-pass extraction pipeline |
| `report_builder/ast_schema.py` | Enterprise AST Pydantic schema |
| `report_builder/entity_engine.py` | Entity/slot/fact extraction |
| `report_builder/gemini_enrichment.py` | Gemini post-processing |
| `report_builder/chunking.py` | ToC-aware late chunking |
| `.env` | All configuration (V1/V2 toggle, endpoints, keys) |
