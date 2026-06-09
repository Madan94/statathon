"""LayoutLMv3 Document Layout Analysis Service.

FastAPI microservice that accepts PDF files and returns detected regions
with types (title, heading, paragraph, table, figure, chart, list, etc.)
and bounding boxes for each page.

Runs on CPU — no GPU required (~1.4GB RAM for layoutlmv3-large).

Endpoints:
    GET  /health   → {"status": "ok", "model": "..."}
    POST /analyze  → multipart PDF → JSON with regions per page

Environment:
    MODEL_ID        = microsoft/layoutlmv3-large (default)
    LAYOUTLM_PORT   = 8001 (default)
    MAX_PAGES       = 100 (safety limit)
"""
from __future__ import annotations

import gc
import io
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

import pytesseract
tesseract_path = os.getenv("TESSERACT_CMD")
if tesseract_path:
    pytesseract.pytesseract.tesseract_cmd = tesseract_path

import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("layoutlm-service")

app = FastAPI(title="LayoutLM Layout Detection Service", version="1.0.0")

MODEL_ID = os.getenv("MODEL_ID", "microsoft/layoutlmv3-large")
MAX_PAGES = int(os.getenv("MAX_PAGES", "100"))

# ── Model cache — OUTSIDE the git repo to avoid stash/conflict issues ────────
# Priority: HF_HOME env → model/cache/ in repo root → user home .cache
_REPO_ROOT = Path(__file__).resolve().parents[2]  # services/layoutlm/../../ = repo root
_MODEL_CACHE = Path(os.getenv("HF_HOME", "")) if os.getenv("HF_HOME") else (_REPO_ROOT / "model" / "cache")
_MODEL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ["HF_HOME"] = str(_MODEL_CACHE)
os.environ["TRANSFORMERS_CACHE"] = str(_MODEL_CACHE)
os.environ["HF_HUB_CACHE"] = str(_MODEL_CACHE / "hub")

# ── Lazy-loaded globals ──────────────────────────────────────────────────────
_processor = None
_model = None
_device = "cpu"

# LayoutLMv3 label mapping (from fine-tuned DocLayNet / PubLayNet)
LABEL_MAP = {
    0: "text",
    1: "title",
    2: "list",
    3: "table",
    4: "figure",
    5: "heading",
    6: "header",
    7: "footer",
    8: "caption",
    9: "chart",
}


def _load_model():
    """Load LayoutLMv3 model + processor (lazy, first request)."""
    global _processor, _model, _device

    if _model is not None:
        return

    logger.info("Loading LayoutLMv3 model: %s", MODEL_ID)
    t0 = time.monotonic()

    from transformers import AutoProcessor, AutoModelForTokenClassification

    _cache = str(_MODEL_CACHE / "hub")
    _processor = AutoProcessor.from_pretrained(MODEL_ID, apply_ocr=True, cache_dir=_cache)
    _model = AutoModelForTokenClassification.from_pretrained(MODEL_ID, cache_dir=_cache)
    _model.eval()
    _device = "cpu"
    _model.to(_device)

    elapsed = time.monotonic() - t0
    logger.info("Model loaded in %.1fs on %s", elapsed, _device)


