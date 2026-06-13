"""Provider-agnostic semantic enrichment (R1).

Replaces direct Gemini calls in gemini_enrichment.py with provider-agnostic
routing through llm_router. Enrichment runs ONLY when explicitly enabled:

    ENRICHMENT_ENABLED=true

This is NOT triggered by REASONING_PROVIDER=gemini or VLM_PROVIDER=gemini.
Provider is determined by RuntimeConfig.enrichmentProvider or the resolved
task config for "semantic_enrichment".

Usage:
    from report_builder.semantic_enrichment import run_semantic_enrichment
    enriched_ast = run_semantic_enrichment(ast_dict, config=config)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from report_builder.llm_router import llm_text_call
from report_builder.model_runtime.config import RuntimeConfig, build_runtime_config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Individual enrichment tasks
# ─────────────────────────────────────────────────────────────────────────────


def extract_semantic_hierarchy(
    pages_text: list[dict[str, Any]],
    doc_title: str = "Document",
    *,
    config: RuntimeConfig | None = None,
) -> list[dict[str, Any]]:
    """Extract semantic hierarchy from document text via configured provider.

    Returns list of SemanticNode-compatible dicts, or [] on failure/disabled.
    """
    if config is None:
        config = build_runtime_config()
    if not config.enrichmentEnabled:
        return []

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

    task_config = config.task("semantic_enrichment")
    doc_text = doc_text[:task_config.maxInputChars]

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

    result = llm_text_call(
        prompt=prompt,
        task="semantic_enrichment",
        max_tokens=task_config.maxOutputTokens,
        temperature=task_config.temperature,
    )

    if not result:
        return []

    data = _parse_json(result)
    if data and "nodes" in data:
        logger.info("[semantic-enrichment] Hierarchy: %d top-level nodes", len(data["nodes"]))
        return data["nodes"]
    return []


def extract_entities_and_slots(
    pages_text: list[dict[str, Any]],
    doc_title: str = "Document",
    *,
    config: RuntimeConfig | None = None,
) -> tuple[list[dict], list[dict]]:
    """Extract entities and template slots via configured provider.

    Returns (entities, slots) as lists of dicts.
    """
    if config is None:
        config = build_runtime_config()
    if not config.enrichmentEnabled:
        return [], []

    task_config = config.task("semantic_enrichment")
    doc_text = ""
    for p in pages_text[:20]:
        text = (p.get("raw_text") or p.get("text") or "")[:500]
        doc_text += text + "\n"
    doc_text = doc_text[:task_config.maxInputChars]

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
      "description": "what this represents"
    }}
  ]
}}

Output ONLY valid JSON."""

    result = llm_text_call(
        prompt=prompt,
        task="semantic_enrichment",
        max_tokens=task_config.maxOutputTokens,
        temperature=task_config.temperature,
    )

    if not result:
        return [], []

    data = _parse_json(result)
    if data:
        entities = data.get("entities") or []
        slots = data.get("slots") or []
        logger.info("[semantic-enrichment] Entities: %d, Slots: %d", len(entities), len(slots))
        return entities, slots
    return [], []


def extract_facts(
    pages_text: list[dict[str, Any]],
    doc_title: str = "Document",
    *,
    config: RuntimeConfig | None = None,
) -> list[dict[str, Any]]:
    """Extract factual statements via configured provider."""
    if config is None:
        config = build_runtime_config()
    if not config.enrichmentEnabled:
        return []

    task_config = config.task("semantic_enrichment")
    doc_text = ""
    for p in pages_text[:15]:
        text = (p.get("raw_text") or p.get("text") or "")[:600]
        doc_text += text + "\n"
    doc_text = doc_text[:task_config.maxInputChars]

    prompt = f"""\
Extract key factual statements from this document that contain specific data points.

Document: "{doc_title}"
{doc_text}

Output JSON:
{{
  "facts": [
    {{
      "factId": "fact_001",
      "statement": "A specific factual claim with a number or date",
      "entityRefs": ["e_relevant"],
      "confidence": 0.95
    }}
  ]
}}

Rules:
- Only include statements with specific numbers, dates, or verifiable claims
- Each fact should be self-contained
- confidence: 0.9+ for explicit data, 0.7-0.9 for derived/comparative
- Output ONLY valid JSON"""

    result = llm_text_call(
        prompt=prompt,
        task="semantic_enrichment",
        max_tokens=task_config.maxOutputTokens,
        temperature=task_config.temperature,
    )

    if not result:
        return []

    data = _parse_json(result)
    if data and "facts" in data:
        logger.info("[semantic-enrichment] Facts: %d", len(data["facts"]))
        return data["facts"]
    return []


