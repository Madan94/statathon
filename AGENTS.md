# AGENTS.md — BharatStat working guide for AI assistants

> Local assistant guide (untracked working doc, like `INTEGRATION_PLAN.md` /
> `TEAM_HANDOFF_REQUEST.md`). Commit it or delete it freely — it changes no app behaviour.
> Auto-loaded by GitHub Copilot CLI from the repo root.

## What this project is
**BharatStat** — turns raw statistical datasets/PDFs into audit-ready intelligence and
publication-grade reports. Stack: **FastAPI** backend + **Next.js** dashboard + a
document-AI extraction pipeline (pdfplumber → LayoutLMv3 → Qwen2.5-VL → report builder),
a **Neo4j** knowledge graph, and a multi-agent reasoning layer.

## Services & ports
| Service | Port | Notes |
|---|---|---|
| FastAPI API | 8000 | `api/` |
| LayoutLMv3 (layout detect) | 8001 | Docker `layoutlm` |
| SGLang / Qwen2.5-VL (vision) | 8002 | Docker `sglang`, GPU |
| Neo4j | 7474 / 7687 | graph; `NEO4J_ENABLED` |
| Redis | 6379 | Celery + checkpoint cache |
| Next.js dashboard | 3000 | `dashboard/` |

## Run & test (Windows / this machine)
- **Python 3.13** local (project supports 3.12+). Repo root is auto-added to `sys.path`
  by `conftest.py` — no `PYTHONPATH` needed. Use the repo `.venv`.
- **Tests:** `python -m pytest -m "not live" -q` (offline-safe; skips live-service tests).
  Markers: `live`, `live_db`, `live_s3`, `live_llm`, `live_vlm`, `live_sglang`.
  CI gates `tests/test_template_engine/` at **70%** coverage.
- **Lint:** CI runs `ruff check template_engine/ agents/ report_builder/ ast_core/ --select E,F,W --ignore E501`.
  (ruff is not installed locally by default — `pip install ruff` if you need it.)
- **Frontend:** `cd dashboard; npm run dev` (or `build` / `lint`). Next 16 / React 19 /
  TypeScript / Tailwind 4 / ESLint 9. `node_modules` is already installed.
- **Smoke scripts:** 40+ in `scripts/smoke_*.py`; pipeline via `scripts/run_pipeline.py`;
  PowerShell helpers `scripts/local-*.ps1`; service check `scripts/verify_vlm_services.py`.

## Hard conventions (do not violate)
1. **Never hardcode model names or endpoints in Python.** Everything lives in `.env`
   (see `.env.example` §5 model selection, §6–9 providers). Read config from env.
2. **Offline / air-gapped mode:** `LLM_DISABLED=1` skips every LLM/VLM call and runs the
   pipeline deterministically on pdfplumber + programmatic fallbacks (LayoutLM auto-degrades
   to pdfplumber when its server is down). Use this for local dev and GPU-less testing.
3. **Pipeline:** `EXTRACTION_PIPELINE=v2` is current. v1 (ColPali) is legacy — don't build on it.
4. **Windows requirements:** install from `requirements-windows.txt` (or
   `requirements-windows-noxlrd.txt`), not the CUDA-heavy `requirements.txt`.

## Key directories
- `api/` FastAPI app · `agents/` reasoning agents (planner, scribe, retrieval, verifier,
  deep, analytics, `consensus_engine`) · `report_builder/` + `template_engine/` report gen
  · `ast_core/` document AST · `graph/` Neo4j · `core/ingestion.py` ingest ·
  `object_storage/` R2/S3 · `imputation/ outliers/ profiling/ validation/ analytics/` stats
  · `dashboard/` Next.js · `scripts/` ops & smoke · `tests/` pytest.

## Data layer
SQLite `statathon.db` (dev) · Postgres/Supabase (prod, `DATABASE_URL`) · Cloudflare R2/S3
via `boto3` · Neo4j graph. Optional Qdrant LTM (`LTM_ENABLED`, off by default).

