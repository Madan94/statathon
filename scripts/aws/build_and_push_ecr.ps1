param(
  [Parameter(Mandatory = $true)][string]$AwsRegion,
  [Parameter(Mandatory = $true)][string]$AwsAccountId,
  [string]$ApiRepo = "bharatstat-api",
  [string]$DashboardRepo = "bharatstat-dashboard",
  [string]$ImageTag = "latest"
)

$ErrorActionPreference = "Stop"

$registry = "$AwsAccountId.dkr.ecr.$AwsRegion.amazonaws.com"

Write-Host "Logging into ECR registry $registry ..."
aws ecr get-login-password --region $AwsRegion | docker login --username AWS --password-stdin $registry

Write-Host "Building API image ..."
docker build -f docker/Dockerfile.api.fargate -t "${ApiRepo}:$ImageTag" .
docker tag "${ApiRepo}:$ImageTag" "$registry/${ApiRepo}:$ImageTag"
docker push "$registry/${ApiRepo}:$ImageTag"

Write-Host "Building dashboard image ..."
docker build -f docker/Dockerfile.dashboard -t "${DashboardRepo}:$ImageTag" .
docker tag "${DashboardRepo}:$ImageTag" "$registry/${DashboardRepo}:$ImageTag"
docker push "$registry/${DashboardRepo}:$ImageTag"

Write-Host "Done."
Write-Host "API image:       $registry/${ApiRepo}:$ImageTag"
Write-Host "Dashboard image: $registry/${DashboardRepo}:$ImageTag"
