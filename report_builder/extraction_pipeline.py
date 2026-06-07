"""Multi-Pass Extraction Pipeline — LayoutLM + Qwen-VL.

Orchestrates the 7-pass extraction flow for Enterprise Document AST + Blueprint:
    Pass 0: PDF rasterization (pdf2image 150dpi + pdfplumber raw text/tables/words)
    Pass 1: Layout detection via LayoutLMv3 (CPU, port 8001) → regions per page
    Pass 2: Entity + Structure extraction via Qwen2.5-VL (GPU, port 8002)
            → per-page entities, structure_type, description, chart_types (50-150 tokens)
    Pass 2.5: Document Knowledge Graph (PROGRAMMATIC, no LLM)
            → entity merge, table structure analysis, chapter hierarchy,
              per-page context scripts, MoSPI section pattern detection
    Pass 3: Two-loop AST building via Qwen-VL (GPU)
            Loop 1: question extraction per section chunk
            Loop 2: entity binding + AnswerStructure per question
    Pass 4: Programmatic assembly → Enterprise AST + embedded blueprint subtree
            (TopicNode → QuestionNode → AnswerStructure → AnswerComponent)
    Pass 5: Optional Gemini enhancement
            → entity classification, alias gen, blueprint validation, gap fill

Architecture:
    - LayoutLM detects WHERE things are (bboxes, types: table/heading/text/figure)
    - Qwen-VL extracts ENTITIES + STRUCTURE + SEMANTIC CONTEXT (NOT text/values)
    - pdfplumber table headers = gold standard entity source
    - Per-page UNIQUE context scripts (position-aware, entity-carrying)
    - Pipeline works fully offline without Gemini

Environment variables:
    LAYOUTLM_ENDPOINT       = http://localhost:8001
    SGLANG_ENDPOINT         = http://localhost:8002
    SGLANG_MODEL            = Qwen/Qwen2.5-VL-3B-Instruct-AWQ
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
    ToCEntry,
    build_toc_from_regions,
)

logger = logging.getLogger(__name__)

_LAYOUTLM_ENDPOINT = os.getenv("LAYOUTLM_ENDPOINT", "http://localhost:8001")
_SGLANG_ENDPOINT = os.getenv("SGLANG_ENDPOINT", "http://localhost:8002")


# ─────────────────────────────────────────────────────────────────────────────
# Robust JSON Extraction (handles truncated / wrapped VLM output)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json_from_response(raw: str) -> dict | None:
    """Extract a JSON dict from potentially messy LLM output.

    Handles:
        - Markdown code blocks (```json ... ```, ``` ... ```)
        - Text before/after JSON
        - Truncated JSON (attempts bracket repair)
        - Partial arrays
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # Strip markdown code fences (multiple formats)
    if "```" in text:
        # Find content between first ``` and last ```
        parts = text.split("```")
        if len(parts) >= 3:
            # Take the content of the first fenced block
            inner = parts[1]
            # Remove language tag (e.g., "json\n")
            if inner and inner.split("\n", 1)[0].strip().isalpha():
                inner = inner.split("\n", 1)[-1]
            text = inner.strip()
        elif len(parts) == 2:
            # Opening ``` without closing — take everything after it
            inner = parts[1]
            if inner and inner.split("\n", 1)[0].strip().isalpha():
                inner = inner.split("\n", 1)[-1]
            text = inner.strip()

    # Try direct parse first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Find the first { and try to parse from there
    brace_start = text.find("{")
    if brace_start == -1:
        return None

    candidate = text[brace_start:]

    # Try direct parse of substring
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Try trimming trailing text after last }
    brace_end = candidate.rfind("}")
    if brace_end >= 0:
        trimmed = candidate[: brace_end + 1]
        try:
            obj = json.loads(trimmed)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # Attempt repair of truncated JSON: close unclosed brackets
    repaired = _repair_truncated_json(candidate)
    if repaired:
        try:
            obj = json.loads(repaired)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    return None


def _repair_truncated_json(text: str) -> str | None:
    """Attempt to close unclosed brackets/braces in truncated JSON."""
    # Count open/close brackets
    open_braces = 0
    open_brackets = 0
    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            open_braces += 1
        elif ch == "}":
            open_braces -= 1
        elif ch == "[":
            open_brackets += 1
        elif ch == "]":
            open_brackets -= 1

    if open_braces <= 0 and open_brackets <= 0:
        return None  # Not truncated, just invalid

    # Close unclosed structures
    # First strip any trailing incomplete key/value
    # Find last complete value (ends with ", or }, or ], or number, or true/false/null)
    import re
    # Remove trailing partial string or key
    cleaned = re.sub(r',\s*"[^"]*$', '', text)  # trailing "incomplete_key
    cleaned = re.sub(r',\s*"[^"]*":\s*"[^"]*$', '', cleaned)  # trailing "key": "incomplete_val
    cleaned = re.sub(r',\s*"[^"]*":\s*\[[^\]]*$', lambda m: m.group(0) + "]", cleaned)  # close trailing array
    cleaned = re.sub(r',\s*$', '', cleaned)  # trailing comma

    # Recount after cleanup
    open_braces = 0
    open_brackets = 0
    in_string = False
    escape_next = False
    for ch in cleaned:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            open_braces += 1
        elif ch == "}":
            open_braces -= 1
        elif ch == "[":
            open_brackets += 1
        elif ch == "]":
            open_brackets -= 1

    # Append closers
    suffix = "]" * max(open_brackets, 0) + "}" * max(open_braces, 0)
    return cleaned + suffix if suffix else None


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
# Pass 2: Entity + Structure Extraction via Qwen-VL (SIMPLIFIED)
# ─────────────────────────────────────────────────────────────────────────────

