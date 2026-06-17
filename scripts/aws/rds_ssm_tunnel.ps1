# Open SSM port-forward tunnel to private RDS via a bastion EC2 instance.
# Requires: AWS CLI, Session Manager plugin, .env.rds-staging values (or env vars).
#
# Usage (from repo root):
#   .\scripts\aws\rds_ssm_tunnel.ps1
#   .\scripts\aws\rds_ssm_tunnel.ps1 -LocalPort 5433

param(
    [string]$EnvFile = ".env.rds-staging.example",
    [string]$InstanceId = $env:RDS_SSM_BASTION_INSTANCE_ID,
    [string]$RemoteHost = $env:RDS_SSM_REMOTE_HOST,
    [int]$LocalPort = 0,
    [int]$RemotePort = 5432,
    [string]$Region = $env:AWS_REGION
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $RepoRoot

function Read-DotEnvValue {
    param([string]$Path, [string]$Key)
    if (-not (Test-Path $Path)) { return $null }
    foreach ($line in Get-Content $Path) {
        if ($line -match "^\s*$Key\s*=\s*(.+)\s*$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

if (-not $InstanceId -and (Test-Path $EnvFile)) {
    $InstanceId = Read-DotEnvValue -Path $EnvFile -Key "RDS_SSM_BASTION_INSTANCE_ID"
}
if (-not $RemoteHost -and (Test-Path $EnvFile)) {
    $RemoteHost = Read-DotEnvValue -Path $EnvFile -Key "RDS_SSM_REMOTE_HOST"
}
if ($LocalPort -eq 0 -and (Test-Path $EnvFile)) {
    $lp = Read-DotEnvValue -Path $EnvFile -Key "RDS_SSM_LOCAL_PORT"
    if ($lp) { $LocalPort = [int]$lp } else { $LocalPort = 5433 }
}
if ($LocalPort -eq 0) { $LocalPort = 5433 }
if (-not $Region -and (Test-Path $EnvFile)) {
    $Region = Read-DotEnvValue -Path $EnvFile -Key "AWS_REGION"
}
if (-not $Region) { $Region = "ap-south-1" }

if (-not $InstanceId -or $InstanceId -match "i-0123456789") {
    Write-Error "Set RDS_SSM_BASTION_INSTANCE_ID in $EnvFile or pass -InstanceId"
}
if (-not $RemoteHost -or $RemoteHost -match "xxxxx") {
    Write-Error "Set RDS_SSM_REMOTE_HOST in $EnvFile or pass -RemoteHost"
}

Write-Host "Starting SSM tunnel:"
Write-Host "  localhost:$LocalPort -> $RemoteHost`:$RemotePort"
Write-Host "  bastion: $InstanceId  region: $Region"
Write-Host "Leave this window open. Press Ctrl+C to stop."
Write-Host ""

aws ssm start-session `
    --target $InstanceId `
    --document-name AWS-StartPortForwardingSessionToRemoteHost `
    --parameters "host=$RemoteHost,portNumber=$RemotePort,localPortNumber=$LocalPort" `
    --region $Region
