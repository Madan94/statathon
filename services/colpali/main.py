"""ColPali vision microservice — PDF in, structured pages out.

Endpoints:
  GET  /health
  POST /extract   multipart file=PDF → {"pages": [...]}
"""
from __future__ import annotations

import gc
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

MODEL_ID = os.getenv("MODEL_ID", "vidore/colpali-v1.2")
DEVICE = os.getenv("DEVICE", "auto").strip().lower()
COLPALI_DPI = int(os.getenv("COLPALI_DPI", "120"))
COLPALI_PAGE_BATCH_SIZE = max(1, int(os.getenv("COLPALI_PAGE_BATCH_SIZE", "1")))

app = FastAPI(title="ColPali Service", version="1.0.0")

_MODEL: Any = None
_PROCESSOR: Any = None


def _resolve_device():
    import torch

    if DEVICE == "cpu":
        return torch.device("cpu")
    if DEVICE in ("cuda", "gpu") and torch.cuda.is_available():
        return torch.device("cuda")
    if DEVICE == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device("cpu")


def _load_model():
    global _MODEL, _PROCESSOR
    if _MODEL is not None:
        return _MODEL, _PROCESSOR

    import torch
    from colpali_engine.models import ColPali
    from colpali_engine.models.paligemma.colpali.processing_colpali import ColPaliProcessor

    logger.info("Loading ColPali model %s on %s", MODEL_ID, _resolve_device())
    dtype = torch.float16 if _resolve_device().type != "cpu" else torch.float32
    _MODEL = ColPali.from_pretrained(MODEL_ID, torch_dtype=dtype, low_cpu_mem_usage=True)
    _MODEL.eval()
    _MODEL.to(_resolve_device())
    _PROCESSOR = ColPaliProcessor.from_pretrained(MODEL_ID)
    return _MODEL, _PROCESSOR


def _vision_pass(images: list[Any]) -> None:
    import torch

    model, processor = _load_model()
    device = next(model.parameters()).device
    for start in range(0, len(images), COLPALI_PAGE_BATCH_SIZE):
        chunk = images[start : start + COLPALI_PAGE_BATCH_SIZE]
        batch = processor.process_images(chunk)
        batch_on_device = {
            k: v.to(device) if hasattr(v, "to") else v for k, v in batch.items()
        }
        with torch.no_grad():
            model(**batch_on_device)
        del batch, batch_on_device, chunk
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()


def _structural_pages(pdf_path: Path) -> list[dict[str, Any]]:
    """pdfplumber → sidecar page dicts (blocks + text)."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber required in ColPali container") from exc

    pages: list[dict[str, Any]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            raw = page.extract_text() or ""
            words = page.extract_words(extra_attrs=["fontname", "size"], use_text_flow=True) or []
            line_map: dict[int, list[dict]] = {}
            for w in words:
                key = round((w.get("top") or 0) / 3) * 3
                line_map.setdefault(key, []).append(w)

            blocks: list[dict[str, Any]] = []
            for _y, wds in sorted(line_map.items()):
                line_text = " ".join(str(w.get("text", "")) for w in wds).strip()
                if not line_text:
                    continue
                sizes = [w.get("size") or 10.0 for w in wds]
                avg_size = sum(sizes) / max(len(sizes), 1)
                is_bold = any("Bold" in str(w.get("fontname", "")) for w in wds)
                blocks.append(
                    {
                        "text": line_text,
                        "x0": float(wds[0].get("x0") or 0),
                        "y0": float(wds[0].get("top") or 0),
                        "x1": float(wds[-1].get("x1") or 0),
                        "y1": float(wds[-1].get("bottom") or 0),
                        "font_size": avg_size,
                        "bold": is_bold,
                        "kind": "heading" if (is_bold or avg_size >= 12) else "text",
                    }
                )

            pages.append(
                {
                    "page_index": i,
                    "width": float(page.width or 595),
                    "height": float(page.height or 842),
                    "blocks": blocks,
                    "text": raw,
                    "has_charts": False,
                }
            )
    return pages


def _extract_pdf(pdf_path: Path) -> dict[str, Any]:
    import pdf2image

    images = pdf2image.convert_from_path(str(pdf_path), dpi=COLPALI_DPI)
    if not images:
        raise RuntimeError("pdf2image produced no pages")
    _vision_pass(images)
    pages = _structural_pages(pdf_path)
    return {"pages": pages, "model": MODEL_ID, "page_count": len(pages)}


@app.on_event("startup")
def warmup():
    if os.getenv("COLPALI_WARMUP", "true").lower() in ("1", "true", "yes"):
        try:
            _load_model()
            logger.info("ColPali model warmed up")
        except Exception as exc:
            logger.warning("Warmup failed (will retry on first /extract): %s", exc)


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_ID, "device": str(_resolve_device())}


@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    suffix = Path(file.filename or "upload.pdf").suffix or ".pdf"
    try:
        raw = await file.read()
        if not raw:
            raise HTTPException(400, "Empty file")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        try:
            result = _extract_pdf(tmp_path)
            return result
        finally:
            tmp_path.unlink(missing_ok=True)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Extract failed")
        raise HTTPException(500, str(exc)[:2000]) from exc
