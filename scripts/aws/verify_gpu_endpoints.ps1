# Verify remote ColPali + SGLang endpoints (local API dev with SSM tunnel or public IP).
param(
    [string]$GpuHost = $(if ($env:GPU_HOST) { $env:GPU_HOST } else { "127.0.0.1" })
)

$ErrorActionPreference = "Continue"
$colUrl = "http://${GpuHost}:8100/health"
$sgUrl = "http://${GpuHost}:30000/health"

Write-Host "ColPali: $colUrl"
try {
    $col = Invoke-RestMethod $colUrl -TimeoutSec 15
    Write-Host "  OK: $($col | ConvertTo-Json -Compress)"
} catch {
    Write-Host "  FAIL: $($_.Exception.Message)"
}

Write-Host "SGLang: $sgUrl"
try {
    $sg = Invoke-RestMethod $sgUrl -TimeoutSec 15
    Write-Host "  OK: $($sg | ConvertTo-Json -Compress)"
} catch {
    Write-Host "  FAIL: $($_.Exception.Message)"
}
