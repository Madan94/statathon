# OPTIONAL — AWS CLI launcher. Prefer AWS Console steps in:
# docs/deploy/aws/06-colpali-sglang-remote.md
#
# Launch a g5.xlarge GPU instance for ColPali + SGLang (eu-north-1 default).
# Prerequisites: AWS CLI configured, key pair optional (SSM-only access).
param(
    [string]$Region = "eu-north-1",
    [string]$InstanceType = "g5.xlarge",
    [int]$VolumeGb = 100,
    [string]$MyIpCidr = ""  # e.g. "203.0.113.10/32" — leave empty for SSM-only (no public ports)
)

$ErrorActionPreference = "Stop"

Write-Host "==> Resolving latest Amazon Linux 2023 AMI in $Region"
$ami = aws ec2 describe-images `
    --region $Region `
    --owners amazon `
    --filters "Name=name,Values=al2023-ami-*-x86_64" "Name=state,Values=available" `
    --query "sort_by(Images, &CreationDate)[-1].ImageId" `
    --output text

if (-not $ami -or $ami -eq "None") {
    throw "Could not resolve AL2023 AMI"
}

$sgName = "statathon-gpu-sidecars"
$sgId = aws ec2 describe-security-groups --region $Region --filters "Name=group-name,Values=$sgName" --query "SecurityGroups[0].GroupId" --output text 2>$null
if (-not $sgId -or $sgId -eq "None") {
    Write-Host "==> Creating security group $sgName"
    $vpcId = aws ec2 describe-vpcs --region $Region --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text
    $sgId = aws ec2 create-security-group --region $Region --group-name $sgName --description "ColPali 8100 + SGLang 30000" --vpc-id $vpcId --output text
    if ($MyIpCidr) {
        aws ec2 authorize-security-group-ingress --region $Region --group-id $sgId --protocol tcp --port 8100 --cidr $MyIpCidr | Out-Null
        aws ec2 authorize-security-group-ingress --region $Region --group-id $sgId --protocol tcp --port 30000 --cidr $MyIpCidr | Out-Null
        Write-Host "    Allowed TCP 8100,30000 from $MyIpCidr"
    } else {
        Write-Host "    No inbound rules (use SSM port forwarding only)"
    }
}

$roleName = "statathon-gpu-ec2-ssm"
$profileArn = aws iam get-instance-profile --instance-profile-name $roleName --query "InstanceProfile.Arn" --output text 2>$null
if (-not $profileArn -or $profileArn -eq "None") {
    Write-Host "==> Create IAM role $roleName with AmazonSSMManagedInstanceCore and instance profile (one-time manual step in AWS console if this fails)"
}

$userData = @"
#!/bin/bash
set -e
dnf install -y docker git
systemctl enable --now docker
usermod -aG docker ec2-user
mkdir -p /data/model/cache
chown ec2-user:ec2-user /data/model/cache
"@

$userDataB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($userData))

$runArgs = @(
    "ec2", "run-instances",
    "--region", $Region,
    "--image-id", $ami,
    "--instance-type", $InstanceType,
    "--security-group-ids", $sgId,
    "--block-device-mappings", "DeviceName=/dev/xvda,Ebs={VolumeSize=$VolumeGb,VolumeType=gp3}",
    "--user-data", $userData,
    "--tag-specifications", "ResourceType=instance,Tags=[{Key=Name,Value=statathon-gpu-models}]",
    "--count", "1"
)
if ($profileArn -and $profileArn -ne "None") {
    $runArgs += @("--iam-instance-profile", "Arn=$profileArn")
}

Write-Host "==> Launching $InstanceType ..."
$result = aws @runArgs --output json | ConvertFrom-Json
$instanceId = $result.Instances[0].InstanceId
Write-Host "InstanceId: $instanceId"
Write-Host "Wait for running, then SSM:"
Write-Host "  aws ssm start-session --target $instanceId --region $Region"
Write-Host "On instance: git clone <repo> && bash scripts/aws/ec2-gpu-bootstrap.sh"
