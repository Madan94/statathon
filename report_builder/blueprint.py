"""Phase 0 — Reverse-Engineering & Template Blueprinting.

Pipeline:
  1. Immutable ingestion: SHA256 hash of source PDF for audit.
  2. Vision-spatial extraction with ColPali — preserves x/y geometry rather
     than relying on brittle OCR. pdfplumber + Gemini Vision act as a
     secondary pipeline when the ColPali endpoint is unreachable.
  3. AST compilation via SGLang: static document sections become a
     hierarchical Abstract Syntax Tree of block specs (kind=narrative/
     table/chart/metric/heading, with layout hints).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------- AST schema ----------------

@dataclass
class BlockSpec:
    """One block in the report skeleton (SGLang-style AST node)."""

    block_id: str
    kind: str  # 'narrative' | 'table' | 'chart' | 'metric' | 'heading' | 'list'
    title: str
    section: str  # parent section name (e.g. 'executive_summary')
    required: bool = True
    hints: dict[str, Any] = field(default_factory=dict)
    # `hints` carries layout intel: page_index, bbox, expected_keywords, chart_type, etc.

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "kind": self.kind,
            "title": self.title,
            "section": self.section,
            "required": self.required,
            "hints": self.hints,
        }


@dataclass
class TemplateAST:
    name: str
    source_hash: str | None
    page_count: int
    blocks: list[BlockSpec] = field(default_factory=list)
    extraction_method: str = "pdfplumber+gemini_vision"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_hash": self.source_hash,
            "page_count": self.page_count,
            "extraction_method": self.extraction_method,
            "blocks": [b.to_dict() for b in self.blocks],
        }


PRODUCTION_STAGE_ORDER = (
    "stage1_immutable_ingestion_vaulting",
    "stage2_vision_spatial_layout_parsing",
    "stage3_semantic_blueprint_extraction",
    "stage4_required_answer_structure_modeling",
    "stage5_detailed_ast_hierarchy_assembly",
    "stage6_final_ast_json_layout",
)


def _layout_extraction_tools(extraction_method: str, *, sequential: bool = False) -> list[str]:
    """Tool chips surfaced in template extraction UI (stage 2)."""
    m = (extraction_method or "").lower()
    tools: list[str] = []
    if "colpali" in m:
        tools.append("ColPali")
    if "pdfplumber" in m:
        tools.append("pdfplumber")
    if "pymupdf" in m or "fitz" in m:
        tools.append("PyMuPDF")
    if "layoutlm" in m or "qwen-vl" in m:
        tools.extend(["LayoutLM", "Qwen-VL"])
    if sequential:
        tools.append("GPU orchestrator")
    return tools or ["pdfplumber", "PyMuPDF"]


def _blueprint_extraction_tools(*, sequential: bool, used_sglang: bool) -> list[str]:
    """Tool chips for stage 3 semantic blueprint extraction."""
    if sequential and used_sglang:
        return ["SGLang", "Qwen2.5-3B"]
    if used_sglang:
        return ["SGLang", "Gemini fallback"]
    return ["Gemini", "Heuristics"]


# ---------------- Built-in default (MoSPI-style) ----------------

DEFAULT_MOSPI_TEMPLATE = TemplateAST(
    name="MoSPI Standard Report",
    source_hash=None,
    page_count=0,
    extraction_method="builtin",
    blocks=[
        BlockSpec("exec_summary", "narrative", "Executive Summary", "executive_summary",
                  hints={"max_words": 220, "tone": "official"}),
        BlockSpec("analytics_summary", "metric", "Analytics Summary",
                  "executive_summary",
                  hints={"metrics": ["row_count", "column_count", "missing_pct",
                                     "anomaly_count", "imputation_count"]}),
        BlockSpec("dataset_overview", "table", "Dataset Overview", "data_overview",
                  hints={"source": "health_summary"}),
        BlockSpec("semantic_map", "table", "Column Semantic Mapping", "data_overview",
                  hints={"source": "semantic_mapping"}),
        BlockSpec("missing_values", "chart", "Missing Values by Column",
                  "data_quality",
                  hints={"chart_type": "bar", "source": "missing_per_column"}),
        BlockSpec("anomaly_detail", "table", "Anomaly Detection Results",
                  "data_quality",
                  hints={"source": "phase3.anomaly_candidates", "group_by": "column"}),
        BlockSpec("imputation_detail", "table", "Imputation Recommendations",
                  "data_quality",
                  hints={"source": "phase3.imputation_candidates"}),
        BlockSpec("dependency_graph", "chart", "Column Dependency Graph",
                  "relationships",
                  hints={"chart_type": "network", "source": "schema_graph"}),
        BlockSpec("kg_export", "metric", "Knowledge Graph Export",
                  "relationships",
                  hints={"formats": ["rdf", "turtle", "owl"]}),
        BlockSpec("narrative_findings", "narrative", "Key Findings", "findings",
                  hints={"max_words": 400, "verify_numbers": True}),
        BlockSpec("recommendations", "narrative", "Recommendations", "recommendations",
                  hints={"max_words": 250}),
        BlockSpec("audit_trail", "metric", "Audit & Integrity", "appendix",
                  hints={"metrics": ["content_hash", "kg_export_path", "generated_at"]}),
    ],
)


# ---------------- Ingestion ----------------

def sha256_of_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _pdfplumber_layout(pdf_path: str | Path) -> list[dict[str, Any]]:
    """Per-page layout: text spans + bounding boxes. Returns [] if pdfplumber missing."""
    try:
        import pdfplumber  # type: ignore
    except Exception:
        logger.warning("pdfplumber not installed; falling back to default template")
        return []

    pages: list[dict[str, Any]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            words = page.extract_words(use_text_flow=True) or []
            tables = page.extract_tables() or []
            images = page.images or []
            table_previews: list[dict[str, Any]] = []
            for tbl in tables[:5]:
                if not tbl:
                    continue
                str_rows = [[str(c or "") for c in row] for row in tbl]
                table_previews.append(
                    {
                        "row_count": len(str_rows),
                        "col_count": max((len(r) for r in str_rows), default=0),
                        "preview_rows": str_rows[:4],
                    }
                )
            image_previews = [
                {
                    "x0": img.get("x0"),
                    "x1": img.get("x1"),
                    "y0": img.get("y0"),
                    "y1": img.get("y1"),
                    "width": img.get("width"),
                    "height": img.get("height"),
                    "name": img.get("name"),
                }
                for img in images[:20]
            ]
            pages.append({
                "page_index": i,
                "width": page.width,
                "height": page.height,
                "word_count": len(words),
                "has_tables": bool(tables),
                "table_count": len(tables),
                "table_previews": table_previews,
                "image_count": len(images),
                "image_previews": image_previews,
                "headings": _heuristic_headings(words),
                "raw_text": (page.extract_text() or ""),
                "raw_text_sample": (page.extract_text() or "")[:600],
            })
    return pages


_HEADING_PAT = re.compile(r"^[A-Z][A-Z0-9 \-:]{3,80}$")


def _heuristic_headings(words: list[dict]) -> list[str]:
    """Group adjacent same-y words; return ones that look like headings (ALL CAPS / Title Case lines)."""
    lines: dict[int, list[str]] = {}
    for w in words:
        y = int(w.get("top", 0) or 0)
        lines.setdefault(y, []).append(str(w.get("text", "")))
    out: list[str] = []
    for _, toks in sorted(lines.items()):
        line = " ".join(toks).strip()
        if 4 <= len(line) <= 90 and (_HEADING_PAT.match(line) or line.istitle()):
            out.append(line)
    # de-dup, keep order
    seen: set[str] = set()
    dedup: list[str] = []
    for h in out:
        if h not in seen:
            seen.add(h)
            dedup.append(h)
    return dedup[:30]


def _gemini_classify_sections(page_summaries: list[dict[str, Any]]) -> list[BlockSpec]:
    """Ask Gemini to map detected headings/layout into our block kinds.

    Returns block specs ordered per page; falls back gracefully if Gemini fails.
    Uses google.genai >= 1.0 SDK with automatic fallback to legacy google.generativeai.
    """
    if not page_summaries:
        return []

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.info("[blueprint] ⚠ GEMINI_API_KEY not set — using heuristic classification")
        return _heuristic_classify_sections(page_summaries)

    model_name = os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash")
    prompt = (
        "You are a report-template compiler. Given a list of pages with detected "
        "headings and layout signals, output a JSON list of block specs. Each item "
        "must have: block_id (slug), kind (one of narrative/table/chart/metric/heading), "
        "title (short), section (slug), required (bool), hints (object with page_index, "
        "and optional chart_type/source).\n"
        "Only return valid JSON. No prose.\n\n"
        f"PAGES:\n{json.dumps(page_summaries, indent=2)[:8000]}"
    )
    logger.info(
        "[blueprint] ▶ Gemini POST    model=%s   pages=%d   prompt=%d chars",
        model_name, len(page_summaries), len(prompt),
    )
    t0 = time.monotonic()
    try:
        text: str = ""
        try:
            # Prefer new google-genai SDK (pip install google-genai)
            import google.genai as _genai  # type: ignore
            client = _genai.Client(api_key=api_key)
            resp = client.models.generate_content(model=model_name, contents=prompt)
            text = (resp.text or "").strip()
        except ImportError:
            # Fall back to legacy google-generativeai SDK
            import google.generativeai as g  # type: ignore
            g.configure(api_key=api_key)
            resp = g.GenerativeModel(model_name).generate_content(prompt)
            text = (resp.text or "").strip()

        elapsed = time.monotonic() - t0
        # Strip markdown fences if present
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        data = json.loads(text)
        blocks: list[BlockSpec] = []
        for entry in data if isinstance(data, list) else []:
            try:
                blocks.append(BlockSpec(
                    block_id=str(entry.get("block_id") or f"blk_{len(blocks)}"),
                    kind=str(entry.get("kind") or "narrative"),
                    title=str(entry.get("title") or "Section"),
                    section=str(entry.get("section") or "body"),
                    required=bool(entry.get("required", True)),
                    hints=entry.get("hints") or {},
                ))
            except Exception:
                continue
        logger.info(
            "[blueprint] ✓ Gemini OK      blocks=%d   elapsed=%.1fs",
            len(blocks), elapsed,
        )
        return blocks or _heuristic_classify_sections(page_summaries)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        logger.warning(
            "[blueprint] ✗ Gemini FAIL    elapsed=%.1fs   %s   → using heuristic",
            elapsed, exc,
        )
        return _heuristic_classify_sections(page_summaries)


def _heuristic_classify_sections(page_summaries: list[dict[str, Any]]) -> list[BlockSpec]:
    """Purely-local fallback: emit one block per detected heading."""
    blocks: list[BlockSpec] = []
    counter = 0
    for page in page_summaries:
        page_idx = page.get("page_index", 0)
        for heading in page.get("headings", []) or []:
            section = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_") or f"section_{counter}"
            kind = "table" if page.get("has_tables") else "narrative"
            blocks.append(BlockSpec(
                block_id=f"blk_{counter}",
                kind=kind,
                title=heading.title(),
                section=section,
                hints={"page_index": page_idx},
            ))
            counter += 1
    return blocks


# ---------------- ColPali + SGLang (primary path) ----------------

def _colpali_extract(pdf_path: str | Path) -> list[dict[str, Any]] | None:
    """Vision-spatial extraction via ColPali.

    Respects COLPALI_IN_PROCESS env var (default: false).
    When false (Docker mode), skips in-process model load and goes directly
    to the HTTP endpoint at COLPALI_ENDPOINT (e.g. http://colpali:8001/extract).
    When true (local dev without Docker), loads colpali-engine in-process.

    Returns the same `page_summaries` shape as `_pdfplumber_layout` so the
    downstream SGLang AST compiler is agnostic to source.
    """
    in_process = os.getenv("COLPALI_IN_PROCESS", "false").strip().lower() in ("1", "true", "yes")

    if in_process:
        try:
            from colpali_engine.models import ColPali  # type: ignore
            from colpali_engine.utils.processing_utils import process_images  # type: ignore
            import pdf2image  # type: ignore

            model = ColPali.from_pretrained(os.getenv("COLPALI_MODEL", "vidore/colpali-v1.2"))
            poppler_path = os.getenv("POPPLER_PATH") or None
            images = pdf2image.convert_from_path(str(pdf_path), poppler_path=poppler_path)
            spatial = process_images(model, images)
            # Adapt ColPali output (per-page bbox + caption tokens) to our shape.
            out = []
            for i, page in enumerate(spatial):
                out.append({
                    "page_index": i,
                    "width": page.get("width"),
                    "height": page.get("height"),
                    "word_count": len(page.get("tokens") or []),
                    "has_tables": any(b.get("kind") == "table" for b in page.get("blocks") or []),
                    "table_count": sum(1 for b in page.get("blocks") or [] if b.get("kind") == "table"),
                    "headings": [b.get("text") for b in page.get("blocks") or [] if b.get("kind") == "heading"],
                    "raw_text_sample": page.get("text", "")[:600],
                    "colpali_blocks": page.get("blocks") or [],
                })
            return out
        except Exception:
            pass

    endpoint = os.getenv("COLPALI_ENDPOINT")
    if endpoint:
        try:
            import requests  # type: ignore

            # Always use base URL + /extract so this is consistent with ColPaliClient
            # which also appends /extract. COLPALI_ENDPOINT must NOT include /extract.
            colpali_url = endpoint.rstrip("/") + "/extract"
            timeout = int(os.getenv("COLPALI_TIMEOUT", "300"))
            logger.info(
                "[blueprint._colpali_extract] → %s  timeout=%ds",
                colpali_url, timeout,
            )
            t0 = time.monotonic()
            with open(pdf_path, "rb") as f:
                r = requests.post(colpali_url, files={"file": f}, timeout=timeout)
            r.raise_for_status()
            pages = r.json().get("pages") or None
            logger.info(
                "[blueprint._colpali_extract] OK  pages=%d  elapsed=%.1fs",
                len(pages) if pages else 0,
                time.monotonic() - t0,
            )
            if pages:
                from report_builder.gpu_orchestrator import _normalize_colpali_pages
                return _normalize_colpali_pages(pages)
            return None
        except Exception as exc:
            logger.info("[blueprint._colpali_extract] endpoint unreachable: %s", exc)
    return None


def _sglang_compile_ast(page_summaries: list[dict[str, Any]]) -> list[BlockSpec]:
    """Compile page summaries to a SGLang-structured block list.

    Priority (first success wins):
      1. SGLang HTTP endpoint at SGLANG_ENDPOINT (Docker container, port 8002).
         This is the primary path when SGLang Docker is running.
      2. sglang Python in-process SDK (only if `sglang` is installed locally).
      3. Gemini gemini-2.5-flash HTTP fallback (always works, no local install).

    Why HTTP-first:
      The UI upload flow goes through blueprint.compile_template_production() which
      calls this function. The Docker SGLang container is only reachable via HTTP —
      trying `import sglang` first completely bypassed the container.
    """
    if not page_summaries:
        return []

    import json as _json

    def _parse_blocks(data: Any, source: str) -> list[BlockSpec]:
        """Parse a raw JSON value into BlockSpec list."""
        if isinstance(data, dict):
            # SGLang may wrap in {"blocks": [...]} or {"items": [...]}
            data = data.get("blocks") or data.get("items") or []
        blocks: list[BlockSpec] = []
        for i, entry in enumerate(data if isinstance(data, list) else []):
            try:
                blocks.append(BlockSpec(
                    block_id=str(entry.get("block_id") or f"blk_{i}"),
                    kind=str(entry.get("kind") or "narrative"),
                    title=str(entry.get("title") or "Section"),
                    section=str(entry.get("section") or "body"),
                    required=bool(entry.get("required", True)),
                    hints=entry.get("hints") or {},
                ))
            except Exception:
                continue
        if blocks:
            logger.info("SGLang (%s) compiled %d blocks", source, len(blocks))
        return blocks

    # ── Attempt 1: HTTP endpoint (Docker SGLang container at SGLANG_ENDPOINT) ──
    endpoint = os.getenv("SGLANG_ENDPOINT", "").strip()
    if endpoint:
        try:
            import requests  # type: ignore

            model = os.getenv("SGLANG_MODEL") or "Qwen/Qwen2.5-VL-3B-Instruct-AWQ"
            # Truncate page data to ~3000 chars so input fits in 4096 context
            pages_text = _json.dumps(page_summaries)[:3000]
            prompt = (
                "You compile statistical-report PDFs into structured block ASTs.\n"
                "Output ONLY a JSON array. Each item must have: "
                "block_id (slug), kind (narrative|table|chart|metric|heading), "
                "title (short string), section (slug), required (bool), "
                "hints (object with at least page_index).\n\n"
                f"PAGES:\n{pages_text}"
            )
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You compile statistical-report PDFs into block ASTs."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 2048,
            }
            timeout = int(os.getenv("SGLANG_TIMEOUT", "120"))
            logger.info(
                "[blueprint] ▶ SGLang POST    url=%s   model=%s   timeout=%ds",
                endpoint, model, timeout,
            )
            t0 = time.monotonic()
            r = requests.post(
                f"{endpoint.rstrip('/')}/v1/chat/completions",
                json=payload,
                timeout=timeout,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            # Strip markdown fences if present
            content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
            data = _json.loads(content)
            blocks = _parse_blocks(data, f"http:{endpoint}")
            if blocks:
                logger.info(
                    "[blueprint] ✓ SGLang OK      blocks=%d   elapsed=%.1fs",
                    len(blocks), time.monotonic() - t0,
                )
                return blocks
        except Exception as exc:
            logger.info("[blueprint] ⚠ SGLang unavailable: %s   🔁 falling back", exc)

    # ── Attempt 2: sglang Python in-process SDK (only if locally installed) ──
    try:
        import sglang as sgl  # type: ignore

        @sgl.function
        def _ast_program(s, pages_json: str):
            s += sgl.system("You compile statistical-report PDFs into block ASTs.")
            s += sgl.user(
                "Output ONLY a JSON array. Each item: {block_id, kind, title, "
                f"section, required, hints}}. Pages:\n{pages_json}"
            )
            s += sgl.assistant(sgl.gen("ast", max_tokens=2048))

        state = _ast_program.run(pages_json=_json.dumps(page_summaries)[:8000])
        try:
            data = _json.loads(state["ast"])
        except Exception:
            data = []
        blocks = _parse_blocks(data, "in-process")
        if blocks:
            return blocks
    except Exception:
        pass

    # ── Attempt 3: Gemini fallback ──
    logger.info("[blueprint] 🔁 fallback chain  SGLang ✗ → in-process ✗ → Gemini")
    return _gemini_classify_sections(page_summaries)


# ---------------- Public API ----------------


def compile_template_production(
    pdf_path: str | Path,
    template_name: str,
    *,
    progress: Callable[[str, int, dict[str, Any]], None] | None = None,
) -> tuple[TemplateAST, dict[str, Any]]:
    """Run full 6-stage extraction with strict architecture payload."""
    path = Path(pdf_path)
    diagnostics: dict[str, Any] = {"stages": {}, "doc_id": "MOSPI_TPL_01"}

    def _tick(stage: str, pct: int, payload: dict[str, Any] | None = None) -> None:
        diagnostics["stages"][stage] = payload or {}
        if progress:
            progress(stage, pct, payload or {})

    _tick(PRODUCTION_STAGE_ORDER[0], 10, {"status": "started"})
    file_hash = sha256_of_file(path) if path.exists() else None
    diagnostics["source_hash"] = file_hash
    _tick(PRODUCTION_STAGE_ORDER[0], 20, {"sha256": file_hash, "status": "completed"})

    _tick(PRODUCTION_STAGE_ORDER[1], 35, {"status": "started"})

    # ── V2 Multi-Pass Pipeline (LayoutLM + Qwen-VL) ──────────────────────────
    # Activated by EXTRACTION_PIPELINE=v2 (default: v1 for backwards compat)
    if os.getenv("EXTRACTION_PIPELINE", "v1") == "v2" and path.exists():
        logger.info("[blueprint] ▶ EXTRACTION_PIPELINE=v2 — using multi-pass pipeline")
        from report_builder.extraction_pipeline import run_extraction_pipeline

        enterprise_ast = run_extraction_pipeline(
            pdf_path=path,
            doc_title=template_name or "Document",
            source_hash=file_hash or "",
            progress_callback=lambda stage, pct, data: _tick(stage, pct, {"v2": True}),
        )
        # Build TemplateAST from enterprise AST for backward compat
        v2_blocks: list[BlockSpec] = []

        # Use semantic hierarchy for section-level blocks
        hierarchy = enterprise_ast.get("semanticAST", {}).get("hierarchy") or []
        for node in hierarchy[:30]:
            node_id = node.get("nodeId") or node.get("id") or f"sec_{len(v2_blocks)}"
            title = node.get("title", "Section")[:80]
            level = node.get("level", 2)
            kind = "heading" if level <= 1 else "narrative"
            v2_blocks.append(BlockSpec(
                block_id=node_id,
                kind=kind,
                title=title,
                section="body",
                required=True,
                hints={"level": level},
            ))

        # Add table blocks from tableAST
        for tbl in (enterprise_ast.get("tableAST", {}).get("tables") or [])[:20]:
            v2_blocks.append(BlockSpec(
                block_id=tbl.get("tableId", f"tbl_{len(v2_blocks)}"),
                kind="table",
                title=tbl.get("title", "Table"),
                section="body",
                required=True,
                hints={"columns": tbl.get("columns", [])},
            ))

        # Add figure/chart blocks
        for fig in (enterprise_ast.get("figureAST", {}).get("figures") or [])[:10]:
            v2_blocks.append(BlockSpec(
                block_id=fig.get("figureId", f"fig_{len(v2_blocks)}"),
                kind="chart",
                title=fig.get("caption", "Figure")[:80],
                section="body",
                required=False,
                hints={},
            ))
        for chart in (enterprise_ast.get("chartAST", {}).get("charts") or [])[:10]:
            v2_blocks.append(BlockSpec(
                block_id=chart.get("chartId", f"chart_{len(v2_blocks)}"),
                kind="chart",
                title=chart.get("title", "Chart")[:80],
                section="body",
                required=False,
                hints={"chartType": chart.get("type", "unknown")},
            ))

        # If hierarchy was empty, fall back to page-level narrative blocks
        if not v2_blocks:
            for para in (enterprise_ast.get("contentAST", {}).get("paragraphs") or [])[:40]:
                v2_blocks.append(BlockSpec(
                    block_id=para.get("id", f"blk_{len(v2_blocks)}"),
                    kind="narrative",
                    title=para.get("content", "")[:60],
                    section="body",
                    required=True,
                    hints={},
                ))

        if not v2_blocks:
            v2_blocks = list(DEFAULT_MOSPI_TEMPLATE.blocks)

        ast = TemplateAST(
            name=template_name or "Enterprise Document",
            source_hash=file_hash,
            page_count=enterprise_ast.get("metadata", {}).get("pageCount", 0),
            blocks=v2_blocks,
            extraction_method="layoutlm+qwen-vl+sequential",
        )
        payload = ast.to_dict()
        payload["enterprise_ast"] = enterprise_ast
        payload["extracted_assets"] = enterprise_ast.get("extracted_assets", {})
        payload["questions"] = enterprise_ast.get("questions", [])
        payload["templateSlots"] = enterprise_ast.get("templateSlots", {})
        payload["pipeline_trace"] = enterprise_ast.get("pipeline_trace", {})
        payload["doc_id"] = enterprise_ast.get("metadata", {}).get("documentId", "MOSPI_TPL_01")
        diagnostics["blueprint_payload"] = payload
        diagnostics["stages"]["v2_pipeline"] = {"status": "completed"}
        _tick(PRODUCTION_STAGE_ORDER[5], 100, {"status": "completed"})
        return ast, diagnostics

    # ── V1 Legacy Pipeline ────────────────────────────────────────────────────
    pages: list[dict[str, Any]] = []
    extraction_method = "unknown"

    # ── Sequential GPU mode: use orchestrator (ColPali Docker → stop → SGLang Docker → stop)
    from report_builder.gpu_orchestrator import get_pipeline_mode, extract_with_colpali

    gpu_mode = get_pipeline_mode()
    _sequential = gpu_mode == "sequential"

    if _sequential and path.exists():
        logger.info("[blueprint] ▶ PIPELINE_GPU_MODE=sequential   orchestrating Docker containers")
        raw_pages = extract_with_colpali(path)
        if raw_pages:
            pages = raw_pages
            extraction_method = "colpali+sequential"
        else:
            logger.warning("[blueprint] ⚠ sequential ColPali failed — falling back to local extractors")
            _sequential = False  # fall through to local path below

    if not _sequential and path.exists():
        try:
            from template_engine.ingestion.pdf_loader import load_pdf  # type: ignore

            loaded_pages, extraction_method = load_pdf(path)
            pages = []
            for p in loaded_pages:
                tbl_previews = []
                for t in (p.tables or [])[:6]:
                    tbl_rows = [[str(c or "") for c in row] for row in (t.rows or [])]
                    tbl_previews.append(
                        {
                            "row_count": int(t.row_count or len(tbl_rows)),
                            "col_count": int(t.col_count or max((len(r) for r in tbl_rows), default=0)),
                            "preview_rows": tbl_rows[:5],
                        }
                    )
                pages.append(
                    {
                        "page_index": p.page_index,
                        "width": p.width,
                        "height": p.height,
                        "word_count": p.word_count,
                        "has_tables": bool(p.tables),
                        "table_count": len(p.tables or []),
                        "table_previews": tbl_previews,
                        "image_count": 0,
                        "image_previews": [],
                        "headings": p.headings[:30],
                        "raw_text": p.raw_text or "",
                        "raw_text_sample": (p.raw_text or "")[:800],
                    }
                )
        except Exception as exc:
            logger.warning("template_engine load_pdf failed: %s; using legacy loader", exc)
            pages = _colpali_extract(path) if path.exists() else None
            extraction_method = "colpali+sglang"
            if pages is None and path.exists():
                pages = _pdfplumber_layout(path)
                extraction_method = "pdfplumber+sglang"
            pages = pages or []

    if extraction_method == "stub":
        raise RuntimeError(
            "Real PDF extraction unavailable (stub loader used). Install/enable pdfplumber or PyMuPDF."
        )
    if not pages:
        raise RuntimeError("No PDF pages extracted. Cannot build production blueprint from empty content.")
    section_hierarchy = [
        {
            "page_index": p.get("page_index"),
            "titles": p.get("headings") or [],
            "paragraph_count": p.get("word_count") or 0,
            "table_count": p.get("table_count") or 0,
            "image_count": p.get("image_count") or 0,
        }
        for p in pages
    ]
    page_layout_preview = [
        {
            "page_index": p.get("page_index"),
            "headings": p.get("headings") or [],
            "has_tables": bool(p.get("has_tables")),
            "table_count": p.get("table_count") or 0,
            "table_previews": p.get("table_previews") or [],
            "image_count": p.get("image_count") or 0,
            "image_previews": p.get("image_previews") or [],
            "paragraph_excerpt": (p.get("raw_text_sample") or "")[:400],
        }
        for p in pages[:20]
    ]
    extracted_text_pages = [
        {
            "page_index": p.get("page_index"),
            "text": (p.get("raw_text") or "")[:5000],
        }
        for p in pages[:20]
    ]
    extracted_tables = [
        {
            "page_index": p.get("page_index"),
            "tables": p.get("table_previews") or [],
        }
        for p in pages[:20]
        if (p.get("table_previews") or [])
    ]
    extracted_images = [
        {
            "page_index": p.get("page_index"),
            "images": p.get("image_previews") or [],
        }
        for p in pages[:20]
        if (p.get("image_previews") or [])
    ]
    diagnostics["stages"][PRODUCTION_STAGE_ORDER[1]] = {
        "page_count": len(pages),
        "extraction_method": extraction_method,
        "section_hierarchy": section_hierarchy[:25],
        "page_layout_preview": page_layout_preview,
        "layout_extractors": {"paragraphs": True, "tables": True},
        "tools": _layout_extraction_tools(extraction_method, sequential=_sequential),
        "status": "completed",
    }
    _tick(PRODUCTION_STAGE_ORDER[1], 45, diagnostics["stages"][PRODUCTION_STAGE_ORDER[1]])

    _tick(PRODUCTION_STAGE_ORDER[2], 55, {"status": "started"})

    # ── Sequential GPU mode: use orchestrator for SGLang too
    inferred_blocks: list[BlockSpec] = []
    used_sglang = False
    if _sequential:
        from report_builder.gpu_orchestrator import compile_with_sglang
        raw_blocks = compile_with_sglang(pages)
        if raw_blocks:
            for i, entry in enumerate(raw_blocks):
                try:
                    inferred_blocks.append(BlockSpec(
                        block_id=str(entry.get("block_id") or f"blk_{i}"),
                        kind=str(entry.get("kind") or "narrative"),
                        title=str(entry.get("title") or "Section"),
                        section=str(entry.get("section") or "body"),
                        required=bool(entry.get("required", True)),
                        hints=entry.get("hints") or {},
                    ))
                except Exception:
                    continue
            if inferred_blocks:
                used_sglang = True
                logger.info(
                    "[blueprint] ✓ sequential SGLang   blocks=%d", len(inferred_blocks)
                )
        if not inferred_blocks:
            logger.info("[blueprint] ⚠ sequential SGLang returned 0 blocks — trying Gemini fallback")
            inferred_blocks = _sglang_compile_ast(pages)
    else:
        inferred_blocks = _sglang_compile_ast(pages)

    if not inferred_blocks:
        # fallback still uses real headings from extracted pages
        inferred_blocks = _heuristic_classify_sections(pages)
    generalized_questions: list[dict[str, Any]] = []
    for idx, blk in enumerate(inferred_blocks[:40]):
        generalized_questions.append(
            {
                "id": f"q_{idx+1}",
                "question": f"What does the report section '{blk.title}' reveal and how does it compare over categories/time?",
                "section": blk.section,
            }
        )
    _tick(
        PRODUCTION_STAGE_ORDER[2],
        65,
        {
            "questions_count": len(generalized_questions),
            "block_count": len(inferred_blocks),
            "tools": _blueprint_extraction_tools(sequential=_sequential, used_sglang=used_sglang),
            "status": "completed",
        },
    )

    _tick(PRODUCTION_STAGE_ORDER[3], 75, {"status": "started"})
    answer_schema = {
        "datagrid_schema_generator": {
            "required_columns": ["dimension", "metric", "period", "value", "variance_yoy"],
        },
        "narrative_schema_generator": {"tone": "official", "min_words": 80, "max_words": 220},
        "chart_schema_generator": {
            "allowed": ["grouped_bar", "line_trend", "pie"],
        },
    }
    _tick(PRODUCTION_STAGE_ORDER[3], 82, {"answer_schema": answer_schema, "status": "completed"})

    _tick(PRODUCTION_STAGE_ORDER[4], 90, {"status": "started"})
    heading_pool: list[str] = []
    for p in pages:
        for h in (p.get("headings") or []):
            hs = str(h).strip()
            if hs and hs.lower() not in {x.lower() for x in heading_pool}:
                heading_pool.append(hs)
    topics = [
        {"id": f"t_{i+1}", "name": h}
        for i, h in enumerate(heading_pool[:8])
    ]
    subtopics = [
        {"topic_id": (topics[i % len(topics)]["id"] if topics else "t_1"), "name": h}
        for i, h in enumerate(heading_pool[8:20])
    ]
    _tick(
        PRODUCTION_STAGE_ORDER[4],
        94,
        {
            "topics": topics,
            "subtopics": subtopics,
            "block_count": len(inferred_blocks),
            "status": "completed",
        },
    )

    _tick(PRODUCTION_STAGE_ORDER[5], 98, {"status": "started"})
    ast = TemplateAST(
        name=template_name or "MoSPI Standard Report",
        source_hash=file_hash,
        page_count=len(pages),
        blocks=inferred_blocks,
        extraction_method=extraction_method,
    )
    payload = ast.to_dict()
    payload["doc_id"] = diagnostics["doc_id"]
    payload["main_topics"] = topics
    payload["sub_topics"] = subtopics
    payload["questions"] = generalized_questions
    payload["expected_answer_structure"] = answer_schema
    payload["extracted_layout"] = {
        "page_layout_preview": page_layout_preview,
        "section_hierarchy": section_hierarchy[:25],
    }
    payload["extracted_assets"] = {
        "text_pages": extracted_text_pages,
        "tables": extracted_tables,
        "images": extracted_images,
    }
    payload["context_fill_options"] = {
        "kg_hooks": {
            "Sector": {"enum": "Target DB Entities"},
        }
    }
    diagnostics["blueprint_payload"] = payload
    diagnostics["final_payload_preview"] = {
        "doc_id": payload.get("doc_id"),
        "main_topics_count": len(payload.get("main_topics") or []),
        "questions_count": len(payload.get("questions") or []),
    }
    _tick(PRODUCTION_STAGE_ORDER[5], 100, {"status": "completed"})
    return ast, diagnostics

def compile_template(pdf_path: str | Path, template_name: str) -> TemplateAST:
    """Phase 0 entry point: PDF -> TemplateAST."""
    ast, _ = compile_template_production(pdf_path, template_name)
    if not ast.blocks:
        return TemplateAST(
            name=template_name or "MoSPI Standard Report",
            source_hash=ast.source_hash,
            page_count=ast.page_count,
            blocks=list(DEFAULT_MOSPI_TEMPLATE.blocks),
            extraction_method="builtin_fallback",
        )
    return ast


def template_from_ast_json(payload: dict[str, Any]) -> TemplateAST:
    return TemplateAST(
        name=str(payload.get("name") or "Template"),
        source_hash=payload.get("source_hash"),
        page_count=int(payload.get("page_count") or 0),
        extraction_method=str(payload.get("extraction_method") or "unknown"),
        blocks=[
            BlockSpec(
                block_id=str(b.get("block_id") or f"blk_{i}"),
                kind=str(b.get("kind") or "narrative"),
                title=str(b.get("title") or "Section"),
                section=str(b.get("section") or "body"),
                required=bool(b.get("required", True)),
                hints=b.get("hints") or {},
            )
            for i, b in enumerate(payload.get("blocks") or [])
        ],
    )


# ---------------------------------------------------------------------------
# Bridge: new deep TemplateBlueprintAST → legacy TemplateAST
# ---------------------------------------------------------------------------

def template_from_deep_blueprint(blueprint) -> TemplateAST:
    """Convert a TemplateBlueprintAST (new pipeline) to the legacy TemplateAST.

    This shim allows the report_builder pipeline to consume output from the
    enhanced template_engine.pipeline without modification to downstream phases.

    Maps: topic → section, question → block (kind inferred from answer components).
    """
    blocks: list[BlockSpec] = []
    counter = 0

    for topic in (blueprint.topics or []):
        # Emit heading block for topic
        section_slug = re.sub(r"[^a-z0-9]+", "_", topic.title.lower()).strip("_") or f"section_{counter}"
        blocks.append(BlockSpec(
            block_id=f"blk_{counter}",
            kind="heading",
            title=topic.title,
            section=section_slug,
            hints={"page_range": topic.pageRange},
        ))
        counter += 1

        for question in (topic.questions or []):
            kind = _infer_block_kind(question)
            blocks.append(BlockSpec(
                block_id=f"blk_{counter}",
                kind=kind,
                title=question.intent[:80] if question.intent else "Section",
                section=section_slug,
                hints={
                    "question_id": question.questionId,
                    "question_type": question.questionType,
                    "confidence": question.inferenceConfidence,
                    "component_count": len(question.answerStructure.components),
                },
            ))
            counter += 1

    return TemplateAST(
        name=blueprint.name,
        source_hash=blueprint.sourceHash,
        page_count=blueprint.pageCount,
        blocks=blocks or list(DEFAULT_MOSPI_TEMPLATE.blocks),
        extraction_method=blueprint.extractionMethod or "deep_pipeline",
    )


def _infer_block_kind(question) -> str:
    """Infer legacy block kind from a QuestionNode's answer components."""
    if not question.answerStructure or not question.answerStructure.components:
        return "narrative"

    type_counts: dict[str, int] = {}
    for comp in question.answerStructure.components:
        type_counts[comp.type] = type_counts.get(comp.type, 0) + 1

    # Priority: table > chart > metric > narrative
    if "data_table" in type_counts or "cross_tabulation_matrix" in type_counts:
        return "table"
    if any(k in type_counts for k in ("grouped_bar_chart", "line_chart", "pie_chart", "geographic_map")):
        return "chart"
    if "metric_card" in type_counts:
        return "metric"
    return "narrative"


def compile_template_from_deep_pipeline(
    pdf_path: str | Path,
    template_name: str,
    *,
    progress: Callable[[str, int, dict[str, Any]], None] | None = None,
) -> tuple[TemplateAST, dict[str, Any]]:
    """Bridge: run the new deep pipeline and return legacy-format TemplateAST.

    Falls back to compile_template_production if the deep pipeline fails.
    """
    try:
        from template_engine.pipeline import run_extraction_pipeline

        result = run_extraction_pipeline(
            pdf_path=pdf_path,
            template_name=template_name,
            progress_callback=(lambda p: progress(p.stage, p.progress_pct, p.to_dict()))
            if progress else None,
        )

        if result.success and result.ast:
            legacy_ast = template_from_deep_blueprint(result.ast)
            diagnostics = {
                "source_hash": result.source_hash,
                "stages": result.progress.timings,
                "deep_pipeline": True,
                "topics": len(result.ast.topics),
                "questions": sum(len(t.questions) for t in result.ast.topics),
                "entities": len(result.ast.entities),
                "blueprint_payload": result.ast.to_dict(),
            }
            return legacy_ast, diagnostics

    except Exception as exc:
        logger.warning("Deep pipeline failed, falling back: %s", exc)

    # Fallback to original production pipeline
    return compile_template_production(pdf_path, template_name, progress=progress)
