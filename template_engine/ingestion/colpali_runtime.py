"""In-process ColPali model runtime for PDF vision-spatial extraction."""
from __future__ import annotations

import gc
import logging
import os
from pathlib import Path
from typing import Any

from template_engine.ingestion.pdf_loader import PageData, TableBlock, TextBlock

logger = logging.getLogger(__name__)

_COLPALI_MODEL: Any = None
_COLPALI_PROCESSOR: Any = None
_LAST_LOAD_ERROR: str | None = None

DEFAULT_COLPALI_MODEL = "vidore/colpali-v1.2"
DEFAULT_COLPALI_DPI = 120
DEFAULT_COLPALI_PAGE_BATCH_SIZE = 1


def colpali_model_id() -> str:
    return (os.getenv("COLPALI_MODEL") or DEFAULT_COLPALI_MODEL).strip()


def _env_int(name: str, default: int, minimum: int = 1, maximum: int = 512) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def colpali_raster_dpi() -> int:
    """Lower DPI reduces vision forward RAM (default 120 vs pdf2image's 200)."""
    return _env_int("COLPALI_DPI", DEFAULT_COLPALI_DPI, minimum=72, maximum=300)


def colpali_page_batch_size() -> int:
    return _env_int("COLPALI_PAGE_BATCH_SIZE", DEFAULT_COLPALI_PAGE_BATCH_SIZE, minimum=1, maximum=8)


def _skip_vision_forward() -> bool:
    return os.getenv("COLPALI_SKIP_VISION_FORWARD", "false").lower() in ("1", "true", "yes")


def _ensure_hf_cache() -> None:
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "7200")
    try:
        from pipelines.model_path import ensure_huggingface_hub_cache, repo_root

        ensure_huggingface_hub_cache(repo_root())
    except Exception:
        pass


def _colpali_load_dtype():
    import torch

    raw = (os.getenv("COLPALI_TORCH_DTYPE") or "auto").strip().lower()
    if raw in ("float16", "fp16", "half"):
        return torch.float16
    if raw in ("bfloat16", "bf16"):
        return torch.bfloat16
    if raw in ("float32", "fp32"):
        return torch.float32
    # auto: half precision on CPU/CUDA to cut RAM (~10GB multi-page batches)
    return torch.float16


def get_colpali_model():
    """Lazy singleton ColPali model (loads once per process)."""
    global _COLPALI_MODEL, _LAST_LOAD_ERROR
    if _COLPALI_MODEL is not None:
        return _COLPALI_MODEL
    _ensure_hf_cache()
    model_id = colpali_model_id()
    try:
        import torch
        from colpali_engine.models import ColPali  # type: ignore

        dtype = _colpali_load_dtype()
        load_kwargs: dict[str, Any] = {
            "low_cpu_mem_usage": True,
            "torch_dtype": dtype,
        }
        if torch.cuda.is_available():
            load_kwargs["device_map"] = "auto"

        logger.info("Loading ColPali model: %s (dtype=%s)", model_id, dtype)
        _COLPALI_MODEL = ColPali.from_pretrained(model_id, **load_kwargs)
        _COLPALI_MODEL.eval()
        if not torch.cuda.is_available():
            _COLPALI_MODEL = _COLPALI_MODEL.to(dtype=dtype)
        _LAST_LOAD_ERROR = None
        return _COLPALI_MODEL
    except Exception as exc:
        _LAST_LOAD_ERROR = str(exc)
        logger.exception("ColPali model load failed: %s", exc)
        raise


def get_colpali_processor():
    """Lazy singleton ColPaliProcessor (paired with model checkpoint)."""
    global _COLPALI_PROCESSOR
    if _COLPALI_PROCESSOR is not None:
        return _COLPALI_PROCESSOR
    _ensure_hf_cache()
    model_id = colpali_model_id()
    try:
        from colpali_engine.models.paligemma.colpali.processing_colpali import (  # type: ignore
            ColPaliProcessor,
        )

        logger.info("Loading ColPali processor: %s", model_id)
        _COLPALI_PROCESSOR = ColPaliProcessor.from_pretrained(model_id)
        return _COLPALI_PROCESSOR
    except Exception as exc:
        logger.exception("ColPali processor load failed: %s", exc)
        raise RuntimeError(
            f"colpali-engine processor failed to load for {model_id}: {exc}"
        ) from exc


