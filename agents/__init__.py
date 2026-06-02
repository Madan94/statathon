"""Agents — 6-agent Government Statistical DeepAgent system.

  PlannerAgent   — intent classification + task decomposition
  RetrievalAgent — dataset / KG / rulebooks / history / phase3
  AnalyticsAgent — correlation, trend, forecast, stat tests, aggregation
  ScribeAgent    — grounded narrative generation (Gemini + deterministic fallback)
  VerifierAgent  — multi-pass factual verification against dataset
  ConsensusEngine — orchestrates Scribe/Verifier retry loop
  DeepAgent      — orchestrator wiring all 6 agents
"""
from agents.scribe_agent import ScribeAgent
from agents.verifier_agent import VerifierAgent
from agents.consensus_engine import ConsensusEngine, run_consensus
from agents.planner_agent import PlannerAgent, ExecutionPlan
from agents.retrieval_agent import RetrievalAgent, RetrievalBundle
from agents.analytics_agent import AnalyticsAgent, AnalyticsResult
from agents.deep_agent import DeepAgent, DeepAgentTurn

__all__ = [
    "ScribeAgent", "VerifierAgent", "ConsensusEngine", "run_consensus",
    "PlannerAgent", "ExecutionPlan",
    "RetrievalAgent", "RetrievalBundle",
    "AnalyticsAgent", "AnalyticsResult",
    "DeepAgent", "DeepAgentTurn",
]
