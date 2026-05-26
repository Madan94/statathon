"""Agents — Phase 4/5: Scribe → Verifier → Consensus pipeline.

  ScribeAgent    — grounded narrative generation (Gemini + deterministic fallback)
  VerifierAgent  — multi-pass factual verification against dataset
  ConsensusEngine — orchestrates Scribe/Verifier loops until block passes
"""
from agents.scribe_agent import ScribeAgent
from agents.verifier_agent import VerifierAgent
from agents.consensus_engine import ConsensusEngine, run_consensus

__all__ = ["ScribeAgent", "VerifierAgent", "ConsensusEngine", "run_consensus"]