def _pdf_page_count(pdf_path: Path) -> int:
    try:
        import fitz  # type: ignore

        with fitz.open(str(pdf_path)) as doc:
            return max(doc.page_count, 0)
    except Exception:
        pass
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(str(pdf_path)) as pdf:
            return len(pdf.pages)
    except Exception:
        pass
    imgs = _rasterize_pdf_pages(pdf_path, first_page=1, last_page=1)
    if imgs:
        all_imgs = _rasterize_pdf_pages(pdf_path)
        return len(all_imgs)
    return 0


def _rasterize_pdf_pages(
    pdf_path: Path,
    *,
    first_page: int | None = None,
    last_page: int | None = None,
) -> list[Any]:
    import pdf2image  # type: ignore

    poppler_path = os.getenv("POPPLER_PATH") or None
    convert_kwargs: dict[str, Any] = {"dpi": colpali_raster_dpi()}
    if poppler_path:
        convert_kwargs["poppler_path"] = poppler_path
    if first_page is not None:
        convert_kwargs["first_page"] = first_page
    if last_page is not None:
        convert_kwargs["last_page"] = last_page
    return pdf2image.convert_from_path(str(pdf_path), **convert_kwargs)


def _run_colpali_vision_pass(model: Any, processor: Any, images: list[Any]) -> None:
    """Run ColPali forward in small page batches to avoid multi-page RAM spikes."""
    import torch

    if not images:
        return

    batch_size = colpali_page_batch_size()
    device = next(model.parameters()).device

    for start in range(0, len(images), batch_size):
        chunk = images[start : start + batch_size]
        batch = processor.process_images(chunk)
        batch_on_device = {
            key: value.to(device) if hasattr(value, "to") else value
            for key, value in batch.items()
        }
        with torch.no_grad():
            model(**batch_on_device)
        del batch, batch_on_device, chunk
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

    logger.info(
        "ColPali vision pass completed for %d page(s) (batch_size=%d, dpi=%d)",
        len(images),
        batch_size,
        colpali_raster_dpi(),
    )


def _load_structural_pages(pdf_path: Path) -> list[PageData]:
    """Text/geometry from pdfplumber or PyMuPDF (ColPali does not emit OCR blocks)."""
    from template_engine.ingestion import pdf_loader as pl

    pages = pl._load_pdfplumber(pdf_path)
    if pages:
        return pages
    pages = pl._load_pymupdf(pdf_path)
    if pages:
        return pages
    raise RuntimeError(
        "ColPali vision passed but no text could be extracted. "
        "Install pdfplumber or pymupdf: pip install pdfplumber pymupdf"
    )


def _block_to_text_block(b: dict[str, Any]) -> TextBlock | None:
    text = str(b.get("text") or "").strip()
    if not text:
        return None
    kind = str(b.get("kind") or "").lower()
    is_heading = kind in ("heading", "title", "header")
    x0 = float(b.get("x0") or b.get("left") or 0)
    y0 = float(b.get("y0") or b.get("top") or 0)
    x1 = float(b.get("x1") or b.get("right") or x0 + 100)
    y1 = float(b.get("y1") or b.get("bottom") or y0 + 12)
    return TextBlock(
        text=text,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        font_size=14.0 if is_heading else 10.0,
        bold=is_heading,
        all_caps=text.isupper() and len(text) > 3,
    )