def pass2_entity_structure_extraction(
    page_images: list[bytes],
    layout_pages: list[dict[str, Any]],
    page_texts: list[dict[str, Any]],
    doc_title: str = "Document",
) -> list[dict[str, Any]]:
    """Extract ENTITIES + STRUCTURE TYPE + DESCRIPTION per page using Qwen-VL.

    This pass does NOT extract paragraph text or table values.
    Qwen-VL's job is to identify:
        - What entities/concepts appear on this page
        - What is the structural purpose of this page (data table, chart, narrative, etc.)
        - A one-line description of the page's content
        - What chart types are visible (if any)

    Output per page: ~50-150 tokens (never truncates at 2048 context).

    Falls back to pdfplumber headings + table headers as entity source if VLM fails.

    Returns:
        List of per-page dicts with {page_index, entities[], structure_type, description, chart_types[]}.
    """
    endpoint = _SGLANG_ENDPOINT.rstrip("/") + "/v1/chat/completions"
    model = os.getenv("SGLANG_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct-AWQ")
    timeout = int(os.getenv("SGLANG_TIMEOUT", "120"))
    total_pages = len(page_images)

    # Pre-flight: check if vLLM is alive
    vlm_alive = False
    if total_pages > 0:
        try:
            health_url = _SGLANG_ENDPOINT.rstrip("/") + "/v1/models"
            hr = requests.get(health_url, timeout=5)
            vlm_alive = hr.status_code == 200
        except Exception:
            pass
        if not vlm_alive:
            logger.warning("[pass2] vLLM not reachable — falling back to pdfplumber-only entities")

    # If vLLM is down, extract entities from pdfplumber only
    if not vlm_alive or total_pages == 0:
        results: list[dict[str, Any]] = []
        for i, page_text in enumerate(page_texts):
            entities = _entities_from_pdfplumber(page_text, i)
            has_tables = bool(page_text.get("tables"))
            results.append({
                "page_index": i,
                "entities": entities,
                "structure_type": "data_table" if has_tables else "narrative",
                "description": "",
                "chart_types": [],
                "vlm_used": False,
            })
        logger.info("[pass2] ✓ Built %d entity pages from pdfplumber (no VLM)", len(results))
        return results

    logger.info("[pass2] ▶ Entity+structure extraction: %d pages via Qwen-VL", total_pages)
    t0 = time.monotonic()

    results: list[dict[str, Any]] = []
    hard_failures = 0
    _max_hard_fail = int(os.getenv("VLM_MAX_CONSECUTIVE_FAIL", "3"))
    vlm_skipped = False

    for i, img_bytes in enumerate(page_images):
        page_text = page_texts[i] if i < len(page_texts) else {}
        page_layout = layout_pages[i] if i < len(layout_pages) else {}
        regions = page_layout.get("regions") or []

        vlm_result = None

        if vlm_skipped:
            pass
        elif hard_failures >= _max_hard_fail:
            logger.warning("[pass2] %d hard VLM failures — skipping VLM for remaining pages", hard_failures)
            vlm_skipped = True
        else:
            try:
                img_b64 = base64.b64encode(img_bytes).decode("utf-8")

                # Concise region hint from LayoutLM
                region_types = ", ".join(set(r.get("type", "?") for r in regions[:10])) or "none"

                prompt = (
                    f"Page {i + 1}/{total_pages} of \"{doc_title}\".\n"
                    f"Detected layout regions: {region_types}\n\n"
                    "List ALL entities/concepts on this page (organizations, metrics, "
                    "demographics, time periods, locations). Identify the page structure. "
                    "Output ONLY this compact JSON:\n"
                    '{"entities":["entity1","entity2"],'
                    '"structure_type":"data_table|chart_page|narrative|title_page|appendix|mixed",'
                    '"description":"one-line summary",'
                    '"chart_types":["bar","line","pie"]}\n'
                    "Keep entities as short names. JSON only, no explanation."
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
                    "max_tokens": 256,
                }

                r = requests.post(endpoint, json=payload, timeout=timeout)
                if r.status_code == 200:
                    raw = r.json()["choices"][0]["message"]["content"].strip()
                    vlm_result = _extract_json_from_response(raw)
                    if vlm_result:
                        hard_failures = 0
                        logger.debug("[pass2] Page %d VLM OK — %d entities", i,
                                     len(vlm_result.get("entities") or []))
                    else:
                        logger.info("[pass2] Page %d VLM returned text but no valid JSON", i)
                elif r.status_code >= 500:
                    logger.warning("[pass2] Page %d VLM returned %d (hard failure)", i, r.status_code)
                    hard_failures += 1
                else:
                    logger.debug("[pass2] Page %d VLM returned %d", i, r.status_code)
                    hard_failures += 1
            except (requests.ConnectionError, requests.Timeout) as exc:
                logger.warning("[pass2] Page %d connection failed: %s", i, type(exc).__name__)
                hard_failures += 1
            except Exception as exc:
                logger.warning("[pass2] Page %d error: %s", i, exc)
                hard_failures += 1

        # Build result — merge VLM entities with pdfplumber entities
        pdfplumber_entities = _entities_from_pdfplumber(page_text, i)

        if vlm_result:
            vlm_entities = vlm_result.get("entities") or []
            # Normalize: VLM returns list of strings
            vlm_entity_names = [str(e).strip() for e in vlm_entities if isinstance(e, str) and e.strip()]
            # Merge: VLM + pdfplumber, dedup by lowered name
            seen_lower: set[str] = set()
            merged_entities: list[dict[str, Any]] = []
            for name in vlm_entity_names:
                key = name.lower().strip()
                if key not in seen_lower and len(key) > 1:
                    seen_lower.add(key)
                    merged_entities.append({"name": name, "source": "vlm", "page": i})
            for ent in pdfplumber_entities:
                key = ent["name"].lower().strip()
                if key not in seen_lower and len(key) > 1:
                    seen_lower.add(key)
                    merged_entities.append(ent)

            results.append({
                "page_index": i,
                "entities": merged_entities,
                "structure_type": vlm_result.get("structure_type", "mixed"),
                "description": str(vlm_result.get("description", ""))[:200],
                "chart_types": vlm_result.get("chart_types") or [],
                "vlm_used": True,
            })
        else:
            # Fallback: pdfplumber only
            has_tables = bool(page_text.get("tables"))
            has_charts = any(r.get("type") in ("chart", "figure") for r in regions)
            if has_tables and has_charts:
                stype = "mixed"
            elif has_tables:
                stype = "data_table"
            elif has_charts:
                stype = "chart_page"
            else:
                stype = "narrative"

            results.append({
                "page_index": i,
                "entities": pdfplumber_entities,
                "structure_type": stype,
                "description": "",
                "chart_types": [],
                "vlm_used": False,
            })

        if (i + 1) % 5 == 0 or i == total_pages - 1:
            logger.info("[pass2]   processed %d/%d pages (vlm_ok=%d)", i + 1, total_pages,
                        sum(1 for r in results if r.get("vlm_used")))

    elapsed = time.monotonic() - t0
    total_entities = sum(len(r.get("entities") or []) for r in results)
    logger.info("[pass2] ✓ Extracted %d entities from %d pages (%.1fs)", total_entities, len(results), elapsed)
    return results


def _entities_from_pdfplumber(page_text: dict[str, Any], page_index: int) -> list[dict[str, Any]]:
    """Extract entity candidates from pdfplumber data (headings + table headers + bold words).

    Priority: table headers > headings > bold/large words.
    """
    entities: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(name: str, source: str):
        key = name.lower().strip()
        if key and key not in seen and len(key) > 1:
            seen.add(key)
            entities.append({"name": name.strip(), "source": source, "page": page_index})

    # Priority 1: Table headers (most reliable entity source for govt reports)
    for table in (page_text.get("tables") or []):
        if table and len(table) >= 1 and table[0]:
            for cell in table[0]:
                cell_str = str(cell or "").strip()
                if cell_str and len(cell_str) > 1 and len(cell_str) < 80:
                    _add(cell_str, "table_header")

    # Priority 2: Headings
    for h in (page_text.get("headings") or []):
        if isinstance(h, str) and h.strip():
            _add(h.strip(), "heading")

    # Priority 3: Bold / large font words
    for w in (page_text.get("words") or []):
        font_size = w.get("size", 0)
        font_name = str(w.get("fontname", ""))
        text = str(w.get("text", "")).strip()
        if (font_size >= 12 or "Bold" in font_name) and text and len(text) > 2 and len(text) < 60:
            _add(text, "bold_word")

    return entities


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2.5: Document Knowledge Graph (PROGRAMMATIC — no LLM)
# ─────────────────────────────────────────────────────────────────────────────

