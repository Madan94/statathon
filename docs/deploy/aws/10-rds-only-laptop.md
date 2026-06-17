# Amazon RDS as your only database (AWS Console)

Create PostgreSQL in **Mumbai (`ap-south-1`)** and connect your laptop API to it. No scripts required.

---

## Part 1 — Create RDS in AWS Console

### Step 1: Open the right region

1. Sign in to [AWS Console](https://console.aws.amazon.com/)
2. Top-right region → **Asia Pacific (Mumbai) `ap-south-1`**

### Step 2: Start database creation

1. Search **RDS** → open **RDS**
2. Left menu → **Databases** → **Create database**

### Step 3: Engine and template

| Setting | Value |
|---------|--------|
| Creation method | **Standard create** |
| Engine type | **PostgreSQL** |
| Engine version | **PostgreSQL 16.x** (latest 16 in list) |
| Templates | **Free tier** or **Dev/Test** |

### Step 4: Settings

| Setting | Value |
|---------|--------|
| DB instance identifier | `statathon-dev` |
| Master username | `statathon` |
| Master password | Choose a strong password (save it — you need it for `.env`) |
| Confirm password | Same |

### Step 5: Instance size

| Setting | Value |
|---------|--------|
| DB instance class | **Burstable classes** → `db.t4g.micro` (or `db.t3.micro`) |
| Storage type | gp3 (default) |
| Allocated storage | 20 GiB |
| Storage autoscaling | Optional (off is fine for dev) |

### Step 6: Connectivity (important for laptop access)

| Setting | Value |
|---------|--------|
| Compute resource | **Don't connect to an EC2 compute resource** |
| Network type | IPv4 |
| VPC | **Default VPC** |
| DB subnet group | default (auto) |
| **Public access** | **Yes** |
| VPC security group | **Create new** |
| New VPC security group name | `statathon-rds-dev` |
| Availability Zone | No preference |
| RDS Proxy | No |

After creation you will edit the security group to allow **your IP only** on port 5432.

### Step 7: Database authentication

| Setting | Value |
|---------|--------|
| Database authentication | **Password authentication** |

### Step 8: Additional configuration

| Setting | Value |
|---------|--------|
| Initial database name | `statathon` |
| DB parameter group | default |
| Option group | default |
| Backup retention | 1–7 days (1 is fine for dev) |
| Encryption | Enable (recommended) |
| Deletion protection | **Off** for dev (so you can delete later) |

### Step 9: Create

Click **Create database**. Status will show **Creating** for about **5–10 minutes**, then **Available**.

---

## Part 2 — Open port 5432 to your laptop only

1. RDS → **Databases** → click `statathon-dev`
2. Under **Connectivity & security** → click the **VPC security group** link (e.g. `statathon-rds-dev`)
3. **Inbound rules** → **Edit inbound rules** → **Add rule**:

| Type | Port | Source | Description |
|------|------|--------|-------------|
| PostgreSQL | 5432 | **My IP** | Laptop dev access |

4. **Save rules**

Do **not** use `0.0.0.0/0` (open to the world).

> If your home IP changes, repeat this step with **My IP** again.

---

## Part 3 — Copy the endpoint

1. RDS → **Databases** → `statathon-dev`
2. Under **Connectivity & security**, copy **Endpoint**, e.g.  
   `statathon-dev.xxxxxxxxxxxx.ap-south-1.rds.amazonaws.com`
3. Note **Port**: `5432`

---

## Part 4 — Update `.env`

In your repo [`.env`](../../../.env), **comment out** local Postgres and set RDS:

```env
# Local Docker (disabled — using RDS):
# DATABASE_URL=postgresql://postgres:postgres@localhost:5432/statathon

# Amazon RDS Mumbai:
DATABASE_URL=postgresql://statathon:YOUR_PASSWORD@statathon-dev.xxxxxxxxxxxx.ap-south-1.rds.amazonaws.com:5432/statathon?sslmode=require
RDS_MASTER_PASSWORD=YOUR_PASSWORD

DB_POOL_SIZE=5
DB_POOL_MAX_OVERFLOW=10
DB_STATEMENT_TIMEOUT_MS=30000
DB_CONNECT_TIMEOUT=10
```

Replace `YOUR_PASSWORD` and the hostname with your real values.

Optional — stop local Docker Postgres (not needed anymore):

```powershell
docker stop statathon-pg
```

---

## Part 5 — Bootstrap schema (first time)

From repo root in PowerShell:

```powershell
cd d:\statathon-hack\statathon
python scripts/migrate_db.py --bootstrap
python scripts/migrate_db.py
```

Or restart the API — startup runs migrations automatically ([`api/main.py`](../../../api/main.py)).

---

## Part 6 — Restart API and verify

```powershell
# Restart uvicorn (stop old process, then):
cd d:\statathon-hack\statathon\api
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd d:\statathon-hack\statathon
python scripts/verify_db_connection.py
Invoke-RestMethod http://127.0.0.1:8000/health/db
```

**Expected:**

- `Backend: postgresql`
- Host contains `ap-south-1.rds.amazonaws.com`
- `ping_ms` roughly **30–80 ms** from India (not 600+ ms like Xata)

---

## Part 7 — Re-seed app data

RDS starts **empty**. After switching:

1. Log in at http://localhost:3000/login (`DEV_TEST_EMAIL` / `DEV_TEST_PASSWORD` in `.env`)
2. Re-upload datasets
3. Run new analyses through the pipeline

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Connection timeout | Security group: add **My IP** on port 5432; confirm **Public access = Yes** |
| `password authentication failed` | Check username `statathon` and password in `DATABASE_URL` |
| `database "statathon" does not exist` | Initial database name was skipped at creation — run `python scripts/aws/create_rds_database.py` from repo root |
| IP changed (new Wi‑Fi) | Update security group **My IP** rule again |
| Still slow on file upload | S3 is separate — DB is fast; large CSV reads still hit S3 region |

---

## Cost and cleanup

- `db.t4g.micro` in Mumbai ≈ **$12–15/month** + storage
- When finished: RDS → `statathon-dev` → **Actions** → **Delete** → uncheck final snapshot if you don't need backup

---

## Production later

For real deploy: **private RDS** (Public access = No) in same VPC as ECS. See [09-ap-south-1-colocation.md](./09-ap-south-1-colocation.md).
