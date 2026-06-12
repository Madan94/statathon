---
name: gold-integration
description: 'Use when merging report-builder-ui with feature/report-render-customization, wiring ExecutionBundle-driven generation, fixing the freeze-store signature bug, building the S4 execution coordinator / formula_exec, or validating gold + synthetic formula fixtures. Encodes the verified invariants from INTEGRATION_PLAN.md so generation conforms to the team binding contract instead of re-deriving plans.'
argument-hint: 'phase (0a/0b/2..8), bug (freeze-key, reported_value, multi-measure), or integration task'
---

# Gold Integration (BharatStat: render branch ⟶ deploy trunk)

Authoritative working plan: `INTEGRATION_PLAN.md` (repo root, untracked). Handoff asks: `TEAM_HANDOFF_REQUEST.md`.
Read both before acting. This skill is the durable, verified summary.

## Branch doctrine
- `report-builder-ui` = **canonical truth** (extraction v2, binding, `ExecutionBundle`, readiness gate, lineage, `llm_router`).
- `feature/report-render-customization` = **frozen product donor** (generation schema, executor scaffolding, filler/narrator/assembler/renderer, dashboard render UI, PDF/HTML, edit UI). **Do not commit to it.**
- `integration/gold-trunk` = **the only branch where integration work happens** (deploy + maintain). Base it on the team branch, merge the render donor in with `--no-ff`. Never push or rewrite the two source branches; never rebase published history.

## The core problem (verified in code)
1. Render generation **bypasses** the `ExecutionBundle` and re-derives plans from the flat stash. Make it **consume the bundle**.
2. The render executor is **physical-column based**: `generation/executor.py::_agg_value` does `pd.to_numeric(frame[plan.measure.columnExpr])`. There is **no expression evaluator**; `100 * weighted_share(...)` in the source is a comment. So formula math (SHARE/RATE/RATIO/GROWTH/CAGR/INDEX) and deterministic `reported_value` **must be built**.

## Architecture: C-native (do NOT do a full rewrite unless formula_exec duplicates the executor's output assembly)
```
generate_phase_api → bundle_adapter (map + fan-out multi-measure, stable identity)
  → S4 execution coordinator (route by plan.status then formulaSpec.type)
      → physical executor (KEPT) for DIRECT / simple group_aggregate·rank·trend·metric
      → formula_exec (NEW) for SHARE/RATE/RATIO/GROWTH/CAGR/INDEX/reported_value
  → unified analyticsAST / evidenceAST
  → S5/S6 render pipeline (KEPT): filler → narrator → assembler → renderer
```
New files are **ours**: `report_builder/generation/bundle_adapter.py`, `report_builder/generation/formula_exec.py`,
and the coordinator. Keep the legacy flat-stash path behind a flag (Option-A fallback) during bring-up.

## Invariants (hard rules)
- **Consume `ExecutionBundle`** (`binding.executionBundle.v1`), not rebuilt `BindingAST`. Blueprint = render/output fallback only.
- **No expression strings** to the executor — compute in `formula_exec`.
- **SHARE/RATE/RATIO** = `multiplier · agg(numerator)/agg(denominator)` at the **same grain**, then divide. Never average row ratios.
- **`reported_value`** deterministic per group: one non-null → use; many equal → use; many differing → weighted_mean iff a valid `weightColumn` exists and policy permits, else mark **ambiguous/DEGRADED** (never silent `mean()`).
- **Readiness status gate** (verified in `binding/readiness_gate.py`): `NOT_READY` → block generation; `plan.status == BLOCKED` (missing/absent denominator for SHARE/RATE/RATIO, missing CAGR `timeWindow`, missing INDEX `baseValue`, missing columns) → **do not execute**; `DEGRADED` (GROWTH-missing-periods, `reported_value` ambiguity, `RATE_SUMMED`) → generate with **visible caveats**. **Never** downgrade a contract `error/BLOCKED` into a runnable degrade.
- **Freeze/load keys** must use `BindingAST.datasetSignature`, not `DatasetAST.signature` (absent) or `datasetId`. The bug lives in `freeze_store.py::freeze_bundle` (~L88).
- **Multi-measure**: `analyticsSpec.measure` collapses to `[0]` but the full list is in `plan.resolvedRoles.measures`. Fan out → `plan_<qid>__<measure>` with mapping back to `outputContract.components[]`, table column ID, measure label, `lineage.sourceColumnIds`, evidence ref (else right value, wrong slot).
- **Provenance**: thread `bundle.lineageIndex` + executor `rowIds` into `evidenceAST` and the `ProvenanceDrawer`.
- **LLM**: route via `report_builder.llm_router.llm_text_call/llm_vision_call` (`llm_disabled()` first-class; OpenRouter `openrouter_cheap_dev`). `LLM_DISABLED=1` ⇒ no network, deterministic, offline tests pass.
- **Do-not-touch (team)**: binding execution-contract fields, gold fixtures/tests, freeze-store semantics, value-free validators, `ExecutionBundle` schema. Mandatory fix only → patch + document + change-note (never a silent edit to the team branch).