def _spatial_pages_to_page_data(spatial: list[dict[str, Any]]) -> list[PageData]:
    """Map sidecar / legacy spatial JSON into PageData (optional path)."""
    pages: list[PageData] = []
    for i, page in enumerate(spatial):
        if not isinstance(page, dict):
            continue
        blocks = page.get("blocks") or []
        text_blocks: list[TextBlock] = []
        table_blocks: list[TableBlock] = []
        line_parts: list[str] = []
        has_charts = False

        for b in blocks:
            if not isinstance(b, dict):
                continue
            kind = str(b.get("kind") or "").lower()
            if kind in ("chart", "figure", "image"):
                has_charts = True
            if kind == "table":
                rows = b.get("rows")
                if isinstance(rows, list) and rows:
                    str_rows = [[str(c or "") for c in row] for row in rows if isinstance(row, (list, tuple))]
                    if str_rows:
                        table_blocks.append(
                            TableBlock(
                                rows=str_rows,
                                col_count=max((len(r) for r in str_rows), default=0),
                                row_count=len(str_rows),
                            )
                        )
                tb = _block_to_text_block(b)
                if tb:
                    text_blocks.append(tb)
                    line_parts.append(tb.text)
            else:
                tb = _block_to_text_block(b)
                if tb:
                    text_blocks.append(tb)
                    line_parts.append(tb.text)

        raw_text = str(page.get("text") or "").strip() or "\n".join(line_parts)
        if not text_blocks and raw_text:
            text_blocks.append(TextBlock(text=raw_text[:500], font_size=10.0))

        pages.append(
            PageData(
                page_index=int(page.get("page_index", i)),
                width=float(page.get("width") or 595.0),
                height=float(page.get("height") or 842.0),
                text_blocks=text_blocks,
                tables=table_blocks,
                raw_text=raw_text,
                has_charts=has_charts or bool(page.get("has_charts")),
            )
        )
    return pages


def extract_pdf_colpali_inprocess(pdf_path: Path) -> list[PageData]:
    """Run ColPali on PDF pages (one page at a time), then structural text extract."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    page_count = _pdf_page_count(pdf_path)
    if page_count <= 0:
        try:
            probe = _rasterize_pdf_pages(pdf_path, first_page=1, last_page=1)
        except Exception as exc:
            msg = str(exc).lower()
            if "poppler" in msg or "pdftoppm" in msg:
                raise RuntimeError(
                    "Poppler is required for pdf2image. Install Poppler and add bin to PATH, "
                    "or set POPPLER_PATH in .env"
                ) from exc
            raise RuntimeError(f"pdf2image failed to rasterize PDF: {exc}") from exc
        if not probe:
            raise RuntimeError("pdf2image produced no pages from PDF")
        page_count = 1

    model = get_colpali_model()
    processor = get_colpali_processor()

    if not _skip_vision_forward():
        try:
            for page_num in range(1, page_count + 1):
                try:
                    page_images = _rasterize_pdf_pages(
                        pdf_path, first_page=page_num, last_page=page_num
                    )
                except Exception as exc:
                    msg = str(exc).lower()
                    if "poppler" in msg or "pdftoppm" in msg:
                        raise RuntimeError(
                            "Poppler is required for pdf2image. Install Poppler and add bin to PATH, "
                            "or set POPPLER_PATH in .env"
                        ) from exc
                    raise RuntimeError(f"pdf2image failed on page {page_num}: {exc}") from exc
                if not page_images:
                    logger.warning("ColPali: empty raster for page %s", page_num)
                    continue
                _run_colpali_vision_pass(model, processor, page_images)
                del page_images
                gc.collect()
        except Exception as exc:
            hint = (
                " If RAM is limited, set COLPALI_DPI=96, COLPALI_PAGE_BATCH_SIZE=1, "
                "COLPALI_TORCH_DTYPE=float16, or PDF_PARSER=legacy."
            )
            raise RuntimeError(f"ColPali vision forward failed: {exc}.{hint}") from exc
    else:
        logger.warning(
            "COLPALI_SKIP_VISION_FORWARD=true — skipping ColPali forward (structural extract only)"
        )

    pages = _load_structural_pages(pdf_path)
    if len(pages) != page_count:
        logger.warning(
            "ColPali expected %d pages but structural extract returned %d",
            page_count,
            len(pages),
        )
    if not pages:
        raise RuntimeError("ColPali extraction produced no PageData")
    return pages


def last_colpali_load_error() -> str | None:
    return _LAST_LOAD_ERROR