def generate_questions(
    pages_text: list[dict[str, Any]],
    doc_title: str = "Document",
    *,
    config: RuntimeConfig | None = None,
) -> list[dict[str, Any]]:
    """Generate analytical questions via configured provider."""
    if config is None:
        config = build_runtime_config()
    if not config.enrichmentEnabled:
        return []

    task_config = config.task("semantic_enrichment")
    doc_text = ""
    for p in pages_text[:10]:
        text = (p.get("raw_text") or p.get("text") or "")[:400]
        headings = p.get("headings") or []
        if headings:
            doc_text += f"[{', '.join(headings[:3])}] "
        doc_text += text + "\n"
    doc_text = doc_text[:task_config.maxInputChars]

    prompt = f"""\
Generate analytical questions that this document answers.

Document: "{doc_title}"
{doc_text}

Output JSON:
{{
  "questions": [
    {{
      "id": "q_001",
      "question": "A specific analytical question",
      "section": "Section Name",
      "answerType": "metric|narrative|table|chart"
    }}
  ]
}}

Generate 10-20 diverse questions covering all major sections.
Output ONLY valid JSON."""

    result = llm_text_call(
        prompt=prompt,
        task="semantic_enrichment",
        max_tokens=task_config.maxOutputTokens,
        temperature=task_config.temperature,
    )

    if not result:
        return []

    data = _parse_json(result)
    if data and "questions" in data:
        logger.info("[semantic-enrichment] Questions: %d", len(data["questions"]))
        return data["questions"]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────


def run_semantic_enrichment(
    ast_dict: dict[str, Any],
    *,
    config: RuntimeConfig | None = None,
) -> dict[str, Any]:
    """Run full semantic enrichment pass on an existing AST.

    Provider-agnostic replacement for gemini_full_enrichment().

    Gate: runs ONLY when config.enrichmentEnabled == True.
    Provider: determined by config.task("semantic_enrichment").provider.

    If enrichment is disabled, returns ast_dict unchanged with zero model calls.
    """
    if config is None:
        config = build_runtime_config()

    if not config.enrichmentEnabled:
        logger.info("[semantic-enrichment] Disabled (ENRICHMENT_ENABLED=false) — no-op")
        return ast_dict

    if config.llmDisabled:
        logger.info("[semantic-enrichment] LLM_DISABLED — no-op")
        return ast_dict

    logger.info(
        "[semantic-enrichment] Starting enrichment (provider=%s)",
        config.task("semantic_enrichment").provider,
    )

    # Build pages_text from extracted_assets or contentAST
    pages_text: list[dict[str, Any]] = []
    extracted = ast_dict.get("extracted_assets", {})
    text_pages = extracted.get("text_pages") or []

    if text_pages:
        pages_text = text_pages
    else:
        for para in (ast_dict.get("contentAST", {}).get("paragraphs") or []):
            pages_text.append({
                "page_index": 0,
                "text": para.get("content", ""),
            })

    if not pages_text:
        logger.warning("[semantic-enrichment] No text content to enrich")
        return ast_dict

    doc_title = ast_dict.get("metadata", {}).get("title", "Document")

    # ── Semantic hierarchy (if empty) ──
    semantic_nodes = ast_dict.get("semanticAST", {}).get("nodes") or []
    if not semantic_nodes:
        nodes = extract_semantic_hierarchy(pages_text, doc_title, config=config)
        if nodes:
            ast_dict.setdefault("semanticAST", {})["nodes"] = nodes

    # ── Entities + Slots ──
    existing_entities = ast_dict.get("entityGraph", {}).get("entities") or []
    if len(existing_entities) < 5:
        entities, slots = extract_entities_and_slots(pages_text, doc_title, config=config)
        if entities:
            ast_dict.setdefault("entityGraph", {})["entities"] = entities
        if slots:
            ast_dict.setdefault("templateSlots", {})["slots"] = slots

    # ── Facts ──
    existing_facts = ast_dict.get("factGraph", {}).get("facts") or []
    if len(existing_facts) < 3:
        facts = extract_facts(pages_text, doc_title, config=config)
        if facts:
            ast_dict.setdefault("factGraph", {})["facts"] = facts

    # ── Questions ──
    existing_questions = ast_dict.get("questions") or []
    if len(existing_questions) < 5:
        questions = generate_questions(pages_text, doc_title, config=config)
        if questions:
            ast_dict["questions"] = questions

    logger.info("[semantic-enrichment] Enrichment complete")
    return ast_dict


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_json(text: str) -> dict[str, Any] | None:
    """Parse JSON from model output, stripping markdown fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("[semantic-enrichment] JSON parse failed")
        return None