def _analyze_page_image(image, page_index: int) -> dict[str, Any]:
    """Run LayoutLMv3 on a single page image → detected regions.

    Returns:
        {
            "page_index": int,
            "width": float,
            "height": float,
            "regions": [
                {
                    "bbox": [x0, y0, x1, y1],  # normalized 0-1000
                    "type": "title"|"heading"|"paragraph"|"table"|"figure"|"chart"|...,
                    "confidence": float,
                    "text": str  # OCR text within this region
                }
            ]
        }
    """
    from PIL import Image

    if not isinstance(image, Image.Image):
        image = Image.open(io.BytesIO(image))

    width, height = image.size

    # Process with LayoutLMv3's built-in OCR
    encoding = _processor(image, return_tensors="pt", truncation=True, max_length=512)
    encoding = {k: v.to(_device) for k, v in encoding.items()}

    with torch.no_grad():
        outputs = _model(**encoding)

    # Get predictions
    logits = outputs.logits
    predictions = logits.argmax(-1).squeeze().tolist()
    if isinstance(predictions, int):
        predictions = [predictions]

    # Get confidence scores
    probs = torch.softmax(logits, dim=-1).squeeze()
    confidences = probs.max(dim=-1).values.tolist()
    if isinstance(confidences, float):
        confidences = [confidences]

    # Extract words and boxes from encoding
    words = encoding.get("input_ids", None)
    boxes = encoding.get("bbox", None)

    # Group consecutive tokens with same label into regions
    regions: list[dict[str, Any]] = []
    current_region: dict[str, Any] | None = None

    # Use the processor's OCR results if available
    ocr_words = []
    ocr_boxes = []
    if hasattr(_processor, "current_ocr_words"):
        ocr_words = _processor.current_ocr_words or []
        ocr_boxes = _processor.current_ocr_boxes or []

    # Fallback: use token-level bbox from encoding
    token_boxes = boxes.squeeze().tolist() if boxes is not None else []

    for i, (pred, conf) in enumerate(zip(predictions, confidences)):
        label = LABEL_MAP.get(pred, "text")
        bbox = token_boxes[i] if i < len(token_boxes) else [0, 0, 0, 0]

        # Skip special tokens (bbox = [0,0,0,0])
        if bbox == [0, 0, 0, 0]:
            continue

        if current_region and current_region["type"] == label:
            # Extend current region
            current_region["bbox"][0] = min(current_region["bbox"][0], bbox[0])
            current_region["bbox"][1] = min(current_region["bbox"][1], bbox[1])
            current_region["bbox"][2] = max(current_region["bbox"][2], bbox[2])
            current_region["bbox"][3] = max(current_region["bbox"][3], bbox[3])
            current_region["_confidences"].append(conf)
        else:
            # Save previous region
            if current_region:
                current_region["confidence"] = sum(current_region["_confidences"]) / len(current_region["_confidences"])
                del current_region["_confidences"]
                regions.append(current_region)
            # Start new region
            current_region = {
                "bbox": list(bbox),
                "type": label,
                "text": "",
                "_confidences": [conf],
            }

    # Save last region
    if current_region:
        current_region["confidence"] = sum(current_region["_confidences"]) / len(current_region["_confidences"])
        del current_region["_confidences"]
        regions.append(current_region)

    # Deduplicate overlapping regions of same type
    merged_regions = _merge_overlapping_regions(regions)

    return {
        "page_index": page_index,
        "width": width,
        "height": height,
        "regions": merged_regions,
    }


def _merge_overlapping_regions(regions: list[dict]) -> list[dict]:
    """Merge overlapping regions of the same type."""
    if not regions:
        return []

    merged: list[dict] = []
    for region in regions:
        found_merge = False
        for existing in merged:
            if existing["type"] == region["type"] and _iou(existing["bbox"], region["bbox"]) > 0.3:
                # Merge bboxes
                existing["bbox"][0] = min(existing["bbox"][0], region["bbox"][0])
                existing["bbox"][1] = min(existing["bbox"][1], region["bbox"][1])
                existing["bbox"][2] = max(existing["bbox"][2], region["bbox"][2])
                existing["bbox"][3] = max(existing["bbox"][3], region["bbox"][3])
                existing["confidence"] = max(existing["confidence"], region["confidence"])
                found_merge = True
                break
        if not found_merge:
            merged.append(region.copy())

    return merged


def _iou(box1: list, box2: list) -> float:
    """Intersection over union for two boxes [x0, y0, x1, y1]."""
    x0 = max(box1[0], box2[0])
    y0 = max(box1[1], box2[1])
    x1 = min(box1[2], box2[2])
    y1 = min(box1[3], box2[3])

    inter = max(0, x1 - x0) * max(0, y1 - y0)
    area1 = max(0, box1[2] - box1[0]) * max(0, box1[3] - box1[1])
    area2 = max(0, box2[2] - box2[0]) * max(0, box2[3] - box2[1])
    union = area1 + area2 - inter

    return inter / union if union > 0 else 0.0


