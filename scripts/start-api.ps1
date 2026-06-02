# Start BharatStat API with full request logs (run from repo root)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Host "ERROR: .venv not found. Create venv and install requirements-windows.txt first." -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = (Get-Location).Path
$env:PYTHONUNBUFFERED = "1"

Write-Host "Starting API on http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "Logs: startup + every HTTP request (GET/POST ...)" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop`n" -ForegroundColor Yellow

Set-Location api
& ..\.venv\Scripts\python.exe -m uvicorn main:app `
    --reload `
    --host 127.0.0.1 `
    --port 8000 `
    --log-level info `
    --access-log
