# Full testing guide — Statathon semantic platform

This document explains **how verification works**, **accuracy numbers** (with caveats), **commands to run everything**, and **what to do when something fails**.

---

## 1. What “accuracy” means here

The semantic layer does **not** train on your labels. It combines:

1. **Sentence embeddings** (MiniLM) on normalized column names (+ optional **profiling snippets** inside the full pipeline).
2. **Static domain prototypes** from `domain_definitions` / repository.
3. **Dynamic domains** (`dyn_<theme>_…`) synthesized per dataset archetype.
4. **Keyword / context boosts** over tokens and dataset archetype from `DatasetContextInferencer`.
5. **Cluster cohesion** and **schema-graph consistency** in confidence (not a separate classifier).

**Therefore:**

- **Exact domain string match** vs a hand-made benchmark is often **low**, because predictions may be `dyn_income_…` instead of `income`. That is **expected**, not a regression.
- The benchmark script’s **relaxed accuracy** treats a match when:
  - predicted equals gold, **or**
  - predicted **contains** gold as substring, **or**
  - predicted looks like `dyn_<gold>_…`.

Use relaxed metrics for “did we land in the right semantic neighbourhood?”

**Profiling + HTTP path:** The API runs **real pandas profiling** and passes **profile snippets** into embeddings. That can **change** clustering vs “column names only” (`scripts/benchmark_semantic_e2e.py` direct mode), so benchmarks between modes are **not apples-to-apples**.

---

## 2. Automated suite (always run this first)

From **repo root** (`statathon/statathon`):

```powershell
cd S:\PROJECTS\statathon\statathon
python -m pip install -r requirements-windows.txt   # or requirements.txt on Linux/CUDA stack
python -m pytest tests -v --tb=short
```

**Latest run (representative):** **15 passed** covering:

| Area | File |
|------|------|
| AnalysisState / API payload | `tests/test_analysis_state.py` |
| Semantic adapter + clusters | `tests/test_analysis_state.py` |
| Dataset profiling + snippets | `tests/test_dataset_intel.py` |
| Ingestion health | `tests/test_ingestion.py` |
| Semantic pipeline (fake embedder — fast, deterministic) | `tests/test_semantic_pipeline.py` |
| R2/object key shape | `tests/test_storage_keys.py` |

**Known noise:** `DeprecationWarning` from `audit_logger.py` (`utcnow`) — does not fail tests.

---

## 3. Semantic benchmark (real MiniLM + synthetic CSV)

### A) Direct pipeline (column names only, no HTTP)

```powershell
cd S:\PROJECTS\statathon\statathon
python scripts\benchmark_semantic_e2e.py
```

**Example output (this environment):**

| Metric | Value |
|--------|--------|
| Wall time | ~3.5 s (weights already cached) |
| Exact match rate | **30%** (3/10 columns) |
| Relaxed match rate | **70%** (7/10) |
| Graph edges (deduped list) | 8 |
| Audit steps | 9 (normalization → embeddings → … → priority) |

### B) Full HTTP path (SQLite temp DB + profiling + checkpoint)

```powershell
cd S:\PROJECTS\statathon\statathon
python scripts\benchmark_semantic_e2e.py --http
```

**Example output (this environment, first run with model download):**

| Phase | Time |
|-------|------|
| Upload | ~0.05 s |
| Analyze (includes profiling + transformers) | **~113 s** (dominated by first MiniLM load + GPU/CPU) |
| GET /results | ~0.02 s |

**Accuracy (same gold labels, different path):**

| Metric | Value |
|--------|--------|
| Exact | **10%** (1/10) |
| Relaxed | **50%** (5/10) |

**Why HTTP can look “worse” on exact/relaxed:**

- Embeddings include **profile-derived text** → different similarity geometry.
- Small synthetic table → **one dominant cluster** sometimes (all columns in `cluster_0` in the sample run); hierarchical linkage is sensitive to thresholds and sample size.
- **Not a failure** if API returns 200 and payload includes `column_profiles`, `schema_blueprint`, `knowledge_graph`.

