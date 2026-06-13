#!/usr/bin/env pwsh
# ─────────────────────────────────────────────────────────────────────────────
# Stop all local services started by local-stack.ps1
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "Stopping local services..." -ForegroundColor Yellow

# Stop Python processes (vLLM, LayoutLM, API)
Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match "vllm|layoutlm|uvicorn"
} | Stop-Process -Force -ErrorAction SilentlyContinue

# Stop Node (Dashboard)
Get-Process node -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match "next"
} | Stop-Process -Force -ErrorAction SilentlyContinue

# Stop Docker infrastructure
docker rm -f statathon-neo4j 2>$null
docker rm -f statathon-redis 2>$null

Write-Host "✓ All services stopped." -ForegroundColor Green
