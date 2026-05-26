"""AST Builder — compiles PDF spatial layouts into a TemplateAST.

Pipeline:
  1. Load PDF  (pdf_loader.py — ColPali → pdfplumber → PyMuPDF → stub)
  2. Hash      (pdf_hasher.py — SHA-256 audit fingerprint)
  3. Spatial   (spatial_extractor.py — region classification)
  4. Classify  (section_classifier.py — canonical section taxonomy)
  5. LLM merge (Gemini) — optional; enriches hints from raw text
  6. Fallback  (builtin MoSPI default if no blocks found)

Produces a TemplateAST compatible with report_builder/blueprint.py.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from template_engine.ingestion.pdf_hasher import sha256_file
from template_engine.ingestion.pdf_loader import load_pdf
from template_engine.ingestion.spatial_extractor import (
    SpatialLayout,
    extract_spatial_layout,
)
from template_engine.ast.section_classifier import (
    ClassifiedBlock,
    classify_heading,
    infer_block_kind,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TemplateAST (canonical model)
# ---------------------------------------------------------------------------

@dataclass
class BlockSpec:
    block_id: str
    kind: str
    title: str
    section: str
    required: bool = True
    hints: dict[str, Any] = field(default_factory=dict)

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
    extraction_method: str = "pdfplumber"
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_hash": self.source_hash,
            "page_count": self.page_count,
            "extraction_method": self.extraction_method,
            "blocks": [b.to_dict() for b in self.blocks],
            "manifest": self.manifest,
        }


# ---------------------------------------------------------------------------
# Built-in MoSPI default template (ground truth fallback)
# ---------------------------------------------------------------------------

_MOSPI_BLOCKS: list[tuple[str, str, str, bool, dict]] = [
    # (block_id, kind, title, required, hints)
    ("cover",             "heading",   "Cover Page",                        True,  {"max_words": 60, "tone": "official"}),
    ("exec_summary",      "narrative", "Executive Summary",                  True,  {"max_words": 250, "tone": "official, neutral", "section_num": "1"}),
    ("analytics_summary", "metric",    "Analytics Summary",                  True,  {"metrics": ["row_count", "column_count", "missing_pct", "anomaly_count", "imputation_count", "mapped_column_count"]}),
    ("methodology",       "narrative", "Data Collection Methodology",        True,  {"max_words": 300, "section_num": "2", "verify_numbers": False}),
    ("dataset_overview",  "table",     "Dataset Overview",                   True,  {"source": "health_summary", "section_num": "3.1"}),
    ("semantic_map",      "table",     "Column Semantic Mapping",            True,  {"source": "semantic_mapping", "section_num": "3.2"}),
    ("cluster_summary",   "table",     "Cluster Analysis Summary",           True,  {"source": "clusters", "section_num": "3.3"}),
    ("missing_values",    "chart",     "Missing Values by Column",           True,  {"chart_type": "bar", "source": "missing_per_column", "section_num": "4.1"}),
    ("anomaly_detail",    "table",     "Anomaly Detection Results",          True,  {"source": "phase3.anomaly_candidates", "group_by": "column", "section_num": "4.2"}),
    ("imputation_detail", "table",     "Imputation Recommendations",         True,  {"source": "phase3.imputation_candidates", "section_num": "4.3"}),
    ("column_dist",       "chart",     "Column Distribution Overview",       False, {"chart_type": "bar", "source": "column_types", "section_num": "4.4"}),
    ("dependency_graph",  "chart",     "Column Dependency Graph",            True,  {"chart_type": "network", "source": "schema_graph", "section_num": "5.1"}),
    ("kg_export",         "metric",    "Knowledge Graph Export",             True,  {"formats": ["rdf", "turtle", "owl"], "section_num": "5.2"}),
    ("narrative_findings","narrative", "Key Findings & Statistical Insights",True,  {"max_words": 450, "verify_numbers": True, "section_num": "6"}),
    ("recommendations",   "narrative", "Recommendations",                    True,  {"max_words": 280, "section_num": "7"}),
    ("audit_trail",       "metric",    "Audit & Integrity",                  True,  {"metrics": ["content_hash", "kg_export_path", "generated_at", "analysis_id", "job_id"]}),
]

def _section_for(block_id: str) -> str:
    _map = {
        "cover": "cover",
        "exec_summary": "executive_summary",
        "analytics_summary": "executive_summary",
        "methodology": "methodology",
        "dataset_overview": "data_overview",
        "semantic_map": "data_overview",
        "cluster_summary": "data_overview",
        "missing_values": "data_quality",
        "anomaly_detail": "data_quality",
        "imputation_detail": "data_quality",
        "column_dist": "data_quality",
        "dependency_graph": "relationships",
        "kg_export": "relationships",
        "narrative_findings": "findings",
        "recommendations": "recommendations",
        "audit_trail": "appendix",
    }
    return _map.get(block_id, "body")


DEFAULT_MOSPI_TEMPLATE = TemplateAST(
    name="MoSPI Standard Statistical Report",
    source_hash=None,
    page_count=0,
    extraction_method="builtin",
    blocks=[
        BlockSpec(
            block_id=bid,
            kind=kind,
            title=title,
            section=_section_for(bid),
            required=req,
            hints=hints,
        )
        for bid, kind, title, req, hints in _MOSPI_BLOCKS
    ],
)


# ---------------------------------------------------------------------------
# Spatial → BlockSpec conversion
# ---------------------------------------------------------------------------

def _layouts_to_blocks(layouts: list[SpatialLayout]) -> list[BlockSpec]:
    """Convert SpatialLayout pages to a deduplicated ordered BlockSpec list."""
    blocks: list[BlockSpec] = []
    seen_sections: set[str] = set()
    counter = 0

    for layout in layouts:
        for heading in layout.headings:
            if not heading.strip() or len(heading) < 4:
                continue

            section = classify_heading(heading)
            kind = infer_block_kind(heading, bool(layout.tables), layout.has_charts)

            # One block per (section, kind) combination to avoid duplicates
            dedup_key = f"{section}::{kind}"
            if dedup_key in seen_sections and section not in ("findings", "body"):
                continue
            seen_sections.add(dedup_key)

            hints: dict[str, Any] = {"page_index": layout.page_index}
            if kind == "chart":
                # Detect chart sub-type from heading keywords
                h_lower = heading.lower()
                if "bar" in h_lower or "distribution" in h_lower:
                    hints["chart_type"] = "bar"
                elif "line" in h_lower or "trend" in h_lower:
                    hints["chart_type"] = "line"
                elif "pie" in h_lower:
                    hints["chart_type"] = "pie"
                else:
                    hints["chart_type"] = "bar"

            if kind == "narrative":
                hints["max_words"] = 300
                hints["verify_numbers"] = True

            slug = re.sub(r"[^a-z0-9]+", "_", heading.lower())[:40].strip("_")
            blocks.append(BlockSpec(
                block_id=f"{slug}_{counter}",
                kind=kind,
                title=heading.title(),
                section=section,
                required=True,
                hints=hints,
            ))
            counter += 1

        # Add a table block if the page has tables not yet captured by a heading
        if layout.tables and "data_overview::table" not in seen_sections:
            seen_sections.add("data_overview::table")
            blocks.append(BlockSpec(
                block_id=f"table_p{layout.page_index}",
                kind="table",
                title=f"Data Table (Page {layout.page_index + 1})",
                section="data_overview",
                required=False,
                hints={"page_index": layout.page_index, "source": "dataset"},
            ))
            counter += 1

    return blocks


# ---------------------------------------------------------------------------
# Gemini enrichment (optional)
# ---------------------------------------------------------------------------

def _gemini_enrich(
    blocks: list[BlockSpec],
    page_summaries: list[dict[str, Any]],
) -> list[BlockSpec]:
    """Ask Gemini to add semantic hints (source, verify_numbers, chart_type) to blocks."""
    try:
        import google.generativeai as g  # type: ignore
    except Exception:
        return blocks

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return blocks

    try:
        g.configure(api_key=api_key)
        model = g.GenerativeModel(os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash"))
        blocks_json = json.dumps([b.to_dict() for b in blocks], indent=2)[:4000]
        pages_json = json.dumps([p for p in page_summaries[:6]], indent=2)[:4000]

        prompt = (
            "You are a government report template compiler. "
            "Given a partially-extracted block list and page summaries from a statistical PDF, "
            "enrich each block's `hints` with:\n"
            "  - `source`: where data comes from (e.g. semantic_mapping, phase3.anomaly_candidates, health_summary)\n"
            "  - `chart_type`: bar/line/pie for chart blocks\n"
            "  - `verify_numbers`: true for blocks containing quantitative claims\n"
            "  - `max_words`: target length for narrative blocks (100-500)\n"
            "Return ONLY a JSON array matching the input blocks, with enriched hints. No prose.\n\n"
            f"BLOCKS:\n{blocks_json}\n\nPAGE SUMMARIES:\n{pages_json}"
        )
        resp = model.generate_content(prompt)
        text = re.sub(r"^```(?:json)?|```$", "", (resp.text or "").strip(), flags=re.MULTILINE).strip()
        enriched = json.loads(text)
        if isinstance(enriched, list) and len(enriched) == len(blocks):
            for orig, upd in zip(blocks, enriched):
                if isinstance(upd.get("hints"), dict):
                    orig.hints.update(upd["hints"])
    except Exception as exc:
        logger.info("Gemini block enrichment failed: %s", exc)

    return blocks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compile_template(pdf_path: str | Path, template_name: str) -> TemplateAST:
    """Phase 0 main entry: PDF → TemplateAST.

    Pipeline:
      load → hash → spatial → classify → (gemini enrich) → fallback
    """
    path = Path(pdf_path)

    # 1. Hash
    file_hash = sha256_file(path) if path.exists() else None

    # 2. Load
    pages, extraction_method = load_pdf(path)
    page_count = len(pages)

    # 3. Spatial layout
    layouts = extract_spatial_layout(pages)

    # 4. Classification
    page_summaries = [lay.to_summary_dict() for lay in layouts]
    blocks = _layouts_to_blocks(layouts)

    # 5. Gemini enrichment (optional)
    if blocks:
        blocks = _gemini_enrich(blocks, page_summaries)

    # 6. Fallback to default MoSPI template if nothing extracted
    if not blocks:
        logger.info("No blocks extracted from %s; using MoSPI default", path.name)
        return TemplateAST(
            name=template_name or DEFAULT_MOSPI_TEMPLATE.name,
            source_hash=file_hash,
            page_count=page_count,
            blocks=list(DEFAULT_MOSPI_TEMPLATE.blocks),
            extraction_method="builtin_fallback",
        )

    return TemplateAST(
        name=template_name,
        source_hash=file_hash,
        page_count=page_count,
        blocks=blocks,
        extraction_method=extraction_method,
        manifest={"source_file": path.name, "page_summaries_count": len(page_summaries)},
    )
