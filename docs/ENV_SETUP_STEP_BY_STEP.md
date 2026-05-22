# Step-by-step: filling `.env` from `.env.example`

Copy `.env.example` to `.env` in the **repo root** (same folder as `api/`). The API loads `.env` from there. Fill only what you use; omit or leave blank optional keys.

---

## 1. `SECRET_KEY` (JWT signing)

**What:** Long random string for signing auth tokens.

**How to get it:**
- **Windows PowerShell:**  
  `[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }))`
- **Python:**  
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- Or any password manager “generate secure password” (~32+ chars).

Paste the result into `SECRET_KEY=...`. Use a **new** value in production.

---

## 2. `DATABASE_URL` (Postgres / SQLite)

**What:** SQLAlchemy connection string.

**How to get it:**

| Setup | Steps |
|--------|--------|
| **Neon (hosted Postgres)** | 1. [neon.tech](https://neon.tech) → Sign up → New project.<br>2. Dashboard → **Connection details**.<br>3. Copy URI; ensure `sslmode=require` if Neon shows it.<br>Example: `postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require` |
| **Local SQLite** | No host. Uncomment/set: `DATABASE_URL=sqlite:///./statathon.db` (paths relative to how you start the API). |

---

## 3. `UPLOAD_STORAGE_PATH` / `REPORT_STORAGE_PATH`

**What:** Folders on disk for multipart uploads and PDF reports.

**How to get it:**
- Defaults `./storage/uploads` and `./storage/reports` work if those directories exist or your app creates them.
- Use **absolute paths** on Windows if the process cwd differs, e.g. `S:\PROJECTS\statathon\statathon\storage\uploads`.

No cloud account required for local-only flow.

---

## 4. `REDIS_URL` (optional — Celery / queues)

**What:** Redis connection string.

**How to get it:**
- **Local Docker:**  
  `docker run -p 6379:6379 redis:7-alpine`  
  Then `REDIS_URL=redis://localhost:6379/0`
- **Hosted:** Use the URL from Upstash, Redis Cloud, Railway, etc.

If you are not running Celery workers, you can leave the default or leave it unset if nothing in your deployment reads it.

---

## 5. `HUGGINGFACE_API_KEY` / `HUGGINGFACE_HUB_CACHE`

**What:** Authentication for gated models (optional); cache directory for transformers.

**How to get it:**
1. Go to [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
2. Create a **Read** token.
3. Set `HUGGINGFACE_API_KEY=hf_...`

**Cache:** Leave `HUGGINGFACE_HUB_CACHE=./model/cache` or point to a fast disk folder. SentenceTransformer will download MiniLM here on first semantic run unless already cached.

*Statathon semantic pipeline uses Sentence Transformers MiniLM (`all-MiniLM-L6-v2`); usually **no HF token is required** for public models.*

---

## 6. `OPENAI_API_KEY` (optional)

**What:** Only if you add or enable code paths that call OpenAI.

**How to get it:** [platform.openai.com](https://platform.openai.com) → API keys → Create key → paste into `.env`.

If unused, leave empty.

---

## 7. `GEMINI_API_KEY` / `GOOGLE_API_KEY` / `GEMINI_SEMANTIC_MODEL` *(semantic ambiguity refinement)*

**What:** Optional **small** LLM adjustment when deterministic domain scores are **ambiguous**. The code accepts either `GEMINI_API_KEY` **or** `GOOGLE_API_KEY` (see `services/gemini_semantic_fallback.py`).

**How to get it:**
1. Open **Google AI Studio**: [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey) (Google account required).
2. **Create API key** → copy it.
3. Set **one** of:
   - `GEMINI_API_KEY=...`
   - or `GOOGLE_API_KEY=...`
4. Optional: uncomment in `.env` and set  
   `GEMINI_SEMANTIC_MODEL=gemini-1.5-flash`  
   (or another model ID supported by `google.generativeai`).

**Cost note:** Gemini is called **only when** the gap between the top two domain scores is **&lt; 0.08**. Empty keys ⇒ no Gemini usage.

---

## 8. S3-compatible storage (`STORAGE_PROVIDER`, `S3_*`)

**What:** Presigned uploads (`POST /datasets/upload-url` + register).

**How to get it:**

| Piece | Where it comes from |
|--------|---------------------|
| `STORAGE_PROVIDER` | Leave `s3` for R2 / AWS-compatible APIs. |
| `S3_BUCKET` | Bucket name in R2/AWS console. |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Cloudflare R2 **S3 API** keys (or IAM user keys on AWS). |
| `S3_ENDPOINT_URL` | **Empty** on AWS S3 default endpoint. **R2:** `https://<account_id>.r2.cloudflarestorage.com` from dashboard. |
| `AWS_REGION` | R2 often `auto`. AWS: your bucket’s region (`us-east-1`, etc.). |
| `OBJECT_STORAGE_DISABLED` | Leave empty unless you intentionally disable remote storage. |

**R2 clicks + screenshots:** your repo **`docs/R2_STEP_BY_STEP.md`**.

---

## 9. `STATATHON_CLUSTERING` *(cluster backend)*

**What:** Algorithm for grouping similar columns (`model/semantic_mapping/cluster_engine.py`).

**How to get it:**
- **No external account.** Values:
  - `hierarchical` — default (SciPy; already installed).
  - `hdbscan` — density clustering; requires `pip install hdbscan` on that machine.

If `hdbscan` is missing, the pipeline falls back to hierarchical.

**Skinny CSVs (few columns):** Defaults now use a **`STATATHON_LINKAGE_SIMILARITY_SMALL`** floor and **`STATATHON_SKIP_CLUSTER_MERGE_SMALL`** so HTTP upload benchmarks do not collapse into one cluster. Tune in `.env` (listed next to `STATATHON_CLUSTERING` in `.env.example`).

---

## 10. Neo4j (`NEO4J_*`) *(optional knowledge-graph sync)*

**What:** After each analysis, an optional subgraph is written into Neo4j (columns, domains, clusters, similarity + influence relationships). Requires the Python **`neo4j`** package (`requirements.txt`).

### 10a. Get a Neo4j database

| Option | Steps |
|--------|--------|
| **Docker (local)** | `docker run --name neo4j -p7474:7474 -p7687:7687 -e NEO4J_AUTH=neo4j/your-strong-password neo4j:5` Then use `bolt://localhost:7687` and password you set. |
| **Neo4j Aura Free** | [neo4j.com/cloud/aura/](https://neo4j.com/cloud/aura/) → create instance → note **Neo4j URI**, username, password, database name from connection UI. |

### 10b. Map to `.env`

| Variable | What to put |
|-----------|--------------|
| `NEO4J_ENABLED` | `true` to enable sync each run; `false` to disable (recommended until Neo4j is ready). |
| `NEO4J_URI` | Aura/Router URL (often `neo4j+s://...` or `neo4j://...`) — use exactly what the console shows under “Connect”; local Docker: `bolt://localhost:7687`. |
| `NEO4J_USER` | Usually `neo4j`. |
| `NEO4J_PASSWORD` | The password set for that user. |
| `NEO4J_DATABASE` | Often `neo4j` unless you define another DB (Neo4j 5 Enterprise / Aura shows the name). |

After a successful run, check **`GET /analysis/{analysis_id}/knowledge-graph`** or the **`knowledge_graph`** field in the full results payload.

---

## Quick checklist: “new implementation” knobs only

| Goal | Variables / steps |
|------|-------------------|
| Optional ambiguous-domain LLM nudge | `GEMINI_API_KEY` or `GOOGLE_API_KEY` (+ optional model) |
| HDBSCAN instead of linkage | `STATATHON_CLUSTERING=hdbscan` + `pip install hdbscan` |
| Push graph to Neo4j | Provision DB → `NEO4J_ENABLED=true` + fill URI, user, password, database |
