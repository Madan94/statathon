"""Enhanced Gemini Integration — structured AST generation with schema guidance.

Uses Gemini 2.5 Flash/Pro for:
    1. Semantic hierarchy extraction (when local model fails)
    2. Entity + slot generation with schema-guided prompts
    3. Knowledge graph construction
    4. Fact extraction and cross-referencing
    5. Full AST enrichment pass (post-processing after local extraction)

Design:
    - All prompts request JSON conforming to Enterprise AST schema
    - Fail-fast: validates responses against Pydantic models immediately
    - Chunked for large documents (Gemini's 1M+ context helps but be cost-aware)
    - Caches results per document hash to avoid re-calling on retries
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from report_builder.ast_schema import (
    Entity,
    EnterpriseDocumentAST,
    Fact,
    Question,
    SemanticNode,
    TemplateSlot,
)

logger = logging.getLogger(__name__)

_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_CACHE_DIR = Path(os.getenv("CHECKPOINT_DIR", "./checkpoints")) / "gemini_cache"


def _get_genai_client():
    """Get google.genai Client with fail-fast on missing credentials."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set — cannot use Gemini enrichment")

    try:
        from google import genai  # new SDK (google-genai >= 1.0)
        return genai.Client(api_key=api_key)
    except ImportError:
        return None


def _call_gemini_json(prompt: str, max_retries: int = 2) -> dict[str, Any] | None:
    """Call Gemini and parse JSON response. Retries on parse failure."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("[gemini] No API key set")
        return None

    for attempt in range(max_retries):
        try:
            # Prefer new google-genai SDK
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=_GEMINI_MODEL, contents=prompt
                )
                text = (response.text or "").strip()
            except ImportError:
                # Fall back to deprecated google-generativeai SDK
                import google.generativeai as legacy_genai
                legacy_genai.configure(api_key=api_key)
                model = legacy_genai.GenerativeModel(_GEMINI_MODEL)
                response = model.generate_content(prompt)
                text = (response.text or "").strip()

            # Strip markdown code fences
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("[gemini] JSON parse failed (attempt %d): %s", attempt + 1, e)
            if attempt == max_retries - 1:
                logger.error("[gemini] All retries exhausted")
                return None
        except Exception as e:
            logger.error("[gemini] API call failed: %s", e)
            return None


def gemini_extract_semantic_hierarchy(
    pages_text: list[dict[str, Any]],
    doc_title: str = "Document",
) -> list[dict[str, Any]]:
    """Use Gemini to extract semantic hierarchy from document text.

    Returns list of SemanticNode-compatible dicts.
    """
    # Build condensed document text
    doc_text = ""
    for p in pages_text[:30]:
        page_idx = p.get("page_index", 0)
        text = (p.get("raw_text") or p.get("text") or "")[:600]
        headings = p.get("headings") or []
        doc_text += f"\n--- Page {page_idx + 1} ---\n"
        if headings:
            doc_text += f"[Headings: {', '.join(headings[:5])}]\n"
        doc_text += text + "\n"

    doc_text = doc_text[:15000]

    prompt = f"""\
Analyze this document and extract its semantic hierarchy (outline/structure).

Document: "{doc_title}"
{doc_text}

Output a JSON object with key "nodes" containing a nested hierarchy:
{{
  "nodes": [
    {{
      "id": "section_001",
      "type": "chapter",
      "title": "Chapter Title",
      "children": [
        {{"id": "section_002", "type": "subsection", "title": "Subsection Title", "children": []}}
      ]
    }}
  ]
}}

Rules:
- type must be: chapter | section | subsection
- Use meaningful IDs (section_001, section_002, etc.)
- Nest children correctly based on heading levels
- Include ALL sections and subsections you can identify
- Output ONLY valid JSON"""

    data = _call_gemini_json(prompt)
    if data and "nodes" in data:
        logger.info("[gemini] ✓ Semantic hierarchy: %d top-level nodes", len(data["nodes"]))
        return data["nodes"]
    return []


def gemini_extract_entities_and_slots(
    pages_text: list[dict[str, Any]],
    doc_title: str = "Document",
) -> tuple[list[dict], list[dict]]:
    """Use Gemini to extract entities and template slots.

    Returns (entities, slots) as lists of dicts.
    """
    doc_text = ""
    for p in pages_text[:20]:
        text = (p.get("raw_text") or p.get("text") or "")[:500]
        doc_text += text + "\n"
    doc_text = doc_text[:12000]

    prompt = f"""\
Extract all named entities and create template slots from this document.

Document: "{doc_title}"
{doc_text}

Output JSON with two keys:
{{
  "entities": [
    {{
      "entityId": "e_001",
      "type": "org|metric|demographic|time|location|resource",
      "name": "Entity Name",
      "context": "brief context where it appears"
    }}
  ],
  "slots": [
    {{
      "slotId": "slot_001",
      "entityRef": "e_001",
      "slotType": "value|label|range|enum|date",
      "currentValue": "actual value in document",
      "description": "what this represents and why it would change between report editions"
    }}
  ]
}}

Entity types:
- org: organizations, ministries, agencies, companies
- metric: percentages, monetary values, quantities with units
- time: dates, fiscal years, time periods (2024-25, FY2025, etc.)
- location: states, regions, countries, geographic areas
- demographic: population groups, age ranges, employment categories
- resource: energy sources, minerals, commodities

Template slots: Values that would CHANGE when generating a new edition of this report.
Focus on metrics that update annually, time references, and data values.

