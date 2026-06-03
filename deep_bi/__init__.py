"""Research-grade Deep BI.

A user query passes through:

    intent_parser.IntentParser
        -> emits concepts + question_type + metrics_needed, NOT raw columns
    column_synonym_kg.ColumnSynonymKG
        -> resolves concepts to concrete dataset columns via a synonym graph
    reasoning_engine.ReasoningEngine
        -> multi-hop concept traversal (Education -> Income -> Employment)
    analytics_planner.AnalyticsPlanner
        -> compiles a multi-step computation plan (aggregate, normalize,
           ratio, rank, outlier, ...) BEFORE any compute happens
    analytics_executor.AnalyticsExecutor
        -> runs the plan against the DataFrame and the KG, returning facts
           bound to row_ids (no aggregate is anonymous)
    evidence_ledger.EvidenceLedger
        -> writes every claim with its supporting row_ids + computation
    verifier.ClaimVerifier (existing module)
        -> recomputes each claim independently
    confidence_scorer.ConfidenceScorer
        -> rolls up evidence + verifier into a calibrated 0..1 score
    response_builder.ResponseBuilder
        -> packages narrative + reasoning_path + evidence + blocks for the UI
"""

from .intent_parser import IntentParser, ParsedIntent
from .column_synonym_kg import ColumnSynonymKG, ColumnMatch
from .reasoning_engine import ReasoningEngine, ReasoningPath
from .analytics_planner import AnalyticsPlanner, AnalyticsPlan, AnalyticsStep
from .analytics_executor import AnalyticsExecutor, AnalyticsExecution
from .evidence_ledger import EvidenceLedger, EvidenceRecord
from .confidence_scorer import ConfidenceScorer
from .response_builder import ResponseBuilder, DeepBIResponse

__all__ = [
    "IntentParser", "ParsedIntent",
    "ColumnSynonymKG", "ColumnMatch",
    "ReasoningEngine", "ReasoningPath",
    "AnalyticsPlanner", "AnalyticsPlan", "AnalyticsStep",
    "AnalyticsExecutor", "AnalyticsExecution",
    "EvidenceLedger", "EvidenceRecord",
    "ConfidenceScorer",
    "ResponseBuilder", "DeepBIResponse",
]
