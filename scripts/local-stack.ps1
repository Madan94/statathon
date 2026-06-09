#!/usr/bin/env pwsh
# ─────────────────────────────────────────────────────────────────────────────
# LOCAL STACK — Run all services WITHOUT Docker
# Models cached in ./model/cache (shared with Docker volumes)
#
# Usage:
#   .\scripts\local-stack.ps1 -Service all       # Everything
#   .\scripts\local-stack.ps1 -Service vllm      # Just vLLM (GPU)
#   .\scripts\local-stack.ps1 -Service layoutlm  # Just LayoutLM (CPU)
#   .\scripts\local-stack.ps1 -Service api       # Just API
#   .\scripts\local-stack.ps1 -Service dashboard  # Just Dashboard
#   .\scripts\local-stack.ps1 -Service infra     # Neo4j + Redis (Docker minimal)
#
# Prerequisites:
#   - Python 3.12+ with venv at .\.venv
#   - Node.js 18+ (for dashboard)
#   - NVIDIA GPU + CUDA 12.x (for vLLM)
#   - Tesseract OCR installed (for LayoutLM)
#   - Poppler (pdftoimage) installed (for LayoutLM)
#
# Model Cache:
#   All models download to ./model/cache/
#   This is the SAME path mounted in Docker (docker-compose volumes: ./model/cache:/cache)
#   So: run locally first → models cached → Docker uses same cache → no re-download!
# ─────────────────────────────────────────────────────────────────────────────

param(
    [ValidateSet("all", "vllm", "layoutlm", "api", "dashboard", "infra")]
    [string]$Service = "all"
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ROOT

# ── Shared Config ────────────────────────────────────────────────────────────
$MODEL_CACHE = Join-Path $ROOT "model\cache"
$HF_TOKEN = $env:HF_TOKEN
if (-not $HF_TOKEN) {
    Write-Host "⚠ HF_TOKEN not set. Gated models (Qwen) will fail." -ForegroundColor Yellow
    Write-Host "  Set with: `$env:HF_TOKEN = 'hf_xxxxx'" -ForegroundColor Yellow
}

# Ensure cache dir exists
New-Item -ItemType Directory -Path $MODEL_CACHE -Force | Out-Null

# ── Environment Variables (shared across all services) ───────────────────────
$env:HF_HOME = $MODEL_CACHE
$env:HUGGINGFACE_HUB_CACHE = Join-Path $MODEL_CACHE "hub"
$env:PYTHONPATH = $ROOT
$env:APP_ENV = "development"
$env:AUTH_REQUIRED = "false"
$env:DATABASE_URL = "sqlite:///./statathon_local.db"
$env:NEO4J_URI = "bolt://localhost:7687"
$env:NEO4J_PASSWORD = "mospi_secure_password"
$env:REDIS_URL = "redis://localhost:6379/0"
$env:LAYOUTLM_ENDPOINT = "http://localhost:8001"
$env:SGLANG_ENDPOINT = "http://localhost:8002"
$env:EXTRACTION_PIPELINE = "v2"
$env:CHECKPOINT_ENABLED = "true"
$env:LOG_LEVEL = "INFO"
$env:CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Local Stack — Service: $Service" -ForegroundColor Cyan
Write-Host "  Model Cache: $MODEL_CACHE" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── Functions ────────────────────────────────────────────────────────────────

function Start-Infra {
    Write-Host "▶ Starting Infrastructure (Neo4j + Redis via Docker)..." -ForegroundColor Green
    Write-Host "  Neo4j: http://localhost:7474 (bolt://localhost:7687)"
    Write-Host "  Redis: localhost:6379"
    Write-Host ""
    docker run -d --name statathon-neo4j -p 7474:7474 -p 7687:7687 `
        -e NEO4J_AUTH="neo4j/mospi_secure_password" `
        -v "${ROOT}\data\neo4j:/data" `
        neo4j:5-community 2>$null
    docker run -d --name statathon-redis -p 6379:6379 redis:7-alpine 2>$null
    Write-Host "  ✓ Infrastructure ready" -ForegroundColor Green
}

function Start-LayoutLM {
    Write-Host "▶ Starting LayoutLM (CPU, port 8001)..." -ForegroundColor Green
    $modelId = $env:LAYOUTLM_MODEL_ID
    if (-not $modelId) { $modelId = $env:LAYOUTLM_MODEL }
    if (-not $modelId) { $modelId = $env:MODEL_ID }
    if (-not $modelId) { $modelId = "microsoft/layoutlmv3-large" }
    Write-Host "  Model: $modelId"
    Write-Host "  First run downloads model weights to $MODEL_CACHE"
    Write-Host ""
    
    $env:MODEL_ID = $modelId
    if (-not $env:LAYOUTLM_MODEL_ID) { $env:LAYOUTLM_MODEL_ID = $modelId }
    $env:LAYOUTLM_PORT = "8001"
    $env:MAX_PAGES = "100"
    
    $venvPython = Join-Path $ROOT ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "  ✗ No .venv found. Create with:" -ForegroundColor Red
        Write-Host "    python -m venv .venv" -ForegroundColor Red
        Write-Host "    .\.venv\Scripts\activate" -ForegroundColor Red
        Write-Host "    pip install -r services/layoutlm/requirements.txt" -ForegroundColor Red
        return
    }
    
    Start-Process -FilePath $venvPython -ArgumentList "-u", "services/layoutlm/main.py" `
        -WorkingDirectory $ROOT -NoNewWindow -PassThru
    Write-Host "  ✓ LayoutLM starting on http://localhost:8001" -ForegroundColor Green
}

function Start-VLLM {
    Write-Host "▶ Starting vLLM (GPU, port 8002)..." -ForegroundColor Green
    Write-Host "  Model: Qwen/Qwen2.5-VL-3B-Instruct-AWQ (~2.5GB download)"
    Write-Host "  Needs: NVIDIA GPU with ≥5GB free VRAM, CUDA 12.x"
    Write-Host ""
    
    # Check NVIDIA
    $nvsmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $nvsmi) {
        Write-Host "  ✗ nvidia-smi not found. Install NVIDIA drivers." -ForegroundColor Red
        return
    }
    
    $freeVram = (nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | Select-Object -First 1).Trim()
    Write-Host "  GPU VRAM free: ${freeVram}MB"
    if ([int]$freeVram -lt 5000) {
        Write-Host "  ⚠ Only ${freeVram}MB free — need 5000MB. Close GPU apps." -ForegroundColor Yellow
    }
    
    $MODEL = if ($env:VLLM_MODEL) { $env:VLLM_MODEL } else { "Qwen/Qwen2.5-VL-3B-Instruct-AWQ" }
    
    $vllmArgs = @(
        "-m", "vllm.entrypoints.openai.api_server",
        "--model", $MODEL,
        "--host", "0.0.0.0",
        "--port", "8002",
        "--gpu-memory-utilization", "0.90",
        "--max-model-len", "4096",
        "--enforce-eager",
        "--max-num-seqs", "1",
        "--limit-mm-per-prompt", '{"image": 1}',
        "--trust-remote-code",
        "--download-dir", $MODEL_CACHE
    )
    
    Write-Host "  Command: python $($vllmArgs -join ' ')" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  ⏳ First run: downloads ~2.5GB + FlashAttention JIT compile (2-7 min)" -ForegroundColor Yellow
    Write-Host ""
    
    # Run in current terminal (GPU process — needs to see output)
    $venvPython = Join-Path $ROOT ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        # Try system python
        $venvPython = "python"
    }
    
    Start-Process -FilePath $venvPython -ArgumentList $vllmArgs `
        -WorkingDirectory $ROOT -NoNewWindow -PassThru
    Write-Host "  ✓ vLLM starting on http://localhost:8002" -ForegroundColor Green
}

function Start-API {
    Write-Host "▶ Starting API (port 8000)..." -ForegroundColor Green
    Write-Host "  Endpoints: http://localhost:8000/docs (Swagger)"
    Write-Host ""
    
    $venvPython = Join-Path $ROOT ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "  ✗ No .venv found." -ForegroundColor Red
        return
    }
    
    $apiArgs = @("-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload", "--log-level", "info")
    Start-Process -FilePath $venvPython -ArgumentList $apiArgs `
        -WorkingDirectory $ROOT -NoNewWindow -PassThru
    Write-Host "  ✓ API starting on http://localhost:8000" -ForegroundColor Green
}

