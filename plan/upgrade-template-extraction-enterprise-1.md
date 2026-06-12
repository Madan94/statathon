---
goal: Upgrade template extraction to emit enterprise-grade binder-ready template packages
version: 1.0
date_created: 2026-06-12
last_updated: 2026-06-12
owner: BharatStat report builder
status: 'Planned'
tags: [upgrade, report-builder, extraction, binder, enterprise-template]
---

# Introduction

![Status: Planned](https://img.shields.io/badge/status-Planned-blue)

This plan upgrades BharatStat template extraction so generated packages match the enterprise-grade binder contract used by `report_builder\gold_standard\plfs_enterprise_annual.template.blueprint.json`, `report_builder\gold_standard\plfs_enterprise_annual.template.ast.json`, and `report_builder\gold_standard\plfs_enterprise_annual.semantic_slot_graph.json` without copying PLFS-specific content into other domains. The target output is a domain-adaptive package with nested outline structure, officer controls, data/publication/binder contracts, rich question contracts, evidence-linked entities, publication AST sections, and an internally consistent semantic slot graph.

## 1. Requirements & Constraints

- **REQ-001**: Generated extraction packages MUST include `template.blueprint.json`, `template.ast.json`, `semantic_slot_graph.json`, `template.diagnostics.json`, and `template.package.json`.
- **REQ-002**: `template.blueprint.json` MUST support nested `topics[].chapters[].sections[].questions[]` while preserving compatibility with legacy `topics[].questions[]`.
- **REQ-003**: `template.blueprint.json` MUST include top-level enterprise contracts: `officerCustomization`, `dataContract`, `binderDeliverableContract`, `publicationContract`, `formulaCatalog`, `qualityGateProfile`, and `officerWorkbench`.
- **REQ-004**: Every final entity in `template.blueprint.json.entities[]` MUST include `entityId`, `name`, `entityType`, `aliases`, `sourceRefs`, `evidence`, `aggregationPolicy`, `binderHints`, `qualityRules`, and `officerReview`.
- **REQ-005**: Every final question MUST include `questionId`, `intent`, `questionText`, `questionType`, `requiredEntities`, `formulaSpec`, `binderContract`, `qualityGates`, `provenanceRequirements`, `customization`, `answerPlan`, and `answerStructure`.
- **REQ-006**: Every final question MUST include at least one provenance component in `answerStructure.components[]`.
- **REQ-007**: `template.ast.json` MUST include `customizationAST`, `publicationAST`, and `officerGuideAST`.
- **REQ-008**: `semantic_slot_graph.json` MUST have no broken `fillFrom`, no missing `componentId` for analytical slots, no duplicate slot IDs, and complete question/component/topic lineage.
- **REQ-009**: `fillFrom` fields MUST reference component IDs, not question IDs.
- **REQ-010**: Diagnostics MUST mark any package with broken slot refs, duplicate IDs, missing required source/evidence, or low slot integrity as `INVALID`.
- **REQ-011**: `binderReadinessScore` MUST be capped below passing thresholds when blocking errors exist.
- **REQ-012**: Provider calls with JSON schemas MUST record whether API-level schema enforcement occurred and diagnostics MUST warn when schema-required calls were not enforced.
- **REQ-013**: Existing PLFS enterprise built-in outputs MUST remain valid.
- **REQ-014**: Existing offline tests MUST continue to pass.
- **SEC-001**: Do not write or commit secrets, credentials, `.env*`, `audit_log.json`, `weights\`, or model cache artifacts.
- **CON-001**: Do not hardcode model names or endpoints in Python; model/provider behavior MUST remain environment-configured.
- **CON-002**: Local validation MUST work with `LLM_DISABLED=1` and without Docker services.
- **CON-003**: Do not copy PLFS-specific content into extracted energy templates; reuse only enterprise structure and contract style.
- **PAT-001**: Prefer deterministic post-processing for enterprise contracts over asking an LLM to invent binder contracts.
- **PAT-002**: Preserve backward compatibility for legacy flat templates unless a stricter enterprise validation path explicitly requires nested structure.

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: Add shared recursive outline/question traversal utilities and replace shallow extraction traversal.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Create `report_builder\template_traversal.py` with `walk_outline_nodes(blueprint: dict) -> list[dict]`, `iter_questions(blueprint: dict) -> list[dict]`, `iter_question_contexts(blueprint: dict) -> list[dict]`, and `iter_components(question: dict) -> list[dict]`. The traversal MUST recursively support `topics`, `chapters`, `sections`, `children`, `subtopics`, `subsections`, and legacy direct `questions`. Each context MUST include `topicId`, `topicTitle`, `chapterId`, `chapterTitle`, `sectionId`, `sectionTitle`, `question`, and `path`. | ✅ | 2026-06-12 |
| TASK-002 | Update `report_builder\slot_wiring.py` so its public `iter_questions()` delegates to `report_builder.template_traversal.iter_questions()` and all slot graph context mapping uses `iter_question_contexts()`. | ✅ | 2026-06-12 |
| TASK-003 | Update `report_builder\template_emit.py` functions that loop over `topics[].questions[]`, including `compact_skeleton_ast`, `conform_components`, `conform_entities`, and `synthesize_figure_templates`, to use `iter_question_contexts()` and `iter_components()`. | ✅ | 2026-06-12 |
| TASK-004 | Update `report_builder\extraction_diagnostics.py` private `_iter_questions()` to delegate to `report_builder.template_traversal.iter_questions()` so diagnostics count nested questions correctly. | ✅ | 2026-06-12 |
| TASK-005 | Add tests in `tests\test_template_extraction_enterprise.py` verifying recursive traversal returns questions from `topics[].chapters[].sections[].questions[]` and legacy `topics[].questions[]`. | ✅ | 2026-06-12 |

### Implementation Phase 2

- GOAL-002: Add deterministic enterprise contract enrichment for extracted blueprints.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-006 | Create `report_builder\enterprise_template_contract.py` with `enrich_enterprise_blueprint(blueprint: dict, *, domain: str | None = None) -> dict`. The function MUST deep-copy input, preserve domain content, and inject missing top-level enterprise contracts. | ✅ | 2026-06-12 |
| TASK-007 | In `enterprise_template_contract.py`, implement `infer_domain(blueprint: dict) -> str` using title/entity keywords and support at least `energy`, `labour`, and `generic`. | ✅ | 2026-06-12 |
| TASK-008 | In `enterprise_template_contract.py`, implement deterministic builders for `officerCustomization`, `dataContract`, `binderDeliverableContract`, `publicationContract`, `formulaCatalog`, `qualityGateProfile`, and `officerWorkbench`. Energy domain MUST include units and controls for coal, lignite, crude oil, natural gas, hydro, renewable energy, reserves, potential, geography, and year comparisons. | ✅ | 2026-06-12 |
| TASK-009 | Wire `enrich_enterprise_blueprint()` into `report_builder\template_emit.py` before final blueprint serialization so extraction output receives enterprise contracts without modifying gold-standard PLFS content. | ✅ | 2026-06-12 |
| TASK-010 | Add tests verifying an energy extraction blueprint gains all enterprise top-level contracts and does not gain PLFS-specific LFPR/WPR/UR concepts. | ✅ | 2026-06-12 |

### Implementation Phase 3

- GOAL-003: Enrich entities into binder-effective canonical entities with evidence and officer-review contracts.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-011 | Add `enrich_entities(blueprint: dict, domain: str) -> None` in `report_builder\enterprise_template_contract.py`. It MUST normalize every entity with aliases, `sourceRefs`, `evidence`, `aggregationPolicy`, `binderHints`, `qualityRules`, `officerReview`, and `riskFlags`. | ✅ | 2026-06-12 |
| TASK-012 | Entity enrichment MUST convert existing `sourceRefs` into `evidence[]` records with `evidenceId`, `sourceType`, `page`, `confidence`, `tableId`, `figureId`, `regionRef`, `bbox`, `headerPath`, and `physicalColumn` when present. | ✅ | 2026-06-12 |
| TASK-013 | Entity enrichment MUST assign measure aggregation policies deterministically: rate/percent/share/index entities use `weighted_mean_or_reported_value`; count/total/reserve/capacity entities use `sum`; unknown measures use `reported_value_review_required`. | ✅ | 2026-06-12 |
| TASK-014 | Entity enrichment MUST add a blocking risk flag `missing_source_refs` when an entity lacks real source refs; it MUST NOT silently fabricate page/table evidence. | ✅ | 2026-06-12 |
| TASK-015 | Add tests verifying entities with source refs receive evidence and entities without source refs are flagged. | ✅ | 2026-06-12 |

### Implementation Phase 4

- GOAL-004: Upgrade question and answer component contracts to enterprise binder style.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-016 | Add `enrich_questions(blueprint: dict, domain: str) -> None` in `report_builder\enterprise_template_contract.py`. It MUST process every question from recursive traversal. | ✅ | 2026-06-12 |
| TASK-017 | Question enrichment MUST add `questionText` from `intent` when missing and preserve existing `questionText` when present. | ✅ | 2026-06-12 |
| TASK-018 | Question enrichment MUST add structured `formulaSpec` with `type`, `measureEntityIds`, `dimensionEntityIds`, `timeEntityIds`, `weightColumn`, `multiplier`, `readiness`, and `blockedReasons`. Formula type MUST be inferred deterministically from `questionType`, `intent`, and required entity names: `SHARE`, `RATE`, `RATIO`, `GROWTH`, `INDEX`, `REPORTED_VALUE`, or `DESCRIPTIVE`. | ✅ | 2026-06-12 |
| TASK-019 | Question enrichment MUST add `binderContract`, `qualityGates`, `provenanceRequirements`, `customization`, `answerPlan`, and `reviewChecklist` fields. | ✅ | 2026-06-12 |
| TASK-020 | Question enrichment MUST normalize `answerStructure.components[]` so every question has stable component IDs for `narrative`, `formula_metric` or `metric_card`, optional `chart`, optional `table`, and mandatory `provenance`. | ✅ | 2026-06-12 |
| TASK-021 | Add tests verifying enriched questions contain all enterprise fields and include a provenance component. | ✅ | 2026-06-12 |

### Implementation Phase 5

- GOAL-005: Fix semantic slot graph generation so every slot is component-driven and lineage-complete.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-022 | Update `report_builder\slot_wiring.py.build_semantic_slot_graph()` to build `topic_by_question`, `chapter_by_question`, and `section_by_question` from `iter_question_contexts()` instead of direct topic loops. | ✅ | 2026-06-12 |
| TASK-023 | Update slot graph slot construction so every analytical slot includes `slotId`, `questionId`, `componentId`, `componentKind`, `topicId`, optional `chapterId`, optional `sectionId`, `fillFrom`, `lineageRequired`, `officerEditable`, and `slotPolicies`. | ✅ | 2026-06-12 |
| TASK-024 | Update slot graph validation to treat `fillFrom` pointing at a question ID as `BROKEN_FILLFROM`, not a repairable warning. | ✅ | 2026-06-12 |
| TASK-025 | Add deterministic duplicate ID handling before graph emission: duplicate question IDs and duplicate component IDs MUST become blocking diagnostics and MUST NOT be auto-silenced. | ✅ | 2026-06-12 |
| TASK-026 | Add tests verifying nested question slots have topic/chapter/section lineage and no `fillFrom` references a question ID. | ✅ | 2026-06-12 |

### Implementation Phase 6

- GOAL-006: Add enterprise AST overlays and publication-ready layout scaffolding.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-027 | Add `enrich_enterprise_ast(ast: dict, blueprint: dict) -> dict` in `report_builder\enterprise_template_contract.py`. The function MUST add `customizationAST`, `publicationAST`, and `officerGuideAST` when absent. | ✅ | 2026-06-12 |
| TASK-028 | Update `report_builder\template_emit.py` so emitted ASTs call `enrich_enterprise_ast()` before serialization. | ✅ | 2026-06-12 |
| TASK-029 | Update `compact_skeleton_ast()` so layout pages are generated from recursive outline contexts and document-control pages instead of collapsing all extracted content into one page. | ✅ | 2026-06-12 |
| TASK-030 | Add tests verifying extracted AST output includes enterprise AST overlays and more than one layout page for a blueprint with multiple nested sections. | ✅ | 2026-06-12 |

### Implementation Phase 7

- GOAL-007: Strengthen diagnostics and binder readiness scoring for enterprise packages.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-031 | Update `report_builder\extraction_diagnostics.py` to add enterprise shape checks for required top-level contracts, nested outline presence, required per-question fields, provenance component presence, AST overlays, and slot lineage completeness. | ✅ | 2026-06-12 |
| TASK-032 | Update `determine_status()` or score computation so any blocking error caps `binderReadinessScore` at `0.59` and returns `INVALID`. | ✅ | 2026-06-12 |
| TASK-033 | Update provider diagnostics so `schemaRequiredCalls > schemaEnforcedCalls` is a warning and contributes to score reduction; it MUST NOT be blocking in offline or Azure-only environments unless strict enterprise mode is explicitly enabled. | ✅ | 2026-06-12 |
| TASK-034 | Add tests verifying broken fillFrom, missing evidence, missing enterprise contracts, and duplicate IDs force invalid diagnostics. | ✅ | 2026-06-12 |

### Implementation Phase 8

- GOAL-008: Improve LayoutLM/ToC heading hygiene to reduce noisy sections.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-035 | Update `report_builder\extraction_pipeline.py` section extraction helpers to reject footnote-like headings matching `total may not tally`, `source:`, `note:`, `fig.`, and one-token numeric artifacts. | ✅ | 2026-06-12 |
| TASK-036 | Update heading promotion logic so long sentence-like lines are retained as candidate notes, not promoted to level-1 sections, unless backed by ToC numbering and layout evidence. | ✅ | 2026-06-12 |
| TASK-037 | Add deterministic deduplication for repeated chapter titles while preserving source page refs. | ✅ | 2026-06-12 |
| TASK-038 | Add tests for heading hygiene using `As of 01-04-2025...`, `2 Total may not tally due to rounding off`, and repeated `Chapter 1: Energy Reserves and Potential`. | ✅ | 2026-06-12 |

### Implementation Phase 9

- GOAL-009: Expand schema definitions and provider trace expectations without hardcoding providers.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-039 | Update `report_builder\llm_schemas.py` to add enterprise schema fragments for question contracts, answer components, formula specs, provenance requirements, and entity evidence. | ✅ | 2026-06-12 |
| TASK-040 | Keep `report_builder\llm_router.py` provider selection environment-driven. Do not hardcode Azure, OpenAI, Qwen, or model names. | ✅ | 2026-06-12 |
| TASK-041 | If adding API-level JSON schema support for Azure/OpenAI-compatible providers, implement it behind an environment flag and update `schemaEnforced` only when the payload actually uses provider-level schema enforcement. | ✅ | 2026-06-12 |
| TASK-042 | Add tests verifying `summarize_provider_call_ledger()` preserves `schemaRequiredCalls` and `schemaEnforcedCalls` semantics. | ✅ | 2026-06-12 |

### Implementation Phase 10

- GOAL-010: Add end-to-end enterprise extraction regression tests and validate existing suites.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-043 | Add a compact synthetic energy extraction fixture in tests that includes nested sections, energy entities, source refs, questions, components, AST skeleton, and a broken-fillFrom negative case. | ✅ | 2026-06-12 |
| TASK-044 | Add an end-to-end test that emits an enriched energy package and asserts required enterprise contracts, recursive question counts, evidence, provenance components, AST overlays, and clean slot graph. | ✅ | 2026-06-12 |
| TASK-045 | Run `.venv\Scripts\python.exe -m pytest tests\test_template_extraction_enterprise.py tests\test_binding.py tests\test_generate_phase_bundle.py tests\test_generation_s7_api.py -q -p no:cacheprovider`. |  |  |
| TASK-046 | Run `.venv\Scripts\python.exe -m pytest -m "not live" -q -p no:cacheprovider` unless runtime exceeds 10 minutes or a pre-existing unrelated failure is identified and documented. |  |  |
| TASK-047 | Update this plan file by marking completed tasks with `✅` and date `2026-06-12`. |  |  |

## 3. Alternatives

- **ALT-001**: Modify only `outputs\testing_17` JSON manually. Rejected because it fixes one artifact but leaves extraction unable to generate enterprise-grade packages for new documents.
- **ALT-002**: Ask the VLM to emit the complete enterprise package directly. Rejected because it increases cost, makes output nondeterministic, and risks fabricated officer/data contracts.
- **ALT-003**: Copy the PLFS enterprise template for all domains. Rejected because energy, labour, prices, and other MoSPI domains require different entity families, units, formulas, and officer controls.
- **ALT-004**: Treat broken slot refs as auto-repairable warnings. Rejected because S3.5 binder readiness requires deterministic component-slot lineage.

## 4. Dependencies

- **DEP-001**: Existing Python runtime `.venv\Scripts\python.exe`.
- **DEP-002**: Existing pytest test suite and markers.
- **DEP-003**: Existing gold-standard PLFS enterprise template files under `report_builder\gold_standard\`.
- **DEP-004**: Existing extraction package emit path in `report_builder\template_emit.py`.
- **DEP-005**: Existing slot graph builder in `report_builder\slot_wiring.py`.

## 5. Files

- **FILE-001**: `report_builder\template_traversal.py` — new shared recursive traversal helper.
- **FILE-002**: `report_builder\enterprise_template_contract.py` — new deterministic enterprise enrichment helper.
- **FILE-003**: `report_builder\slot_wiring.py` — recursive traversal, slot graph lineage, broken fillFrom handling.
- **FILE-004**: `report_builder\template_emit.py` — blueprint/AST enrichment and recursive emission loops.
- **FILE-005**: `report_builder\extraction_diagnostics.py` — enterprise checks and score caps.
- **FILE-006**: `report_builder\extraction_pipeline.py` — heading hygiene and section deduplication.
- **FILE-007**: `report_builder\llm_schemas.py` — enterprise JSON schema fragments.
- **FILE-008**: `tests\test_template_extraction_enterprise.py` — new enterprise extraction regression tests.
- **FILE-009**: `plan\upgrade-template-extraction-enterprise-1.md` — this execution plan.

## 6. Testing

- **TEST-001**: `tests\test_template_extraction_enterprise.py::test_recursive_question_traversal_supports_nested_and_legacy_shapes`.
- **TEST-002**: `tests\test_template_extraction_enterprise.py::test_energy_blueprint_gets_enterprise_contracts_without_plfs_concepts`.
- **TEST-003**: `tests\test_template_extraction_enterprise.py::test_entity_enrichment_adds_evidence_and_flags_missing_source_refs`.
- **TEST-004**: `tests\test_template_extraction_enterprise.py::test_question_enrichment_adds_binder_fields_and_provenance_component`.
- **TEST-005**: `tests\test_template_extraction_enterprise.py::test_slot_graph_uses_component_fillfrom_and_nested_lineage`.
- **TEST-006**: `tests\test_template_extraction_enterprise.py::test_enterprise_ast_overlays_and_multiple_pages`.
- **TEST-007**: `tests\test_template_extraction_enterprise.py::test_enterprise_diagnostics_block_broken_fillfrom_and_missing_contracts`.
- **TEST-008**: `.venv\Scripts\python.exe -m pytest tests\test_template_extraction_enterprise.py tests\test_binding.py tests\test_generate_phase_bundle.py tests\test_generation_s7_api.py -q -p no:cacheprovider`.
- **TEST-009**: `.venv\Scripts\python.exe -m pytest -m "not live" -q -p no:cacheprovider`.

## 7. Risks & Assumptions

- **RISK-001**: Strict enterprise diagnostics may expose pre-existing invalid generated fixtures. Mitigation: scope strict checks to extracted enterprise package paths and preserve legacy compatibility where required.
- **RISK-002**: Recursive traversal changes may alter counts in tests that assumed direct topic questions only. Mitigation: update tests only when the old count was semantically wrong.
- **RISK-003**: Heading hygiene may reject legitimate unusual headings. Mitigation: quarantine rejected candidates with reasons instead of dropping evidence entirely.
- **RISK-004**: Provider schema enforcement support differs across providers. Mitigation: trace enforcement honestly and validate locally; do not claim enforcement unless API-level schema constraints were applied.
- **ASSUMPTION-001**: `testing_17` is an energy statistics extraction and should become energy-enterprise-shaped, not PLFS-content-shaped.
- **ASSUMPTION-002**: Existing gold-standard PLFS enterprise generator remains the shape reference, not the content source for other domains.
- **ASSUMPTION-003**: Local tests should run offline with `LLM_DISABLED=1` behavior available.

## 8. Related Specifications / Further Reading

- `report_builder\gold_standard\plfs_enterprise_annual.template.blueprint.json`
- `report_builder\gold_standard\plfs_enterprise_annual.template.ast.json`
- `report_builder\gold_standard\plfs_enterprise_annual.semantic_slot_graph.json`
- `outputs\testing_17\template.diagnostics.json`
- `outputs\testing_17\template.blueprint.json`
- `outputs\testing_17\template.ast.json`
- `outputs\testing_17\semantic_slot_graph.json`
- `outputs\testing_17\_pass_outputs\pipeline_trace.json`
