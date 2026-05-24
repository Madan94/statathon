# Semantic intelligence platform — inputs to configure

Covers **profiling → static ontology → hybrid embeddings → clustering → Postgres/JSON checkpoints → optional Neo4j**.

For **how to obtain each `.env.example` value** (Neon, R2, Gemini, Neo4j, etc.), see **[ENV_SETUP_STEP_BY_STEP.md](ENV_SETUP_STEP_BY_STEP.md)**.

**Full pytest + benchmark workflow, measured accuracy examples, troubleshooting:** **[TESTING_FULL_GUIDE.md](TESTING_FULL_GUIDE.md)**.

**Phase 3 — rule validation, outlier scoring, imputation scoring (detect → candidates → human decision; no auto-destructive edits):** **[PHASE3_PIPELINE.md](PHASE3_PIPELINE.md)**.

## Minimum to run analyses

| Input | Purpose |
|--------|---------|
| `DATABASE_URL` | Postgres (Neon) or SQLite for analyses + semantic/intelligence rows. |
| `UPLOAD_STORAGE_PATH` **or** S3-compatible env (`STORAGE_PROVIDER`, `S3_BUCKET`, credentials) | Load dataset bytes into the profiler + semantic orchestrator. |
| `SECRET_KEY` | JWT signing for protected API routes. |

## Hybrid semantic mapping (embeddings)

- Default: **SentenceTransformers MiniLM** on column names, plus deterministic **profiling snippets** fused into the same text (`Profile signals: type=…; car=…; hints=…`).
- Hugging Face cache: optional `HUGGINGFACE_API_KEY`, `HUGGINGFACE_HUB_CACHE`.
- **Gemini** (optional cost control): refines ambiguous domain scores **only when top-two margins &lt; 0.08** — set `GEMINI_API_KEY` or `GOOGLE_API_KEY`; model via `GEMINI_SEMANTIC_MODEL` (see `services/gemini_semantic_fallback.py`).

## Clustering

| `STATATHON_CLUSTERING` | Behavior |
|------------------------|----------|
| `hierarchical` (default) | Scipy linkage in `cluster_engine.py`. |
| `hdbscan` | Density clustering if `pip install hdbscan` succeeds; smaller `min_cluster_size` on skinny tables (`STATATHON_HDBSCAN_MIN_CLUSTER_SMALL`); otherwise falls back. |

**Small datasets (survey-style, few columns)** — linkage uses a higher similarity bar (`STATATHON_LINKAGE_SIMILARITY_SMALL`) and skips cross-cluster merge by default (`STATATHON_SKIP_CLUSTER_MERGE_SMALL=true`) so Upload→analyze matches direct-pipeline granularity better:

| Variable | Role |
|-----------|------|
| `STATATHON_SMALL_DATASET_MAX_COLS` | Column-count cutoff (default `24`). |
| `STATATHON_LINKAGE_SIMILARITY` | Base linkage cosine bar (default `0.45`, env overrides constructor). |
| `STATATHON_LINKAGE_SIMILARITY_SMALL` | Floor used with small tables (`max(base, small)` default `0.58`). |
| `STATATHON_LINKAGE_SIMILARITY_CAP` | Upper bound (`0.88` default). |
| `STATATHON_SKIP_CLUSTER_MERGE_SMALL` | `true`: no semantic cross-cluster merges when small. |

## Neo4j (optional external graph DB)

Requires `neo4j` Python package (`requirements.txt`). Per-analysis subgraph uses labels prefixed with `Statathon*` and property `analysis_id` for isolation.

| Variable | Notes |
|---------|-------|
| `NEO4J_ENABLED` | `true` / `false` |
| `NEO4J_URI` | e.g. `bolt://localhost:7687` or Aura URI |
| `NEO4J_USER` | default `neo4j` |
| `NEO4J_PASSWORD` | required when enabled |
| `NEO4J_DATABASE` | default `neo4j` |

After sync, summaries appear in API payload `knowledge_graph` and blueprint `neo4j_sync_summary`, and REST `GET /analysis/{analysis_id}/knowledge-graph`.

## Relational profiling tables

Per-analysis rollup and column blobs are mirrored in **`dataset_intelligence_records`** and **`column_intelligence_profiles`** (created by `create_all` on startup) so payloads can be partially reconstructed without the JSON checkpoint.

## HTTP slices

After `POST /analysis/{dataset_id}/analyze`:

- `GET /analysis/{analysis_id}/summary`
- `GET /analysis/{analysis_id}/domains`
- `GET /analysis/{analysis_id}/clusters`
- `GET /analysis/{analysis_id}/graph`
- `GET /analysis/{analysis_id}/blueprint`
- `GET /analysis/{analysis_id}/knowledge-graph`
- `GET /analysis/{analysis_id}/results` — full payload