function Start-Dashboard {
    Write-Host "▶ Starting Dashboard (port 3000)..." -ForegroundColor Green
    Write-Host "  URL: http://localhost:3000"
    Write-Host ""
    
    $dashDir = Join-Path $ROOT "dashboard"
    if (-not (Test-Path (Join-Path $dashDir "node_modules"))) {
        Write-Host "  Installing dependencies..." -ForegroundColor Yellow
        Push-Location $dashDir
        npm install
        Pop-Location
    }
    
    $env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
    Start-Process -FilePath "npm" -ArgumentList "run", "dev" `
        -WorkingDirectory $dashDir -NoNewWindow -PassThru
    Write-Host "  ✓ Dashboard starting on http://localhost:3000" -ForegroundColor Green
}

# ── Main ─────────────────────────────────────────────────────────────────────

switch ($Service) {
    "all" {
        Start-Infra
        Write-Host ""
        Start-Sleep -Seconds 3
        Start-LayoutLM
        Write-Host ""
        Start-VLLM
        Write-Host ""
        Start-API
        Write-Host ""
        Start-Dashboard
    }
    "vllm"      { Start-VLLM }
    "layoutlm"  { Start-LayoutLM }
    "api"       { Start-API }
    "dashboard" { Start-Dashboard }
    "infra"     { Start-Infra }
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Services Status:" -ForegroundColor Cyan
Write-Host "    LayoutLM:  http://localhost:8001/health" -ForegroundColor White
Write-Host "    vLLM:      http://localhost:8002/health" -ForegroundColor White
Write-Host "    API:       http://localhost:8000/docs" -ForegroundColor White
Write-Host "    Dashboard: http://localhost:3000" -ForegroundColor White
Write-Host "    Neo4j:     http://localhost:7474" -ForegroundColor White
Write-Host "    Redis:     localhost:6379" -ForegroundColor White
Write-Host ""
Write-Host "  Model Cache: $MODEL_CACHE" -ForegroundColor DarkGray
Write-Host "  (Same dir used by Docker — no re-download!)" -ForegroundColor DarkGray
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop. Use 'scripts\local-stop.ps1' to cleanup." -ForegroundColor Yellow
