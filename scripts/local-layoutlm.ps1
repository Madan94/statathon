#!/usr/bin/env pwsh
# ─────────────────────────────────────────────────────────────────────────────
# Run LayoutLM locally (NO Docker) — CPU only, port 8001
#
# Usage: .\scripts\local-layoutlm.ps1
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ROOT

$MODEL_CACHE = Join-Path $ROOT "model\cache"
New-Item -ItemType Directory -Path $MODEL_CACHE -Force | Out-Null

$env:HF_HOME = $MODEL_CACHE
$env:HUGGINGFACE_HUB_CACHE = Join-Path $MODEL_CACHE "hub"
$env:MODEL_ID = "microsoft/layoutlmv3-large"
$env:LAYOUTLM_PORT = "8001"
$env:MAX_PAGES = "100"

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  LayoutLM Local Server (CPU)" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Model:    microsoft/layoutlmv3-large (~1.4GB RAM)" -ForegroundColor White
Write-Host "  Port:     8001" -ForegroundColor White
Write-Host "  Endpoint: http://localhost:8001/health" -ForegroundColor White
Write-Host "  Cache:    $MODEL_CACHE" -ForegroundColor White
Write-Host ""

$venvPython = Join-Path $ROOT ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = "python"
}

& $venvPython services/layoutlm/main.py
