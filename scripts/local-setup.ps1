#!/usr/bin/env pwsh
# ─────────────────────────────────────────────────────────────────────────────
# ONE-TIME SETUP for local development on GPU laptop (RTX 4050, 6GB VRAM)
#
# Run this ONCE to:
#   1. Create Python venv
#   2. Install all dependencies (Windows-optimized)
#   3. Install vLLM with CUDA support
#   4. Install LayoutLM service deps
#   5. Install dashboard deps (Node.js)
#   6. Pre-download models to shared cache
#
# After this, run: .\scripts\local-stack.ps1 -Service all
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ROOT

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Statathon — Local Setup (GPU Laptop)" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Python venv ──────────────────────────────────────────────────────
Write-Host "▶ Step 1/6: Python virtual environment" -ForegroundColor Green
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Host "  ✓ Created .venv"
} else {
    Write-Host "  ✓ .venv already exists"
}

$venvPip = Join-Path $ROOT ".venv\Scripts\pip.exe"
$venvPython = Join-Path $ROOT ".venv\Scripts\python.exe"

# ── Step 2: Core Python deps ────────────────────────────────────────────────
Write-Host ""
Write-Host "▶ Step 2/6: Python dependencies (requirements-windows.txt)" -ForegroundColor Green
& $venvPip install --upgrade pip
& $venvPip install -r requirements-windows.txt
Write-Host "  ✓ Core deps installed"

# ── Step 3: vLLM with CUDA ──────────────────────────────────────────────────
Write-Host ""
Write-Host "▶ Step 3/6: vLLM (GPU inference engine)" -ForegroundColor Green
Write-Host "  Installing vLLM... (this may take 5-10 min)"
& $venvPip install vllm
Write-Host "  ✓ vLLM installed"

# ── Step 4: LayoutLM service deps ───────────────────────────────────────────
Write-Host ""
Write-Host "▶ Step 4/6: LayoutLM service dependencies" -ForegroundColor Green
& $venvPip install -r services/layoutlm/requirements.txt
Write-Host "  ✓ LayoutLM deps installed"

# Check tesseract
$tess = Get-Command tesseract -ErrorAction SilentlyContinue
if (-not $tess) {
    Write-Host "  ⚠ Tesseract OCR not found!" -ForegroundColor Yellow
    Write-Host "    Install from: https://github.com/UB-Mannheim/tesseract/wiki" -ForegroundColor Yellow
    Write-Host "    Or: winget install UB-Mannheim.TesseractOCR" -ForegroundColor Yellow
}

# Check poppler
$poppler = Get-Command pdftoppm -ErrorAction SilentlyContinue
if (-not $poppler) {
    Write-Host "  ⚠ Poppler (pdftoppm) not found!" -ForegroundColor Yellow
    Write-Host "    Install from: https://github.com/oschwartz10612/poppler-windows/releases" -ForegroundColor Yellow
    Write-Host "    Add to PATH after install" -ForegroundColor Yellow
}

# ── Step 5: Dashboard (Node.js) ─────────────────────────────────────────────
Write-Host ""
Write-Host "▶ Step 5/6: Dashboard (Next.js)" -ForegroundColor Green
Push-Location dashboard
npm install
Pop-Location
Write-Host "  ✓ Dashboard deps installed"

# ── Step 6: Pre-download models ─────────────────────────────────────────────
Write-Host ""
Write-Host "▶ Step 6/6: Pre-download models to shared cache" -ForegroundColor Green

$MODEL_CACHE = Join-Path $ROOT "model\cache"
New-Item -ItemType Directory -Path $MODEL_CACHE -Force | Out-Null
$env:HF_HOME = $MODEL_CACHE
$env:HUGGINGFACE_HUB_CACHE = Join-Path $MODEL_CACHE "hub"

Write-Host "  Cache directory: $MODEL_CACHE"
Write-Host "  (Docker will use this same dir — no re-download!)"
Write-Host ""

# Download LayoutLM
Write-Host "  Downloading LayoutLMv3-large (~1.2GB)..." -ForegroundColor Yellow
& $venvPython -c "
from huggingface_hub import snapshot_download
import os
os.environ['HF_HOME'] = r'$MODEL_CACHE'
snapshot_download('microsoft/layoutlmv3-large', cache_dir=r'$MODEL_CACHE\hub')
print('  ✓ LayoutLMv3-large cached')
"

# Download Qwen VL
Write-Host "  Downloading Qwen2.5-VL-3B-Instruct-AWQ (~2.5GB)..." -ForegroundColor Yellow
$hfToken = $env:HF_TOKEN
if (-not $hfToken) {
    Write-Host "  ⚠ Set HF_TOKEN first: `$env:HF_TOKEN = 'hf_xxxxx'" -ForegroundColor Yellow
    Write-Host "  Get token from: https://huggingface.co/settings/tokens" -ForegroundColor Yellow
    Write-Host "  Then re-run this script to download the model" -ForegroundColor Yellow
} else {
    & $venvPython -c "
from huggingface_hub import snapshot_download
import os
os.environ['HF_HOME'] = r'$MODEL_CACHE'
os.environ['HF_TOKEN'] = r'$hfToken'
snapshot_download('Qwen/Qwen2.5-VL-3B-Instruct-AWQ', cache_dir=r'$MODEL_CACHE\hub', token=r'$hfToken')
print('  ✓ Qwen2.5-VL-3B-Instruct-AWQ cached')
"
}

# ── Done ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✓ Setup Complete!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Models cached at: $MODEL_CACHE" -ForegroundColor White
Write-Host "  Docker uses same cache (volume mount) — zero re-download!" -ForegroundColor White
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Yellow
Write-Host "    1. Set HF token:  `$env:HF_TOKEN = 'hf_xxxxx'" -ForegroundColor White
Write-Host "    2. Run all:       .\scripts\local-stack.ps1 -Service all" -ForegroundColor White
Write-Host "    3. Or individual: .\scripts\local-stack.ps1 -Service vllm" -ForegroundColor White
Write-Host ""
Write-Host "  When ready for Docker:" -ForegroundColor Yellow
Write-Host "    docker compose -f docker-compose.gpu.yml --profile gpu up" -ForegroundColor White
Write-Host "    (Models already cached — instant start!)" -ForegroundColor White
Write-Host ""