## Phase gates (see INTEGRATION_PLAN.md for full steps/rollbacks)
- **0a (no source/history writes):** fetch; create local reversible tags `preint-team`/`preint-render` (`git tag -d` to undo); verify clean tree + overlap ⊆ `.gitignore`; inspect+record the freeze-key bug. The failing freeze test is added later, on the trunk (0b/2).
- **1 (merge):** create trunk from team base; `git merge --no-ff` render; union `.gitignore`; untrack `api/statathon.db` (gitignore `*.db`); keep `storage/bindings/demo__*` fixtures.
- **0b/2 (test-first, on trunk):** failing freeze round-trip test → fix key → green; build `bundle_adapter`; rewire `generate_phase_api` to bundle→adapter→coordinator. Gate: plans are bundle-sourced; freeze round-trips by `(template_id, signature)`.
- **3:** `formula_exec` + coordinator; synthetic test per `formulaSpec.type`; `reported_value` no longer averaged.
- **4:** multi-measure fan-out (stable identity) + safe normalization `NONE/WIDE_TO_LONG/DERIVE_COLUMN/FILTER_ROWS`; **block** `JOIN/UNION/PIVOT` → DEGRADE.
- **5:** provenance + supported StatisticalContext propagation (no CV/MoE — fields absent).
- **6:** LLM governance (no direct SDK calls; offline works).
- **7:** energy E2E fixture + synthetic formula fixtures under `tests/fixtures/gold_e2e/`; run guardians + `test_generation_*` + `test_render_*` with `LLM_DISABLED=1`.
- **8:** enhancement (BI robustness, render/UI polish, connectivity).

## Required tests / commands (offline)
```
$env:PYTHONPATH=(Get-Location).Path + ';' + (Join-Path (Get-Location).Path 'api'); $env:LLM_DISABLED='1'
python -m pytest tests/test_extraction_gold.py tests/test_extraction_binder_e2e.py tests/test_binding_contracts.py tests/test_template_compiler_wrapper.py tests/test_template_emit.py -q -p no:cacheprovider
python -m pytest tests/test_generation_s4.py tests/test_generation_s5a.py tests/test_generation_s5b.py tests/test_generation_s5c.py tests/test_generation_s6.py tests/test_generation_s7_api.py tests/test_render_charts.py tests/test_render_document.py tests/test_render_tables.py -q -p no:cacheprovider
```

## MCP usage
`pdf-ocr`/`markitdown` for source statistical PDFs; `memory` for durable branch-integration decisions; `sequential-thinking` for risky contract/merge/formula decisions; `filesystem` for bulk customization edits. **Not** a substitute for code search — use grep/glob/read for code facts.

## Before any merge or formula-execution change
Run the `gold-integration-reviewer` agent to verify claims against code and catch contradictions, stale assumptions, contract violations, and missing tests.
