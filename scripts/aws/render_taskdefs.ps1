param(
  [Parameter(Mandatory = $true)][string]$AwsRegion,
  [Parameter(Mandatory = $true)][string]$ApiImageUri,
  [Parameter(Mandatory = $true)][string]$DashboardImageUri,
  [Parameter(Mandatory = $true)][string]$ExecutionRoleArn,
  [Parameter(Mandatory = $true)][string]$ApiTaskRoleArn,
  [Parameter(Mandatory = $true)][string]$DashboardTaskRoleArn,
  [Parameter(Mandatory = $true)][string]$DatabaseUrl,
  [Parameter(Mandatory = $true)][string]$CorsOrigins,
  [Parameter(Mandatory = $true)][string]$NextInternalUrl,
  [Parameter(Mandatory = $true)][string]$S3Bucket,
  [Parameter(Mandatory = $true)][string]$RedisUrl,
  [Parameter(Mandatory = $true)][string]$GpuWorkerEndpoint,
  [Parameter(Mandatory = $true)][string]$SecretsArnPrefix,
  [Parameter(Mandatory = $true)][string]$ApiInternalUrl,
  [Parameter(Mandatory = $true)][string]$ApiPublicUrl,
  [Parameter(Mandatory = $true)][string]$MailInternalSecret
)

$ErrorActionPreference = "Stop"

function Expand-Template([string]$path, [hashtable]$vars) {
  $raw = Get-Content $path -Raw
  foreach ($key in $vars.Keys) {
    $raw = $raw.Replace($key, $vars[$key])
  }
  return $raw
}

$apiTemplatePath = "deploy/ecs/taskdef-api.template.json"
$dashTemplatePath = "deploy/ecs/taskdef-dashboard.template.json"

$apiVars = @{
  "__AWS_REGION__" = $AwsRegion
  "__API_IMAGE_URI__" = $ApiImageUri
  "__ECS_EXECUTION_ROLE_ARN__" = $ExecutionRoleArn
  "__API_TASK_ROLE_ARN__" = $ApiTaskRoleArn
  "__DATABASE_URL__" = $DatabaseUrl
  "__CORS_ORIGINS__" = $CorsOrigins
  "__NEXT_INTERNAL_URL__" = $NextInternalUrl
  "__S3_BUCKET__" = $S3Bucket
  "__REDIS_URL__" = $RedisUrl
  "__GPU_WORKER_ENDPOINT__" = $GpuWorkerEndpoint
  "__SECRET_ARN__" = "$SecretsArnPrefix:"
}

$dashVars = @{
  "__AWS_REGION__" = $AwsRegion
  "__DASHBOARD_IMAGE_URI__" = $DashboardImageUri
  "__ECS_EXECUTION_ROLE_ARN__" = $ExecutionRoleArn
  "__DASHBOARD_TASK_ROLE_ARN__" = $DashboardTaskRoleArn
  "__API_INTERNAL_URL__" = $ApiInternalUrl
  "__API_PUBLIC_URL__" = $ApiPublicUrl
  "__MAIL_INTERNAL_SECRET__" = $MailInternalSecret
}

$apiOut = Expand-Template $apiTemplatePath $apiVars
$dashOut = Expand-Template $dashTemplatePath $dashVars

Set-Content -Path "deploy/ecs/taskdef-api.rendered.json" -Value $apiOut
Set-Content -Path "deploy/ecs/taskdef-dashboard.rendered.json" -Value $dashOut

Write-Host "Rendered:"
Write-Host " - deploy/ecs/taskdef-api.rendered.json"
Write-Host " - deploy/ecs/taskdef-dashboard.rendered.json"
Write-Host ""
Write-Host "Next:"
Write-Host "aws ecs register-task-definition --cli-input-json file://deploy/ecs/taskdef-api.rendered.json --region $AwsRegion"
Write-Host "aws ecs register-task-definition --cli-input-json file://deploy/ecs/taskdef-dashboard.rendered.json --region $AwsRegion"
