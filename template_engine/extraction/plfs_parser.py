"""PLFS Statement Parser — domain-specific extractor for MoSPI PLFS reports.

PLFS reports follow a structured format:
  - Statements numbered as "Statement X.Y" (chapter.sequence)
  - Each statement has a title describing the data cross-tabulation
  - Tables immediately follow their statement heading

This parser:
  1. Detects "Statement X.Y" patterns in VLM page text
  2. Maps to glossary archetypes (distribution, rate, trend, etc.)
  3. Extracts domain entities from the statement title
  4. Generates a typed QuestionNode with high confidence
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from ast_core.schema import (
    AnswerComponent,
    AnswerComponentRef,
    AnswerStructure,
    QuestionEntityBinding,
    QuestionNode,
    TemplateEntity,
    TopicNode,
)
from template_engine.vlm.schemas import VLMPageResult, VLMRegion

logger = logging.getLogger(__name__)

# Load glossary once
_GLOSSARY_PATH = Path(__file__).parent.parent / "inference" / "patterns" / "plfs_glossary.json"
_GLOSSARY: dict[str, Any] = {}


def _load_glossary() -> dict[str, Any]:
    global _GLOSSARY
    if not _GLOSSARY:
        try:
            _GLOSSARY = json.loads(_GLOSSARY_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load PLFS glossary: %s", exc)
            _GLOSSARY = {}
    return _GLOSSARY


# Pre-compiled patterns
_STATEMENT_RE = re.compile(
    r"Statement\s+(\d+)\.(\d+)(?:\s*\(([^)]+)\))?\s*[:.]?\s*(.*)",
    re.IGNORECASE,
)

_QUARTER_RE = re.compile(
    r"(?:January|April|July|October)[-–](?:March|June|September|December)\s*\d{4}",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Statement Detection
# ---------------------------------------------------------------------------

def detect_plfs_statements(pages: list[VLMPageResult]) -> list[dict[str, Any]]:
    """Scan all pages for PLFS Statement patterns.

    Returns list of raw statement detections:
      {chapter, sequence, qualifier, title, page_index, region_id}
    """
    detections: list[dict[str, Any]] = []

    for page in pages:
        # Check raw text and region text
        texts_to_scan = [(page.rawText, None)]
        for region in page.regions:
            if region.role in ("heading_h1", "heading_h2", "title", "paragraph"):
                texts_to_scan.append((region.text, region.regionId))

        for text, region_id in texts_to_scan:
            for match in _STATEMENT_RE.finditer(text):
                chapter = int(match.group(1))
                seq = int(match.group(2))
                qualifier = match.group(3) or ""
                title = match.group(4).strip()

                # Avoid duplicate detections on same page
                key = (page.pageIndex, chapter, seq)
                if any(
                    (d["page_index"], d["chapter"], d["sequence"]) == key
                    for d in detections
                ):
                    continue

                detections.append({
                    "chapter": chapter,
                    "sequence": seq,
                    "qualifier": qualifier,
                    "title": title,
                    "page_index": page.pageIndex,
                    "region_id": region_id,
                    "full_match": match.group(0),
                })

    logger.info("Detected %d PLFS statements across %d pages", len(detections), len(pages))
    return detections


# ---------------------------------------------------------------------------
# Archetype Classification
# ---------------------------------------------------------------------------

def classify_statement(title: str, glossary: dict[str, Any] | None = None) -> str:
    """Map statement title to archetype (distribution, rate, trend, etc.)."""
    g = glossary or _load_glossary()
    archetypes = g.get("statement_archetypes", {})

    title_lower = title.lower()

    for archetype_name, config in archetypes.items():
        pattern = config.get("pattern", "")
        if pattern and re.search(pattern, title_lower):
            return archetype_name

    return "descriptive"  # fallback


# ---------------------------------------------------------------------------
# Entity Extraction from Title
# ---------------------------------------------------------------------------

def extract_entities_from_statement(
    title: str,
    chapter: int,
    sequence: int,
    page_index: int,
    glossary: dict[str, Any] | None = None,
) -> list[TemplateEntity]:
    """Extract domain entities from a PLFS statement title using glossary hints."""
    g = glossary or _load_glossary()
    entities: list[TemplateEntity] = []
    entity_hints = g.get("entity_hints", {})
    abbreviations = g.get("abbreviations", {})

    # Check for known abbreviations in title
    title_upper = title.upper()
    for abbr, full_name in abbreviations.items():
        if abbr in title_upper or abbr.lower() in title.lower():
            hint = entity_hints.get(abbr, {})
            entities.append(TemplateEntity(
                entityId=f"plfs_{chapter}_{sequence}_{abbr.lower()}",
                name=abbr,
                entityType=hint.get("entityType", "measure"),
                sourceType="section_heading",
                confidence=0.90,
                aliases=[full_name],
                pageIndex=page_index,
                sourceContext=title,
            ))

    # Check for dimension keywords
    dimensions = g.get("column_semantics", {}).get("dimensions", {})
    for dim_name, values in dimensions.items():
        for val in values:
            if val.lower() in title.lower():
                entities.append(TemplateEntity(
                    entityId=f"plfs_{chapter}_{sequence}_{dim_name}_{val.lower().replace(' ', '_')}",
                    name=val,
                    entityType="dimension",
                    sourceType="section_heading",
                    confidence=0.85,
                    pageIndex=page_index,
                    sourceContext=title,
                ))
                break  # One per dimension category

    # Extract quarter/time reference
    quarter_match = _QUARTER_RE.search(title)
    if quarter_match:
        entities.append(TemplateEntity(
            entityId=f"plfs_{chapter}_{sequence}_quarter",
            name=quarter_match.group(0),
            entityType="time",
            sourceType="section_heading",
            confidence=0.92,
            pageIndex=page_index,
            sourceContext=title,
        ))

    return entities


# ---------------------------------------------------------------------------
# Question Generation from Statement
# ---------------------------------------------------------------------------

def statement_to_question(
    detection: dict[str, Any],
    entities: list[TemplateEntity],
    glossary: dict[str, Any] | None = None,
) -> QuestionNode:
    """Convert a detected statement into a QuestionNode.

    PLFS statements map cleanly to analytical questions because they already
    describe the data cross-tabulation.
    """
    g = glossary or _load_glossary()
    chapter = detection["chapter"]
    seq = detection["sequence"]
    title = detection["title"]
    page_index = detection["page_index"]

    archetype = classify_statement(title, g)
    question_type_map = {
        "distribution": "composition",
        "rate": "comparative",
        "trend": "trend",
        "cross_tabulation": "multi_dimensional",
        "state_level": "geographic",
        "descriptive": "descriptive",
    }
    question_type = question_type_map.get(archetype, "descriptive")

    # Generate question text from title
    question_text = _title_to_question(title, archetype)

    # Build entity bindings
    bindings = [
        QuestionEntityBinding(
            entityId=ent.entityId,
            role="required" if ent.entityType == "measure" else "grouping",
            confidence=ent.confidence,
            bindingMethod="plfs_parser",
        )
        for ent in entities
    ]

    # Build answer structure based on archetype
    answer_structure = _archetype_to_answer_structure(
        archetype, chapter, seq, title
    )

    return QuestionNode(
        questionId=f"q_plfs_{chapter}_{seq}",
        intent=question_text,
        questionType=question_type,
        inferenceConfidence=0.88,
        inferenceMethod="plfs_parser",
        requiredEntities=bindings,
        answerStructure=answer_structure,
        pageIndex=page_index,
        sourceHeading=title,
    )


def _title_to_question(title: str, archetype: str) -> str:
    """Convert a statement title to a natural-language analytical question."""
    title = title.rstrip(".")

    if archetype == "distribution":
        return f"What is the {title.lower()}?"
    elif archetype == "rate":
        return f"How does {title.lower()} vary across categories?"
    elif archetype == "trend":
        return f"What is the {title.lower()}?"
    elif archetype == "cross_tabulation":
        return f"How is {title.lower()} distributed?"
    elif archetype == "state_level":
        return f"How does {title.lower()} compare across states/UTs?"
    else:
        return f"What does {title.lower()} show?"


def _archetype_to_answer_structure(
    archetype: str, chapter: int, seq: int, title: str
) -> AnswerStructure:
    """Build an AnswerStructure appropriate for the statement archetype."""
    base_id = f"c_plfs_{chapter}_{seq}"

    components: list[AnswerComponent] = []

    if archetype in ("distribution", "cross_tabulation"):
        components = [
            AnswerComponent(
                componentId=f"{base_id}_tbl",
                renderOrder=0,
                type="data_table",
                suggestedConstraints={"table_max_rows": 20, "precision": 1},
            ),
            AnswerComponent(
                componentId=f"{base_id}_chart",
                renderOrder=1,
                type="chart",
                suggestedConstraints={"chart_type": "stacked_bar", "max_categories": 10},
            ),
            AnswerComponent(
                componentId=f"{base_id}_narr",
                renderOrder=2,
                type="narrative_paragraph",
                suggestedConstraints={"max_words": 150, "style": "analytical"},
            ),
        ]
        layout_type = "multi-panel"
    elif archetype == "rate":
        components = [
            AnswerComponent(
                componentId=f"{base_id}_kpi",
                renderOrder=0,
                type="kpi_card",
                suggestedConstraints={"precision": 1, "unit": "%"},
            ),
            AnswerComponent(
                componentId=f"{base_id}_tbl",
                renderOrder=1,
                type="data_table",
                suggestedConstraints={"table_max_rows": 15, "precision": 1},
            ),
            AnswerComponent(
                componentId=f"{base_id}_narr",
                renderOrder=2,
                type="narrative_paragraph",
                suggestedConstraints={"max_words": 120, "style": "comparative"},
            ),
        ]
        layout_type = "split"
    elif archetype == "trend":
        components = [
            AnswerComponent(
                componentId=f"{base_id}_chart",
                renderOrder=0,
                type="chart",
                suggestedConstraints={"chart_type": "line", "show_trend_line": True},
            ),
            AnswerComponent(
                componentId=f"{base_id}_tbl",
                renderOrder=1,
                type="data_table",
                suggestedConstraints={"table_max_rows": 12, "precision": 1},
            ),
            AnswerComponent(
                componentId=f"{base_id}_narr",
                renderOrder=2,
                type="narrative_paragraph",
                suggestedConstraints={"max_words": 100, "style": "trend_analysis"},
            ),
        ]
        layout_type = "split"
    elif archetype == "state_level":
        components = [
            AnswerComponent(
                componentId=f"{base_id}_tbl",
                renderOrder=0,
                type="data_table",
                suggestedConstraints={"table_max_rows": 40, "precision": 1},
            ),
            AnswerComponent(
                componentId=f"{base_id}_narr",
                renderOrder=1,
                type="narrative_paragraph",
                suggestedConstraints={"max_words": 200, "style": "geographic_comparison"},
            ),
        ]
        layout_type = "single"
    else:
        components = [
            AnswerComponent(
                componentId=f"{base_id}_tbl",
                renderOrder=0,
                type="data_table",
                suggestedConstraints={"table_max_rows": 20},
            ),
            AnswerComponent(
                componentId=f"{base_id}_narr",
                renderOrder=1,
                type="narrative_paragraph",
                suggestedConstraints={"max_words": 150},
            ),
        ]
        layout_type = "single"

    return AnswerStructure(layoutType=layout_type, components=components)


# ---------------------------------------------------------------------------
# Full PLFS extraction pipeline
# ---------------------------------------------------------------------------

def extract_plfs_questions(
    pages: list[VLMPageResult],
) -> tuple[list[TopicNode], list[TemplateEntity]]:
    """Full PLFS extraction: detect statements → classify → generate questions.

    Returns:
        (topics, entities) ready to merge into the main pipeline.
    """
    glossary = _load_glossary()
    detections = detect_plfs_statements(pages)

    if not detections:
        logger.info("No PLFS statements found — not a PLFS document")
        return [], []

    # Group statements by chapter → topics
    chapters: dict[int, list[dict[str, Any]]] = {}
    for det in detections:
        chapters.setdefault(det["chapter"], []).append(det)

    all_entities: list[TemplateEntity] = []
    topics: list[TopicNode] = []

    chapter_names = {
        1: "Introduction and Survey Design",
        2: "Key Labour Force Indicators",
        3: "Activity Status Distribution",
        4: "Employment and Unemployment",
        5: "Labour Force Participation Rates",
        6: "Industry and Occupation",
        7: "State-Level Estimates",
        8: "Special Topics",
    }

    for chapter_num, statements in sorted(chapters.items()):
        chapter_title = chapter_names.get(chapter_num, f"Chapter {chapter_num}")
        topic_id = f"topic_plfs_ch{chapter_num}"

        questions: list[QuestionNode] = []
        for det in statements:
            # Extract entities from statement title
            stmt_entities = extract_entities_from_statement(
                det["title"], det["chapter"], det["sequence"],
                det["page_index"], glossary,
            )
            all_entities.extend(stmt_entities)

            # Generate question
            question = statement_to_question(det, stmt_entities, glossary)
            questions.append(question)

        # Determine page range for this topic
        page_indices = sorted(set(d["page_index"] for d in statements))

        topics.append(TopicNode(
            topicId=topic_id,
            title=chapter_title,
            questions=questions,
            pageRange=page_indices,
        ))

    logger.info(
        "PLFS extraction: %d chapters, %d statements, %d entities",
        len(topics), len(detections), len(all_entities),
    )
    return topics, all_entities