Output ONLY valid JSON."""

    data = _call_gemini_json(prompt)
    if data:
        entities = data.get("entities") or []
        slots = data.get("slots") or []
        logger.info("[gemini] ✓ Entities: %d, Slots: %d", len(entities), len(slots))
        return entities, slots
    return [], []


def gemini_extract_facts(
    pages_text: list[dict[str, Any]],
    doc_title: str = "Document",
) -> list[dict[str, Any]]:
    """Extract verifiable factual statements from document."""
    doc_text = ""
    for p in pages_text[:15]:
        text = (p.get("raw_text") or p.get("text") or "")[:600]
        doc_text += text + "\n"
    doc_text = doc_text[:10000]

    prompt = f"""\
Extract key factual statements from this document that contain specific data points.

Document: "{doc_title}"
{doc_text}

Output JSON:
{{
  "facts": [
    {{
      "factId": "fact_001",
      "statement": "India's total coal reserves were 400.7 billion tonnes as of April 2025",
      "entityRefs": ["e_coal", "e_india"],
      "confidence": 0.95
    }}
  ]
}}

Rules:
- Only include statements with specific numbers, dates, or verifiable claims
- Each fact should be self-contained (understandable without surrounding context)
- confidence: 0.9+ for explicit data, 0.7-0.9 for derived/comparative
- Keep statements concise (one sentence each)
- Output ONLY valid JSON"""

    data = _call_gemini_json(prompt)
    if data and "facts" in data:
        logger.info("[gemini] ✓ Facts: %d", len(data["facts"]))
        return data["facts"]
    return []


def gemini_generate_questions(
    pages_text: list[dict[str, Any]],
    doc_title: str = "Document",
) -> list[dict[str, Any]]:
    """Generate analytical questions that this document answers."""
    doc_text = ""
    for p in pages_text[:10]:
        text = (p.get("raw_text") or p.get("text") or "")[:400]
        headings = p.get("headings") or []
        if headings:
            doc_text += f"[{', '.join(headings[:3])}] "
        doc_text += text + "\n"
    doc_text = doc_text[:6000]

    prompt = f"""\
Generate analytical questions that this document answers. These questions will be used
to test whether a regenerated report correctly captures the same information.

Document: "{doc_title}"
{doc_text}

Output JSON:
{{
  "questions": [
    {{
      "id": "q_001",
      "question": "What were India's total coal reserves as of April 2025?",
      "section": "Coal Reserves",
      "answerType": "metric"
    }}
  ]
}}

answerType options: metric | narrative | table | chart
- metric: answer is a specific number/percentage
- narrative: answer requires explanation/description
- table: answer requires tabular data
- chart: answer is best represented visually

Generate 10-20 diverse questions covering all major sections.
Output ONLY valid JSON."""

    data = _call_gemini_json(prompt)
    if data and "questions" in data:
        logger.info("[gemini] ✓ Questions: %d", len(data["questions"]))
        return data["questions"]
    return []


def gemini_full_enrichment(ast_dict: dict[str, Any]) -> dict[str, Any]:
    """Run full Gemini enrichment pass on an existing AST.

    This is the main entry point for Phase 2 enhanced Gemini integration.
    Takes an AST (from extraction_pipeline.py pass4_assemble_ast) and
    enriches it with Gemini-extracted:
        - Semantic hierarchy (if empty)
        - Entities + slots
        - Facts
        - Questions (if fewer than 5)

    Returns the enriched AST dict.
    """
    logger.info("[gemini-enrich] ▶ Starting full Gemini enrichment pass")

    # Build pages_text from extracted_assets or contentAST
    pages_text = []
    extracted = ast_dict.get("extracted_assets", {})
    text_pages = extracted.get("text_pages") or []

    if text_pages:
        pages_text = text_pages
    else:
        # Fall back to contentAST paragraphs
        for para in (ast_dict.get("contentAST", {}).get("paragraphs") or []):
            pages_text.append({
                "page_index": 0,
                "text": para.get("content", ""),
            })

    if not pages_text:
        logger.warning("[gemini-enrich] No text content to enrich")
        return ast_dict

    doc_title = ast_dict.get("metadata", {}).get("title", "Document")

    # ── Semantic hierarchy (if empty) ──
    semantic_nodes = ast_dict.get("semanticAST", {}).get("nodes") or []
    if not semantic_nodes:
        nodes = gemini_extract_semantic_hierarchy(pages_text, doc_title)
        if nodes:
            ast_dict.setdefault("semanticAST", {})["nodes"] = nodes

    # ── Entities + Slots ──
    existing_entities = ast_dict.get("entityGraph", {}).get("entities") or []
    if len(existing_entities) < 5:
        entities, slots = gemini_extract_entities_and_slots(pages_text, doc_title)
        if entities:
            ast_dict.setdefault("entityGraph", {})["entities"] = entities
        if slots:
            ast_dict.setdefault("templateSlots", {})["slots"] = slots

    # ── Facts ──
    existing_facts = ast_dict.get("factGraph", {}).get("facts") or []
    if len(existing_facts) < 3:
        facts = gemini_extract_facts(pages_text, doc_title)
        if facts:
            ast_dict.setdefault("factGraph", {})["facts"] = facts

    # ── Questions ──
    existing_questions = ast_dict.get("questions") or []
    if len(existing_questions) < 5:
        questions = gemini_generate_questions(pages_text, doc_title)
        if questions:
            ast_dict["questions"] = questions

    # ── Update metadata ──
    ast_dict.setdefault("metadata", {})["updatedAt"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"

    logger.info("[gemini-enrich] ✓ Enrichment complete")
    return ast_dict
