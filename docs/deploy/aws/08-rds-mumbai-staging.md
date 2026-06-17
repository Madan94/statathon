# RDS Mumbai Staging (shared cloud DB from laptop)

Use this when teammates need a **shared** database for demos. For daily dev, keep **local Docker Postgres** (fastest).

## When to use RDS vs local

| Goal | Use |
|------|-----|
| Fastest pipeline work on your laptop | Local Postgres (`localhost:5432`) |
| Shared staging / demo data across team | RDS Mumbai + SSM tunnel |
| Production | ECS + private RDS in same VPC (see [09-ap-south-1-colocation.md](./09-ap-south-1-colocation.md)) |

RDS Mumbai from a laptop is faster than Xata us-east-1 for DB operations (~30–80 ms vs 600+ ms), but **slower than local Postgres** (~0–15 ms).

---

## 1) Create RDS in ap-south-1 (AWS Console)

1. Region: **Asia Pacific (Mumbai) `ap-south-1`**
2. RDS → Create database:
   - Engine: **PostgreSQL 16**
   - Template: Dev/Test (or Production for backups)
   - Instance: **db.t4g.micro** or **db.t4g.small**
   - DB identifier: `statathon-staging`
   - Master username: `statathon`
   - Master password: (store in Secrets Manager or password vault)
   - Database name: `statathon`
3. Connectivity:
   - VPC: same VPC you will use for future ECS
   - **Private subnets only** (no public access)
   - Security group `sg-rds`: inbound **5432** from bastion SG and (later) `sg-ecs-api`
4. Encryption: ON  
5. Automated backups: ON (7 days minimum for staging)

Note the RDS endpoint, e.g. `statathon-staging.xxxxx.ap-south-1.rds.amazonaws.com`.

---

## 2) Bastion EC2 for SSM tunnel

1. Launch **Amazon Linux 2023** t3.micro in a **public subnet** of the same VPC.
2. Attach IAM role with `AmazonSSMManagedInstanceCore`.
3. Security group `sg-bastion`:
   - No inbound from internet required (SSM agent uses outbound)
   - Outbound: all (or restrict to RDS SG on 5432)
4. Update `sg-rds`: allow **5432** from `sg-bastion`.

Install Session Manager plugin on your laptop:  
https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html

---

## 3) Start SSM port forward

Copy [`.env.rds-staging.example`](../../../.env.rds-staging.example) and fill in instance ID + RDS endpoint.

```powershell
# From repo root — keeps tunnel open in this terminal
.\scripts\aws\rds_ssm_tunnel.ps1
```

Or manually:

```powershell
aws ssm start-session `
  --target i-0123456789abcdef0 `
  --document-name AWS-StartPortForwardingSessionToRemoteHost `
  --parameters host="statathon-staging.xxxxx.ap-south-1.rds.amazonaws.com",portNumber="5432",localPortNumber="5433" `
  --region ap-south-1
```

Leave this terminal open while developing.

---

## 4) Point `.env` at the tunnel

Comment local `DATABASE_URL` and uncomment RDS staging lines (or merge from `.env.rds-staging.example`):

```env
# DATABASE_URL=postgresql://postgres:postgres@localhost:5432/statathon
DATABASE_URL=postgresql://statathon:PASSWORD@127.0.0.1:5433/statathon?sslmode=require
DB_POOL_SIZE=5
DB_POOL_MAX_OVERFLOW=10
DB_STATEMENT_TIMEOUT_MS=30000
```

Restart uvicorn after changing `.env`.

---

## 5) Bootstrap schema (first time only)

With tunnel active:

```powershell
.\scripts\aws\bootstrap_rds_schema.ps1
```

Or manually:

```powershell
python scripts/migrate_db.py --bootstrap
python scripts/migrate_db.py
cd api
python -c "
from database.database import engine, Base
import database.models
from database.migrate_drop_weight_application import migrate_drop_weight_application_schema
from database.migrate_schema_graph_edges import migrate_schema_graph_edges_schema
from database.migrate_column_dictionary import migrate_column_dictionary_schema
from database.migrate_perf_indexes import migrate_perf_indexes
Base.metadata.create_all(bind=engine)
migrate_drop_weight_application_schema()
migrate_schema_graph_edges_schema()
migrate_column_dictionary_schema()
migrate_perf_indexes()
print('OK')
"
```

---

## 6) Verify

```powershell
python scripts/verify_db_connection.py
Invoke-RestMethod http://127.0.0.1:8000/health/db
```

Expect `backend: postgresql`, host `127.0.0.1:5433`, `ping_ms` roughly 30–80 from India.

---

## Switch back to local dev

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/statathon
DB_POOL_SIZE=10
DB_POOL_MAX_OVERFLOW=20
DB_STATEMENT_TIMEOUT_MS=15000
```

Restart uvicorn. Stop the SSM tunnel (Ctrl+C).

---

## Security notes

- Do **not** expose RDS to `0.0.0.0/0` for convenience.
- Do **not** commit `.env` or RDS passwords.
- Rotate staging credentials if a tunnel endpoint was shared broadly.
