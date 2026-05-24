from typing import Literal

from pydantic import BaseModel, Field

DecisionAction = Literal["keep", "delete", "normalize"]


class AnalysisDecisionsRequest(BaseModel):
    decisions: dict[str, DecisionAction] = Field(default_factory=dict)
