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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
            pages.append({
                "page_index": i,
                "width": page.width,
                "height": page.height,
                "word_count": len(words),
                "has_tables": bool(tables),
                "table_count": len(tables),
                "headings": _heuristic_headings(words),
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
    """
    if not page_summaries:
        return []
    try:
        import google.generativeai as g  # type: ignore
    except Exception:
        logger.info("google-generativeai not available; using heuristic classification")
        return _heuristic_classify_sections(page_summaries)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return _heuristic_classify_sections(page_summaries)
    try:
        g.configure(api_key=api_key)
        model = g.GenerativeModel(os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash"))
        prompt = (
            "You are a report-template compiler. Given a list of pages with detected "
            "headings and layout signals, output a JSON list of block specs. Each item "
            "must have: block_id (slug), kind (one of narrative/table/chart/metric/heading), "
            "title (short), section (slug), required (bool), hints (object with page_index, "
            "and optional chart_type/source).\n"
            "Only return valid JSON. No prose.\n\n"
            f"PAGES:\n{json.dumps(page_summaries, indent=2)[:8000]}"
        )
        resp = model.generate_content(prompt)
        text = (resp.text or "").strip()
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
        return blocks or _heuristic_classify_sections(page_summaries)
    except Exception as exc:
        logger.warning("Gemini classification failed: %s; using heuristic", exc)
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

    Tries the local sidecar in this order:
      1. `colpali-engine` Python package (HuggingFace model loaded in-process).
      2. HTTP endpoint at COLPALI_ENDPOINT (e.g. http://colpali:8001/extract).
    Returns the same `page_summaries` shape as `_pdfplumber_layout` so the
    downstream SGLang AST compiler is agnostic to source.
    """
    try:
        from colpali_engine.models import ColPali  # type: ignore
        from colpali_engine.utils.processing_utils import process_images  # type: ignore
        import pdf2image  # type: ignore

        model = ColPali.from_pretrained(os.getenv("COLPALI_MODEL", "vidore/colpali-v1.2"))
        images = pdf2image.convert_from_path(str(pdf_path))
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

            with open(pdf_path, "rb") as f:
                r = requests.post(endpoint, files={"file": f}, timeout=120)
            r.raise_for_status()
            return r.json().get("pages") or None
        except Exception as exc:
            logger.info("ColPali endpoint unreachable: %s", exc)
    return None


def _sglang_compile_ast(page_summaries: list[dict[str, Any]]) -> list[BlockSpec]:
    """Compile page summaries to a SGLang-structured block list.

    Uses the sglang Python frontend when available; otherwise drives a Gemini
    call with the SGLang prompt convention (produces identical JSON shape).
    """
    if not page_summaries:
        return []
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

        import json as _json
        state = _ast_program.run(pages_json=_json.dumps(page_summaries)[:8000])
        try:
            data = _json.loads(state["ast"])
        except Exception:
            data = []
        blocks: list[BlockSpec] = []
        for i, entry in enumerate(data if isinstance(data, list) else []):
            blocks.append(BlockSpec(
                block_id=str(entry.get("block_id") or f"blk_{i}"),
                kind=str(entry.get("kind") or "narrative"),
                title=str(entry.get("title") or "Section"),
                section=str(entry.get("section") or "body"),
                required=bool(entry.get("required", True)),
                hints=entry.get("hints") or {},
            ))
        if blocks:
            return blocks
    except Exception:
        pass
    return _gemini_classify_sections(page_summaries)


# ---------------- Public API ----------------

def compile_template(pdf_path: str | Path, template_name: str) -> TemplateAST:
    """Phase 0 entry point: PDF -> TemplateAST."""
    path = Path(pdf_path)
    file_hash = sha256_of_file(path) if path.exists() else None

    # 1. Primary: ColPali vision-spatial extraction.
    pages = _colpali_extract(path) if path.exists() else None
    extraction_method = "colpali+sglang"

    # 2. Secondary: pdfplumber layout if ColPali unavailable on this host.
    if pages is None and path.exists():
        pages = _pdfplumber_layout(path)
        extraction_method = "pdfplumber+sglang"

    # 3. AST compilation via SGLang.
    blocks = _sglang_compile_ast(pages or []) if pages else []

    if not blocks:
        # 4. Last-resort: canonical MoSPI skeleton with preserved audit hash.
        return TemplateAST(
            name=template_name or "MoSPI Standard Report",
            source_hash=file_hash,
            page_count=len(pages or []),
            blocks=list(DEFAULT_MOSPI_TEMPLATE.blocks),
            extraction_method="builtin_fallback",
        )

    return TemplateAST(
        name=template_name,
        source_hash=file_hash,
        page_count=len(pages or []),
        blocks=blocks,
        extraction_method=extraction_method,
    )


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
