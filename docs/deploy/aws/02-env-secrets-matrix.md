# Production Environment and Secrets Matrix

This maps current app settings from [`.env.example`](d:/statathon-hack/statathon/.env.example) into ECS task env + Secrets Manager.

## API service (`bharatstat-api`)

### Non-secret ECS environment

- `APP_ENV=production`
- `AUTH_REQUIRED=true`
- `ALLOW_LEGACY_ANON_USER=false`
- `COOKIE_SECURE=true`
- `CSRF_ENABLED=true`
- `JWT_ACCESS_MINUTES=30`
- `JWT_REFRESH_DAYS=14`
- `OTP_LENGTH=6`
- `OTP_TTL_MINUTES=10`
- `OTP_MAX_ATTEMPTS=5`
- `AUTH_RATE_MAX_PER_WINDOW=20`
- `DATABASE_URL=postgresql://...` (can also be moved to secret)
- `NEXT_INTERNAL_URL=https://<frontend-domain>`
- `CORS_ORIGINS=https://<frontend-domain>`
- `STORAGE_PROVIDER=s3`
- `S3_BUCKET=<bucket>`
- `AWS_REGION=<region>`
- `S3_UPLOAD_PREFIX=datasets`
- `S3_KMS_KEY_ID=arn:aws:kms:<region>:<account>:key/<key-id>`
- `S3_VAULT_KMS_KEY_ID=` (optional; defaults to `S3_KMS_KEY_ID`)
- `PRESIGNED_UPLOAD_EXPIRES_SECONDS=3600`
- `REGISTER_SIZE_TOLERANCE_BYTES=8`
- `REPORT_STORAGE_PATH=/tmp/reports` (derived reports only; raw datasets are S3-only)
- `REDIS_URL=redis://<elasticache-endpoint>:6379/0`
- `INFERENCE_MODE=remote`
- `GPU_WORKER_ENDPOINT=http://<private-worker-endpoint>:8080`

### Secrets Manager keys

- `SECRET_KEY`
- `MAIL_INTERNAL_SECRET`
- `SMTP_USER`
- `SMTP_PASS`
- `GOOGLE_API_KEY`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `AWS_ACCESS_KEY_ID` (skip if task role has proper S3 permissions)
- `AWS_SECRET_ACCESS_KEY` (skip if task role has proper S3 permissions)
- `DATABASE_URL` (recommended as secret when embedding credentials)

## Dashboard service (`bharatstat-dashboard`)

### ECS environment

- `NODE_ENV=production`
- `API_INTERNAL_URL=http://<api-service-private-dns>:8000`
- `NEXT_PUBLIC_API_URL=https://<public-domain>/api/backend`
- `MAIL_INTERNAL_SECRET=<same as API>`
- `SMTP_HOST=smtp.gmail.com` (or SES endpoint)
- `SMTP_PORT=587`
- `SMTP_USER=<smtp-user>`
- `SMTP_PASS=<smtp-pass>`
- `SMTP_FROM=BharatStat <no-reply@<domain>>`

## Required alignment checks

- `MAIL_INTERNAL_SECRET` must match between frontend and API.
- `NEXT_INTERNAL_URL` should point to frontend URL over HTTPS.
- `COOKIE_SECURE=true` in production.
- CORS must include only production frontend origins.
