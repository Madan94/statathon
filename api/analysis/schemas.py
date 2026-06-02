from typing import Literal

from pydantic import BaseModel, Field

DecisionAction = Literal["keep", "delete", "normalize"]


class AnalysisDecisionsRequest(BaseModel):
    decisions: dict[str, DecisionAction] = Field(default_factory=dict)


class NormalizationColumnUpdate(BaseModel):
    original_name: str = Field(..., max_length=512)
    normalized_name: str | None = Field(None, max_length=512)
    is_deleted: bool = False
    is_excluded: bool = False


class NormalizationSaveRequest(BaseModel):
    columns: list[NormalizationColumnUpdate] = Field(default_factory=list)