def pass2_5_document_knowledge_graph(
    entity_pages: list[dict[str, Any]],
    layout_pages: list[dict[str, Any]],
    page_texts: list[dict[str, Any]],
    toc: list[ToCEntry],
    doc_title: str = "Document",
) -> dict[str, Any]:
    """Build a complete Document Knowledge Graph programmatically (no LLM).

    Steps:
        1. Entity collection + dedup from 4 sources (pdfplumber headers priority)
        2. Table structure analysis (columns → dimensions/measures/breakdowns)
        3. Chapter/section hierarchy from ToC
        4. Entity relationship detection (co-occurrence, prefix patterns)
        5. Per-page unique context script generation
        6. MoSPI section pattern detection

    Returns:
        document_map: {
            title, page_count,
            chapters: [{chapterId, title, pageRange, sections[]}],
            all_entities: [{entityId, name, source, pages[], entityType_hint}],
            table_structures: [{tableId, page, columns, dimensions[], measures[], breakdowns[], layout}],
            entity_relationships: [{from, to, relation}],
            section_patterns: [{sectionId, pattern, components[]}],
            per_page_context_scripts: [str per page],
        }
    """
    logger.info("[pass2.5] ▶ Building Document Knowledge Graph")
    t0 = time.monotonic()
    total_pages = max(len(entity_pages), len(page_texts))

    # ── Step 1: Entity Collection + Dedup ──
    entity_index: dict[str, dict[str, Any]] = {}  # key=lowered name → entity dict

    def _register_entity(name: str, source: str, page: int, priority: int):
        key = name.lower().strip()
        if not key or len(key) <= 1:
            return
        if key in entity_index:
            ent = entity_index[key]
            if page not in ent["pages"]:
                ent["pages"].append(page)
            # Upgrade source if higher priority
            if priority < ent["_priority"]:
                ent["source"] = source
                ent["_priority"] = priority
        else:
            entity_index[key] = {
                "entityId": f"ent_{len(entity_index) + 1:03d}",
                "name": name.strip(),
                "source": source,
                "pages": [page],
                "_priority": priority,
            }

    # Source 1 (priority 0): pdfplumber table headers — most reliable
    for i, pt in enumerate(page_texts):
        for table in (pt.get("tables") or []):
            if table and len(table) >= 1 and table[0]:
                for cell in table[0]:
                    cell_str = str(cell or "").strip()
                    if cell_str and 1 < len(cell_str) < 80:
                        _register_entity(cell_str, "table_header", i, 0)

    # Source 2 (priority 1): LayoutLM heading region text
    for i, page in enumerate(layout_pages or []):
        for region in (page.get("regions") or []):
            if region.get("type") in ("heading", "title"):
                text = (region.get("text") or "").strip()
                if text and 2 < len(text) < 120:
                    _register_entity(text, "heading", i, 1)

    # Source 3 (priority 2): VLM-extracted entities
    for ep in entity_pages:
        page_idx = ep.get("page_index", 0)
        for ent in (ep.get("entities") or []):
            name = ent.get("name", "") if isinstance(ent, dict) else str(ent)
            if name.strip():
                _register_entity(name, "vlm", page_idx, 2)

    # Source 4 (priority 3): pdfplumber bold/large font words
    for i, pt in enumerate(page_texts):
        for w in (pt.get("words") or []):
            font_size = w.get("size", 0)
            font_name = str(w.get("fontname", ""))
            text = str(w.get("text", "")).strip()
            if (font_size >= 12 or "Bold" in font_name) and 2 < len(text) < 60:
                _register_entity(text, "bold_word", i, 3)

    # Finalize entities
    all_entities = []
    for ent in entity_index.values():
        del ent["_priority"]
        all_entities.append(ent)

    logger.info("[pass2.5]   Step 1: %d unique entities from %d pages", len(all_entities), total_pages)

    # ── Step 2: Table Structure Analysis ──
    table_structures: list[dict[str, Any]] = []
    for i, pt in enumerate(page_texts):
        for t_idx, table in enumerate(pt.get("tables") or []):
            if not table or len(table) < 2:
                continue
            headers = [str(c or "").strip() for c in table[0]] if table[0] else []
            if not headers or len(headers) < 2:
                continue

            # Classify columns: dimension vs measure vs breakdown
            dimensions: list[str] = []
            measures: list[str] = []
            breakdowns: list[dict[str, str]] = []

            # Analyze data rows to infer column types
            data_rows = table[1:min(6, len(table))]  # sample up to 5 data rows
            for col_idx, header in enumerate(headers):
                if not header:
                    continue
                # Check if column values are mostly numeric
                numeric_count = 0
                text_count = 0
                for row in data_rows:
                    if col_idx < len(row):
                        val = str(row[col_idx] or "").strip().replace(",", "").replace("%", "")
                        try:
                            float(val)
                            numeric_count += 1
                        except (ValueError, TypeError):
                            if val:
                                text_count += 1

                if numeric_count > text_count:
                    measures.append(header)
                else:
                    dimensions.append(header)

            # Detect breakdowns: repeated prefix + qualifier (e.g., "LFPR Male", "LFPR Female")
            import re as _re
            prefix_groups: dict[str, list[str]] = {}
            for h in headers:
                # Split on last space to get potential prefix
                parts = h.rsplit(" ", 1)
                if len(parts) == 2 and len(parts[0]) > 2:
                    prefix_groups.setdefault(parts[0], []).append(parts[1])

            for prefix, qualifiers in prefix_groups.items():
                if len(qualifiers) >= 2:
                    breakdowns.append({
                        "measure": prefix,
                        "breakdown_by": "qualifier",
                        "values": qualifiers,
                    })

            # Detect layout type
            if breakdowns:
                layout_type = "cross_tabulation"
            elif len(dimensions) >= 2:
                layout_type = "multi_dimension"
            else:
                layout_type = "simple"

            table_structures.append({
                "tableId": f"tbl_{i + 1}_{t_idx + 1}",
                "page": i,
                "columns": headers,
                "dimensions": dimensions,
                "measures": measures,
                "breakdowns": breakdowns,
                "layout": layout_type,
                "row_count": len(table) - 1,
                "description": f"Table with {len(headers)} columns, {len(table) - 1} rows",
            })

    # Also try borderless table detection via text heuristics on pages with no pdfplumber tables
    for i, pt in enumerate(page_texts):
        if any(ts["page"] == i for ts in table_structures):
            continue  # already have a table for this page
        # Check if LayoutLM detected a table region
        has_layout_table = False
        if i < len(layout_pages):
            has_layout_table = any(r.get("type") == "table" for r in (layout_pages[i].get("regions") or []))

        if has_layout_table or (entity_pages[i].get("structure_type") == "data_table" if i < len(entity_pages) else False):
            parsed = _extract_table_from_text(pt.get("raw_text") or "")
            if parsed and parsed["row_count"] >= 3:
                table_structures.append({
                    "tableId": f"tbl_{i + 1}_h1",
                    "page": i,
                    "columns": parsed["columns"],
                    "dimensions": [],
                    "measures": [],
                    "breakdowns": [],
                    "layout": "simple",
                    "row_count": parsed["row_count"],
                    "description": "Table detected from text heuristics",
                })

    logger.info("[pass2.5]   Step 2: %d table structures analyzed", len(table_structures))

    # ── Step 3: Chapter/Section Hierarchy ──
    chapters: list[dict[str, Any]] = []
    current_chapter: dict[str, Any] | None = None

    for entry in toc:
        if entry.level == 1:
            # New chapter
            if current_chapter:
                chapters.append(current_chapter)
            current_chapter = {
                "chapterId": f"ch_{len(chapters) + 1:02d}",
                "title": entry.title,
                "pageRange": [entry.page_index, entry.page_index],
                "sections": [],
            }
        elif entry.level >= 2 and current_chapter:
            current_chapter["sections"].append({
                "sectionId": f"sec_{len(chapters) + 1:02d}_{len(current_chapter['sections']) + 1:02d}",
                "title": entry.title,
                "page": entry.page_index,
                "level": entry.level,
            })
            # Extend chapter page range
            current_chapter["pageRange"][1] = max(current_chapter["pageRange"][1], entry.page_index)
        elif entry.level == 1 or (entry.level >= 2 and not current_chapter):
            current_chapter = {
                "chapterId": f"ch_{len(chapters) + 1:02d}",
                "title": entry.title,
                "pageRange": [entry.page_index, entry.page_index],
                "sections": [],
            }

    if current_chapter:
        # Extend last chapter to end of document
        current_chapter["pageRange"][1] = max(current_chapter["pageRange"][1], total_pages - 1)
        chapters.append(current_chapter)

    # If no ToC found, create a single chapter for the whole document
    if not chapters:
        chapters.append({
            "chapterId": "ch_01",
            "title": doc_title,
            "pageRange": [0, total_pages - 1],
            "sections": [],
        })

    logger.info("[pass2.5]   Step 3: %d chapters from ToC", len(chapters))

    # ── Step 4: Entity Relationship Detection ──
    entity_relationships: list[dict[str, str]] = []

    # Co-occurrence: entities appearing on same page in tables
    for ts in table_structures:
        page = ts["page"]
        page_ents = [e for e in all_entities if page in e["pages"]]
        for dim in ts["dimensions"]:
            dim_ent = next((e for e in page_ents if e["name"].lower() == dim.lower()), None)
            for meas in ts["measures"]:
                meas_ent = next((e for e in page_ents if e["name"].lower() == meas.lower()), None)
                if dim_ent and meas_ent:
                    entity_relationships.append({
                        "from": dim_ent["entityId"],
                        "to": meas_ent["entityId"],
                        "relation": "dimension_of",
                    })

    # Prefix-based: same prefix columns → measure × breakdown
    for ts in table_structures:
        for bd in ts.get("breakdowns") or []:
            entity_relationships.append({
                "from": bd["measure"],
                "to": ", ".join(bd["values"]),
                "relation": "breakdown_by",
            })

    logger.info("[pass2.5]   Step 4: %d entity relationships", len(entity_relationships))

    # ── Step 5: Per-Page Context Script Generation ──
    per_page_context_scripts: list[str] = []

    for i in range(total_pages):
        # Find chapter for this page
        chapter_title = doc_title
        chapter_range = [0, total_pages - 1]
        for ch in chapters:
            if ch["pageRange"][0] <= i <= ch["pageRange"][1]:
                chapter_title = ch["title"]
                chapter_range = ch["pageRange"]
                break

        # Get structure type from pass 2
        stype = "unknown"
        page_desc = ""
        if i < len(entity_pages):
            stype = entity_pages[i].get("structure_type", "unknown")
            page_desc = entity_pages[i].get("description", "")

        # Entities in scope (this page + prior pages in same chapter)
        chapter_entities = [
            e["name"] for e in all_entities
            if any(p >= chapter_range[0] and p <= i for p in e["pages"])
        ][:15]  # cap to avoid overflow

        # Table structures on this page
        page_tables = [ts for ts in table_structures if ts["page"] == i]
        table_desc = ""
        if page_tables:
            t = page_tables[0]
            table_desc = f"Table: {len(t['columns'])} cols ({', '.join(t['dimensions'][:3])}) × ({', '.join(t['measures'][:3])})"

        # Build condensed prior summary
        prior_summary = ""
        if i > chapter_range[0]:
            prior_pages = [ep for ep in entity_pages if chapter_range[0] <= ep.get("page_index", -1) < i]
            prior_types = [ep.get("structure_type", "?") for ep in prior_pages[:5]]
            if prior_types:
                prior_summary = f"Prior: {', '.join(prior_types)}"

        # Coming next
        next_section = ""
        for entry in toc:
            if entry.page_index > i:
                next_section = f"Next: \"{entry.title}\""
                break

        # Assemble context script
        parts = [
            f'[Doc: "{doc_title}" ({total_pages}p)',
            f'Ch: "{chapter_title}" (p{chapter_range[0] + 1}-{chapter_range[1] + 1})',
        ]
        if prior_summary:
            parts.append(prior_summary)
        parts.append(f"This page: {stype}")
        if page_desc:
            parts.append(page_desc)
        if table_desc:
            parts.append(table_desc)
        if chapter_entities:
            parts.append(f"Entities: {', '.join(chapter_entities[:10])}")
        if next_section:
            parts.append(next_section)
        parts.append("]")

        script = ". ".join(parts)
        per_page_context_scripts.append(script[:500])  # hard cap

    logger.info("[pass2.5]   Step 5: %d context scripts generated", len(per_page_context_scripts))

    # ── Step 6: MoSPI Section Pattern Detection ──
    section_patterns: list[dict[str, Any]] = []

    for ch in chapters:
        for sec in ch.get("sections") or [{"sectionId": ch["chapterId"], "title": ch["title"], "page": ch["pageRange"][0]}]:
            sec_page = sec.get("page", ch["pageRange"][0])
            # Gather structure types for pages in this section
            sec_end = total_pages - 1
            # Find next section's page
            for s2 in ch.get("sections") or []:
                if s2.get("page", 0) > sec_page:
                    sec_end = s2["page"] - 1
                    break

            sec_types = []
            for ep in entity_pages:
                if sec_page <= ep.get("page_index", -1) <= sec_end:
                    sec_types.append(ep.get("structure_type", "unknown"))

            has_tables = any(ts["page"] >= sec_page and ts["page"] <= sec_end for ts in table_structures)
            has_charts = "chart_page" in sec_types or "mixed" in sec_types
            mostly_text = all(t in ("narrative", "title_page") for t in sec_types) if sec_types else True

            # Pattern matching
            if mostly_text and not has_tables:
                pattern = "executive_summary"
                components = ["narrative_paragraph", "metric_card"]
            elif has_charts and has_tables:
                pattern = "trend_analysis"
                components = ["narrative_paragraph", "line_chart", "data_table"]
            elif has_tables and len([ts for ts in table_structures if sec_page <= ts["page"] <= sec_end]) >= 2:
                pattern = "state_comparison"
                components = ["narrative_paragraph", "data_table", "grouped_bar_chart"]
            elif has_tables:
                pattern = "demographic_breakdown"
                components = ["narrative_paragraph", "data_table", "pie_chart"]
            else:
                pattern = "descriptive"
                components = ["narrative_paragraph"]

            section_patterns.append({
                "sectionId": sec.get("sectionId", ch["chapterId"]),
                "title": sec.get("title", ch["title"]),
                "pageRange": [sec_page, sec_end],
                "pattern": pattern,
                "suggested_components": components,
            })

    logger.info("[pass2.5]   Step 6: %d section patterns detected", len(section_patterns))

    # ── Assemble Document Knowledge Graph ──
    document_map = {
        "title": doc_title,
        "page_count": total_pages,
        "chapters": chapters,
        "all_entities": all_entities,
        "table_structures": table_structures,
        "entity_relationships": entity_relationships,
        "section_patterns": section_patterns,
        "per_page_context_scripts": per_page_context_scripts,
    }

    elapsed = time.monotonic() - t0
    logger.info(
        "[pass2.5] ✓ Document KG built: %d entities, %d tables, %d chapters, "
        "%d patterns, %d context scripts (%.1fs)",
        len(all_entities), len(table_structures), len(chapters),
        len(section_patterns), len(per_page_context_scripts), elapsed,
    )
    return document_map


