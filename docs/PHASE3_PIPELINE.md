# Phase 3 — validation, anomaly, imputation (candidates-first)

Detect → explain → store candidates → **user decision** → apply (future). The main pipeline does **not** auto-delete or auto-impute.

- Orchestration: `pipelines/phase3_pipeline.run_phase3_intel`
- Rules library: `model/config/validation_rule_library.json`
- Packages: `validation/`, `outliers/`, `imputation/`, `decision_engine/`
- API payload: `phase3` under `state.to_api_payload()`
- Tables: `validation_candidates`, `anomaly_results`, `imputation_results` (+ decision stubs `anomaly_decisions`, `imputation_decisions`)

Persistence: `api/services/phase3_persistence_service.py` after semantic persistence in `pipelines/orchestrator.py`.
