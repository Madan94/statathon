# BharatStat AWS Deployment Pack

This folder contains the production deployment assets for the console-first AWS rollout.

## Documents

- [01-console-runbook.md](./01-console-runbook.md)  
  End-to-end AWS console steps for VPC, ECS, ALB, RDS, S3, TLS, and service deploy.

- [02-env-secrets-matrix.md](./02-env-secrets-matrix.md)  
  Production environment and secret mappings for API and dashboard.

- [03-gpu-worker.md](./03-gpu-worker.md)  
  EC2 GPU worker topology and integration contract.

- [04-security-observability.md](./04-security-observability.md)  
  Security hardening, IAM least privilege, alarms, backup policy.

- [05-cutover-checklist.md](./05-cutover-checklist.md)  
  Smoke tests, cutover execution, and rollback flow.

- [06-colpali-sglang-remote.md](./06-colpali-sglang-remote.md)  
  ColPali + SGLang on EC2 GPU; local Windows API via HTTP endpoints.

- [07-s3-datasets-kms.md](./07-s3-datasets-kms.md)  
  S3 raw dataset storage with SSE-KMS, bucket policy, IAM, and migration.

- [10-rds-only-laptop.md](./10-rds-only-laptop.md)  
  **Console walkthrough:** create RDS in Mumbai and connect laptop dev (recommended if using RDS only).

- [09-ap-south-1-colocation.md](./09-ap-south-1-colocation.md)  
  Production checklist: co-locate ECS, RDS, Redis, and S3 in Mumbai.

## Templates

- `deploy/ecs/taskdef-api.template.json`
- `deploy/ecs/taskdef-dashboard.template.json`

## Build and push helper

- `scripts/aws/build_and_push_ecr.ps1`
- `scripts/aws/render_taskdefs.ps1`
- `scripts/aws/rds_ssm_tunnel.ps1` — SSM port-forward to private RDS (staging)
- `scripts/aws/bootstrap_rds_schema.ps1` — run migrations against `DATABASE_URL`
