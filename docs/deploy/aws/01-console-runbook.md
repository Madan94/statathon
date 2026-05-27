# AWS Console-First Runbook (ECS Fargate + RDS + S3 + GPU Worker)

## 1) Build and Push Images

1. Create ECR repositories:
   - `bharatstat-api`
   - `bharatstat-dashboard`
2. From repo root run:
   - `.\scripts\aws\build_and_push_ecr.ps1 -AwsRegion <region> -AwsAccountId <account>`
3. Confirm images exist in ECR with tag `latest` (or your release tag).

## 2) Create Networking

1. VPC with CIDR (e.g. `10.40.0.0/16`)
2. Subnets:
   - 2 public subnets (ALB + NAT)
   - 2 private subnets (ECS + RDS + Redis + GPU worker)
3. Route tables:
   - Public: Internet Gateway route
   - Private: NAT Gateway route for outbound package pulls

## 3) Security Groups

- `sg-alb`:
  - Inbound: 80/443 from internet
  - Outbound: all to `sg-ecs`
- `sg-ecs-api`:
  - Inbound: 8000 from `sg-alb`
  - Outbound: to RDS/Redis/S3/NAT
- `sg-ecs-dashboard`:
  - Inbound: 3000 from `sg-alb`
  - Outbound: to API (internal ALB target), internet via NAT
- `sg-rds`:
  - Inbound: 5432 from `sg-ecs-api`
- `sg-redis`:
  - Inbound: 6379 from `sg-ecs-api` and `sg-gpu-worker`
- `sg-gpu-worker`:
  - Inbound: only from `sg-ecs-api` on worker API port (if HTTP pull model)

## 4) Data Plane

1. **RDS PostgreSQL**
   - Engine: PostgreSQL 15/16
   - Private subnet group
   - Encryption enabled
   - Automatic backups enabled
2. **S3 bucket**
   - Name: `bharatstat-prod-data` (or your naming policy)
   - Block public access ON
   - Server-side encryption ON
3. **ElastiCache Redis** (if using queue/session cache paths)
   - Private subnet only

## 5) ECS Cluster and Services

1. Create ECS cluster (Fargate).
2. Register task definitions using templates:
   - `deploy/ecs/taskdef-api.template.json`
   - `deploy/ecs/taskdef-dashboard.template.json`
3. Create services:
   - `bharatstat-api` (port 8000 target group)
   - `bharatstat-dashboard` (port 3000 target group)
4. Set service minimum 2 tasks per AZ for HA.

## 6) Application Load Balancer + Routing

1. Create ALB in public subnets.
2. Target groups:
   - `tg-dashboard` -> port 3000 `/`
   - `tg-api` -> port 8000 `/health`
3. Listener rules:
   - `/api/*` -> `tg-api`
   - default `/*` -> `tg-dashboard`
4. If needed, add explicit API rule for `/auth/*`.

## 7) TLS + DNS

1. Request ACM certificate for your domain.
2. Attach cert to ALB 443 listener.
3. Redirect 80 -> 443.
4. Create Route53 alias A record to ALB.

## 8) Deploy Verification

1. Open `/` -> landing page loads.
2. Signup -> OTP -> login -> `/dashboard`.
3. Upload CSV/XLSX.
4. Run analysis and generate report.
5. Verify API `/health` and `/health/db`.
