# Cloudflare R2 — step-by-step (STATATHON)

Use this checklist with STATATHON’s presigned upload API. Backend code treats R2 like **S3-compatible storage** (`boto3` + **`S3_ENDPOINT_URL`** pointing at R2).

---

## Phase A — Cloudflare (outside the repo)

### Step 1 — Cloudflare account + R2 enabled

**Do**

1. Log in to [dash.cloudflare.com](https://dash.cloudflare.com).
2. Sidebar → **R2** → turn on/buy R2 if prompted (billing may attach; free tier still applies within limits).

**How you know it worked**

| Check | Confidence |
|--------|------------|
| R2 dashboard opens without “enable R2” blockers | **High** |

---

### Step 2 — Create bucket

**Do**

1. R2 → **Create bucket** → name it (e.g. `statathon-datasets`).
2. Note the **exact bucket name** → this is **`S3_BUCKET`**.

**How you know it worked**

| Check | Confidence |
|--------|------------|
| Bucket appears in the list | **High** |

---

### Step 3 — S3 API credentials (Access Key ID + Secret)

**Do**

1. R2 → **Manage R2 API Tokens** (or **Overview** → API section).
2. **Create API token** with permission to **read + write** the bucket you created (scoped to that bucket when possible).
3. Save **`Access Key ID`** and **`Secret Access Key`** — shown **once**.
4. These map directly to **`AWS_ACCESS_KEY_ID`** and **`AWS_SECRET_ACCESS_KEY`** in `.env` (the names stay “AWS…” for boto3 compatibility; you are still talking to R2).

**How you know it worked**

| Check | Confidence |
|--------|------------|
| Token listed in dashboard; secrets only you have locally | **High** |

---

### Step 4 — Account ID → endpoint URL

**Do**

1. Cloudflare dashboard home / R2 sidebar — copy **`Account ID`**.
2. Set:

```text
S3_ENDPOINT_URL=https://<YOUR_ACCOUNT_ID>.r2.cloudflarestorage.com
```

(no trailing slash; replace `<YOUR_ACCOUNT_ID>`).

**How you know it worked**

| Check | Confidence |
|--------|------------|
| URL matches Cloudflare docs pattern for account | **High** |

---

### Step 5 — CORS on the bucket (required for browser uploads)

**Skip** if you only test from **curl / Postman / server-side scripts** on the **same machine** as the API — CORS is a **browser** rule.

For a **SPA** uploading from another origin:

**Do**

1. R2 → your bucket → **Settings** → **CORS**.
2. Add a policy that allows your frontend origin:

```json
[
  {
    "AllowedOrigins": [
      "http://localhost:3000",
      "http://127.0.0.1:3000",
      "https://your-production-domain.com"
    ],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag", "Content-Length"],
    "MaxAgeSeconds": 3600
  }
]
```

**Important:** `AllowedOrigins` must match the **exact** frontend origin shown in your browser address bar. If you open the app at `http://127.0.0.1:3000`, **`http://localhost:3000` alone does not qualify** — add both origins (as above) or always use one URL.

`AllowedHeaders: ["*"]` avoids flaky “preflight succeeded but PUT blocked” behaviour when extra headers slip in beside `Content-Type`.

**How you know it worked**

| Check | Confidence |
|--------|------------|
| Browser PUT to presigned URL no longer blocked by CORS in devtools Network | **High** when testing from FE |
| Curl-only tests unaffected | **N/A — CORS not applied** |

---

## Phase B — STATATHON `.env`

### Step 6 — Database + Neon migration (Postgres)

**Do**

1. Set **`DATABASE_URL`** for Neon (recommended) — same as today.
2. If this database already had **`datasets`** before storage columns existed, run the **`ALTER TABLE`** block in **`docs/OBJECT_STORAGE.md`** (once).

**SQLite local**

- Easiest smoke test: use a **new** SQLite path or delete the old file so **`create_all`** builds the new schema.

**How you know it worked**

| Check | Confidence |
|--------|------------|
| `GET /health/db` returns reachable | **High** |
| `POST /datasets/register` does not crash with **missing column** errors | **High** |

---

### Step 7 — R2 variables (copy into `.env`)

```bash
STORAGE_PROVIDER=s3         # boto3 client is still named "s3"; R2 is S3-compatible
S3_BUCKET=statathon-datasets
AWS_ACCESS_KEY_ID=<from R2 token>
AWS_SECRET_ACCESS_KEY=<from R2 token>
S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
AWS_REGION=auto
S3_UPLOAD_PREFIX=datasets
PRESIGNED_UPLOAD_EXPIRES_SECONDS=3600
```

**Do**

1. Paste into **`.env`** at repo root (same file **`database`** already loads).

**How you know it worked**

| Check | Confidence |
|--------|------------|
| `pip show boto3` shows installed | **High** |

---

### Step 8 — Run the API

**Do** (PowerShell — from **`api/`** folder):

```powershell
cd S:\PROJECTS\statathon\statathon\api
$repo = "S:\PROJECTS\statathon\statathon"
# Optional if something still can't import `storage` / `pipelines`:
$env:PYTHONPATH = "$repo;$repo\api"

pip install boto3 pydantic-settings -q  # plus requirements-windows.txt etc.
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Replace `S:\PROJECTS\statathon\statathon` with your actual repo root.  
**Note:** `main.py` already adds the repo root to `sys.path`, so **`PYTHONPATH` is mainly a fallback** when running tests or tooling from arbitrary cwd.

**How you know it worked**

| Check | Accuracy |
|--------|----------|
| `GET http://localhost:8000/health` → `{"status":"ok"}` | **High** |

---

## Phase C — End-to-end API test (manual)

Assume API base **`http://127.0.0.1:8000`**.

### Step 9 — Mint presigned PUT

**Accuracy this step**: **High** — wrong env → **`503`** with a clear **`StorageConfigError`** message.

```powershell
$r = Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/datasets/upload-url" `
  -ContentType "application/json" `
  -Body '{"filename":"demo.csv","content_type":"text/csv"}'
$r.upload_url
$r.object_key
```

Expect JSON: **`upload_url`**, **`object_key`**, **`expires_in`**.

---

### Step 10 — PUT file bytes **with same Content-Type**

**Accuracy**: **High** — wrong `Content-Type` → **`403`** from storage (signature mismatch).

```powershell
# Create a tiny CSV
"a,b`n1,2" | Out-File -FilePath .\demo.csv -Encoding utf8NoBOM
$bytes = [System.IO.File]::ReadAllBytes((Resolve-Path .\demo.csv))

Invoke-WebRequest -Method PUT -Uri $r.upload_url `
  -ContentType "text/csv" `
  -Body $bytes
```

Use **exactly** **`text/csv`** if step 9 used **`text/csv`**.

Expect **HTTP 200** or **204** from R2.

---

### Step 11 — Register (size must match exactly)

**Accuracy**: **High** — **`HeadObject`** checks **`Content-Length`** vs your **`file_size`** (± `REGISTER_SIZE_TOLERANCE_BYTES`, default **8** bytes).

```powershell
$len = $bytes.Length
$reg = @{ object_key = $r.object_key; filename = "demo.csv"; file_size = $len; checksum = $null }
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/datasets/register" `
  -ContentType "application/json" `
  -Body ($reg | ConvertTo-Json)
```

Expect **`dataset_id`** and **`analysis_id`**.

Failure modes:

| Symptom | Likely cause |
|--------|----------------|
| 400 **file_size mismatch** | BOM / wrong file read / length not raw byte length |
| 400 **object_key not found** | PUT failed or wrong key |

---

### Step 12 — Poll dataset + analysis

**Accuracy**:

| Endpoint | Validates |
|-----------|-----------|
| `GET /datasets/{id}` | Row exists + **`upload_status`** transitions |
| `GET /analysis/{id}/results` | Semantic payload when status **`complete`** |

```powershell
# replace IDs from register response
Invoke-RestMethod "http://127.0.0.1:8000/datasets/1"
Invoke-RestMethod "http://127.0.0.1:8000/analysis/1/results"
```

While background job runs: results may respond **`409 Analysis still running`**. Retry until **200**.

**Semantic / domain “accuracy”** is **not** scored by these HTTP steps — run **`scripts/benchmark_semantic_e2e.py`** for pipeline vs gold labels separately.

---

## Phase D — Automated tests we already ship (repo)

Does **not** call live R2; checks wiring/helpers.

```powershell
cd S:\PROJECTS\statathon\statathon
$env:PYTHONPATH = "S:\PROJECTS\statathon\statathon\api;S:\PROJECTS\statathon\statathon"
python -m pytest tests/test_storage_keys.py tests/test_analysis_state.py -q
```

Expect **green**.

---

## One-page accuracy summary (this flow — not ML)

| Step | What is verified |
|------|-------------------|
| 1–5 | Manual Cloudflare correctness | **Operational** |
| Presigned mint | boto3 SigV4 + **`Content-Type` in signature | **Strong** |
| PUT | Bytes stored under **`object_key`** | **Strong** |
| Register | **`HeadObject` + ContentLength vs `file_size`** | **Strong** |
| Analyze | Downloads object, runs **`SemanticPipeline`** + persistence | Same as multipart path (**functional** correctness; **taxonomy** accuracy = separate benchmarks) |

---

## Troubleshooting

| Issue | Fix |
|--------|-----|
| `503` “Object storage…” on `/datasets/upload-url` | Missing **`S3_BUCKET`** / keys / **`pip install boto3`** |
| `403` on PUT | **`Content-Type`** must match **`upload-url`** request |
| `SignatureDoesNotMatch` | **`S3_ENDPOINT_URL`** typo; keys wrong; clock skew rare |
| **`storage.vector_store`** / semantic import errors | The S3 adapter lives in **`object_storage/`** (top-level), so **`model/storage/`** stays available for embeddings — pull latest code and restart |

For policy details always confirm on [Cloudflare R2 docs](https://developers.cloudflare.com/r2/).
