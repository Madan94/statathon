#!/usr/bin/env pwsh
# ─────────────────────────────────────────────────────────────────────────────
# Run vLLM locally (NO Docker) — Qwen2.5-VL-3B-Instruct-AWQ on RTX 4050
#
# Usage:
#   $env:HF_TOKEN = "hf_xxxxx"
#   .\scripts\local-vllm.ps1
#
# Models cached in ./model/cache (shared with Docker)
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ROOT

$MODEL_CACHE = Join-Path $ROOT "model\cache"
New-Item -ItemType Directory -Path $MODEL_CACHE -Force | Out-Null

# Set environment
$env:HF_HOME = $MODEL_CACHE
$env:HUGGINGFACE_HUB_CACHE = Join-Path $MODEL_CACHE "hub"

$MODEL = if ($env:VLLM_MODEL) { $env:VLLM_MODEL } else { "Qwen/Qwen2.5-VL-3B-Instruct-AWQ" }
$PORT = if ($env:VLLM_PORT) { $env:VLLM_PORT } else { "8002" }

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  vLLM Local Server" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# GPU Check
$freeVram = (nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
if ($freeVram) {
    $freeVram = $freeVram.Trim()
    Write-Host "  GPU VRAM free: ${freeVram}MB" -ForegroundColor White
    if ([int]$freeVram -lt 5000) {
        Write-Host "  ⚠ Need 5000MB+ free VRAM. Close GPU apps!" -ForegroundColor Yellow
    } else {
        Write-Host "  ✓ Sufficient VRAM" -ForegroundColor Green
    }
} else {
    Write-Host "  ✗ No NVIDIA GPU detected!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  Model:     $MODEL" -ForegroundColor White
Write-Host "  Port:      $PORT" -ForegroundColor White
Write-Host "  Cache:     $MODEL_CACHE" -ForegroundColor White
Write-Host "  Endpoint:  http://localhost:${PORT}/v1/chat/completions" -ForegroundColor White
Write-Host ""
Write-Host "  First run: downloads ~2.5GB + JIT compile (5-10 min total)" -ForegroundColor Yellow
Write-Host "  Subsequent: starts in ~30-60 seconds" -ForegroundColor Yellow
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# Find python
$venvPython = Join-Path $ROOT ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = "python"
    Write-Host "  Using system python (no .venv found)" -ForegroundColor Yellow
}

# Launch vLLM
& $venvPython -m vllm.entrypoints.openai.api_server `
    --model $MODEL `
    --host "0.0.0.0" `
    --port $PORT `
    --gpu-memory-utilization 0.95 `
    --max-model-len 2048 `
    --enforce-eager `
    --max-num-seqs 1 `
    --limit-mm-per-prompt '{"image": 1}' `
    --mm-processor-kwargs '{"max_pixels": 360448, "min_pixels": 3136}' `
    --trust-remote-code `
    --download-dir $MODEL_CACHE
