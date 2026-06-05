"""Question Inferrer — cascade pipeline for inferring analytical questions.

Cascade order (first above confidence threshold wins):
  1. VLM Direct — ColPali infers question from visual context
  2. Hybrid — structure from VLM + LLM reasoning (Gemini/Qwen)
  3. Pattern — predefined MoSPI question templates matched to structure
  4. Stub — generic question derived from heading text alone

Each inferrer returns (question_text, confidence, method).
"""
from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC, abstractmethod
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
    BBox,
)
from template_engine.vlm.schemas import VLMPageResult, VLMRegion, VLMChartData, VLMTableData

logger = logging.getLogger(__name__)

# Minimum confidence to accept a question from the cascade
_CONFIDENCE_THRESHOLD = 0.3


class QuestionInferrer(ABC):
    """Abstract base for question inference backends."""

    @abstractmethod
    def infer(self, page: VLMPageResult, region: VLMRegion,
              entities: list[TemplateEntity]) -> tuple[str, float] | None:
        """Infer analytical question from a visual region.

        Returns:
            (question_intent, confidence) or None if cannot infer.
        """
        ...

    @property
    @abstractmethod
    def method_name(self) -> str:
        ...


class PatternInferrer(QuestionInferrer):
    """Infers questions using predefined MoSPI question pattern templates."""

    def __init__(self):
        self._patterns = self._load_patterns()

    @property
    def method_name(self) -> str:
        return "pattern"

    def infer(self, page: VLMPageResult, region: VLMRegion,
              entities: list[TemplateEntity]) -> tuple[str, float] | None:
        heading = region.text.strip().lower()

        for pattern in self._patterns:
            for trigger in pattern.get("triggers", []):
                if trigger.lower() in heading:
                    # Fill template with extracted context
                    question = pattern["template"]
                    question = question.replace("{heading}", region.text.strip())

                    # Fill entity placeholders
                    dims = [e.name for e in entities if e.entityType == "dimension"]
                    measures = [e.name for e in entities if e.entityType == "measure"]
                    if dims:
                        question = question.replace("{dimension}", dims[0])
                    if measures:
                        question = question.replace("{measure}", measures[0])

                    return question, pattern.get("confidence", 0.65)

        return None

    def _load_patterns(self) -> list[dict[str, Any]]:
        """Load patterns from JSON file or use built-in defaults."""
        patterns_file = Path(__file__).parent / "patterns" / "mospi_patterns.json"
        if patterns_file.exists():
            try:
                return json.loads(patterns_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return _DEFAULT_PATTERNS


class HybridInferrer(QuestionInferrer):
    """Uses VLM structure + separate LLM (Gemini) to infer questions."""

    @property
    def method_name(self) -> str:
        return "hybrid"

    def infer(self, page: VLMPageResult, region: VLMRegion,
              entities: list[TemplateEntity]) -> tuple[str, float] | None:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return None

        # Support both current google-genai SDK and legacy google-generativeai
        try:
            import google.genai as genai_new  # type: ignore  # noqa: F401
            _use_new_sdk = True
        except ImportError:
            try:
                import google.generativeai as genai  # type: ignore  # noqa: F401
                _use_new_sdk = False
            except ImportError:
                return None

        try:
            model_name = os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash")
            if _use_new_sdk:
                import google.genai as genai_new  # type: ignore
                client = genai_new.Client(api_key=api_key)
                # Thin wrapper: generate_content equivalent
                _generate = lambda prompt: client.models.generate_content(
                    model=model_name, contents=prompt
                ).text
            else:
                import google.generativeai as genai  # type: ignore
                genai.configure(api_key=api_key)
                _model = genai.GenerativeModel(model_name)
                _generate = lambda prompt: (_model.generate_content(prompt).text or "")

            # Build context
            entity_names = [e.name for e in entities[:10]]
            context = {
                "heading": region.text,
                "role": region.role,
                "page_has_tables": page.has_tables,
                "page_has_charts": page.has_charts,
                "entities_on_page": entity_names,
                "chart_info": [c.to_dict() for c in page.charts[:3]],
                "table_headers": [t.headers for t in page.tables[:3]],
            }

            prompt = (
                "You are a data analyst reviewing a government statistical report section. "
                "Given the following extracted context from a PDF page, infer the analytical "
                "question that this section is answering.\n\n"
                f"Context: {json.dumps(context, indent=2)}\n\n"
                "Return ONLY the analytical question as a single sentence. "
                "The question should be specific enough to be answered by a BI query. "
                "Examples: 'Compare monthly per capita expenditure across states by sector', "
                "'What is the distribution of household size in rural areas?'\n\n"
                "Question:"
            )

            question = (_generate(prompt) or "").strip().strip('"').strip("'")

            if question and len(question) > 10:
                return question, 0.80

        except Exception as exc:
            logger.debug("Hybrid inference failed: %s", exc)

        return None


class StubInferrer(QuestionInferrer):
    """Generates generic questions from heading text — always succeeds."""

    @property
    def method_name(self) -> str:
        return "stub"

    def infer(self, page: VLMPageResult, region: VLMRegion,
              entities: list[TemplateEntity]) -> tuple[str, float] | None:
        heading = region.text.strip()
        if not heading:
            return None

        # Convert heading to question form
        heading_lower = heading.lower()

        if any(kw in heading_lower for kw in ("distribution", "pattern", "composition")):
            question = f"What is the {heading.lower()}?"
        elif any(kw in heading_lower for kw in ("comparison", "vs", "versus", "difference")):
            question = f"How do the groups compare in terms of {heading.lower()}?"
        elif any(kw in heading_lower for kw in ("trend", "growth", "change", "over time")):
            question = f"What is the trend in {heading.lower()}?"
        elif "by" in heading_lower:
            question = f"Analyze {heading.lower()}"
        else:
            question = f"Describe the {heading.lower()}"

        return question, 0.40


# ---------------------------------------------------------------------------
# Cascade orchestrator
# ---------------------------------------------------------------------------

def _determine_question_type(region: VLMRegion, page: VLMPageResult) -> str:
    """Infer question type from visual context."""
    heading = region.text.lower()

    if any(kw in heading for kw in ("trend", "growth", "over time", "time series")):
        return "trend"
    if any(kw in heading for kw in ("vs", "versus", "comparison", "compare", "difference")):
        return "comparison"
    if any(kw in heading for kw in ("distribution", "spread", "pattern")):
        return "distribution"
    if any(kw in heading for kw in ("composition", "share", "proportion", "breakdown")):
        return "composition"
    if any(kw in heading for kw in ("rank", "top", "bottom", "highest", "lowest")):
        return "ranking"
    if any(kw in heading for kw in ("correlation", "relationship", "association")):
        return "correlation"

    # Infer from page content
    if page.has_charts:
        for chart in page.charts:
            if chart.chartType in ("line",):
                return "trend"
            if chart.chartType in ("pie",):
                return "composition"
            if chart.chartType in ("grouped_bar", "bar"):
                return "comparison"

    return "describe"


def _build_answer_structure(page: VLMPageResult, region: VLMRegion,
                            question_type: str) -> AnswerStructure:
    """Build answer structure from visual context on the page."""
    components: list[AnswerComponent] = []
    comp_counter = 0

    # Always start with a narrative paragraph
    comp_counter += 1
    components.append(AnswerComponent(
        componentId=f"comp_{comp_counter:03d}",
        renderOrder=comp_counter,
        type="narrative_paragraph",
        constraints={"max_words": 150, "verify_numbers": True},
        refs=AnswerComponentRef(),
        bbox=None,
    ))

    # Add chart component if charts present
    for chart in page.charts:
        comp_counter += 1
        chart_type_map = {
            "bar": "grouped_bar_chart",
            "grouped_bar": "grouped_bar_chart",
            "stacked_bar": "grouped_bar_chart",
            "line": "line_chart",
            "pie": "pie_chart",
            "scatter": "line_chart",
        }
        comp_type = chart_type_map.get(chart.chartType, "grouped_bar_chart")
        constraints: dict[str, Any] = {}
        if chart.xAxis:
            constraints["x_axis"] = chart.xAxis
        if chart.yAxis:
            constraints["y_axis"] = chart.yAxis
        if chart.legendItems:
            constraints["grouping"] = chart.legendItems

        # Find bbox from chart region
        bbox = None
        for r in page.regions:
            if r.regionId == chart.regionId:
                bbox = BBox(x=r.bbox.x0, y=r.bbox.y0,
                            width=r.bbox.width, height=r.bbox.height)
                break

        components.append(AnswerComponent(
            componentId=f"comp_{comp_counter:03d}",
            renderOrder=comp_counter,
            type=comp_type,
            constraints=constraints,
            refs=AnswerComponentRef(chartRef=chart.regionId),
            bbox=bbox,
        ))

    # Add table component if tables present
    for table in page.tables:
        comp_counter += 1
        constraints = {
            "columns": table.headers,
            "max_rows": len(table.rows),
        }
        components.append(AnswerComponent(
            componentId=f"comp_{comp_counter:03d}",
            renderOrder=comp_counter,
            type="data_table",
            constraints=constraints,
            refs=AnswerComponentRef(tableRef=table.regionId),
        ))

    # Determine layout type
    layout_type = "single"
    if len(components) >= 3:
        layout_type = "multi-panel"
    elif len(components) == 2:
        layout_type = "split"

    return AnswerStructure(layoutType=layout_type, components=components)


def _bind_entities_to_question(page: VLMPageResult, region: VLMRegion,
                               entities: list[TemplateEntity]) -> list[QuestionEntityBinding]:
    """Auto-bind relevant entities to the question based on proximity and relevance."""
    bindings: list[QuestionEntityBinding] = []

    # Entities from the same page are candidates
    page_entities = [e for e in entities if e.pageIndex == page.pageIndex]

    for ent in page_entities:
        # Determine binding role
        if ent.entityType == "dimension":
            role = "grouping" if ent.sourceType == "chart_legend" else "required"
        elif ent.entityType == "filter":
            role = "filter"
        else:
            role = "required"

        bindings.append(QuestionEntityBinding(
            entityId=ent.entityId,
            role=role,
            confidence=ent.confidence * 0.9,  # slight reduction for auto-binding
            bindingMethod="auto",
        ))

    return bindings


def infer_questions(pages: list[VLMPageResult],
                    entities: list[TemplateEntity]) -> list[TopicNode]:
    """Main cascade: infer questions from VLM pages and group into topics.

    Args:
        pages: VLM extraction results per page.
        entities: Extracted and deduplicated entities.

    Returns:
        List of TopicNode containing nested QuestionNodes.
    """
    # Build inferrer cascade
    inferrers: list[QuestionInferrer] = [
        HybridInferrer(),
        PatternInferrer(),
        StubInferrer(),
    ]

    # Group pages into topics by heading hierarchy
    topics: list[TopicNode] = []
    current_topic: TopicNode | None = None
    question_counter = 0
    topic_counter = 0

    for page in pages:
        # Find heading regions that could anchor questions
        heading_regions = [
            r for r in page.regions
            if r.role in ("heading_h1", "heading_h2", "title")
            and len(r.text.strip()) > 3
        ]

        for region in heading_regions:
            # H1 headings start new topics
            if region.role in ("heading_h1", "title"):
                topic_counter += 1
                current_topic = TopicNode(
                    topicId=f"topic_{topic_counter:03d}",
                    title=region.text.strip(),
                    description="",
                    questions=[],
                    pageRange=[page.pageIndex],
                )
                topics.append(current_topic)

            # Ensure we have a topic
            if current_topic is None:
                topic_counter += 1
                current_topic = TopicNode(
                    topicId=f"topic_{topic_counter:03d}",
                    title=region.text.strip(),
                    questions=[],
                    pageRange=[page.pageIndex],
                )
                topics.append(current_topic)

            # Update page range
            if page.pageIndex not in current_topic.pageRange:
                current_topic.pageRange.append(page.pageIndex)

            # Run inference cascade
            intent: str | None = None
            confidence = 0.0
            method = "stub"

            for inferrer in inferrers:
                result = inferrer.infer(page, region, entities)
                if result and result[1] >= _CONFIDENCE_THRESHOLD:
                    intent, confidence = result
                    method = inferrer.method_name
                    break

            if not intent:
                continue

            # Build question
            question_counter += 1
            question_type = _determine_question_type(region, page)
            answer_structure = _build_answer_structure(page, region, question_type)
            entity_bindings = _bind_entities_to_question(page, region, entities)

            question = QuestionNode(
                questionId=f"Q_{question_counter:04d}",
                intent=intent,
                questionType=question_type,
                inferenceMethod=method,
                inferenceConfidence=confidence,
                requiredEntities=entity_bindings,
                answerStructure=answer_structure,
                pageIndex=page.pageIndex,
                sourceHeading=region.text.strip(),
            )
            current_topic.questions.append(question)

    logger.info(
        "Inferred %d questions across %d topics from %d pages",
        question_counter, len(topics), len(pages),
    )
    return topics


# ---------------------------------------------------------------------------
# Default patterns (built-in when mospi_patterns.json doesn't exist)
# ---------------------------------------------------------------------------

_DEFAULT_PATTERNS: list[dict[str, Any]] = [
    {
        "triggers": ["consumption expenditure", "mpce", "household expenditure"],
        "template": "Compare {measure} across {dimension} categories",
        "confidence": 0.70,
    },
    {
        "triggers": ["distribution", "spread", "breakdown"],
        "template": "What is the distribution of {heading}?",
        "confidence": 0.65,
    },
    {
        "triggers": ["rural vs urban", "rural and urban", "sector-wise"],
        "template": "Compare {measure} between rural and urban sectors",
        "confidence": 0.72,
    },
    {
        "triggers": ["state-wise", "by state", "across states"],
        "template": "Analyze {measure} variation across states",
        "confidence": 0.70,
    },
    {
        "triggers": ["trend", "growth", "over the years", "time series"],
        "template": "What is the trend in {heading} over time?",
        "confidence": 0.68,
    },
    {
        "triggers": ["employment", "unemployment", "workforce"],
        "template": "Analyze employment patterns by {dimension}",
        "confidence": 0.67,
    },
    {
        "triggers": ["literacy", "education", "enrollment"],
        "template": "Compare education metrics across {dimension} groups",
        "confidence": 0.66,
    },
    {
        "triggers": ["health", "mortality", "morbidity", "nutrition"],
        "template": "Analyze health indicators by {dimension}",
        "confidence": 0.66,
    },
    {
        "triggers": ["poverty", "inequality", "gini"],
        "template": "Measure poverty and inequality across {dimension}",
        "confidence": 0.68,
    },
    {
        "triggers": ["population", "demographic", "census"],
        "template": "Describe population distribution by {dimension}",
        "confidence": 0.65,
    },
]
