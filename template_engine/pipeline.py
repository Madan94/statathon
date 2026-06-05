"""Template Engine Pipeline — main orchestrator for Phase 0 reverse-engineering.

This is the primary entry point for the enhanced template engine. It coordinates:
  1. Immutable ingestion (hash + store)
  2. Vision-spatial parsing (VLM)
  3. Entity extraction (all sources)
  4. Question inference (cascade)
  5. Grammar-constrained AST generation (SGLang)
  6. Validation and cross-linking
  7. Progressive extraction support (partial commit + resume)

Usage:
    from template_engine.pipeline import run_extraction_pipeline
    result = run_extraction_pipeline(pdf_path, template_name="MoSPI Report 2024")
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ast_core.schema import TemplateBlueprintAST, TemplateEntity, TopicNode
from template_engine.config import PipelineConfig, get_config
from template_engine.ingestion.pdf_hasher import sha256_file
from template_engine.storage.checkpoint import CheckpointBackend, get_checkpoint_backend
from template_engine.vlm.client import VLMClient, VLMClientFactory, VLMExtractionError
from template_engine.vlm.schemas import VLMPageResult
from template_engine.extraction.entity_extractor import extract_entities
from template_engine.extraction.entity_deduplicator import deduplicate_entities
from template_engine.inference.question_inferrer import infer_questions
from template_engine.generation.ast_assembler import assemble_template_ast
from template_engine.generation.sglang_client import SGLangClientFactory
from template_engine.review.reviewer import TemplateReviewer, ReviewResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

PIPELINE_STAGES = [
    "hashing",
    "vlm_parsing",
    "entity_extraction",
    "entity_deduplication",
    "question_inference",
    "ast_assembly",
    "validation",
    "complete",
]


@dataclass
class ExtractionProgress:
    """Tracks pipeline progress for async jobs."""
    stage: str = "pending"
    stage_index: int = 0
    total_stages: int = len(PIPELINE_STAGES)
    progress_pct: int = 0
    pages_processed: int = 0
    pages_total: int = 0
    entities_found: int = 0
    questions_inferred: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "stage_index": self.stage_index,
            "total_stages": self.total_stages,
            "progress_pct": self.progress_pct,
            "pages_processed": self.pages_processed,
            "pages_total": self.pages_total,
            "entities_found": self.entities_found,
            "questions_inferred": self.questions_inferred,
            "errors": self.errors,
            "timings": self.timings,
        }


@dataclass
class ExtractionResult:
    """Complete result from the extraction pipeline."""
    success: bool
    ast: TemplateBlueprintAST | None = None
    progress: ExtractionProgress = field(default_factory=ExtractionProgress)
    source_hash: str = ""
    partial: bool = False  # True if some pages failed
    failed_pages: list[int] = field(default_factory=list)
    review: ReviewResult | None = None  # Automated review result
    warnings: list[str] = field(default_factory=list)  # Non-fatal issues


# Type for progress callbacks
ProgressCallback = Callable[[ExtractionProgress], None]


def run_extraction_pipeline(
    pdf_path: str | Path,
    template_name: str,
    *,
    vlm_backend: str | None = None,
    sglang_backend: str | None = None,
    progress_callback: ProgressCallback | None = None,
    resume_from: TemplateBlueprintAST | None = None,
    skip_pages: list[int] | None = None,
    config: PipelineConfig | None = None,
) -> ExtractionResult:
    """Run the full Phase 0 extraction pipeline.

    Args:
        pdf_path: Path to the source PDF file.
        template_name: Display name for the generated template.
        vlm_backend: Override VLM backend (mock/colpali/fallback).
        sglang_backend: Override SGLang backend (mock/sglang).
        progress_callback: Optional callback invoked at each stage transition.
        resume_from: Existing partial AST to merge with (for resume flows).
        skip_pages: Pages to skip (already extracted in previous run).
        config: Override pipeline config (uses global if None).

    Returns:
        ExtractionResult with the assembled TemplateBlueprintAST.
    """
    cfg = config or get_config()
    path = Path(pdf_path)
    progress = ExtractionProgress()
    result = ExtractionResult(success=False, progress=progress)

    # Initialize checkpoint backend
    checkpoint: CheckpointBackend | None = None
    if cfg.checkpoint.enabled:
        try:
            checkpoint = get_checkpoint_backend(
                backend=cfg.checkpoint.backend,
                file_dir=cfg.checkpoint.file_dir,
            )
        except Exception as exc:
            logger.warning("Checkpoint init failed (non-fatal): %s", exc)
            result.warnings.append(f"Checkpoint unavailable: {exc}")

    def _update(stage: str, pct: int) -> None:
        progress.stage = stage
        progress.stage_index = PIPELINE_STAGES.index(stage) if stage in PIPELINE_STAGES else 0
        progress.progress_pct = pct
        if progress_callback:
            progress_callback(progress)

    def _save_checkpoint(stage: str, data: dict[str, Any]) -> None:
        if checkpoint and result.source_hash:
            try:
                checkpoint.save(result.source_hash, stage, data)
            except Exception as exc:
                logger.warning("Checkpoint save failed (non-fatal): %s", exc)

    # ─── Stage 1: Hashing ───────────────────────────────────────────────
    _update("hashing", 5)
    t0 = time.time()

    if path.exists():
        source_hash = sha256_file(path)
    else:
        source_hash = ""
        progress.errors.append({
            "stage": "hashing",
            "message": f"PDF file not found: {path}",
            "severity": "warning",
        })

    result.source_hash = source_hash
    progress.timings["hashing"] = time.time() - t0

    # Check for completed checkpoint (cache hit)
    try:
        has_cache = (
            checkpoint and source_hash
            and checkpoint.exists(source_hash, "complete")
        )
    except Exception as exc:
        logger.warning("Checkpoint lookup failed (non-fatal): %s", exc)
        has_cache = False
        checkpoint = None  # Disable broken checkpoint for rest of pipeline

    if has_cache:
        cached = checkpoint.load(source_hash, "complete")
        if cached and "ast" in cached:
            try:
                ast = TemplateBlueprintAST.from_dict(cached["ast"])
                _update("complete", 100)
                result.success = True
                result.ast = ast
                result.warnings.append("Loaded from checkpoint cache")
                logger.info("Cache hit for %s — returning stored AST", source_hash[:8])
                return result
            except Exception:
                pass  # Stale cache — continue extraction

    result.source_hash = source_hash
    progress.timings["hashing"] = time.time() - t0

    # ─── Stage 2: VLM Parsing ──────────────────────────────────────────
    _update("vlm_parsing", 15)
    t0 = time.time()

    vlm_client = VLMClientFactory.create(vlm_backend)
    pages: list[VLMPageResult] = []
    failed_pages: list[int] = []

    try:
        all_pages = vlm_client.extract_pages(path)

        # Filter out skip_pages (for resume)
        if skip_pages:
            pages = [p for p in all_pages if p.pageIndex not in skip_pages]
        else:
            pages = all_pages

        progress.pages_processed = len(pages)
        progress.pages_total = len(all_pages)

    except VLMExtractionError as exc:
        # Partial extraction — save what we got
        pages = exc.partial_results
        progress.pages_processed = len(pages)
        progress.errors.append({
            "stage": "vlm_parsing",
            "message": str(exc),
            "severity": "error",
            "page_index": exc.page_index,
        })
        if exc.page_index is not None:
            failed_pages = list(range(exc.page_index, progress.pages_total))
        result.partial = True

    except Exception as exc:
        progress.errors.append({
            "stage": "vlm_parsing",
            "message": f"VLM extraction failed: {exc}",
            "severity": "fatal",
        })
        logger.error("VLM extraction failed: %s", exc)
        _update("complete", 100)
        return result

    progress.timings["vlm_parsing"] = time.time() - t0

    if not pages:
        progress.errors.append({
            "stage": "vlm_parsing",
            "message": "No pages extracted",
            "severity": "fatal",
        })
        _update("complete", 100)
        return result

    # Checkpoint VLM results
    _save_checkpoint("vlm_parsing", {
        "pages_count": len(pages),
        "failed_pages": failed_pages,
    })

    # ─── Stage 3: Entity Extraction ────────────────────────────────────
    _update("entity_extraction", 40)
    t0 = time.time()

    try:
        raw_entities = extract_entities(pages)
    except Exception as exc:
        logger.warning("Entity extraction failed (non-fatal): %s", exc)
        raw_entities = []
        result.warnings.append(f"Entity extraction failed: {exc}")
        progress.errors.append({
            "stage": "entity_extraction",
            "message": str(exc),
            "severity": "warning",
        })

    progress.timings["entity_extraction"] = time.time() - t0

    # ─── Stage 4: Entity Deduplication ─────────────────────────────────
    _update("entity_deduplication", 50)
    t0 = time.time()

    try:
        entities = deduplicate_entities(raw_entities)
    except Exception as exc:
        logger.warning("Entity dedup failed (non-fatal): %s", exc)
        entities = raw_entities  # Use raw entities as fallback
        result.warnings.append(f"Entity dedup failed: {exc}")

    progress.entities_found = len(entities)
    progress.timings["entity_deduplication"] = time.time() - t0

    _save_checkpoint("entity_deduplication", {
        "entity_count": len(entities),
    })

    # ─── Stage 5: Question Inference ───────────────────────────────────
    _update("question_inference", 65)
    t0 = time.time()

    try:
        topics = infer_questions(pages, entities)
    except Exception as exc:
        logger.warning("Question inference failed (non-fatal): %s", exc)
        topics = []
        result.warnings.append(f"Question inference failed: {exc}")
        progress.errors.append({
            "stage": "question_inference",
            "message": str(exc),
            "severity": "warning",
        })

    progress.questions_inferred = sum(len(t.questions) for t in topics)
    progress.timings["question_inference"] = time.time() - t0

    _save_checkpoint("question_inference", {
        "topic_count": len(topics),
        "question_count": progress.questions_inferred,
    })

    # ─── Stage 6: AST Assembly ─────────────────────────────────────────
    _update("ast_assembly", 80)
    t0 = time.time()

    sglang_client = SGLangClientFactory.create(sglang_backend or cfg.sglang.backend or None)
    # Always use the client's actual backend_name (not the user-supplied alias).
    resolved_vlm_backend = vlm_client.backend_name

    try:
        ast = assemble_template_ast(
            pages=pages,
            entities=entities,
            topics=topics,
            template_name=template_name,
            source_hash=source_hash,
            sglang_client=sglang_client,
            vlm_backend=resolved_vlm_backend,
        )
    except Exception as exc:
        logger.warning("AST assembly failed (non-fatal): %s", exc)
        result.warnings.append(f"AST assembly failed: {exc}")
        progress.errors.append({
            "stage": "ast_assembly",
            "message": str(exc),
            "severity": "error",
        })
        # Build minimal AST so pipeline can still return partial results
        ast = TemplateBlueprintAST(
            templateId=f"tmpl_{source_hash[:12]}",
            name=template_name,
            sourceHash=source_hash,
            pageCount=len(pages),
            extractionMethod=f"{resolved_vlm_backend}+{sglang_client.backend_name if sglang_client else 'none'}",
            topics=topics,
            entities=entities,
            extractionMeta={
                "total_pages": len(pages),
                "total_entities": len(entities),
                "total_topics": len(topics),
                "total_questions": progress.questions_inferred,
                "assembly_failed": True,
            },
        )
        result.partial = True

    progress.timings["ast_assembly"] = time.time() - t0

    # ─── Stage 7: Merge with resume (if applicable) ───────────────────
    if resume_from:
        _update("validation", 90)
        ast = _merge_with_existing(ast, resume_from)

    # ─── Stage 8: Automated review + validation ───────────────────────
    _update("validation", 95)
    t0 = time.time()
    try:
        reviewer = TemplateReviewer(
            min_topics=cfg.review.min_topics,
            min_questions=cfg.review.min_questions,
            min_entities=cfg.review.min_entities,
            min_confidence=cfg.review.min_confidence,
        )
        review = reviewer.review(ast)
        result.review = review
        if review.has_errors:
            progress.errors.append({
                "stage": "validation",
                "message": f"Review found {sum(1 for i in review.issues if i.severity == 'error')} error(s)",
                "severity": "warning",
                "issues": [i.message for i in review.issues if i.severity == "error"],
            })
        logger.info(
            "Review: %s (confidence=%.2f, issues=%d)",
            review.decision.value, review.confidence_score, len(review.issues),
        )
    except Exception as exc:
        logger.warning("Review step failed (non-fatal): %s", exc)
    progress.timings["validation"] = time.time() - t0

    # ─── Done ──────────────────────────────────────────────────────────
    _update("complete", 100)

    result.success = True
    result.ast = ast
    result.failed_pages = failed_pages

    # Save completed AST to checkpoint
    _save_checkpoint("complete", {
        "ast": ast.to_dict() if hasattr(ast, "to_dict") else {},
        "template_name": template_name,
    })

    logger.info(
        "Pipeline complete for '%s': %d pages → %d entities → %d questions in %d topics (%.1fs)",
        template_name,
        len(pages),
        len(entities),
        progress.questions_inferred,
        len(topics),
        sum(progress.timings.values()),
    )

    return result


def _merge_with_existing(new_ast: TemplateBlueprintAST,
                         existing: TemplateBlueprintAST) -> TemplateBlueprintAST:
    """Merge new extraction with existing partial AST (resume flow).

    Strategy:
      - Topics: merge by topicId (prefer new if conflict)
      - Entities: deduplicate across both sets
      - Keep existing questions that don't overlap with new ones
    """
    # Merge entities
    all_entities = list(existing.entities) + list(new_ast.entities)
    merged_entities = deduplicate_entities(all_entities)

    # Merge topics (new takes precedence for same topicId)
    existing_topic_ids = {t.topicId for t in existing.topics}
    new_topic_ids = {t.topicId for t in new_ast.topics}

    merged_topics: list[TopicNode] = []
    # Keep existing topics not in new
    for topic in existing.topics:
        if topic.topicId not in new_topic_ids:
            merged_topics.append(topic)
    # Add all new topics
    merged_topics.extend(new_ast.topics)

    return TemplateBlueprintAST(
        templateId=new_ast.templateId or existing.templateId,
        name=new_ast.name or existing.name,
        sourceHash=new_ast.sourceHash or existing.sourceHash,
        pageCount=max(new_ast.pageCount, existing.pageCount),
        extractionMethod=new_ast.extractionMethod,
        topics=merged_topics,
        entities=merged_entities,
        extractionMeta={
            **existing.extractionMeta,
            **new_ast.extractionMeta,
            "merged": True,
            "merge_source_topics": len(existing.topics),
            "merge_new_topics": len(new_ast.topics),
        },
    )