Optional: save JSON

```powershell
python scripts\benchmark_semantic_e2e.py --http --dump-json .\tmp\bench_results.json
```

---

## 4. Manual API smoke (your real `.env`)

1. Start API (from repo root, `api` on `PYTHONPATH`):

   ```powershell
   cd S:\PROJECTS\statathon\statathon\api
   python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

2. Check:

   - `GET http://localhost:8000/health`
   - `GET http://localhost:8000/health/db` (needs valid `DATABASE_URL`)

3. Authenticated flows: register user, upload dataset, `POST /analysis/{dataset_id}/analyze`, then:

   - `GET /analysis/{id}/summary`
   - `GET /analysis/{id}/domains`
   - `GET /analysis/{id}/clusters`
   - `GET /analysis/{id}/graph`
   - `GET /analysis/{id}/blueprint`
   - `GET /analysis/{id}/knowledge-graph`
   - `GET /analysis/{id}/results`

---

## 5. Failure playbook → fix

| Symptom | Likely cause | What to do |
|--------|----------------|------------|
| `pytest` import errors for `semantic_mapping` | Wrong cwd | Always run from **repo root**, or `sys.path` as in `tests/`. |
| `ModuleNotFoundError: neo4j` | Neo4j sync enabled but package missing | `python -m pip install "neo4j>=5.26,<6"` **or** set `NEO4J_ENABLED=false`. |
| Neo4j sync: `ok: false` in `knowledge_graph` | Auth / URI / firewall | Check `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`; Aura needs **TLS** URI from console. |
| `database unreachable` | Bad `DATABASE_URL` or SSL | Neon: include `?sslmode=require`. Test with `/health/db`. |
| Presigned upload fails | R2/S3 env | Follow `docs/R2_STEP_BY_STEP.md`; rotate keys if leaked. |
| **HF Hub** warnings / slow first run | No token, Windows symlinks | Optional: `HUGGINGFACE_API_KEY`; symlink warning: enable **Developer Mode** or ignore (cache still works). |
| **All columns in one cluster** | Small survey tables + coherence merge | Defaults now raise linkage bar and skip merges when `≤STATATHON_SMALL_DATASET_MAX_COLS` (see `SEMANTIC_PLATFORM_INPUTS.md`). Optionally `STATATHON_CLUSTERING=hdbscan` after `pip install hdbscan`. |
| Gemini errors | Wrong key / quota | Gemini is optional; unset keys disables it or fix key in `.env`. |
| `permission denied` on upload/report paths | Paths missing | Ensure `storage/uploads`, `storage/reports` exist; match `.env`. |
| `SECRET_KEY` / JWT failures | Weak or unset | Generate long random secret (see `docs/ENV_SETUP_STEP_BY_STEP.md`). |

---

## 6. How to interpret “success” end-to-end

**Green path:**

1. `pytest tests` → all pass.
2. `benchmark_semantic_e2e.py` (direct or `--http`) exits **0** and prints JSON with `accuracy` and audit steps **without** `error` keys.
3. Live API: upload + analyze completes; `/results` includes `semantic_mapping`, `column_profiles`, `dataset_profile`, `schema_blueprint`, `knowledge_graph` (Neo4j may show `enabled: false`).

**Accuracy expectations:** Benchmark numbers are **diagnostic**, not production SLAs: they depend on ontology, synthetic gold labels, and whether profiling is on. Tune **ontology JSON**, **domain descriptions**, thresholds, or add **labeled feedback** loops if you need higher exact match rates.

---

## 7. One-liner recap

```powershell
cd S:\PROJECTS\statathon\statathon
python -m pytest tests -v --tb=short
python scripts\benchmark_semantic_e2e.py
python scripts\benchmark_semantic_e2e.py --http
```

For environment variables and where to obtain them, see **`docs/ENV_SETUP_STEP_BY_STEP.md`** and **`docs/SEMANTIC_PLATFORM_INPUTS.md`**.
