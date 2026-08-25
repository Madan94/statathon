<div align="center">

# BharatStat

**Audit-ready intelligence and publication-grade reports from raw statistical data.**

[![API](https://img.shields.io/badge/API-FastAPI-009688?style=flat-square)](https://fastapi.tiangolo.com/)
[![Dashboard](https://img.shields.io/badge/Dashboard-Next.js_16-000000?style=flat-square)](https://nextjs.org/)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square)](https://www.python.org/)
[![Contract](https://img.shields.io/badge/Contract-ExecutionBundle_v1-3A6EA5?style=flat-square)](docs/BINDING_AND_EXTRACTION_ARCHITECTURE.md)

<br />

<img src="docs/images/header-image1.png" alt="BharatStat platform overview" width="100%" />

<img src="docs/images/header-image2.png" alt="BharatStat platform overview" width="100%" />

</div>

## What BharatStat does

BharatStat helps government and research teams turn heterogeneous CSV and Excel files, together with reference PDF reports, into explainable analysis and reusable reports. It combines deterministic data engineering with optional machine learning and language-model services. The workflow remains officer-in-the-loop: the system proposes mappings, quality actions, and report bindings; a user confirms decisions before they become operational.

### Core capabilities

| Capability | Outcome |
| --- | --- |
| Ingestion | CSV, XLS, and XLSX uploads from local or S3-compatible storage |
| Profiling | Dataset health, types, cardinality, ranges, units, and column roles |
| Semantic mapping | Ontology and embedding-assisted domain mapping with evidence and confidence |
| Quality intelligence | Validation findings, outlier signals, and imputation candidates for review |
| Analysis workspace | Normalization, domains, clusters, schema blueprint, and knowledge graph views |
| Template extraction | PDF layout and semantic structure compiled into an Enterprise AST |
| Contract binding | Confirmed `ExecutionBundle` plans with readiness, severity, freeze, and lineage controls |
| Report generation | Filtered analytics, verified narrative, charts, tables, and MoSPI-style PDF export |
| Auditability | Evidence references, provenance, versioned artifacts, and activity history |

## Architecture

```mermaid
flowchart LR
    U[Officer] --> D[Next.js dashboard]
    D --> A[FastAPI API]
    A --> I[Ingestion and profiling]
    I --> S[Semantic mapping]
    S --> Q[Validation, outliers, imputation]
    Q --> C[Human confirmation]
    C --> B[Binding contract compiler]
    B --> E[ExecutionBundle v1]
    E --> X[S4 execution coordinator]
    X --> R[Report renderer and exporter]

    A --> DB[(PostgreSQL or SQLite)]
    A --> OS[(Local, S3, or R2 storage)]
    S -. optional .-> KG[(Neo4j)]
    X --> AD[DuckDB analytics]
    B -. optional .-> VLM[LayoutLM and Qwen VLM]
    R -. optional .-> LLM[Scribe and verifier LLMs]
```

### Data and report lifecycle

```mermaid
flowchart TB
    PDF[Reference PDF] --> EX[Multi-pass extraction]
    EX --> AST[Enterprise AST and blueprint]
    CSV[Dataset] --> PROF[DatasetAST profiling]
    PROF --> RES[Resolver proposals]
    AST --> RES
    RES --> CONF[Officer confirmation]
    CONF --> PLAN[Question execution plans]
    PLAN --> GATE{Readiness gate}
    GATE -->|NOT_READY or BLOCKED| STOP[Stop and show actionable reason]
    GATE -->|READY| FREEZE[Freeze versioned binding]
    FREEZE --> BUNDLE[ExecutionBundle v1]
    BUNDLE --> FORM[formula_exec and S4 coordinator]
    FORM --> ANALYTICS[Aggregate at the requested grain]
    ANALYTICS --> EVIDENCE[Evidence and lineage]
    EVIDENCE --> OUT[PDF, preview, and delivery]
```

The binding contract is the handoff between interpretation and execution. The renderer consumes physical columns and confirmed plans; formulas such as shares, rates, ratios, growth, CAGR, and index values are computed by `formula_exec` before rendering. This prevents the renderer from silently reinterpreting a loose binding or formula string.

## Technology stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4 |
| API | FastAPI, Uvicorn, SQLAlchemy 2, Pydantic 2 |
| Data and statistics | pandas, NumPy, SciPy, scikit-learn, DuckDB |
| Semantic intelligence | Sentence Transformers, ontology rules, optional LLM providers |
| Documents | pdfplumber, PyMuPDF, ReportLab, LayoutLMv3, optional Qwen VLM |
| Persistence | PostgreSQL or SQLite, Redis, local disk or S3/R2 |
| Knowledge graph | Neo4j 5.x (optional) |
| Deployment | Docker Compose locally; ECS, RDS, S3, and optional GPU worker on AWS |

## Repository map

```text
api/                 FastAPI application, routers, auth, services, persistence
dashboard/           Next.js officer dashboard
pipelines/           Analysis orchestration and semantic runner
core/                Ingestion and shared data processing
profiling/           Dataset and column intelligence
validation/          Rule validation and multi-column checks
outliers/            IQR, Z-score, isolation, and distribution analysis
imputation/          Missing-value candidates and mechanism detection
report_builder/      Extraction, binding, execution, narrative, and export
template_engine/     PDF-to-AST template compiler
ast_core/            Enterprise document AST and rendering primitives
analytics_engine/    DuckDB, ClickHouse, and Cube adapters
agents/              Planner, retrieval, scribe, verifier, and consensus agents
graph/               Neo4j synchronization and graph utilities
tests/               Offline and service-backed tests
scripts/             Smoke tests, benchmarks, and operations helpers
docs/                Architecture, setup, testing, storage, and deployment guides
```

## Quick start

### Prerequisites

- Python 3.12 or newer
- Node.js 20 or newer
- Git
- PostgreSQL for a production-like setup, or SQLite for a lightweight local run
- Docker Desktop only when Redis, Neo4j, LayoutLM, or GPU services are needed

On Windows, use `requirements-windows.txt`. On Linux or macOS, use `requirements.txt`.

### 1. Install the backend

```powershell
git clone https://github.com/Madan94/statathon.git
cd statathon
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-windows.txt
Copy-Item .env.example .env
```

For Linux or macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

For the fastest offline smoke test, set these values in `.env`:

```env
LLM_DISABLED=1
NEO4J_ENABLED=false
OBJECT_STORAGE_DISABLED=true
DATABASE_URL=sqlite:///./statathon.db
AUTH_REQUIRED=false
```

Never commit `.env`, credentials, model weights, or generated audit artifacts.

### 2. Start the API

From the repository root:

```powershell
cd api
$env:PYTHONPATH = (Resolve-Path "..").Path
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Linux or macOS:

```bash
cd api
export PYTHONPATH="$(cd .. && pwd)"
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Useful endpoints:

- Health: `http://127.0.0.1:8000/health`
- Database health: `http://127.0.0.1:8000/health/db`
- OpenAPI: `http://127.0.0.1:8000/docs`

### 3. Start the dashboard

```powershell
cd dashboard
Copy-Item .env.local.example .env.local -ErrorAction SilentlyContinue
npm install
npm run dev
```

Open `http://localhost:3000`. Set `NEXT_PUBLIC_API_URL` in `dashboard/.env.local` when the API is not running at `http://localhost:8000`.

### Local extraction and report generation

For PDF template extraction, use the detailed [GUIDE.md](GUIDE.md). It documents offline, local-GPU, cloud-provider, and hybrid modes. The shortest deterministic extraction check is:

```powershell
$env:PYTHONPATH = (Get-Location).Path
& .\.venv\Scripts\python.exe scripts\simulate_offline.py "test_data\Stat reports.pdf"
```

For the configurable V2 runner:

```powershell
$env:PYTHONPATH = (Get-Location).Path
$env:PDF_INPUT_PATH = "test_data\Stat reports.pdf"
$env:TEMPLATE_NAME = "Stat reports"
$env:OUTPUT_DIR = "outputs"
$env:EXTRACTION_PIPELINE = "v2"
& .\.venv\Scripts\python.exe scripts\run_pipeline.py
```

Successful extraction writes a value-free `template.ast.json` and `template.blueprint.json` below `outputs/<document-title>/`. A filled report is produced later by binding a ready analysis to a template; do not treat extraction output as a report containing source values.

### 4. Start optional services

```powershell
# Redis and Neo4j
docker compose up -d redis neo4j

# LayoutLM and Qwen VLM; requires an NVIDIA GPU and Docker GPU support
docker compose --profile gpu up -d
```

| Service | Port | Required? |
| --- | ---: | --- |
| Dashboard | 3000 | For the web UI |
| FastAPI | 8000 | Yes |
| LayoutLM | 8001 | Optional; PDF layout extraction |
| Qwen VLM / SGLang | 8002 | Optional; vision extraction |
| Neo4j | 7474 / 7687 | Optional; knowledge graph |
| Redis | 6379 | Optional; cache and workers |

## Configuration

`.env.example` is the configuration reference. The most important production settings are:

| Variable | Purpose | Production guidance |
| --- | --- | --- |
| `SECRET_KEY` | JWT signing | Use a long random secret from a secret manager |
| `AUTH_REQUIRED` | Protects authenticated routes | `true` |
| `DATABASE_URL` | SQL database connection | PostgreSQL with TLS |
| `CORS_ORIGINS` | Allowed dashboard origins | Exact HTTPS origins only |
| `OBJECT_STORAGE_DISABLED` | Local versus object storage | `false` with S3/R2 configured |
| `IMMUTABLE_VAULT_REQUIRED` | Protects report/template artifacts | `true` |
| `NEO4J_ENABLED` | Knowledge graph sync | Enable only when configured |
| `LLM_DISABLED` | Deterministic offline mode | `1` for tests and air-gapped operation |
| `VLM_PROVIDER`, `REASONING_PROVIDER` | Model routing | Configure through environment only |
| `SGLANG_ENDPOINT`, `LAYOUTLM_ENDPOINT` | Vision service endpoints | Private service URLs in deployment |

All model calls should go through `report_builder.llm_router`; model names and endpoints belong in environment configuration, not Python source.

## End-to-end workflow

```mermaid
sequenceDiagram
    actor Officer
    participant UI as Dashboard
    participant API as FastAPI
    participant Worker as Analysis worker
    participant Store as DB / object storage
    participant Builder as Report builder

    Officer->>UI: Upload CSV or XLSX
    UI->>API: Register dataset
    API->>Store: Persist source and metadata
    Officer->>UI: Start analysis
    UI->>API: Create async analysis job
    API->>Worker: Run ingestion, profiling, semantics, quality checks
    Worker->>Store: Persist candidates and results
    UI->>API: Poll status and review findings
    Officer->>UI: Confirm mappings and normalization
    UI->>API: Select ready analysis and PDF template
    API->>Builder: Extract, bind, freeze, and execute
    Builder->>Store: Write evidence and report artifact
    UI->>API: Stream progress and download PDF
```

## Report Builder contract

The production report path is deliberately staged:

| Stage | Responsibility | Representative code |
| --- | --- | --- |
| S0 | Profile dataset and identify roles | `report_builder/binding/` |
| S1 | Resolve entities to dataset columns | `report_builder/binding/` |
| S2 | Capture human confirmation | Dashboard and binding state |
| S3 | Compile question execution plans | Binding compiler |
| S3.5 | Enforce readiness and severity gates | Binding readiness gate |
| Freeze | Persist immutable, versioned binding | Freeze store |
| S4 | Execute confirmed plans and formulas | Execution coordinator / `formula_exec` |
| S5-S6 | Verify content and render output | Firewall, agents, exporter |

Important invariants:

- `NOT_READY` blocks generation.
- `BLOCKED` plans, such as a missing denominator or base value, are not softened into runnable degradation.
- Shares, rates, and ratios aggregate numerator and denominator at the same grain before division.
- `reported_value` never silently falls back to `mean()` when values disagree.
- Freeze keys use `BindingAST.datasetSignature`.
- Multi-measure plans preserve stable plan IDs, slots, and lineage.

See [BINDING_AND_EXTRACTION_ARCHITECTURE.md](docs/BINDING_AND_EXTRACTION_ARCHITECTURE.md), [REPORT_BUILDER_ARCHITECTURE.md](docs/REPORT_BUILDER_ARCHITECTURE.md), and [report_builder/gold_standard/README.md](report_builder/gold_standard/README.md).

## Benchmarks and quality gates

Benchmarks are diagnostic evaluations, not production SLAs. Results vary with CPU/GPU, model-cache state, dataset shape, ontology configuration, and whether profiling is enabled.

### Reproduce semantic benchmarks

```powershell
# Synthetic end-to-end benchmark, direct semantic pipeline
python scripts\benchmark_semantic_e2e.py

# Full HTTP path with upload, profiling, and persistence
python scripts\benchmark_semantic_e2e.py --http

# Holdout dataset benchmark
python scripts\benchmark_holdout.py --dataset "test_data\Economics - MoSPI.csv"

# Header-drift resilience benchmark
python scripts\benchmark_resilience.py --dataset "test_data\Economics - MoSPI.csv"
```

### Representative documented results

The following values are from the repository testing guide and should be refreshed when models, ontology, or pipeline thresholds change:

| Scenario | Metric | Representative result | Interpretation |
| --- | --- | ---: | --- |
| Direct synthetic pipeline, 10 columns | Exact match | 30% (3/10) | Strict ontology label match |
| Direct synthetic pipeline, 10 columns | Relaxed match | 70% (7/10) | Includes valid dynamic-domain matches |
| Direct synthetic pipeline | Wall time | About 3.5 s | Warm model cache |
| Full HTTP path | Analyze time | About 113 s | First MiniLM load and profiling included |
| Full HTTP path, 10 columns | Exact match | 10% (1/10) | Profile-derived embeddings change results |
| Full HTTP path, 10 columns | Relaxed match | 50% (5/10) | Diagnostic, not an SLA |

The automated suite is the primary regression gate:

```powershell
python -m pytest -m "not live" -q
```

For the full local suite and benchmark interpretation, see [docs/TESTING_FULL_GUIDE.md](docs/TESTING_FULL_GUIDE.md). For frontend checks:

```powershell
cd dashboard
npm run lint
npm run build
```

## API surface

| Area | Prefix | Examples |
| --- | --- | --- |
| Authentication | `/auth` | Login, OTP, refresh, current user |
| Datasets | `/datasets` | Upload, registration, profiles, effective schema |
| Analysis | `/analysis` | Jobs, status, results, normalization, graph |
| Reports | `/reports` | Legacy report ingestion and downloads |
| Report Builder | `/report-builder` | Templates, generation jobs, progress, downloads |
| Dashboard | `/dashboard` | Activity and aggregate views |

The generated OpenAPI document at `/docs` is the authoritative request/response reference.

## Production deployment

The supported production shape separates the web/API plane from optional GPU inference:

```mermaid
flowchart LR
    Internet --> ALB[HTTPS load balancer]
    ALB --> API[ECS API service]
    ALB --> WEB[ECS dashboard service]
    API --> RDS[(Private RDS PostgreSQL)]
    API --> S3[(S3 or R2 with encryption)]
    API --> REDIS[(Redis)]
    API --> GPU[Private GPU worker]
    GPU --> LM[LayoutLM / Qwen services]
    API -. optional .-> NEO[Neo4j]
    OBS[CloudWatch and alarms] -.-> API
    OBS -.-> WEB
    OBS -.-> GPU
```

Production checklist:

- Store secrets in AWS Secrets Manager or an equivalent secret manager.
- Use PostgreSQL, TLS, backups, connection limits, and migration controls.
- Use S3/R2 with least-privilege credentials, encryption, and immutable report-vault policy.
- Set `AUTH_REQUIRED=true`, `COOKIE_SECURE=true`, strict CORS, and a real SMTP provider.
- Keep GPU services private; expose only the API/dashboard through the load balancer.
- Run `/health` and `/health/db` checks and the production smoke script before cutover.
- Monitor API errors, job failures, queue depth, database health, and p95 latency.

Deployment runbooks are in [docs/deploy/aws/README.md](docs/deploy/aws/README.md). Object storage setup is documented in [docs/R2_STEP_BY_STEP.md](docs/R2_STEP_BY_STEP.md).

### AWS deployment: end to end

The repository includes an ECS Fargate deployment pack. The following sequence is the operational order; the linked runbooks contain console-specific fields and security details.

#### Phase 1: prepare the AWS account

Install and authenticate the AWS CLI and Docker, select one region, and create or identify:

- An ECR repository for `bharatstat-api` and one for `bharatstat-dashboard`.
- A VPC with two public subnets for the ALB and two private subnets for ECS, RDS, Redis, and the optional GPU worker.
- An ECS cluster, task execution role, API task role, and dashboard task role.
- CloudWatch log groups named `/ecs/bharatstat-api` and `/ecs/bharatstat-dashboard`.
- An ACM certificate for the production hostname and a Route 53 hosted zone.

Keep RDS, Redis, and the GPU worker private. The ALB is the only internet-facing application entry point.

#### Phase 2: provision data services

1. Create encrypted PostgreSQL RDS in private subnets with automated backups.
2. Create an encrypted S3 bucket with Block Public Access enabled. Grant the API task role only the required bucket and KMS actions.
3. Create private Redis, such as ElastiCache, when queues, sessions, or checkpoints are enabled.
4. Configure security groups: ALB to ports 8000/3000, API to RDS/Redis/S3, and GPU worker access only from the API security group.
5. Run the schema bootstrap against the production `DATABASE_URL` using `scripts/aws/bootstrap_rds_schema.ps1`.

#### Phase 3: store runtime configuration

Create Secrets Manager entries for `SECRET_KEY`, `MAIL_INTERNAL_SECRET`, SMTP credentials, and any provider credentials. Prefer ECS task roles over static AWS access keys. Set the API environment to:

```text
APP_ENV=production
AUTH_REQUIRED=true
COOKIE_SECURE=true
CSRF_ENABLED=true
DATABASE_URL=postgresql://...
STORAGE_PROVIDER=s3
S3_BUCKET=<bucket>
AWS_REGION=<region>
REDIS_URL=redis://<private-redis-endpoint>:6379/0
INFERENCE_MODE=remote
GPU_WORKER_ENDPOINT=http://<private-gpu-worker>:8080
CORS_ORIGINS=https://<frontend-domain>
NEXT_INTERNAL_URL=https://<frontend-domain>
```

For the dashboard, set `NODE_ENV=production`, `API_INTERNAL_URL` to the private API service address, and `NEXT_PUBLIC_API_URL` to the public API path exposed by the ALB, normally `https://<domain>/api/backend`. `MAIL_INTERNAL_SECRET` must match the API value.

#### Phase 4: build and push release images

From the repository root, run the checked-in helper with an immutable release tag:

```powershell
.\scripts\aws\build_and_push_ecr.ps1 -AwsRegion <region> -AwsAccountId <account-id> -ImageTag <release-tag>
```

The helper builds `docker/Dockerfile.api.fargate` and `docker/Dockerfile.dashboard`, tags both images, logs in to ECR, and pushes them. Record the exact image URIs and avoid using `latest` for a production cutover when rollback traceability matters.

#### Phase 5: render and register ECS tasks

Render the checked-in templates with deployment values:

```powershell
.\scripts\aws\render_taskdefs.ps1 `
    -AwsRegion <region> `
    -ApiImageUri <account-id>.dkr.ecr.<region>.amazonaws.com/bharatstat-api:<release-tag> `
    -DashboardImageUri <account-id>.dkr.ecr.<region>.amazonaws.com/bharatstat-dashboard:<release-tag> `
    -ExecutionRoleArn <ecs-execution-role-arn> `
    -ApiTaskRoleArn <api-task-role-arn> `
    -DashboardTaskRoleArn <dashboard-task-role-arn> `
    -DatabaseUrl <database-url> `
    -CorsOrigins https://<frontend-domain> `
    -NextInternalUrl https://<frontend-domain> `
    -S3Bucket <bucket> `
    -RedisUrl redis://<private-redis-endpoint>:6379/0 `
    -GpuWorkerEndpoint http://<private-gpu-worker>:8080 `
    -SecretsArnPrefix arn:aws:secretsmanager:<region>:<account-id>:secret/bharatstat/ `
    -ApiInternalUrl http://bharatstat-api:8000 `
    -ApiPublicUrl https://<frontend-domain>/api/backend `
    -MailInternalSecret <shared-secret>
```

Review the rendered JSON for unresolved placeholders and secrets exposure. Register both task definitions:

```powershell
aws ecs register-task-definition --cli-input-json file://deploy/ecs/taskdef-api.rendered.json --region <region>
aws ecs register-task-definition --cli-input-json file://deploy/ecs/taskdef-dashboard.rendered.json --region <region>
```

The rendered files are generated artifacts. Keep them out of source control and remove them after registration if they contain inline values.

#### Phase 6: create services and route traffic

Create two ECS services with at least two tasks distributed across availability zones. Attach:

| Target group | Container | Health path |
| --- | --- | --- |
| `tg-dashboard` | Port 3000 | `/` |
| `tg-api` | Port 8000 | `/health` |

Configure the ALB listener to redirect HTTP to HTTPS, route `/api/*` and `/auth/*` to the API target group, and route the default path to the dashboard. The dashboard's internal API URL may use service discovery or an internal load balancer; its browser-facing URL must use the public HTTPS API path.

#### Phase 7: deploy optional GPU inference

Provision the GPU worker using [03-gpu-worker.md](docs/deploy/aws/03-gpu-worker.md) and [06-colpali-sglang-remote.md](docs/deploy/aws/06-colpali-sglang-remote.md). Put it in a private subnet, restrict inbound access to the API security group, configure `GPU_WORKER_ENDPOINT`, and verify it with:

```powershell
.\scripts\aws\verify_gpu_endpoints.ps1
```

If GPU services are unavailable, use a deliberate fallback configuration such as `LLM_DISABLED=1` for deterministic operation. Do not hide readiness failures for report generation behind an apparently successful deployment.

#### Phase 8: verify, observe, and cut over

Run the public smoke test after the ALB target groups are healthy:

```powershell
python scripts/aws/smoke_production.py --base-url https://<frontend-domain>
```

Then verify signup/login, dataset upload, analysis completion, template extraction, report generation, PDF download, and database health. Confirm CloudWatch logs, alarms, task replacement, RDS backups, S3 encryption, and no sustained ALB 5xx responses. Cut DNS over only after these checks pass; retain the previous ECS task definition and ALB target for rollback.

For the full security, observability, and rollback checklist, see [04-security-observability.md](docs/deploy/aws/04-security-observability.md) and [05-cutover-checklist.md](docs/deploy/aws/05-cutover-checklist.md). The source-of-truth variable mapping is [02-env-secrets-matrix.md](docs/deploy/aws/02-env-secrets-matrix.md).

## Security and operational notes

- Treat uploaded datasets, generated reports, API keys, and audit logs as sensitive.
- Do not commit `.env*`, `audit_log.json`, model weights, or cache contents.
- Keep `LLM_DISABLED=1` for deterministic air-gapped tests and environments without model services.
- Optional services degrade only where the pipeline contract permits it; readiness failures must remain visible.
- Rotate leaked credentials immediately and review object-storage and database access logs.

## Documentation index

| Guide | Use it for |
| --- | --- |
| [ENV_SETUP_STEP_BY_STEP.md](docs/ENV_SETUP_STEP_BY_STEP.md) | Environment variables and provider setup |
| [TESTING_FULL_GUIDE.md](docs/TESTING_FULL_GUIDE.md) | Tests, benchmarks, and failure diagnosis |
| [BINDING_AND_EXTRACTION_ARCHITECTURE.md](docs/BINDING_AND_EXTRACTION_ARCHITECTURE.md) | Extraction and `ExecutionBundle` contract |
| [REPORT_BUILDER_ARCHITECTURE.md](docs/REPORT_BUILDER_ARCHITECTURE.md) | Report phases, analytics, and delivery |
| [R2_STEP_BY_STEP.md](docs/R2_STEP_BY_STEP.md) | Cloudflare R2 configuration |
| [docs/deploy/aws/README.md](docs/deploy/aws/README.md) | AWS deployment and rollback runbooks |
| [GUIDE.md](GUIDE.md) | Project usage notes |

## Contributing

1. Create a focused branch from `main`.
2. Keep configuration and secrets out of source control.
3. Add or update focused tests for behavior changes.
4. Run the offline test suite and relevant frontend checks.
5. Update architecture or operational documentation when contracts change.

The binding and extraction contract is shared infrastructure. Changes there should include contract tests and a concise change note.

## License

This repository was created for the Statathon project. Add the project-approved license text here before distributing the software outside the owning organization.