def _split_text_into_paragraphs(text: str) -> list[str]:
    """Split raw text into paragraphs at double newlines or large gaps."""
    import re
    # Split on double newlines, or single newline followed by indent
    paragraphs = re.split(r'\n\s*\n', text)
    # Filter empty
    return [p.strip() for p in paragraphs if p.strip() and len(p.strip()) > 20]


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


def _extract_table_from_text(raw_text: str) -> dict | None:
    """Detect and extract tabular data from raw text using heuristics.

    Looks for:
        - Lines with consistent multi-space or tab separators
        - Numeric columns aligned vertically
        - Header row followed by data rows

    Returns:
        {"columns": [...], "rows": [{col: val, ...}], "row_count": N} or None
    """
    import re

    if not raw_text or len(raw_text) < 20:
        return None

    lines = raw_text.strip().split("\n")
    if len(lines) < 3:
        return None

    # Strategy 1: Tab-separated lines
    tab_lines = [l for l in lines if "\t" in l]
    if len(tab_lines) >= 3:
        cells_per_line = [l.split("\t") for l in tab_lines]
        # Check consistency (all rows have similar column count)
        col_counts = [len(c) for c in cells_per_line]
        mode_cols = max(set(col_counts), key=col_counts.count)
        if mode_cols >= 2:
            consistent = [c for c in cells_per_line if len(c) == mode_cols]
            if len(consistent) >= 2:
                headers = [h.strip() for h in consistent[0]]
                rows = []
                for row_cells in consistent[1:]:
                    rows.append({
                        headers[k] if k < len(headers) and headers[k] else f"col_{k}": v.strip()
                        for k, v in enumerate(row_cells)
                    })
                return {"columns": headers, "rows": rows, "row_count": len(rows)}

    # Strategy 2: Multi-space separated (2+ spaces as delimiter)
    multi_space_lines = []
    for line in lines:
        # Skip very short lines or lines that look like headings
        if len(line.strip()) < 10:
            continue
        # Check if line has 2+ segments separated by 2+ spaces
        parts = re.split(r"  {2,}", line.strip())
        if len(parts) >= 3:
            multi_space_lines.append(parts)

    if len(multi_space_lines) >= 3:
        # Check column count consistency
        col_counts = [len(p) for p in multi_space_lines]
        mode_cols = max(set(col_counts), key=col_counts.count)
        if mode_cols >= 3:
            consistent = [p for p in multi_space_lines if len(p) == mode_cols]
            if len(consistent) >= 3:
                # First consistent row is likely the header
                headers = [h.strip() for h in consistent[0]]
                rows = []
                for row_parts in consistent[1:]:
                    rows.append({
                        headers[k] if k < len(headers) and headers[k] else f"col_{k}": v.strip()
                        for k, v in enumerate(row_parts)
                    })
                return {"columns": headers, "rows": rows, "row_count": len(rows)}

    # Strategy 3: Lines with numbers that look like data rows
    # (common in government statistical reports)
    numeric_lines = []
    for line in lines:
        # Count number-like tokens in the line
        tokens = line.split()
        if len(tokens) >= 3:
            num_count = sum(1 for t in tokens if re.match(r'^[\d,.\-+%]+$', t.strip()))
            if num_count >= 2 and num_count / len(tokens) >= 0.4:
                numeric_lines.append(tokens)

    if len(numeric_lines) >= 3:
        # Find the most common token count
        token_counts = [len(t) for t in numeric_lines]
        mode_tokens = max(set(token_counts), key=token_counts.count)
        consistent = [t for t in numeric_lines if len(t) == mode_tokens]
        if len(consistent) >= 3:
            # Try to find a header line just before the first numeric line
            first_num_idx = None
            for idx, line in enumerate(lines):
                tokens = line.split()
                if len(tokens) >= 3:
                    num_count = sum(1 for t in tokens if re.match(r'^[\d,.\-+%]+$', t.strip()))
                    if num_count >= 2 and num_count / len(tokens) >= 0.4:
                        first_num_idx = idx
                        break

            headers = []
            if first_num_idx and first_num_idx > 0:
                header_line = lines[first_num_idx - 1]
                header_tokens = re.split(r"  {2,}|\t", header_line.strip())
                if len(header_tokens) >= 2:
                    headers = [h.strip() for h in header_tokens]

            if not headers:
                headers = [f"col_{k}" for k in range(mode_tokens)]

            rows = []
            for row_tokens in consistent[:10]:  # Cap at 10 rows
                row_dict = {}
                for k, v in enumerate(row_tokens):
                    col_name = headers[k] if k < len(headers) else f"col_{k}"
                    row_dict[col_name] = v.strip()
                rows.append(row_dict)
            return {"columns": headers, "rows": rows, "row_count": len(rows)}

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Pass 3: Two-Loop AST Building via Qwen-VL
# ─────────────────────────────────────────────────────────────────────────────

