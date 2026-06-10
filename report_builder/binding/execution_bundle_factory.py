"""ExecutionBundle factory — the SINGLE canonical path from confirmed bindings to S4 handoff.

This is the one source of truth. The API endpoint is a thin wrapper around this factory.
S4 consumes ONLY what this factory produces.

Flow:
    ReviewRecord + DatasetAST + Blueprint + CSV
    → confirmed BindingAST
    → QuestionBinding[] (via bind_questions)
    → QuestionExecutionPlan[] (via compile_execution_plans)
    → ExecutionReadinessReport (via validate_execution_ready)
    → ExecutionBundle
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from report_builder.binding import review as R
from report_builder.binding.execution_contracts import (
    ExecutionBundle,
    ExecutionReadinessReport,
    StatisticalContext,
)
from report_builder.binding.freeze_store import freeze_bundle
from report_builder.binding.question_binder import bind_questions, compile_execution_plans
from report_builder.binding.readiness_gate import validate_execution_ready
from report_builder.binding.report import build_coverage
from report_builder.binding.schema import BindingAST, DatasetAST, EntityBinding

logger = logging.getLogger(__name__)


def build_execution_bundle(
    *,
    template_id: str,
    signature: str,
    record: Any,  # ReviewRecord from review.py
    dataset: DatasetAST,
    blueprint: dict[str, Any],
    dataframe_path: str = "",
    df: Any | None = None,
    data_content_hash: str = "",
) -> ExecutionBundle:
    """Build a validated ExecutionBundle from confirmed bindings.

    This is the SINGLE canonical factory. The API endpoint calls this.
    No plan-building logic should exist anywhere else.

    Args:
        template_id: Template identifier.
        signature: Dataset shape signature.
        record: ReviewRecord with proposals + confirmations.
        dataset: Profiled DatasetAST (S0 output).
        blueprint: Full blueprint dict (entities, topics, questions).
        dataframe_path: Path to the stashed CSV for S4 to load.
        df: Optional loaded DataFrame (for question_binder value resolution).
        data_content_hash: Optional value-level hash of the dataframe actually used,
            pinned into ``dataframeRef.contentHash`` so a frozen bundle is reproducible
            and data drift is detectable (see ``generation.run_modes``).

    Returns:
        A complete, validated ExecutionBundle ready for S4 handoff.
    """
    # ── Step 1: Rebuild BindingAST from proposals + apply confirmations ──
    entity_bindings = [EntityBinding.from_dict(p) for p in record.proposals]
    binding = BindingAST(
        templateId=record.templateId,
        datasetId=record.datasetId,
        datasetSignature=signature,
        entityBindings=entity_bindings,
    )
    R.apply_confirmations(binding, record)

    # ── Step 2: Bind questions (S3 role mapping) ──
    binding.questionBindings = bind_questions(blueprint, binding.entityBindings, dataset, df=df)

    # ── Step 3: Compute coverage gate ──
    build_coverage(binding)
    has_gate_errors = any(
        i.get("severity") == "error" for i in binding.coverage.get("issues", [])
    )

    # ── Step 4: Compile execution plans (S3 plan compiler) ──
    plans = compile_execution_plans(blueprint, binding.questionBindings, dataset)

    # ── Step 5: Validate readiness (S3.5 gate) ──
    readiness = validate_execution_ready(plans, dataset)

    # Add S3 blocked questions to readiness report's blocked count
    s3_blocked_count = sum(1 for qb in binding.questionBindings if qb.status == "blocked")
    readiness.blockedCount += s3_blocked_count

    # Add gate errors to readiness
    if has_gate_errors:
        readiness.errors.append("Binding coverage gate has blocking errors — resolve before execution")

    # ── Step 6: Build blocked questions list ──
    blocked = [
        {
            "questionId": qb.questionId,
            "reason": "; ".join(qb.notes) or "Required entities unresolved",
            "unresolvedEntities": qb.unresolvedEntities,
        }
        for qb in binding.questionBindings
        if qb.status == "blocked"
    ]
    # Also include plans that the readiness gate blocked
    for plan in plans:
        if plan.status == "BLOCKED" and plan.questionId not in {b["questionId"] for b in blocked}:
            blocked.append({
                "questionId": plan.questionId,
                "reason": "; ".join(plan.diagnostics) or "Failed readiness gate",
                "unresolvedEntities": [],
            })

    # ── Step 7: Build statistical context ──
    unit_registry: dict[str, str] = {}
    for col in dataset.columns:
        if col.unit:
            unit_registry[col.name] = col.unit

    # Detect geography level from column names
    geo_level = ""
    for col in dataset.columns:
        col_low = col.name.lower()
        if "state" in col_low or "ut" in col_low:
            geo_level = "state_ut"
            break
        elif "district" in col_low:
            geo_level = "district"
            break

    # Extract source notes from blueprint metadata
    source_notes: list[str] = []
    template_meta = blueprint.get("templateMeta", {})
    if template_meta.get("sourceDocument"):
        source_notes.append(template_meta["sourceDocument"])
    if template_meta.get("name"):
        source_notes.append(template_meta["name"])

    stat_ctx = StatisticalContext(
        geographyLevel=geo_level,
        unitRegistry=unit_registry,
        sourceNotes=source_notes,
    )

    # ── Step 8: Build lineage index ──
    lineage_index: dict[str, Any] = {}
    for plan in plans:
        if plan.lineage.sourceQuestionId:
            lineage_index[plan.questionId] = plan.lineage.to_dict()

    # ── Step 9: Determine bundle status ──
    if has_gate_errors or readiness.errors:
        bundle_status = "NOT_READY"
    elif readiness.status == "DEGRADED":
        bundle_status = "DEGRADED"
    else:
        bundle_status = "READY"

    # ── Step 10: Generate STABLE binding AST ID (deterministic, not per-call) ──
    # Same template + same signature + same version = same bindingAstId
    # This ensures repeated GET calls return the same frozen artifact
    import hashlib as _hl
    _version_seed = f"{template_id}|{signature}|{len(entity_bindings)}|{len(plans)}"
    _stable_hash = _hl.md5(_version_seed.encode()).hexdigest()[:12]
    binding_ast_id = f"bind_{template_id}_{_stable_hash}"

    # ── Assemble the bundle ──
    now = datetime.now(timezone.utc).isoformat()
    # Pin the data content hash into dataframeRef when provided (additive: the key is
    # omitted for unpinned bundles, keeping legacy artifacts byte-identical).
    dataframe_ref: dict[str, Any] = {"type": "csv", "path": dataframe_path}
    if data_content_hash:
        dataframe_ref["contentHash"] = data_content_hash
    bundle = ExecutionBundle(
        templateId=template_id,
        datasetId=record.datasetId,
        bindingAstId=binding_ast_id,
        status=bundle_status,
        datasetAst=dataset,
        bindingAst=binding,
        statisticalContext=stat_ctx,
        plans=plans,
        blockedQuestions=blocked,
        readinessReport=readiness,
        dataframeRef=dataframe_ref,
        lineageIndex=lineage_index,
        frozenAt=now,
    )

    logger.info(
        "[bundle-factory] Built ExecutionBundle: status=%s plans=%d (exec=%d, degraded=%d) blocked=%d",
        bundle_status,
        len(plans),
        readiness.executableCount,
        readiness.degradedCount,
        len(blocked),
    )

    # ── Step 11: Freeze to persistent storage ──
    # Idempotent: same content → same version returned (no duplicate writes)
    try:
        freeze_info = freeze_bundle(bundle)
        bundle.frozenAt = freeze_info["frozenAt"]
        logger.info(
            "[bundle-factory] Freeze: v%d isNew=%s path=%s",
            freeze_info["version"], freeze_info["isNew"], freeze_info["path"],
        )
    except Exception as e:
        logger.warning("[bundle-factory] Freeze failed (non-fatal): %s", e)

    return bundle
