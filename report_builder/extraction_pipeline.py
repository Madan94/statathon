"""Multi-Pass Extraction Pipeline — LayoutLM + Qwen-VL.

Orchestrates the 4-pass extraction flow for Enterprise Document AST:
    Pass 0: PDF rasterization (pdf2image + pdfplumber raw text)
    Pass 1: Layout detection via LayoutLMv3 (CPU, port 8001)
    Pass 2: Content extraction via Qwen2.5-VL-7B (GPU, port 8002)
    Pass 3: Semantic analysis via Qwen-VL (GPU, same container, with late chunking)
    Pass 4: AST assembly (programmatic, no LLM)

Environment variables:
    LAYOUTLM_ENDPOINT       = http://localhost:8001
    SGLANG_ENDPOINT         = http://localhost:8002
    SGLANG_MODEL            = Qwen/Qwen2.5-VL-7B-Instruct-AWQ
    PIPELINE_GPU_MODE       = sequential | concurrent | gemini_only
    GEMINI_MODEL            = gemini-2.5-flash
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

from report_builder.chunking import (
    DocumentChunk,
    ToCEntry,
    build_toc_from_regions,
    split_into_chunks,
)

logger = logging.getLogger(__name__)

_LAYOUTLM_ENDPOINT = os.getenv("LAYOUTLM_ENDPOINT", "http://localhost:8001")
_SGLANG_ENDPOINT = os.getenv("SGLANG_ENDPOINT", "http://localhost:8002")


# ─────────────────────────────────────────────────────────────────────────────
# Pass 0: PDF Rasterization
# ─────────────────────────────────────────────────────────────────────────────

def pass0_rasterize(pdf_path: Path) -> tuple[list[bytes], list[dict[str, Any]]]:
    """Rasterize PDF pages to PNG images + extract raw text with pdfplumber.

    Returns:
        (page_images_png, page_texts)
        page_images_png: list of PNG bytes per page
        page_texts: list of {raw_text, words, tables, width, height} per page
    """
    import pdfplumber

    logger.info("[pass0] Rasterizing PDF: %s", pdf_path.name)
    t0 = time.monotonic()

    # Rasterize pages to PNG
    try:
        import pdf2image
        poppler_path = os.getenv("POPPLER_PATH") or None
        images = pdf2image.convert_from_path(str(pdf_path), dpi=150, fmt="png", poppler_path=poppler_path)
    except Exception as exc:
        logger.error("[pass0] pdf2image failed: %s — trying Pillow fallback", exc)
        images = []

    # Resize images to fit within max dimension to reduce VLM token count
    _max_dim = int(os.getenv("VLM_MAX_IMAGE_DIM", "800"))
    page_images: list[bytes] = []
    for img in images:
        w, h = img.size
        if max(w, h) > _max_dim:
            scale = _max_dim / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), resample=1)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page_images.append(buf.getvalue())

    # Extract text with pdfplumber (backup + enrichment)
    page_texts: list[dict[str, Any]] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                raw_text = page.extract_text() or ""
                words = page.extract_words(extra_attrs=["fontname", "size"], use_text_flow=True) or []
                tables = page.extract_tables() or []

                # Detect headings from font analysis
                headings: list[str] = []
                for w in words:
                    if w.get("size", 0) >= 12 or "Bold" in str(w.get("fontname", "")):
                        text = str(w.get("text", "")).strip()
                        if text and len(text) > 3:
                            headings.append(text)

                page_texts.append({
                    "raw_text": raw_text,
                    "words": words,
                    "tables": tables,
                    "headings": headings,
                    "width": float(page.width or 595),
                    "height": float(page.height or 842),
                    "word_count": len(raw_text.split()),
                })
    except Exception as exc:
        logger.warning("[pass0] pdfplumber failed: %s", exc)

    elapsed = time.monotonic() - t0
    logger.info("[pass0] ✓ Rasterized %d images + %d text pages (%.1fs)", len(page_images), len(page_texts), elapsed)
    return page_images, page_texts


# ─────────────────────────────────────────────────────────────────────────────
# Pass 1: Layout Detection via LayoutLMv3
# ─────────────────────────────────────────────────────────────────────────────

def pass1_layout_detection(pdf_path: Path) -> list[dict[str, Any]] | None:
    """Send PDF to LayoutLM service → get regions per page.

    Returns:
        List of page dicts with regions, or None on failure.
    """
    endpoint = _LAYOUTLM_ENDPOINT.rstrip("/") + "/analyze"
    timeout = int(os.getenv("LAYOUTLM_TIMEOUT", "300"))

    logger.info("[pass1] ▶ LayoutLM POST → %s (timeout=%ds)", endpoint, timeout)
    t0 = time.monotonic()

    try:
        with open(pdf_path, "rb") as f:
            r = requests.post(endpoint, files={"file": f}, timeout=timeout)
        r.raise_for_status()
        body = r.json()
        pages = body.get("pages") or []
        elapsed = time.monotonic() - t0
        logger.info("[pass1] ✓ LayoutLM detected regions on %d pages (%.1fs)", len(pages), elapsed)
        return pages
    except Exception as exc:
        elapsed = time.monotonic() - t0
        logger.error("[pass1] ✗ LayoutLM failed: %s (%.1fs)", exc, elapsed)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2: Content Extraction via Qwen-VL
# ─────────────────────────────────────────────────────────────────────────────

def pass2_content_extraction(
    page_images: list[bytes],
    layout_pages: list[dict[str, Any]],
    page_texts: list[dict[str, Any]],
    doc_title: str = "Document",
) -> list[dict[str, Any]]:
    """Extract content from each page using Qwen-VL vision model.

    For each page:
        - Sends page image + detected regions to Qwen-VL
        - Asks it to extract text, table schemas, chart descriptions
        - Falls back to pdfplumber text if Qwen-VL fails

    Returns:
        List of enriched page dicts with extracted content per region.
    """
    endpoint = _SGLANG_ENDPOINT.rstrip("/") + "/v1/chat/completions"
    model = os.getenv("SGLANG_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct-AWQ")
    timeout = int(os.getenv("SGLANG_TIMEOUT", "120"))
    total_pages = len(page_images)

    # Pre-flight: check if vLLM is alive before sending pages
    vlm_alive = False
    if total_pages > 0:
        try:
            health_url = _SGLANG_ENDPOINT.rstrip("/") + "/v1/models"
            hr = requests.get(health_url, timeout=5)
            vlm_alive = hr.status_code == 200
        except Exception:
            pass
        if not vlm_alive:
            logger.warning("[pass2] vLLM not reachable — falling back to pdfplumber text")

    # If no images or vLLM is down, fall back to text-only extraction
    if (total_pages == 0 or not vlm_alive) and page_texts:
        logger.warning("[pass2] No page images available — using pdfplumber text extraction (no VLM)")
        results: list[dict[str, Any]] = []
        for i, page_text in enumerate(page_texts):
            result = {
                "page_index": i,
                "width": page_text.get("width", 595),
                "height": page_text.get("height", 842),
                "layout_regions": layout_pages[i].get("regions", []) if i < len(layout_pages) else [],
                "extracted_content": None,
                "raw_text": page_text.get("raw_text", ""),
                "headings": page_text.get("headings", []),
                "tables_raw": page_text.get("tables", []),
                "word_count": page_text.get("word_count", 0),
            }
            results.append(result)
        logger.info("[pass2] ✓ Built %d text-only pages from pdfplumber (no VLM)", len(results))
        return results

    logger.info("[pass2] ▶ Content extraction: %d pages via Qwen-VL", total_pages)
    t0 = time.monotonic()

    results: list[dict[str, Any]] = []
    consecutive_failures = 0
    _max_consecutive_fail = int(os.getenv("VLM_MAX_CONSECUTIVE_FAIL", "3"))
    vlm_skipped = False

    for i, img_bytes in enumerate(page_images):
        page_layout = layout_pages[i] if i < len(layout_pages) else {}
        page_text = page_texts[i] if i < len(page_texts) else {}
        regions = page_layout.get("regions") or []

        extracted = None

        # Skip VLM if too many consecutive failures (GPU likely crashed)
        if vlm_skipped:
            pass
        elif consecutive_failures >= _max_consecutive_fail:
            logger.warning("[pass2] %d consecutive VLM failures — skipping VLM for remaining pages", consecutive_failures)
            vlm_skipped = True
        else:
            try:
                # Build region description for prompt
                region_desc = _format_regions_for_prompt(regions)

                # Encode image as base64 for vLLM vision API
                img_b64 = base64.b64encode(img_bytes).decode("utf-8")

                # Build prompt
                prompt = (
                    f"You are analyzing page {i + 1} of {total_pages} of document \"{doc_title}\".\n"
                    f"Layout analysis detected these regions:\n{region_desc}\n\n"
                    "For each region, extract:\n"
                    "- text regions: verbatim text content\n"
                    "- table regions: column headers, row labels, and 2 sample data rows\n"
                    "- figure/chart regions: type (bar/line/pie), title, axis labels, series names\n"
                    "- heading regions: heading text and hierarchy level (1=chapter, 2=section, 3=sub)\n\n"
                    "Output JSON: {\"regions\": [{\"region_idx\": 0, \"type\": \"...\", \"content\": {...}}]}"
                )

                payload = {
                    "model": model,
                    "messages": [
                        {"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                            {"type": "text", "text": prompt},
                        ]},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 512,
                }

                r = requests.post(endpoint, json=payload, timeout=timeout)
                if r.status_code == 200:
                    raw = r.json()["choices"][0]["message"]["content"].strip()
                    if raw.startswith("```"):
                        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
                    extracted = json.loads(raw)
                    consecutive_failures = 0
                elif r.status_code >= 500:
                    # Server error (likely CUDA crash) — count as failure
                    logger.warning("[pass2] Page %d VLM returned %d", i, r.status_code)
                    consecutive_failures += 1
                else:
                    logger.debug("[pass2] Page %d VLM returned %d", i, r.status_code)
                    consecutive_failures += 1
            except json.JSONDecodeError:
                logger.debug("[pass2] Page %d JSON parse failed", i)
                consecutive_failures += 1
            except (requests.ConnectionError, requests.Timeout) as exc:
                logger.warning("[pass2] Page %d VLM connection failed: %s", i, type(exc).__name__)
                consecutive_failures += 1
            except Exception as exc:
                logger.warning("[pass2] Page %d VLM unexpected error: %s", i, exc)
                consecutive_failures += 1

        # Build result (always succeeds — pdfplumber text is the floor)
        result = {
            "page_index": i,
            "width": page_layout.get("width", page_text.get("width", 595)),
            "height": page_layout.get("height", page_text.get("height", 842)),
            "layout_regions": regions,
            "extracted_content": extracted,
            "raw_text": page_text.get("raw_text", ""),
            "headings": page_text.get("headings", []),
            "tables_raw": page_text.get("tables", []),
            "word_count": page_text.get("word_count", 0),
        }
        results.append(result)

        if (i + 1) % 5 == 0 or i == total_pages - 1:
            logger.info("[pass2]   processed %d/%d pages (vlm_ok=%d)", i + 1, total_pages,
                        sum(1 for r in results if r.get("extracted_content")))

    elapsed = time.monotonic() - t0
    logger.info("[pass2] ✓ Content extracted from %d pages (%.1fs)", len(results), elapsed)
    return results


def _format_regions_for_prompt(regions: list[dict]) -> str:
    """Format LayoutLM regions into concise prompt text."""
    if not regions:
        return "(No regions detected — analyze the full page)"

    lines = []
    for i, r in enumerate(regions[:15]):  # cap at 15 regions
        rtype = r.get("type", "unknown")
        bbox = r.get("bbox", [0, 0, 0, 0])
        text_hint = (r.get("text") or "")[:80]
        lines.append(f"  [{i}] {rtype} at [{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}]"
                     + (f" hint=\"{text_hint}\"" if text_hint else ""))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Pass 3: Semantic Analysis via Qwen-VL (with late chunking)
# ─────────────────────────────────────────────────────────────────────────────

def pass3_semantic_analysis(
    content_pages: list[dict[str, Any]],
    toc: list[ToCEntry],
    doc_title: str = "Document",
) -> dict[str, Any]:
    """Analyze extracted content for semantic hierarchy + entities.

    Uses late chunking: splits document at section boundaries, prepends
    context from prior sections to each chunk.

    Returns:
        {
            "semantic_hierarchy": [...],
            "entities": [...],
            "template_slots": [...],
            "questions": [...],
        }
    """
    endpoint = _SGLANG_ENDPOINT.rstrip("/") + "/v1/chat/completions"
    model = os.getenv("SGLANG_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct-AWQ")
    timeout = int(os.getenv("SGLANG_TIMEOUT", "120"))

    logger.info("[pass3] ▶ Semantic analysis with late chunking")
    t0 = time.monotonic()

    # Pre-flight: check if vLLM is alive
    vlm_alive = False
    try:
        hr = requests.get(_SGLANG_ENDPOINT.rstrip("/") + "/v1/models", timeout=5)
        vlm_alive = hr.status_code == 200
    except Exception:
        pass

    if not vlm_alive:
        logger.warning("[pass3] vLLM not reachable — skipping local semantic (will try Gemini fallback)")
        return {"semantic_hierarchy": [], "entities": [], "template_slots": [], "questions": []}

    # Build chunks with context prefixes
    chunks = split_into_chunks(content_pages, toc, doc_title=doc_title)

    all_entities: list[dict] = []
    all_hierarchy: list[dict] = []
    all_questions: list[dict] = []
    all_slots: list[dict] = []
    consecutive_failures = 0

    for chunk in chunks:
        # If 3+ consecutive failures, vLLM likely crashed — stop trying
        if consecutive_failures >= 3:
            logger.warning("[pass3] %d consecutive failures — aborting local semantic", consecutive_failures)
            break

        # Build page text for this chunk
        chunk_text = ""
        for p in chunk.content:
            page_text = p.get("raw_text") or ""
            headings = p.get("headings") or []
            chunk_text += f"\n--- Page {p.get('page_index', 0) + 1} ---\n"
            if headings:
                chunk_text += f"Headings: {', '.join(headings[:5])}\n"
            chunk_text += page_text[:1000] + "\n"

        # Truncate to fit in context window (leave room for output)
        max_input_chars = 2500
        chunk_text = chunk_text[:max_input_chars]

        prompt = (
            f"{chunk.context_prefix}\n\n"
            f"Content:\n{chunk_text}\n\n"
            "Extract from this section:\n"
            "1. semantic_hierarchy: [{nodeId, parentId, level, title, pageSpan}]\n"
            "2. entities: [{entityId, type (org|metric|demographic|time), name}]\n"
            "3. template_slots: [{slotId, entityRef, slotType, currentValue, description}]\n"
            "4. questions: [{id, question, section}] — questions this section answers\n\n"
            "Output JSON with these 4 keys. Be concise."
        )

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You extract document structure and entities for template creation."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        }

        try:
            r = requests.post(endpoint, json=payload, timeout=timeout)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"]
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1].rsplit("```", 1)[0]
                data = json.loads(content)

                all_hierarchy.extend(data.get("semantic_hierarchy") or [])
                all_entities.extend(data.get("entities") or [])
                all_slots.extend(data.get("template_slots") or [])
                all_questions.extend(data.get("questions") or [])
                consecutive_failures = 0
            else:
                logger.debug("[pass3] Chunk %d returned %d", chunk.chunk_id, r.status_code)
                consecutive_failures += 1
        except (requests.ConnectionError, requests.Timeout) as exc:
            logger.warning("[pass3] Chunk %d connection failed: %s", chunk.chunk_id, type(exc).__name__)
            consecutive_failures += 1
        except Exception as exc:
            logger.debug("[pass3] Chunk %d failed: %s", chunk.chunk_id, exc)
            consecutive_failures += 1

    elapsed = time.monotonic() - t0
    logger.info(
        "[pass3] ✓ Semantic analysis: %d hierarchy nodes, %d entities, %d slots (%.1fs)",
        len(all_hierarchy), len(all_entities), len(all_slots), elapsed,
    )

    return {
        "semantic_hierarchy": all_hierarchy,
        "entities": _deduplicate_entities(all_entities),
        "template_slots": all_slots,
        "questions": all_questions,
    }


def _deduplicate_entities(entities: list[dict]) -> list[dict]:
    """Remove duplicate entities by name+type."""
    seen: set[str] = set()
    unique: list[dict] = []
    for e in entities:
        key = f"{e.get('type', '')}:{e.get('name', '')}".lower()
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


# ─────────────────────────────────────────────────────────────────────────────
# Pass 4: AST Assembly
# ─────────────────────────────────────────────────────────────────────────────

def pass4_assemble_ast(
    content_pages: list[dict[str, Any]],
    layout_pages: list[dict[str, Any]],
    semantic: dict[str, Any],
    page_texts: list[dict[str, Any]],
    doc_title: str = "Document",
    source_hash: str = "",
) -> dict[str, Any]:
    """Assemble all extraction passes into Enterprise Document AST.

    Programmatic merge — no LLM needed.
    """
    logger.info("[pass4] ▶ Assembling Enterprise Document AST")

    page_count = len(content_pages)

    # ── layoutAST ──
    layout_ast_pages = []
    for i, page in enumerate(layout_pages or []):
        blocks = []
        for j, region in enumerate(page.get("regions") or []):
            blocks.append({
                "blockId": f"b{i + 1}_{j + 1}",
                "type": region.get("type", "text"),
                "readingOrder": j + 1,
                "bbox": region.get("bbox", [0, 0, 0, 0]),
                "confidence": region.get("confidence", 0),
            })
        layout_ast_pages.append({
            "pageId": f"page_{i + 1:03d}",
            "width": page.get("width", 595),
            "height": page.get("height", 842),
            "blocks": blocks,
        })

    # ── geometryAST ──
    geometry_nodes = []
    for i, page in enumerate(layout_pages or []):
        for j, region in enumerate(page.get("regions") or []):
            bbox = region.get("bbox") or [0, 0, 0, 0]
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                bbox = [0, 0, 0, 0]
            geometry_nodes.append({
                "nodeId": f"b{i + 1}_{j + 1}",
                "bbox": {
                    "x": bbox[0],
                    "y": bbox[1],
                    "width": bbox[2] - bbox[0],
                    "height": bbox[3] - bbox[1],
                },
                "pageRef": f"page_{i + 1:03d}",
            })

    # ── contentAST ──
    paragraphs = []
    for i, page in enumerate(content_pages):
        try:
            vlm_content = page.get("extracted_content")
            if vlm_content and isinstance(vlm_content, dict):
                # Use Qwen-VL structured extraction per region
                for r_idx, region in enumerate(vlm_content.get("regions") or []):
                    if not isinstance(region, dict):
                        continue
                    rtype = region.get("type", "text")
                    content = region.get("content", {})
                    if rtype in ("text", "heading", "paragraph", "narrative"):
                        text_val = content if isinstance(content, str) else (content.get("text", "") if isinstance(content, dict) else str(content))
                        if text_val:
                            para_type = "heading" if rtype == "heading" else "paragraph"
                            paragraphs.append({
                                "id": f"p_{i + 1:03d}_{r_idx + 1:02d}",
                                "type": para_type,
                                "content": str(text_val)[:2000],
                                "pageRef": f"page_{i + 1:03d}",
                                "regionIdx": region.get("region_idx", r_idx),
                            })
            else:
                # Fallback: use raw pdfplumber text as single paragraph per page
                text = page.get("raw_text") or ""
                if text:
                    paragraphs.append({
                        "id": f"p_{i + 1:03d}",
                        "type": "paragraph",
                        "content": text[:2000],
                        "pageRef": f"page_{i + 1:03d}",
                    })
        except Exception as exc:
            logger.debug("[pass4] contentAST page %d error: %s", i, exc)
            # Fallback to raw text
            text = page.get("raw_text") or ""
            if text:
                paragraphs.append({
                    "id": f"p_{i + 1:03d}",
                    "type": "paragraph",
                    "content": text[:2000],
                    "pageRef": f"page_{i + 1:03d}",
                })

    # ── tableAST ──
    tables = []
    for i, page in enumerate(content_pages):
        try:
            # Priority 1: Qwen-VL extracted table structures
            vlm_content = page.get("extracted_content")
            if vlm_content and isinstance(vlm_content, dict):
                for r_idx, region in enumerate(vlm_content.get("regions") or []):
                    if not isinstance(region, dict):
                        continue
                    if region.get("type") == "table":
                        content = region.get("content", {})
                        if not isinstance(content, dict):
                            content = {}
                        headers = content.get("columns") or content.get("column_headers") or []
                        sample_rows = content.get("rows") or content.get("sample_rows") or []
                        if headers or sample_rows:
                            tables.append({
                                "tableId": f"table_{i + 1}_{r_idx + 1}",
                                "title": content.get("title", f"Table on page {i + 1}"),
                                "pageRef": f"page_{i + 1:03d}",
                                "columns": [str(h) for h in headers][:20],
                                "sampleRows": sample_rows[:3] if isinstance(sample_rows, list) else [],
                                "rowCount": content.get("row_count", len(sample_rows) if isinstance(sample_rows, list) else 0),
                                "source": "qwen-vl",
                            })
            # Priority 2: pdfplumber tables (if VLM didn't find any for this page)
            page_vlm_tables = [t for t in tables if t.get("pageRef") == f"page_{i + 1:03d}"]
            if not page_vlm_tables:
                for j, table in enumerate(page.get("tables_raw") or []):
                    if table and len(table) >= 2:
                        headers = [str(c or "") for c in table[0]] if table[0] else []
                        sample_rows = []
                        for row in table[1:3]:
                            sample_rows.append({
                                f"col_{k}": str(c or "") for k, c in enumerate(row or [])
                            })
                        tables.append({
                            "tableId": f"table_{i + 1}_{j + 1}",
                            "title": f"Table on page {i + 1}",
                            "pageRef": f"page_{i + 1:03d}",
                            "columns": headers,
                            "sampleRows": sample_rows,
                            "rowCount": len(table) - 1,
                            "source": "pdfplumber",
                        })
        except Exception as exc:
            logger.debug("[pass4] tableAST page %d error: %s", i, exc)

    # ── figureAST + chartAST ──
    figures = []
    charts = []
    for i, page in enumerate(layout_pages or []):
        for j, region in enumerate(page.get("regions") or []):
            if region.get("type") == "figure":
                figures.append({
                    "figureId": f"fig_{i + 1}_{j + 1}",
                    "caption": region.get("text", "")[:200],
                    "pageRef": f"page_{i + 1:03d}",
                })
            elif region.get("type") == "chart":
                charts.append({
                    "chartId": f"chart_{i + 1}_{j + 1}",
                    "type": "unknown",
                    "title": region.get("text", "")[:200],
                    "pageRef": f"page_{i + 1:03d}",
                })

    # ── extracted_assets (text per page) ──
    text_pages = []
    for i, page in enumerate(content_pages):
        text_pages.append({
            "page_index": i,
            "text": (page.get("raw_text") or "")[:5000],
        })

    # ── Assemble final AST ──
    ast = {
        "metadata": {
            "documentId": f"doc_{source_hash[:8]}" if source_hash else "doc_001",
            "title": doc_title,
            "pageCount": page_count,
            "checksum": source_hash,
            "extractionMethod": "layoutlm+qwen-vl+sequential",
            "version": "2.0",
        },
        "layoutAST": {"pages": layout_ast_pages},
        "styleAST": {"styles": []},
        "geometryAST": {"nodes": geometry_nodes},
        "assetAST": {"assets": []},
        "annotationAST": {"headers": [], "footers": [], "footnotes": []},
        "semanticAST": {"hierarchy": semantic.get("semantic_hierarchy") or []},
        "contentAST": {"paragraphs": paragraphs, "lists": [], "quotes": []},
        "tableAST": {"tables": tables},
        "figureAST": {"figures": figures},
        "chartAST": {"charts": charts},
        "entityGraph": {"entities": semantic.get("entities") or []},
        "knowledgeGraph": {"concepts": []},
        "factGraph": {"facts": []},
        "templateSlots": {"slots": semantic.get("template_slots") or []},
        "questions": semantic.get("questions") or [],
        "extracted_assets": {"text_pages": text_pages, "tables": tables, "images": []},
    }

    logger.info(
        "[pass4] ✓ AST assembled: %d layout pages, %d paragraphs, %d tables, "
        "%d figures, %d charts, %d entities, %d slots",
        len(layout_ast_pages), len(paragraphs), len(tables),
        len(figures), len(charts),
        len(semantic.get("entities") or []),
        len(semantic.get("template_slots") or []),
    )
    return ast


# ─────────────────────────────────────────────────────────────────────────────
# Full Pipeline Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def run_extraction_pipeline(
    pdf_path: Path,
    doc_title: str = "Document",
    source_hash: str = "",
    progress_callback: Any = None,
) -> dict[str, Any]:
    """Run the complete 4-pass extraction pipeline.

    Args:
        pdf_path: Path to the PDF file.
        doc_title: Document title for context.
        source_hash: SHA256 hash of the source file.
        progress_callback: Optional callable(stage, pct, data) for progress updates.

    Returns:
        Enterprise Document AST dict.
    """
    import time as _time

    def _tick(stage: str, pct: int, data: Any = None):
        if progress_callback:
            progress_callback(stage, pct, data)

    pipeline_trace: dict[str, Any] = {"passes": {}, "total_elapsed": 0}
    pipeline_start = _time.monotonic()

    logger.info("═══════════════════════════════════════════════════════════")
    logger.info("  Multi-Pass Extraction Pipeline")
    logger.info("  File: %s", pdf_path.name)
    logger.info("═══════════════════════════════════════════════════════════")

    # ── Pass 0: Rasterize ──
    _tick("pass0_rasterization", 10)
    t0 = _time.monotonic()
    page_images, page_texts = pass0_rasterize(pdf_path)
    pass0_elapsed = _time.monotonic() - t0
    pipeline_trace["passes"]["pass0_rasterize"] = {
        "elapsed_s": round(pass0_elapsed, 1),
        "images": len(page_images),
        "text_pages": len(page_texts),
    }

    if not page_images and not page_texts:
        raise RuntimeError("Pass 0 failed: could not rasterize or extract text from PDF")

    # Ensure page_texts covers all images (pad if pdfplumber extracted fewer)
    while len(page_texts) < len(page_images):
        page_texts.append({"raw_text": "", "words": [], "tables": [], "headings": [], "width": 595, "height": 842, "word_count": 0})

    # ── Pass 1: Layout Detection ──
    _tick("pass1_layout_detection", 25)
    t0 = _time.monotonic()
    layout_pages = pass1_layout_detection(pdf_path)
    pass1_elapsed = _time.monotonic() - t0

    # Fallback: build basic layout from pdfplumber headings if LayoutLM unavailable
    layoutlm_used = layout_pages is not None
    if not layout_pages:
        logger.warning("[pipeline] LayoutLM unavailable — building layout from pdfplumber")
        layout_pages = _fallback_layout_from_text(page_texts)

    total_regions = sum(len(p.get("regions") or []) for p in layout_pages)
    pipeline_trace["passes"]["pass1_layout"] = {
        "elapsed_s": round(pass1_elapsed, 1),
        "layoutlm_used": layoutlm_used,
        "pages_with_regions": len(layout_pages),
        "total_regions": total_regions,
    }

    # Build ToC from layout
    toc = build_toc_from_regions(layout_pages)
    pipeline_trace["passes"]["pass1_layout"]["toc_entries"] = len(toc)

    # ── Pass 2: Content Extraction ──
    _tick("pass2_content_extraction", 50)
    t0 = _time.monotonic()
    content_pages = pass2_content_extraction(page_images, layout_pages, page_texts, doc_title)
    pass2_elapsed = _time.monotonic() - t0

    vlm_success = sum(1 for p in content_pages if p.get("extracted_content") is not None)
    pipeline_trace["passes"]["pass2_vlm"] = {
        "elapsed_s": round(pass2_elapsed, 1),
        "pages_total": len(content_pages),
        "vlm_success": vlm_success,
        "vlm_success_rate": round(vlm_success / max(len(content_pages), 1) * 100, 1),
        "mode": "qwen-vl" if page_images else "text-only-fallback",
    }

    # ── Pass 3: Semantic Analysis ──
    _tick("pass3_semantic_analysis", 75)
    t0 = _time.monotonic()
    semantic = pass3_semantic_analysis(content_pages, toc, doc_title)
    pass3_elapsed = _time.monotonic() - t0

    semantic_source = "qwen-vl"
    # If local model produced nothing, try Gemini fallback
    if not semantic.get("entities") and not semantic.get("semantic_hierarchy"):
        logger.info("[pipeline] Local semantic analysis empty — trying Gemini fallback")
        t0_fb = _time.monotonic()
        semantic = _gemini_semantic_fallback(content_pages, toc, doc_title)
        pass3_elapsed += _time.monotonic() - t0_fb
        semantic_source = "gemini-fallback"

    pipeline_trace["passes"]["pass3_semantic"] = {
        "elapsed_s": round(pass3_elapsed, 1),
        "source": semantic_source,
        "hierarchy_nodes": len(semantic.get("semantic_hierarchy") or []),
        "entities": len(semantic.get("entities") or []),
        "template_slots": len(semantic.get("template_slots") or []),
        "questions": len(semantic.get("questions") or []),
    }

    # ── Pass 4: AST Assembly ──
    _tick("pass4_ast_assembly", 90)
    t0 = _time.monotonic()
    ast = pass4_assemble_ast(content_pages, layout_pages, semantic, page_texts, doc_title, source_hash)
    pass4_elapsed = _time.monotonic() - t0
    pipeline_trace["passes"]["pass4_assembly"] = {
        "elapsed_s": round(pass4_elapsed, 1),
        "paragraphs": len(ast.get("contentAST", {}).get("paragraphs") or []),
        "tables": len(ast.get("tableAST", {}).get("tables") or []),
        "figures": len(ast.get("figureAST", {}).get("figures") or []),
        "charts": len(ast.get("chartAST", {}).get("charts") or []),
    }

    # ── Pass 5: Gemini Enrichment (entities, slots, facts, questions) ──
    _tick("pass5_gemini_enrichment", 95)
    t0 = _time.monotonic()
    try:
        from report_builder.gemini_enrichment import gemini_full_enrichment
        ast = gemini_full_enrichment(ast)
        gemini_status = "success"
    except Exception as exc:
        logger.warning("[pipeline] Gemini enrichment failed (non-fatal): %s", exc)
        gemini_status = f"failed: {exc}"
    pass5_elapsed = _time.monotonic() - t0
    pipeline_trace["passes"]["pass5_gemini"] = {
        "elapsed_s": round(pass5_elapsed, 1),
        "status": gemini_status,
        "facts": len(ast.get("factGraph", {}).get("facts") or []),
        "questions": len(ast.get("questions") or []),
    }

    # Finalize trace
    pipeline_trace["total_elapsed"] = round(_time.monotonic() - pipeline_start, 1)
    ast["pipeline_trace"] = pipeline_trace

    _tick("completed", 100)
    logger.info("═══════════════════════════════════════════════════════════")
    logger.info("  ✓ Pipeline complete — Enterprise AST ready")
    logger.info("═══════════════════════════════════════════════════════════")

    return ast


def _fallback_layout_from_text(page_texts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build basic layout page structure from pdfplumber text extraction."""
    pages = []
    for i, pt in enumerate(page_texts):
        regions = []
        # Create heading regions from detected headings
        for h in (pt.get("headings") or [])[:10]:
            regions.append({
                "bbox": [0, 0, 1000, 50],
                "type": "heading",
                "confidence": 0.6,
                "text": h,
            })
        # Create a paragraph region for the body text
        if pt.get("raw_text"):
            regions.append({
                "bbox": [50, 100, 950, 900],
                "type": "text",
                "confidence": 0.5,
                "text": pt["raw_text"][:200],
            })
        # Create table regions
        for j, table in enumerate(pt.get("tables") or []):
            regions.append({
                "bbox": [50, 200 + j * 200, 950, 400 + j * 200],
                "type": "table",
                "confidence": 0.7,
                "text": f"Table with {len(table)} rows",
            })

        pages.append({
            "page_index": i,
            "width": pt.get("width", 595),
            "height": pt.get("height", 842),
            "regions": regions,
        })
    return pages


