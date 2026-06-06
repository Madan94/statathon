"""Pipeline runner script — invoked by the pipeline Docker container.

Usage (inside container):
    python /app/scripts/run_pipeline.py

Environment variables:
    PDF_INPUT_PATH  path to the legacy PDF inside the container (required)
    TEMPLATE_NAME   human-readable label for the output template
    OUTPUT_DIR      directory to write the AST JSON (default /app/outputs)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("pipeline_runner")


def main() -> None:
    pdf_path = os.getenv("PDF_INPUT_PATH", "/app/data/input.pdf")
    template_name = os.getenv("TEMPLATE_NAME", "PLFS Template")
    output_dir = Path(os.getenv("OUTPUT_DIR", "/app/outputs"))
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("PDF input    : %s", pdf_path)
    logger.info("Template name: %s", template_name)
    logger.info("Output dir   : %s", output_dir)

    if not Path(pdf_path).exists():
        logger.error(
            "PDF not found: %s\n"
            "  → Make sure you copied the PDF into ./data/ on the host,\n"
            "    and that PDF_INPUT_PATH uses /app/data/<filename>",
            pdf_path,
        )
        sys.exit(1)

    from template_engine.pipeline import run_extraction_pipeline  # noqa: PLC0415

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
    print("  PIPELINE COMPLETE")
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
            print(f"    - {w}")
    print("=" * 60)


if __name__ == "__main__":
    main()