def pass3_two_loop_ast_building(
    document_map: dict[str, Any],
    page_texts: list[dict[str, Any]],
    doc_title: str = "Document",
) -> dict[str, Any]:
    """Build questions + entity bindings via two Qwen-VL loops.

    Loop 1: Question extraction per section chunk
        Input: per-page context script + section content summary
        Output: [{questionId, intent, questionType, page, sourceHeading}]

    Loop 2: Entity binding + AnswerStructure per question
        Input: question + full entity list + table structures + section pattern
        Output: [{requiredEntities, answerStructure, inferenceConfidence}]

    Returns:
        {
            "questions": [{questionId, intent, questionType, requiredEntities, answerStructure, ...}],
            "topics": [{topicId, title, questionIds, pageRange}],
        }
    """
    endpoint = _SGLANG_ENDPOINT.rstrip("/") + "/v1/chat/completions"
    model = os.getenv("SGLANG_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct-AWQ")
    timeout = int(os.getenv("SGLANG_TIMEOUT", "120"))

    logger.info("[pass3] ▶ Two-loop AST building via Qwen-VL")
    t0 = time.monotonic()

    chapters = document_map.get("chapters") or []
    all_entities = document_map.get("all_entities") or []
    table_structures = document_map.get("table_structures") or []
    section_patterns = document_map.get("section_patterns") or []
    context_scripts = document_map.get("per_page_context_scripts") or []

    # Pre-flight: check if vLLM is alive
    vlm_alive = False
    try:
        hr = requests.get(_SGLANG_ENDPOINT.rstrip("/") + "/v1/models", timeout=5)
        vlm_alive = hr.status_code == 200
    except Exception:
        pass

    if not vlm_alive:
        logger.warning("[pass3] vLLM not reachable — generating stub questions programmatically")
        return _programmatic_question_fallback(document_map, page_texts)

    # ── Build entity summary for Loop 2 (shared across all questions) ──
    entity_summary = ", ".join(e["name"] for e in all_entities[:30])
    if len(entity_summary) > 300:
        entity_summary = entity_summary[:300] + "..."

    # ═══════════════════════════════════════════════════════════════════
    # LOOP 1: Question Extraction per Section
    # ═══════════════════════════════════════════════════════════════════
    logger.info("[pass3] ── Loop 1: Question extraction ──")
    raw_questions: list[dict[str, Any]] = []
    consecutive_failures = 0

    for sp in section_patterns:
        if consecutive_failures >= 3:
            logger.warning("[pass3] L1: %d consecutive failures — stopping", consecutive_failures)
            break

        sec_title = sp.get("title", "Section")
        page_range = sp.get("pageRange", [0, 0])
        pattern = sp.get("pattern", "descriptive")

        # Get context script for first page of section
        ctx = ""
        if page_range[0] < len(context_scripts):
            ctx = context_scripts[page_range[0]]

        # Build section content summary from page_texts
        section_summary = ""
        for p_idx in range(page_range[0], min(page_range[1] + 1, len(page_texts))):
            pt = page_texts[p_idx]
            # Headings
            for h in (pt.get("headings") or [])[:3]:
                section_summary += f"# {h}\n"
            # Table column hints
            for ts in table_structures:
                if ts["page"] == p_idx:
                    section_summary += f"[Table: {', '.join(ts['columns'][:6])}]\n"
            # Short text preview
            raw = (pt.get("raw_text") or "")[:150]
            if raw:
                section_summary += raw + "\n"

        section_summary = section_summary[:600]  # cap

        prompt = (
            f"{ctx}\n\n"
            f"Section: \"{sec_title}\" (pages {page_range[0] + 1}-{page_range[1] + 1})\n"
            f"Pattern: {pattern}\n"
            f"Content:\n{section_summary}\n\n"
            "What analytical questions does this section answer? "
            "Output JSON array:\n"
            '[{"questionId":"q1","intent":"What is...?","questionType":"comparison|trend|ranking|distribution|describe",'
            '"sourceHeading":"..."}]\n'
            "List 1-4 questions. JSON only."
        )

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 512,
        }

        try:
            r = requests.post(endpoint, json=payload, timeout=timeout)
            if r.status_code == 200:
                raw_content = r.json()["choices"][0]["message"]["content"].strip()
                questions = _extract_json_array_from_response(raw_content)
                if questions:
                    for q in questions:
                        q["page"] = page_range[0]
                        q["sectionId"] = sp.get("sectionId", "")
                        q["sectionPattern"] = pattern
                    raw_questions.extend(questions)
                    consecutive_failures = 0
                    logger.debug("[pass3] L1: %d questions from \"%s\"", len(questions), sec_title)
                else:
                    logger.debug("[pass3] L1: No valid JSON from section \"%s\"", sec_title)
            else:
                logger.debug("[pass3] L1: VLM returned %d for section \"%s\"", r.status_code, sec_title)
                consecutive_failures += 1
        except (requests.ConnectionError, requests.Timeout) as exc:
            logger.warning("[pass3] L1: Connection failed: %s", type(exc).__name__)
            consecutive_failures += 1
        except Exception as exc:
            logger.debug("[pass3] L1: Error: %s", exc)
            consecutive_failures += 1

    logger.info("[pass3] L1: Extracted %d raw questions from %d sections", len(raw_questions), len(section_patterns))

    # If Loop 1 produced nothing, fall back
    if not raw_questions:
        logger.warning("[pass3] L1 produced 0 questions — using programmatic fallback")
        return _programmatic_question_fallback(document_map, page_texts)

    # ═══════════════════════════════════════════════════════════════════
    # LOOP 2: Entity Binding + AnswerStructure per Question
    # ═══════════════════════════════════════════════════════════════════
    logger.info("[pass3] ── Loop 2: Entity binding (%d questions) ──", len(raw_questions))
    enriched_questions: list[dict[str, Any]] = []
    consecutive_failures = 0

    for q in raw_questions:
        if consecutive_failures >= 3:
            logger.warning("[pass3] L2: %d consecutive failures — using pattern defaults for remaining", consecutive_failures)
            # Use pattern-based defaults for remaining questions
            for q_remaining in raw_questions[len(enriched_questions):]:
                enriched_questions.append(_default_question_binding(q_remaining, all_entities, section_patterns))
            break

        q_intent = q.get("intent", "")
        q_type = q.get("questionType", "comparison")
        q_page = q.get("page", 0)
        q_pattern = q.get("sectionPattern", "descriptive")

        # Table structures on relevant pages
        relevant_tables = [ts for ts in table_structures if abs(ts["page"] - q_page) <= 2]
        table_hint = ""
        if relevant_tables:
            t = relevant_tables[0]
            table_hint = (
                f"Table: dims=[{', '.join(t['dimensions'][:5])}], "
                f"measures=[{', '.join(t['measures'][:5])}]"
            )

        prompt = (
            f"Question: \"{q_intent}\"\n"
            f"Type: {q_type}\n"
            f"Available entities: {entity_summary}\n"
            f"{table_hint}\n"
            f"Section pattern: {q_pattern}\n\n"
            "Which entities does this question need and what role does each play? "
            "What components should the answer have?\n"
            "Output JSON:\n"
            '{"requiredEntities":[{"entityRef":"entity_name","role":"groupBy|measure|filter|breakdown"}],'
            '"answerStructure":{"layoutType":"single|split|multi-panel",'
            '"components":[{"type":"narrative_paragraph|data_table|grouped_bar_chart|line_chart|pie_chart|metric_card","renderOrder":1}]},'
            '"confidence":0.8}\n'
            "JSON only."
        )

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 384,
        }

        try:
            r = requests.post(endpoint, json=payload, timeout=timeout)
            if r.status_code == 200:
                raw_content = r.json()["choices"][0]["message"]["content"].strip()
                binding = _extract_json_from_response(raw_content)
                if binding:
                    q.update({
                        "requiredEntities": binding.get("requiredEntities") or [],
                        "answerStructure": binding.get("answerStructure") or {},
                        "inferenceConfidence": float(binding.get("confidence", 0.5)),
                    })
                    enriched_questions.append(q)
                    consecutive_failures = 0
                    logger.debug("[pass3] L2: Bound %d entities to \"%s\"",
                                 len(binding.get("requiredEntities") or []), q_intent[:40])
                else:
                    enriched_questions.append(_default_question_binding(q, all_entities, section_patterns))
            else:
                logger.debug("[pass3] L2: VLM returned %d", r.status_code)
                consecutive_failures += 1
                enriched_questions.append(_default_question_binding(q, all_entities, section_patterns))
        except (requests.ConnectionError, requests.Timeout) as exc:
            logger.warning("[pass3] L2: Connection failed: %s", type(exc).__name__)
            consecutive_failures += 1
            enriched_questions.append(_default_question_binding(q, all_entities, section_patterns))
        except Exception as exc:
            logger.debug("[pass3] L2: Error: %s", exc)
            consecutive_failures += 1
            enriched_questions.append(_default_question_binding(q, all_entities, section_patterns))

    # ── Build topics from chapters ──
    topics: list[dict[str, Any]] = []
    for ch in chapters:
        ch_questions = [
            q for q in enriched_questions
            if ch["pageRange"][0] <= q.get("page", -1) <= ch["pageRange"][1]
        ]
        if ch_questions:
            topics.append({
                "topicId": ch["chapterId"].replace("ch_", "topic_"),
                "title": ch["title"],
                "description": f"Questions from chapter: {ch['title']}",
                "questionIds": [q.get("questionId", f"q_{i}") for i, q in enumerate(ch_questions)],
                "pageRange": ch["pageRange"],
            })

    elapsed = time.monotonic() - t0
    logger.info(
        "[pass3] ✓ Two-loop AST: %d questions in %d topics (%.1fs)",
        len(enriched_questions), len(topics), elapsed,
    )

    return {
        "questions": enriched_questions,
        "topics": topics,
    }


