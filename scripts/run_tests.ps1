# scripts/run_tests.ps1 — run the template engine test suite from any directory
# Usage:
#   .\scripts\run_tests.ps1              — all unit tests (no live services)
#   .\scripts\run_tests.ps1 -Live llm   — live Gemini API tests
#   .\scripts\run_tests.ps1 -Live vlm   — live ColPali tests
#   .\scripts\run_tests.ps1 -Live all   — every live marker
#   .\scripts\run_tests.ps1 -Verify     — 10-stage pipeline verification only
#   .\scripts\run_tests.ps1 -All        — everything including enhanced env tests

param(
    [string]$Live  = "",     # llm | vlm | sglang | db | s3 | all
    [switch]$Verify,         # run only the full-pipeline verification
    [switch]$All,            # run all tests including live
    [switch]$Verbose         # -v flag
)

$ErrorActionPreference = "Stop"

# ── Locate repo root ──────────────────────────────────────────────────────────
$RepoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $RepoRoot

# ── Find python interpreter ───────────────────────────────────────────────────
# Priority: project .venv → cne-platform-venv → system python
$Python = $null
foreach ($candidate in @(
    "$RepoRoot\.venv\Scripts\python.exe",
    "$RepoRoot\venv\Scripts\python.exe",
    "C:\dev\src\cne-platform-venv\Scripts\python.exe",
    "python"
)) {
    if (Test-Path $candidate -ErrorAction SilentlyContinue) {
        $Python = $candidate
        break
    }
}

if (-not $Python) {
    Write-Host "ERROR: Could not find Python. Activate your venv or install Python." -ForegroundColor Red
    exit 1
}

Write-Host "Python: $Python" -ForegroundColor DarkGray
Write-Host "Root:   $RepoRoot`n" -ForegroundColor DarkGray

# ── Build pytest command ──────────────────────────────────────────────────────
$PytestArgs = @()
$PytestArgs += "tests/"

if ($Verbose) { $PytestArgs += "-v" }

if ($Verify) {
    $PytestArgs = @("tests/test_template_engine/test_verify_full.py", "-v")
} elseif ($All) {
    # everything
} elseif ($Live -eq "all") {
    $PytestArgs += "-m", "live"
} elseif ($Live -ne "") {
    $PytestArgs += "-m", "live_$Live"
} else {
    # default: skip all live tests
    $PytestArgs += "-m", "not live"
}

# ── Run ───────────────────────────────────────────────────────────────────────
Write-Host "Running: python -m pytest $($PytestArgs -join ' ')`n" -ForegroundColor Cyan
& $Python -m pytest @PytestArgs
exit $LASTEXITCODE