## This machine / corporate-laptop constraints
- **Docker is NOT installed here** → LayoutLM / Qwen / Neo4j / Redis containers can't run
  locally. For local work, prefer `LLM_DISABLED=1` + pdfplumber and `-m "not live"` tests.
- **Corporate network filters some hosts** (the `xlrd` wheel and the UB-Mannheim Tesseract
  host return 403). **`uv`'s managed-Python download is unreliable** (connection resets) —
  always use a **system-Python venv** for tests, never `uv run --with` / uvx-managed Python.
  npm registry and PyPI are otherwise reachable.
- **Keep everything in user-writable paths. No system PATH/env or admin changes.**
- **Never commit secrets** or write to: `.env*`, `audit_log.json`, `weights/`, `model/cache/`.
- Poppler (if needed) lives at `C:\poppler\Library\bin` (`POPPLER_PATH`).

## MCP tooling available in this workspace
Configured in `.vscode/mcp.json` (the file VS Code reads; loads at session start):
`filesystem`, `pdf-ocr` (per-page text + scanned-page OCR; Tesseract via
`TESSDATA_PREFIX=C:\Users\2504861\.copilot-mcp\tessdata`), `markitdown` (PDF→Markdown),
`pdf-reader`, `sequential-thinking`, `memory` (local graph at
`C:\Users\2504861\.copilot-mcp\memory\memory.json`). After editing `.vscode/mcp.json`,
reload VS Code (or run `/mcp`) to pick up changes.

## Current focus
Cross-branch integration: render branch ⟶ deploy trunk, rewiring generation to consume the
team's **`ExecutionBundle`** (`binding.executionBundle.v1`) contract. See `INTEGRATION_PLAN.md`
and `TEAM_HANDOFF_REQUEST.md` (both untracked working docs in the repo root).

## Gold integration invariants (verified — do not violate)
- `report-builder-ui` is canonical for extraction/binding; `feature/report-render-customization` is a **frozen**
  render/UI donor. Integration happens **only** on the new `integration/gold-trunk`; never push/rewrite the two source branches.
- Generation must consume the **`ExecutionBundle`** (`binding.executionBundle.v1`), **not** rebuilt binding internals.
  Blueprint is fallback for render/output shaping only.
- The frozen render executor is **physical-column based** (`_agg_value` reads `frame[plan.measure.columnExpr]`) — it has
  **no expression evaluator**. Never emit formula strings like `100 * weighted_share(...)` expecting evaluation; compute
  formulas in `formula_exec` (SHARE/RATE/RATIO/GROWTH/CAGR/INDEX) via an S4 coordinator that keeps the S5/S6 pipeline.
- SHARE/RATE/RATIO: aggregate numerator & denominator at the **same grain, then divide** — never average row ratios.
- `reported_value` must **never** silently fall through to `mean()` (deterministic: single→use; equal→use; differing→
  weighted_mean iff valid weight & policy, else mark ambiguous/DEGRADED).
- Honor the readiness gate: `NOT_READY` blocks generation; `plan.status == BLOCKED` (missing denominator / CAGR
  `timeWindow` / INDEX `baseValue`) is **not executed** and must **not** be softened to a runnable degrade.
- Freeze/load keys must use **`BindingAST.datasetSignature`**, not `DatasetAST.signature` (absent) or `datasetId`.
- Multi-measure: fan out with stable `plan_<qid>__<measure>` ids + slot/lineage mapping (else right value, wrong slot).
- Keep guardian tests green, never weaken: `test_extraction_gold`, `test_extraction_binder_e2e`, `test_binding_contracts`,
  `test_template_compiler_wrapper`, `test_template_emit`. Touch team `report_builder/binding/**` or extraction only if
  mandatory (error/contract bug) → patch + document + notify (change-note), never a silent edit.
- Route all model calls through `report_builder.llm_router.llm_text_call/llm_vision_call` (`LLM_DISABLED=1` ⇒ deterministic).
- Use MCP deliberately: `pdf-ocr`/`markitdown` for source PDFs, `memory` for durable cross-session integration facts,
  `sequential-thinking` for high-risk branch/contract decisions — **not** as a substitute for code search (use grep/glob/read).