def _extract_json_array_from_response(raw: str) -> list[dict] | None:
    """Extract a JSON array from potentially messy LLM output."""
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # Strip markdown fences
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            inner = parts[1]
            if inner and inner.split("\n", 1)[0].strip().isalpha():
                inner = inner.split("\n", 1)[-1]
            text = inner.strip()

    # Try direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return [item for item in obj if isinstance(item, dict)]
        if isinstance(obj, dict):
            # Maybe it has a "questions" key wrapping the array
            for key in ("questions", "data", "results"):
                if isinstance(obj.get(key), list):
                    return [item for item in obj[key] if isinstance(item, dict)]
            return [obj]
    except json.JSONDecodeError:
        pass

    # Find first [ and try to parse
    bracket_start = text.find("[")
    if bracket_start >= 0:
        candidate = text[bracket_start:]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, list):
                return [item for item in obj if isinstance(item, dict)]
        except json.JSONDecodeError:
            # Try repair
            repaired = _repair_truncated_json(candidate)
            if repaired:
                try:
                    obj = json.loads(repaired)
                    if isinstance(obj, list):
                        return [item for item in obj if isinstance(item, dict)]
                except json.JSONDecodeError:
                    pass

    # Fallback: try extracting a single JSON object
    single = _extract_json_from_response(raw)
    if single:
        return [single]

    return None


