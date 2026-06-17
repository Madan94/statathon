from typing import Any, Literal

from pydantic import BaseModel, Field

DecisionAction = Literal["keep", "delete", "normalize"]
OutlierMethod = Literal["Z_SCORE", "IQR"]
OutlierRowDecision = Literal["KEEP", "NORMALIZE", "DELETE_VALUE", "DELETE_ROW", "EDIT_VALUE"]


class AnalysisDecisionsRequest(BaseModel):
    decisions: dict[str, DecisionAction] = Field(default_factory=dict)


class OutlierMethodSelectRequest(BaseModel):
    column: str
    method: OutlierMethod


class OutlierDetectRequest(BaseModel):
    column: str
    method: OutlierMethod | None = None


class OutlierRowDecisionItem(BaseModel):
    row_index: int
    method: str = ""
    severity: str = ""
    decision: OutlierRowDecision
    old_value: str | float | int | None = None
    new_value: str | float | int | None = None


class OutlierRowDecisionsRequest(BaseModel):
    column: str
    decisions: list[OutlierRowDecisionItem] = Field(default_factory=list)


class ValidationAcknowledgeRequest(BaseModel):
    critical_count: int = 0
    candidate_count: int = 0


class ValidationDecisionItem(BaseModel):
    rule_id: str = "unknown"
    column: str
    row_index: int | None = None
    rule_type: str = "single"
    severity: str = "MEDIUM"
    confidence: float = 0.7
    decision: str
    old_value: str | float | int | None = None
    new_value: str | float | int | None = None


class ValidationDecisionsRequest(BaseModel):
    decisions: list[ValidationDecisionItem] = Field(default_factory=list)


class ValidationProceedRequest(BaseModel):
    decisions: list[ValidationDecisionItem] = Field(default_factory=list)
    critical_count: int = 0
    candidate_count: int = 0


class ValidationCandidatesPageResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


class ImputationMethodRequest(BaseModel):
    column: str
    method: str


class ImputationDecisionsRequest(BaseModel):
    column: str
    method: str
    decisions: list[dict[str, Any]] = Field(default_factory=list)


class NormalizationColumnUpdate(BaseModel):
    original_name: str = Field(..., max_length=512)
    normalized_name: str | None = Field(None, max_length=512)
    is_deleted: bool = False
    is_excluded: bool = False


class NormalizationSaveRequest(BaseModel):
    columns: list[NormalizationColumnUpdate] = Field(default_factory=list)
