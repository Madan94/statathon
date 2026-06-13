"""PLFS ColPali Labelling Pipeline — create training data from legacy PDFs.

Usage:
  python scripts/colpali_finetune/label_plfs.py --pdf-dir ./data/plfs_pdfs/ --output ./data/colpali_labels/

This script:
  1. Opens each PLFS PDF and runs pdfplumber extraction
  2. Detects Statement patterns (Statement X.Y)
  3. For each statement page, creates a training sample:
     - image: rendered PDF page as PNG
     - regions: bounding boxes of tables/headings
     - labels: question_intent, entity annotations, archetype
  4. Outputs JSONL + images ready for ColPali fine-tuning
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from template_engine.extraction.plfs_parser import (
    detect_plfs_statements,
    classify_statement,
    extract_entities_from_statement,
    _load_glossary,
)
from template_engine.vlm.pdfplumber_adapter import PdfPlumberVLMAdapter

logger = logging.getLogger(__name__)


def render_page_to_image(pdf_path: Path, page_index: int, output_dir: Path) -> Path | None:
    """Render a single PDF page to PNG using pdf2image or fitz."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        page = doc[page_index]
        pix = page.get_pixmap(dpi=150)
        img_path = output_dir / f"{pdf_path.stem}_page_{page_index:03d}.png"
        pix.save(str(img_path))
        doc.close()
        return img_path
    except ImportError:
        pass

    try:
        from pdf2image import convert_from_path
        images = convert_from_path(
            str(pdf_path), first_page=page_index + 1,
            last_page=page_index + 1, dpi=150,
        )
        if images:
            img_path = output_dir / f"{pdf_path.stem}_page_{page_index:03d}.png"
            images[0].save(str(img_path))
            return img_path
    except ImportError:
        pass

    logger.warning("Neither PyMuPDF nor pdf2image available for page rendering")
    return None


def label_pdf(pdf_path: Path, output_dir: Path) -> list[dict]:
    """Label a single PLFS PDF and generate training samples."""
    adapter = PdfPlumberVLMAdapter()

    if not adapter.health_check():
        logger.error("pdfplumber not available")
        return []

    try:
        pages = adapter.extract_pages(pdf_path)
    except Exception as exc:
        logger.error("Failed to extract %s: %s", pdf_path.name, exc)
        return []

    # Detect PLFS statements
    detections = detect_plfs_statements(pages)
    if not detections:
        logger.info("No PLFS statements in %s — skipping", pdf_path.name)
        return []

    glossary = _load_glossary()
    samples: list[dict] = []
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    for det in detections:
        page_idx = det["page_index"]
        page = next((p for p in pages if p.pageIndex == page_idx), None)
        if not page:
            continue

        # Render page image
        img_path = render_page_to_image(pdf_path, page_idx, images_dir)

        # Extract entities and classify
        entities = extract_entities_from_statement(
            det["title"], det["chapter"], det["sequence"],
            page_idx, glossary,
        )
        archetype = classify_statement(det["title"], glossary)

        # Build training sample
        sample = {
            "image": str(img_path.relative_to(output_dir)) if img_path else None,
            "pdf_source": pdf_path.name,
            "page_index": page_idx,
            "statement": f"Statement {det['chapter']}.{det['sequence']}",
            "title": det["title"],
            "archetype": archetype,
            "question_intent": _generate_question_intent(det["title"], archetype),
            "entities": [
                {"name": e.name, "type": e.entityType, "confidence": e.confidence}
                for e in entities
            ],
            "regions": [
                {
                    "regionId": r.regionId,
                    "role": r.role,
                    "bbox": r.bbox.to_dict(),
                    "text_preview": r.text[:100],
                }
                for r in page.regions[:20]
            ],
            "tables_count": len(page.tables),
            "has_charts": page.has_charts,
        }
        samples.append(sample)

    logger.info("Labelled %s: %d samples from %d statements", pdf_path.name, len(samples), len(detections))
    return samples


def _generate_question_intent(title: str, archetype: str) -> str:
    """Generate the question_intent label for ColPali training."""
    title_clean = title.rstrip(".")
    intents = {
        "distribution": f"composition:{title_clean}",
        "rate": f"comparative:{title_clean}",
        "trend": f"trend:{title_clean}",
        "cross_tabulation": f"multi_dim:{title_clean}",
        "state_level": f"geographic:{title_clean}",
    }
    return intents.get(archetype, f"descriptive:{title_clean}")


def main():
    parser = argparse.ArgumentParser(description="Label PLFS PDFs for ColPali fine-tuning")
    parser.add_argument("--pdf-dir", type=Path, required=True, help="Directory of PLFS PDFs")
    parser.add_argument("--output", type=Path, required=True, help="Output directory")
    parser.add_argument("--limit", type=int, default=0, help="Max PDFs to process (0=all)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    args.output.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    if args.limit > 0:
        pdfs = pdfs[:args.limit]

    logger.info("Processing %d PDFs from %s", len(pdfs), args.pdf_dir)

    all_samples: list[dict] = []
    for pdf_path in pdfs:
        samples = label_pdf(pdf_path, args.output)
        all_samples.extend(samples)

    # Write JSONL
    output_file = args.output / "plfs_labels.jsonl"
    with open(output_file, "w", encoding="utf-8") as f:
        for sample in all_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    logger.info("Done: %d total samples → %s", len(all_samples), output_file)


if __name__ == "__main__":
    main()