def _default_question_binding(
    question: dict[str, Any],
    all_entities: list[dict[str, Any]],
    section_patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate default entity binding + answer structure from pattern when VLM fails."""
    q_type = question.get("questionType", "comparison")
    q_page = question.get("page", 0)
    q_pattern = question.get("sectionPattern", "descriptive")

    # Default entity bindings: first dimension + first measure on same page
    required_entities: list[dict[str, str]] = []
    page_entities = [e for e in all_entities if q_page in e.get("pages", [])]
    table_header_ents = [e for e in page_entities if e.get("source") == "table_header"]
    if table_header_ents:
        # First table header as groupBy, second as measure
        if len(table_header_ents) >= 1:
            required_entities.append({"entityRef": table_header_ents[0]["name"], "role": "groupBy"})
        if len(table_header_ents) >= 2:
            required_entities.append({"entityRef": table_header_ents[1]["name"], "role": "measure"})

    # Default answer structure from section pattern
    pattern_components = {
        "executive_summary": [
            {"type": "narrative_paragraph", "renderOrder": 1},
            {"type": "metric_card", "renderOrder": 2},
        ],
        "trend_analysis": [
            {"type": "narrative_paragraph", "renderOrder": 1},
            {"type": "line_chart", "renderOrder": 2},
            {"type": "data_table", "renderOrder": 3},
        ],
        "state_comparison": [
            {"type": "narrative_paragraph", "renderOrder": 1},
            {"type": "data_table", "renderOrder": 2},
            {"type": "grouped_bar_chart", "renderOrder": 3},
        ],
        "demographic_breakdown": [
            {"type": "narrative_paragraph", "renderOrder": 1},
            {"type": "data_table", "renderOrder": 2},
            {"type": "pie_chart", "renderOrder": 3},
        ],
        "descriptive": [
            {"type": "narrative_paragraph", "renderOrder": 1},
        ],
    }

    components = pattern_components.get(q_pattern, pattern_components["descriptive"])

    question.update({
        "requiredEntities": required_entities,
        "answerStructure": {
            "layoutType": "single" if len(components) <= 2 else "split",
            "components": components,
        },
        "inferenceConfidence": 0.3,
        "inferenceMethod": "pattern",
    })
    return question


def _programmatic_question_fallback(
    document_map: dict[str, Any],
    page_texts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate questions programmatically when VLM is unavailable.

    Uses table structures + section patterns to infer likely questions.
    """
    all_entities = document_map.get("all_entities") or []
    table_structures = document_map.get("table_structures") or []
    section_patterns = document_map.get("section_patterns") or []
    chapters = document_map.get("chapters") or []

    questions: list[dict[str, Any]] = []
    q_counter = 0

    # Generate questions from table structures
    for ts in table_structures:
        dims = ts.get("dimensions") or []
        measures = ts.get("measures") or []
        if not dims and not measures:
            continue

        q_counter += 1
        intent = ""
        q_type = "comparison"

        if dims and measures:
            intent = f"How does {measures[0]} vary across {dims[0]}?"
            q_type = "comparison"
        elif measures:
            intent = f"What is the distribution of {measures[0]}?"
            q_type = "distribution"
        elif dims:
            intent = f"What categories of {dims[0]} are present?"
            q_type = "describe"

        required_entities = []
        if dims:
            required_entities.append({"entityRef": dims[0], "role": "groupBy"})
        if measures:
            required_entities.append({"entityRef": measures[0], "role": "measure"})

        questions.append({
            "questionId": f"q_{q_counter:03d}",
            "intent": intent,
            "questionType": q_type,
            "page": ts["page"],
            "sourceHeading": ts.get("description", ""),
            "requiredEntities": required_entities,
            "answerStructure": {
                "layoutType": "split",
                "components": [
                    {"type": "narrative_paragraph", "renderOrder": 1},
                    {"type": "data_table", "renderOrder": 2},
                    {"type": "grouped_bar_chart", "renderOrder": 3},
                ],
            },
            "inferenceConfidence": 0.3,
            "inferenceMethod": "programmatic",
        })

    # Generate questions from section patterns
    for sp in section_patterns:
        if sp.get("pattern") in ("executive_summary", "descriptive"):
            q_counter += 1
            questions.append({
                "questionId": f"q_{q_counter:03d}",
                "intent": f"What is the summary of {sp['title']}?",
                "questionType": "describe",
                "page": sp["pageRange"][0],
                "sourceHeading": sp["title"],
                "requiredEntities": [],
                "answerStructure": {
                    "layoutType": "single",
                    "components": [
                        {"type": "narrative_paragraph", "renderOrder": 1},
                    ],
                },
                "inferenceConfidence": 0.2,
                "inferenceMethod": "programmatic",
            })

    # Build topics
    topics: list[dict[str, Any]] = []
    for ch in chapters:
        ch_questions = [
            q for q in questions
            if ch["pageRange"][0] <= q.get("page", -1) <= ch["pageRange"][1]
        ]
        if ch_questions:
            topics.append({
                "topicId": ch["chapterId"].replace("ch_", "topic_"),
                "title": ch["title"],
                "description": f"Programmatic questions from: {ch['title']}",
                "questionIds": [q["questionId"] for q in ch_questions],
                "pageRange": ch["pageRange"],
            })

    logger.info("[pass3] ✓ Programmatic fallback: %d questions in %d topics", len(questions), len(topics))
    return {"questions": questions, "topics": topics}


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
# Pass 4: AST Assembly + Embedded Blueprint
# ─────────────────────────────────────────────────────────────────────────────

def pass4_assemble_ast(
    layout_pages: list[dict[str, Any]],
    page_texts: list[dict[str, Any]],
    document_map: dict[str, Any],
    ast_result: dict[str, Any],
    doc_title: str = "Document",
    source_hash: str = "",
) -> dict[str, Any]:
    """Assemble Enterprise AST + embedded blueprint subtree.

    Merges all extraction passes into the final output:
        - layoutAST, geometryAST from Pass 1
        - contentAST (paragraphs from pdfplumber text, typed by LayoutLM regions)
        - tableAST (table structures from Pass 2.5, NOT values)
        - semanticAST (hierarchy from Pass 2.5 chapters)
        - entityGraph (merged entities)
        - blueprint subtree: TopicNode → QuestionNode → AnswerStructure → AnswerComponent
    """
    logger.info("[pass4] ▶ Assembling Enterprise AST + Blueprint")

    chapters = document_map.get("chapters") or []
    all_entities = document_map.get("all_entities") or []
    table_structures = document_map.get("table_structures") or []
    questions = ast_result.get("questions") or []
    topics_raw = ast_result.get("topics") or []
    page_count = len(page_texts)

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

    # ── contentAST (from pdfplumber text, typed by LayoutLM regions) ──
    paragraphs = []
    for i, pt in enumerate(page_texts):
        regions = (layout_pages[i].get("regions") or []) if i < len(layout_pages) else []

        # Create paragraphs from heading regions
        for h_idx, region in enumerate(regions):
            if region.get("type") in ("heading", "title"):
                text = (region.get("text") or "").strip()
                if text:
                    paragraphs.append({
                        "id": f"p_{i + 1:03d}_h{h_idx + 1:02d}",
                        "type": region["type"],
                        "content": text[:500],
                        "pageRef": f"page_{i + 1:03d}",
                        "source": "layoutlm",
                    })

        # Create paragraphs from text regions
        text_regions = [r for r in regions if r.get("type") in ("text", "paragraph")]
        if text_regions:
            for t_idx, region in enumerate(text_regions[:10]):
                text = (region.get("text") or "").strip()
                if text and len(text) > 10:
                    paragraphs.append({
                        "id": f"p_{i + 1:03d}_t{t_idx + 1:02d}",
                        "type": "paragraph",
                        "content": text[:2000],
                        "pageRef": f"page_{i + 1:03d}",
                        "source": "layoutlm",
                    })
        else:
            # Fallback: pdfplumber raw text
            raw = (pt.get("raw_text") or "").strip()
            if raw:
                paragraphs.append({
                    "id": f"p_{i + 1:03d}",
                    "type": "paragraph",
                    "content": raw[:2000],
                    "pageRef": f"page_{i + 1:03d}",
                    "source": "pdfplumber-fallback",
                })

    # ── tableAST (STRUCTURE only, from Pass 2.5 — no values) ──
    tables = []
    for ts in table_structures:
        tables.append({
            "tableId": ts["tableId"],
            "title": ts.get("description", f"Table on page {ts['page'] + 1}"),
            "pageRef": f"page_{ts['page'] + 1:03d}",
            "columns": ts["columns"],
            "dimensions": ts.get("dimensions") or [],
            "measures": ts.get("measures") or [],
            "breakdowns": ts.get("breakdowns") or [],
            "layout": ts.get("layout", "simple"),
            "rowCount": ts.get("row_count", 0),
            "source": "pdfplumber",
        })

    # ── figureAST + chartAST ──
    figures = []
    charts = []
    for i, page in enumerate(layout_pages or []):
        for j, region in enumerate(page.get("regions") or []):
            if region.get("type") == "chart":
                charts.append({
                    "chartId": f"chart_{i + 1}_{j + 1}",
                    "type": "chart",
                    "title": (region.get("text") or "")[:200],
                    "pageRef": f"page_{i + 1:03d}",
                })
            elif region.get("type") == "figure":
                figures.append({
                    "figureId": f"fig_{i + 1}_{j + 1}",
                    "caption": (region.get("text") or "")[:200],
                    "description": "",
                    "pageRef": f"page_{i + 1:03d}",
                })

    # ── semanticAST (from chapter hierarchy) ──
    semantic_hierarchy = []
    for ch in chapters:
        node = {
            "nodeId": ch["chapterId"],
            "level": 1,
            "title": ch["title"],
            "pageSpan": ch["pageRange"],
            "children": [],
        }
        for sec in ch.get("sections") or []:
            node["children"].append({
                "nodeId": sec["sectionId"],
                "level": sec.get("level", 2),
                "title": sec["title"],
                "pageSpan": [sec.get("page", 0), sec.get("page", 0)],
            })
        semantic_hierarchy.append(node)

    # ── entityGraph (with type hints from table structure analysis) ──
    entity_graph_entries = []
    for ent in all_entities:
        # Infer entityType hint from table structure
        entity_type = "dimension"  # default
        for ts in table_structures:
            if ent["name"] in ts.get("measures", []):
                entity_type = "measure"
                break
            if ent["name"] in ts.get("dimensions", []):
                entity_type = "dimension"
                break

        entity_graph_entries.append({
            "entityId": ent["entityId"],
            "name": ent["name"],
            "entityType": entity_type,
            "sourceType": ent.get("source", "unknown"),
            "confidence": 0.8 if ent.get("source") == "table_header" else 0.5,
            "pages": ent.get("pages", []),
        })

    # ══════════════════════════════════════════════════════════════════
    # BLUEPRINT SUBTREE — the key output for orchestrator.py
    # ══════════════════════════════════════════════════════════════════

    # Build TopicNode → QuestionNode hierarchy
    blueprint_topics = []
    for topic_raw in topics_raw:
        topic_questions = []
        for q in questions:
            q_id = q.get("questionId", "")
            if q_id in (topic_raw.get("questionIds") or []):
                # Build AnswerComponent list
                answer_components = []
                ans_struct = q.get("answerStructure") or {}
                for c_idx, comp in enumerate(ans_struct.get("components") or []):
                    answer_components.append({
                        "componentId": f"{q_id}_c{c_idx + 1}",
                        "renderOrder": comp.get("renderOrder", c_idx + 1),
                        "type": comp.get("type", "narrative_paragraph"),
                        "constraints": comp.get("constraints") or {},
                        "refs": {},
                    })

                # Build entity bindings
                entity_bindings = []
                for eb in (q.get("requiredEntities") or []):
                    # Resolve entityRef to entityId
                    ref_name = eb.get("entityRef", "")
                    matched_ent = next(
                        (e for e in all_entities if e["name"].lower() == ref_name.lower()),
                        None,
                    )
                    entity_bindings.append({
                        "entityId": matched_ent["entityId"] if matched_ent else ref_name,
                        "role": eb.get("role", "required"),
                        "confidence": 0.7,
                        "bindingMethod": q.get("inferenceMethod", "vlm"),
                    })

                topic_questions.append({
                    "questionId": q_id,
                    "intent": q.get("intent", ""),
                    "questionType": q.get("questionType", "comparison"),
                    "inferenceMethod": q.get("inferenceMethod", "vlm"),
                    "inferenceConfidence": q.get("inferenceConfidence", 0.5),
                    "requiredEntities": entity_bindings,
                    "answerStructure": {
                        "layoutType": ans_struct.get("layoutType", "single"),
                        "components": answer_components,
                    },
                    "pageIndex": q.get("page", -1),
                    "sourceHeading": q.get("sourceHeading", ""),
                    "priority": "high" if q.get("inferenceConfidence", 0) > 0.7 else "medium",
                })

        if topic_questions:
            blueprint_topics.append({
                "topicId": topic_raw["topicId"],
                "title": topic_raw.get("title", ""),
                "description": topic_raw.get("description", ""),
                "questions": topic_questions,
                "pageRange": topic_raw.get("pageRange", []),
            })

    # Build TemplateEntity list for blueprint
    blueprint_entities = []
    for ent in entity_graph_entries:
        blueprint_entities.append({
            "entityId": ent["entityId"],
            "name": ent["name"],
            "entityType": ent["entityType"],
            "sourceType": ent["sourceType"],
            "confidence": ent["confidence"],
            "aliases": [],
            "pageIndex": ent["pages"][0] if ent.get("pages") else -1,
            "sourceContext": "",
            "scope": "global",
            "crossRefs": [],
        })

    blueprint = {
        "topics": blueprint_topics,
        "entities": blueprint_entities,
        "tableStructures": [ts for ts in table_structures],
        "documentMap": {
            "title": doc_title,
            "chapters": chapters,
            "sectionPatterns": document_map.get("section_patterns") or [],
        },
    }

    # ── extracted_assets (text per page for frontend) ──
    text_pages = []
    for i, pt in enumerate(page_texts):
        text_pages.append({
            "page_index": i,
            "text": (pt.get("raw_text") or "")[:5000],
        })

    # ── Assemble final AST ──
    ast = {
        "metadata": {
            "documentId": f"doc_{source_hash[:8]}" if source_hash else "doc_001",
            "title": doc_title,
            "pageCount": page_count,
            "checksum": source_hash,
            "extractionMethod": "layoutlm+qwen-vl+knowledge-graph+two-loop",
            "version": "3.0",
        },
        "layoutAST": {"pages": layout_ast_pages},
        "styleAST": {"styles": []},
        "geometryAST": {"nodes": geometry_nodes},
        "assetAST": {"assets": []},
        "annotationAST": {"headers": [], "footers": [], "footnotes": []},
        "semanticAST": {"hierarchy": semantic_hierarchy},
        "contentAST": {"paragraphs": paragraphs, "lists": [], "quotes": []},
        "tableAST": {"tables": tables},
        "figureAST": {"figures": figures},
        "chartAST": {"charts": charts},
        "entityGraph": {"entities": entity_graph_entries},
        "knowledgeGraph": {"concepts": [], "relationships": document_map.get("entity_relationships") or []},
        "factGraph": {"facts": []},
        "templateSlots": {"slots": []},
        "questions": [q.get("intent", "") for q in questions],
        "blueprint": blueprint,
        "extracted_assets": {"text_pages": text_pages, "tables": tables, "images": []},
    }

    logger.info(
        "[pass4] ✓ AST assembled: %d layout pages, %d paragraphs, %d tables, "
        "%d figures, %d charts, %d entities, %d topics, %d questions",
        len(layout_ast_pages), len(paragraphs), len(tables),
        len(figures), len(charts),
        len(entity_graph_entries),
        len(blueprint_topics),
        sum(len(t["questions"]) for t in blueprint_topics),
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
    """Run the complete 7-pass extraction pipeline.

    Pass 0: Rasterize PDF
    Pass 1: LayoutLM layout detection
    Pass 2: Entity + structure extraction (Qwen-VL, 50-150 tokens/page)
    Pass 2.5: Document Knowledge Graph (programmatic)
    Pass 3: Two-loop AST building (questions + entity bindings)
    Pass 4: Enterprise AST + blueprint assembly
    Pass 5: Optional Gemini enhancement

    Returns:
        Enterprise Document AST dict with embedded blueprint subtree.
    """
    import time as _time

    def _tick(stage: str, pct: int, data: Any = None):
        if progress_callback:
            progress_callback(stage, pct, data)

    pipeline_trace: dict[str, Any] = {"passes": {}, "total_elapsed": 0}
    pipeline_start = _time.monotonic()

    logger.info("═══════════════════════════════════════════════════════════")
    logger.info("  Multi-Pass Extraction Pipeline v3.0")
    logger.info("  File: %s", pdf_path.name)
    logger.info("═══════════════════════════════════════════════════════════")

    # ── Pass 0: Rasterize ──
    _tick("pass0_rasterization", 5)
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

    # Ensure page_texts covers all images
    while len(page_texts) < len(page_images):
        page_texts.append({"raw_text": "", "words": [], "tables": [], "headings": [], "width": 595, "height": 842, "word_count": 0})

    # ── Pass 1: Layout Detection ──
    _tick("pass1_layout_detection", 15)
    t0 = _time.monotonic()
    layout_pages = pass1_layout_detection(pdf_path)
    pass1_elapsed = _time.monotonic() - t0

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

    # ── Pass 2: Entity + Structure Extraction ──
    _tick("pass2_entity_extraction", 30)
    t0 = _time.monotonic()
    entity_pages = pass2_entity_structure_extraction(page_images, layout_pages, page_texts, doc_title)
    pass2_elapsed = _time.monotonic() - t0

    vlm_success = sum(1 for p in entity_pages if p.get("vlm_used"))
    total_entities = sum(len(p.get("entities") or []) for p in entity_pages)
    pipeline_trace["passes"]["pass2_entities"] = {
        "elapsed_s": round(pass2_elapsed, 1),
        "pages_total": len(entity_pages),
        "vlm_success": vlm_success,
        "total_entities": total_entities,
    }

    # ── Pass 2.5: Document Knowledge Graph ──
    _tick("pass2_5_knowledge_graph", 45)
    t0 = _time.monotonic()
    document_map = pass2_5_document_knowledge_graph(entity_pages, layout_pages, page_texts, toc, doc_title)
    pass25_elapsed = _time.monotonic() - t0

    pipeline_trace["passes"]["pass2_5_kg"] = {
        "elapsed_s": round(pass25_elapsed, 1),
        "entities": len(document_map.get("all_entities") or []),
        "table_structures": len(document_map.get("table_structures") or []),
        "chapters": len(document_map.get("chapters") or []),
        "section_patterns": len(document_map.get("section_patterns") or []),
    }

    # ── Pass 3: Two-Loop AST Building ──
    _tick("pass3_ast_building", 60)
    t0 = _time.monotonic()
    ast_result = pass3_two_loop_ast_building(document_map, page_texts, doc_title)
    pass3_elapsed = _time.monotonic() - t0

    # If both loops produced nothing, try Gemini fallback
    if not ast_result.get("questions"):
        logger.info("[pipeline] Pass 3 produced 0 questions — trying Gemini fallback")
        t0_fb = _time.monotonic()
        gemini_result = _gemini_semantic_fallback(document_map, toc, doc_title)
        pass3_elapsed += _time.monotonic() - t0_fb
        if gemini_result.get("questions"):
            ast_result = gemini_result

    pipeline_trace["passes"]["pass3_questions"] = {
        "elapsed_s": round(pass3_elapsed, 1),
        "questions": len(ast_result.get("questions") or []),
        "topics": len(ast_result.get("topics") or []),
    }

    # ── Pass 4: AST Assembly + Blueprint ──
    _tick("pass4_ast_assembly", 80)
    t0 = _time.monotonic()
    ast = pass4_assemble_ast(layout_pages, page_texts, document_map, ast_result, doc_title, source_hash)
    pass4_elapsed = _time.monotonic() - t0
    pipeline_trace["passes"]["pass4_assembly"] = {
        "elapsed_s": round(pass4_elapsed, 1),
        "paragraphs": len(ast.get("contentAST", {}).get("paragraphs") or []),
        "tables": len(ast.get("tableAST", {}).get("tables") or []),
        "blueprint_topics": len(ast.get("blueprint", {}).get("topics") or []),
        "blueprint_entities": len(ast.get("blueprint", {}).get("entities") or []),
    }

    # ── Pass 5: Gemini Enhancement (optional) ──
    _tick("pass5_gemini_enhancement", 90)
    t0 = _time.monotonic()
    try:
        from report_builder.gemini_enrichment import gemini_full_enrichment
        ast = gemini_full_enrichment(ast)
        gemini_status = "success"
    except Exception as exc:
        logger.warning("[pipeline] Gemini enhancement failed (non-fatal): %s", exc)
        gemini_status = f"skipped: {exc}"
    pass5_elapsed = _time.monotonic() - t0
    pipeline_trace["passes"]["pass5_gemini"] = {
        "elapsed_s": round(pass5_elapsed, 1),
        "status": gemini_status,
    }

    # Finalize trace
    pipeline_trace["total_elapsed"] = round(_time.monotonic() - pipeline_start, 1)
    ast["pipeline_trace"] = pipeline_trace

    _tick("completed", 100)
    logger.info("═══════════════════════════════════════════════════════════")
    logger.info("  ✓ Pipeline v3.0 complete — Enterprise AST + Blueprint ready")
    logger.info("  ✓ %d topics, %d questions, %d entities",
                len(ast.get("blueprint", {}).get("topics") or []),
                sum(len(t.get("questions", [])) for t in ast.get("blueprint", {}).get("topics", [])),
                len(ast.get("blueprint", {}).get("entities") or []))
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
    document_map: dict[str, Any],
    toc: list[ToCEntry],
    doc_title: str,
) -> dict[str, Any]:
    """Use Gemini as fallback for question generation when local model fails.

    Returns same format as pass3_two_loop_ast_building output.
    """
    try:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("[gemini-fallback] No API key — skipping")
            return {"questions": [], "topics": []}

        gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        # Build entity + table summary from document_map
        all_entities = document_map.get("all_entities") or []
        table_structures = document_map.get("table_structures") or []
        chapters = document_map.get("chapters") or []

        entity_list = ", ".join(e["name"] for e in all_entities[:30])
        table_summary = ""
        for ts in table_structures[:10]:
            table_summary += f"Table p{ts['page'] + 1}: cols=[{', '.join(ts['columns'][:6])}], dims={ts.get('dimensions', [])[:3]}, measures={ts.get('measures', [])[:3]}\n"

        toc_text = "\n".join(f"  {'  ' * (e.level - 1)}{e.title} (p{e.page_index + 1})" for e in toc[:20])

        prompt = (
            f"Document: \"{doc_title}\"\n"
            f"Table of Contents:\n{toc_text}\n\n"
            f"Entities found: {entity_list}\n\n"
            f"Table structures:\n{table_summary}\n\n"
            "Generate analytical questions this document answers. For each question, "
            "specify which entities are needed and what visualization components suit it.\n\n"
            "Output JSON:\n"
            '{"questions":[{"questionId":"q1","intent":"...","questionType":"comparison|trend|ranking|distribution|describe",'
            '"sourceHeading":"...","page":0,'
            '"requiredEntities":[{"entityRef":"entity_name","role":"groupBy|measure|filter"}],'
            '"answerStructure":{"layoutType":"single|split","components":[{"type":"narrative_paragraph|data_table|grouped_bar_chart|line_chart|pie_chart|metric_card","renderOrder":1}]},'
            '"inferenceConfidence":0.6}]}\n'
            "Output 3-8 questions. JSON only."
        )

        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model=gemini_model, contents=prompt)
            text = (response.text or "").strip()
        except ImportError:
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=api_key)
            model_obj = legacy_genai.GenerativeModel(gemini_model)
            response = model_obj.generate_content(prompt)
            text = (response.text or "").strip()

        data = _extract_json_from_response(text)
        if not data:
            return {"questions": [], "topics": []}

        questions = data.get("questions") or []

        # Build topics from chapters
        topics: list[dict[str, Any]] = []
        for ch in chapters:
            ch_questions = [
                q for q in questions
                if ch["pageRange"][0] <= q.get("page", -1) <= ch["pageRange"][1]
            ]
            if ch_questions:
                topics.append({
                    "topicId": ch["chapterId"].replace("ch_", "topic_"),
                    "title": ch["title"],
                    "description": f"Gemini-generated questions for: {ch['title']}",
                    "questionIds": [q.get("questionId", "") for q in ch_questions],
                    "pageRange": ch["pageRange"],
                })

        # If no chapter match, put all in a single topic
        if not topics and questions:
            topics.append({
                "topicId": "topic_gemini",
                "title": doc_title,
                "description": "Gemini-generated questions",
                "questionIds": [q.get("questionId", "") for q in questions],
                "pageRange": [0, document_map.get("page_count", 0) - 1],
            })

        for q in questions:
            q["inferenceMethod"] = "gemini"

        logger.info("[gemini-fallback] ✓ Got %d questions in %d topics", len(questions), len(topics))
        return {"questions": questions, "topics": topics}

    except Exception as exc:
        logger.error("[gemini-fallback] Failed: %s", exc)
        return {"questions": [], "topics": []}
