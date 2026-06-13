"""Pipeline runner script — invoked by the pipeline Docker container.

Usage (inside container):
    python /app/scripts/run_pipeline.py

Environment variables:
    PDF_INPUT_PATH      path to the legacy PDF inside the container (required)
    TEMPLATE_NAME       human-readable label for the output template
    OUTPUT_DIR          directory to write the AST JSON (default /app/outputs)
    EXTRACTION_PIPELINE v1 (legacy) or v2 (LayoutLM + Qwen-VL multi-pass)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("pipeline_runner")


def main() -> None:
    pdf_path = os.getenv("PDF_INPUT_PATH", "/app/data/input.pdf")
    template_name = os.getenv("TEMPLATE_NAME", "Enterprise Template")
    output_dir = Path(os.getenv("OUTPUT_DIR", "/app/outputs"))
    pipeline_version = os.getenv("EXTRACTION_PIPELINE", "v2")
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("═" * 60)
    logger.info("  Pipeline Runner — %s", "V2 Multi-Pass" if pipeline_version == "v2" else "V1 Legacy")
    logger.info("═" * 60)
    logger.info("PDF input    : %s", pdf_path)
    logger.info("Template name: %s", template_name)
    logger.info("Output dir   : %s", output_dir)
    logger.info("Pipeline     : %s", pipeline_version)

    if not Path(pdf_path).exists():
        logger.error(
            "PDF not found: %s\n"
            "  → Make sure you copied the PDF into ./data/ on the host,\n"
            "    and that PDF_INPUT_PATH uses /app/data/<filename>",
            pdf_path,
        )
        sys.exit(1)

    t0 = time.time()

    if pipeline_version == "v2":
        _run_v2(pdf_path, template_name, output_dir)
    else:
        _run_v1(pdf_path, template_name, output_dir)

    elapsed = time.time() - t0
    logger.info("Total elapsed: %.1fs", elapsed)


def _run_v2(pdf_path: str, template_name: str, output_dir: Path) -> None:
    """V2: Multi-pass extraction pipeline (LayoutLM + Qwen-VL + Gemini)."""
    from report_builder.extraction_pipeline import run_extraction_pipeline
    from report_builder.ast_schema import EnterpriseDocumentAST

    # Compute source hash
    import hashlib
    source_hash = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()

    ast_dict = run_extraction_pipeline(
        pdf_path=Path(pdf_path),
        doc_title=template_name,
        source_hash=source_hash,
    )

    # Validate against schema
    try:
        validated = EnterpriseDocumentAST.model_validate(ast_dict)
        summary = validated.summary()
    except Exception as e:
        logger.warning("Schema validation partial: %s", e)
        summary = {"pages": ast_dict.get("metadata", {}).get("pageCount", 0)}

    # Write output
    out_file = output_dir / f"enterprise_ast_{source_hash[:12]}.json"
    out_file.write_text(json.dumps(ast_dict, indent=2, ensure_ascii=False), encoding="utf-8")

    print("")
    print("=" * 60)
    print("  V2 PIPELINE COMPLETE — Enterprise Document AST")
    print("=" * 60)
    for key, val in summary.items():
        print(f"  {key:20s}: {val}")
    print(f"  {'AST saved':20s}: {out_file}")
    print("=" * 60)


def _run_v1(pdf_path: str, template_name: str, output_dir: Path) -> None:
    """V1: Legacy template_engine pipeline."""
    from template_engine.pipeline import run_extraction_pipeline

    result = run_extraction_pipeline(pdf_path, template_name=template_name)

    if not result.success:
        logger.error("Pipeline FAILED. Errors:")
        for err in result.progress.errors:
            logger.error("  [%s] %s", err.get("stage"), err.get("message"))
        sys.exit(1)

    ast_dict = result.ast.to_dict()
    out_file = output_dir / f"template_{result.source_hash[:12]}.json"
    out_file.write_text(json.dumps(ast_dict, indent=2, ensure_ascii=False), encoding="utf-8")

    print("")
    print("=" * 60)
    print("  V1 PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Pages     : {result.progress.pages_processed}")
    print(f"  Entities  : {result.progress.entities_found}")
    print(f"  Questions : {result.progress.questions_inferred}")
    print(f"  AST saved : {out_file}")
    if result.review:
        print(f"  Review    : {result.review.decision.value}  (confidence={result.review.confidence_score:.2f})")
    if result.warnings:
        print(f"  Warnings  : {len(result.warnings)}")
        for w in result.warnings:
            print(f"    • {w}")
    print("=" * 60)


if __name__ == "__main__":
    main()