def _gemini_semantic_fallback(
    content_pages: list[dict[str, Any]],
    toc: list[ToCEntry],
    doc_title: str,
) -> dict[str, Any]:
    """Use Gemini as fallback for semantic analysis when local model fails."""
    try:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("[gemini-fallback] No API key — skipping")
            return {"semantic_hierarchy": [], "entities": [], "template_slots": [], "questions": []}

        gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        # Build document summary for Gemini
        doc_text = ""
        for p in content_pages[:20]:
            text = p.get("raw_text") or ""
            doc_text += f"\n--- Page {p.get('page_index', 0) + 1} ---\n{text[:800]}\n"

        doc_text = doc_text[:12000]  # Gemini has huge context but be reasonable

        toc_text = "\n".join(f"  {'  ' * (e.level - 1)}{e.title} (p{e.page_index + 1})" for e in toc[:20])

        prompt = (
            f"Document: \"{doc_title}\"\n"
            f"Table of Contents:\n{toc_text}\n\n"
            f"Content:\n{doc_text}\n\n"
            "Extract:\n"
            "1. semantic_hierarchy: [{nodeId, parentId, level, title, pageSpan:[start,end]}]\n"
            "2. entities: [{entityId, type (org|metric|demographic|time), name}]\n"
            "3. template_slots: [{slotId, entityRef, slotType, currentValue, description}]\n"
            "4. questions: [{id, question, section}]\n\n"
            "Output ONLY valid JSON with these 4 keys."
        )

        # Prefer new google-genai SDK
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model=gemini_model, contents=prompt)
            text = (response.text or "").strip()
        except ImportError:
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=api_key)
            model = legacy_genai.GenerativeModel(gemini_model)
            response = model.generate_content(prompt)
            text = (response.text or "").strip()

        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]

        data = json.loads(text)
        logger.info("[gemini-fallback] ✓ Got %d entities, %d hierarchy nodes",
                    len(data.get("entities") or []), len(data.get("semantic_hierarchy") or []))
        return data

    except Exception as exc:
        logger.error("[gemini-fallback] Failed: %s", exc)
        return {"semantic_hierarchy": [], "entities": [], "template_slots": [], "questions": []}
