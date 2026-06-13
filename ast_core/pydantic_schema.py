"""Pydantic v2 models mirroring the deep template AST schema.

These models serve two purposes:
  1. Grammar-Constrained Decoding — exported as JSON Schema for SGLang to enforce
     valid output structure during LLM generation.
  2. Validation — incoming AST payloads from VLM/LLM are validated before
     being converted to dataclass instances.

Usage:
  from ast_core.pydantic_schema import TemplateBlueprintModel
  schema = TemplateBlueprintModel.model_json_schema()  # → dict for SGLang
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ComponentType(str, Enum):
    narrative_paragraph = "narrative_paragraph"
    grouped_bar_chart = "grouped_bar_chart"
    line_chart = "line_chart"
    pie_chart = "pie_chart"
    data_table = "data_table"
    metric_card = "metric_card"
    list_bullets = "list_bullets"
    heading = "heading"
    cross_tabulation_matrix = "cross_tabulation_matrix"
    formula_block = "formula_block"
    geographic_map = "geographic_map"


class EntityType(str, Enum):
    dimension = "dimension"
    measure = "measure"
    filter = "filter"
    metadata = "metadata"


class EntitySourceType(str, Enum):
    table_header = "table_header"
    chart_axis = "chart_axis"
    chart_legend = "chart_legend"
    section_heading = "section_heading"
    narrative_term = "narrative_term"
    footnote = "footnote"
    formula_variable = "formula_variable"


class QuestionType(str, Enum):
    comparison = "comparison"
    distribution = "distribution"
    trend = "trend"
    composition = "composition"
    correlation = "correlation"
    ranking = "ranking"
    describe = "describe"


class InferenceMethod(str, Enum):
    vlm = "vlm"
    hybrid = "hybrid"
    pattern = "pattern"
    stub = "stub"


class BindingRole(str, Enum):
    required = "required"
    optional = "optional"
    filter = "filter"
    grouping = "grouping"


class BindingMethod(str, Enum):
    auto = "auto"
    vlm = "vlm"
    pattern = "pattern"
    human = "human"


class LayoutType(str, Enum):
    single = "single"
    split = "split"
    multi_panel = "multi-panel"
    full_page = "full-page"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class BBoxModel(BaseModel):
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0


class AnswerComponentRefModel(BaseModel):
    layoutRef: str = ""
    geometryRef: str = ""
    figureRef: str = ""
    chartRef: str = ""
    tableRef: str = ""
    styleRef: str = ""
    contentRef: str = ""
    entityRefs: list[str] = Field(default_factory=list)
    factRefs: list[str] = Field(default_factory=list)
    evidenceRef: str = ""
    citationRef: str = ""
    analyticsRef: str = ""


class AnswerComponentModel(BaseModel):
    componentId: str
    renderOrder: int = 0
    type: ComponentType = ComponentType.narrative_paragraph
    constraints: dict[str, Any] = Field(default_factory=dict)
    refs: AnswerComponentRefModel = Field(default_factory=AnswerComponentRefModel)
    bbox: BBoxModel | None = None


class AnswerStructureModel(BaseModel):
    layoutType: LayoutType = LayoutType.single
    components: list[AnswerComponentModel] = Field(default_factory=list)


class TemplateEntityModel(BaseModel):
    entityId: str
    name: str = ""
    entityType: EntityType = EntityType.dimension
    sourceType: EntitySourceType = EntitySourceType.table_header
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    aliases: list[str] = Field(default_factory=list)
    pageIndex: int = -1
    sourceContext: str = ""


class QuestionEntityBindingModel(BaseModel):
    entityId: str
    role: BindingRole = BindingRole.required
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    bindingMethod: BindingMethod = BindingMethod.auto


class QuestionNodeModel(BaseModel):
    questionId: str
    intent: str = ""
    questionType: QuestionType = QuestionType.comparison
    inferenceMethod: InferenceMethod = InferenceMethod.vlm
    inferenceConfidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requiredEntities: list[QuestionEntityBindingModel] = Field(default_factory=list)
    answerStructure: AnswerStructureModel = Field(default_factory=AnswerStructureModel)
    pageIndex: int = -1
    sourceHeading: str = ""


class TopicNodeModel(BaseModel):
    topicId: str
    title: str = ""
    description: str = ""
    questions: list[QuestionNodeModel] = Field(default_factory=list)
    pageRange: list[int] = Field(default_factory=list)


class TemplateBlueprintModel(BaseModel):
    """Master Pydantic model for grammar-constrained AST generation.

    Export JSON schema via:
        TemplateBlueprintModel.model_json_schema()
    """
    templateId: str = ""
    name: str = ""
    sourceHash: str = ""
    pageCount: int = 0
    extractionMethod: str = "colpali+sglang"
    topics: list[TopicNodeModel] = Field(default_factory=list)
    entities: list[TemplateEntityModel] = Field(default_factory=list)
    extractionMeta: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def blueprint_model_to_dataclass(model: TemplateBlueprintModel):
    """Convert validated Pydantic model to ast_core dataclass instance."""
    from ast_core.schema import TemplateBlueprintAST
    return TemplateBlueprintAST.from_dict(model.model_dump(mode="python"))


def export_json_schema() -> dict[str, Any]:
    """Export the full JSON schema for SGLang grammar-constrained generation."""
    return TemplateBlueprintModel.model_json_schema()
