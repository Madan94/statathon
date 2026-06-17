# Security, TLS, and Observability Checklist

## TLS and web security

- ACM certificate attached to ALB 443 listener
- HTTP 80 redirected to HTTPS 443
- `COOKIE_SECURE=true`
- `CSRF_ENABLED=true`
- Strict `CORS_ORIGINS` to production domains only
- Add security headers at ALB/app layer:
  - `Strict-Transport-Security`
  - `X-Content-Type-Options`
  - `X-Frame-Options`

## IAM least privilege

- Separate task roles for API and dashboard
- API task role:
  - Scoped S3 access to `s3://<bucket>/datasets/*` and report prefixes
  - No wildcard admin policies
- Dashboard task role:
  - Minimal (typically no direct AWS data-plane actions)
- Remove static AWS keys from env when role-based access is working

## Data protection

- RDS encryption at rest ON
- S3 bucket default encryption: **SSE-KMS** with customer-managed CMK (`S3_KMS_KEY_ID`)
- S3 bucket policy: deny `PutObject` without `aws:kms` encryption
- S3 block public access ON; versioning ON
- CloudTrail data events for S3 + KMS audit trail
- Redis transit and at-rest encryption ON (if enabled)
- Secrets Manager rotation policy for SMTP/API secrets

## Logging and metrics

- CloudWatch log groups:
  - `/ecs/bharatstat-api`
  - `/ecs/bharatstat-dashboard`
  - `/ec2/bharatstat-gpu-worker`
- ALB access logs to S3

## CloudWatch alarms

- ALB: `HTTPCode_Target_5XX_Count > 0`
- ECS API: CPU > 75%, memory > 80%
- ECS Dashboard: CPU > 70%, memory > 75%
- RDS:
  - CPU > 75%
  - FreeStorageSpace low
  - DBConnections near limit
- Redis:
  - evictions > 0
  - memory pressure

## Backups and DR

- RDS automated backups enabled (>= 7 days)
- Manual snapshot before major release
- S3 versioning enabled
- Lifecycle policy for old objects/reports