def _extract_region_text(image, bbox: list, width: int, height: int) -> str:
    """Crop region from image and extract text via OCR (fallback)."""
    try:
        from PIL import Image
        import pytesseract

        # Convert normalized bbox (0-1000) to pixel coords
        x0 = int(bbox[0] * width / 1000)
        y0 = int(bbox[1] * height / 1000)
        x1 = int(bbox[2] * width / 1000)
        y1 = int(bbox[3] * height / 1000)

        cropped = image.crop((x0, y0, x1, y1))
        text = pytesseract.image_to_string(cropped).strip()
        return text
    except Exception:
        return ""


@app.on_event("startup")
async def startup():
    """Pre-load model on startup."""
    _load_model()


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "model": MODEL_ID, "device": _device}


@app.post("/analyze")
async def analyze_pdf(file: UploadFile = File(...)):
    """Analyze PDF layout → regions per page.

    Accepts multipart/form-data with PDF file.
    Returns JSON with detected regions, their types, and bounding boxes.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "File must be a PDF")

    _load_model()

    # Save uploaded file
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        import pdf2image

        poppler_path = os.getenv("POPPLER_PATH") or None
        t0 = time.monotonic()
        images = pdf2image.convert_from_path(
            str(tmp_path),
            dpi=200,
            fmt="png",
            first_page=1,
            last_page=MAX_PAGES,
            poppler_path=poppler_path,
        )
        logger.info("Rasterized %d pages in %.1fs", len(images), time.monotonic() - t0)

        # Also extract text with pdfplumber for enrichment
        page_texts = _extract_text_pdfplumber(tmp_path, len(images))

        # Analyze each page
        results = []
        for i, img in enumerate(images):
            t_page = time.monotonic()
            page_result = _analyze_page_image(img, i)

            # Enrich regions with pdfplumber text
            if i < len(page_texts):
                _enrich_regions_with_text(page_result["regions"], page_texts[i], img.size)

            results.append(page_result)
            logger.info(
                "  Page %d: %d regions (%.1fs)",
                i, len(page_result["regions"]), time.monotonic() - t_page,
            )

        elapsed = time.monotonic() - t0
        logger.info("Analysis complete: %d pages, %.1fs total", len(results), elapsed)

        return JSONResponse({
            "pages": results,
            "model": MODEL_ID,
            "page_count": len(results),
            "elapsed_seconds": round(elapsed, 2),
        })

    except Exception as exc:
        logger.error("Analysis failed: %s", exc, exc_info=True)
        raise HTTPException(500, f"Analysis failed: {exc}")
    finally:
        tmp_path.unlink(missing_ok=True)
        gc.collect()


def _extract_text_pdfplumber(pdf_path: Path, max_pages: int) -> list[dict[str, Any]]:
    """Extract text and tables per page using pdfplumber."""
    try:
        import pdfplumber

        results = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages]):
                raw_text = page.extract_text() or ""
                words = page.extract_words(extra_attrs=["fontname", "size"], use_text_flow=True) or []
                tables = page.extract_tables() or []

                results.append({
                    "raw_text": raw_text,
                    "words": words,
                    "tables": tables,
                    "width": float(page.width or 595),
                    "height": float(page.height or 842),
                })
        return results
    except Exception as exc:
        logger.warning("pdfplumber extraction failed: %s", exc)
        return []


def _enrich_regions_with_text(regions: list[dict], page_text: dict, image_size: tuple):
    """Assign pdfplumber-extracted text to LayoutLM-detected regions."""
    if not page_text or not regions:
        return

    words = page_text.get("words") or []
    pdf_width = page_text.get("width", 595)
    pdf_height = page_text.get("height", 842)

    for region in regions:
        bbox = region["bbox"]  # normalized 0-1000
        # Convert to PDF coordinates
        rx0 = bbox[0] * pdf_width / 1000
        ry0 = bbox[1] * pdf_height / 1000
        rx1 = bbox[2] * pdf_width / 1000
        ry1 = bbox[3] * pdf_height / 1000

        # Collect words that fall inside this region
        region_words = []
        for w in words:
            wx = (float(w.get("x0", 0)) + float(w.get("x1", 0))) / 2
            wy = (float(w.get("top", 0)) + float(w.get("bottom", 0))) / 2
            if rx0 <= wx <= rx1 and ry0 <= wy <= ry1:
                region_words.append(str(w.get("text", "")))

        region["text"] = " ".join(region_words)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("LAYOUTLM_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
