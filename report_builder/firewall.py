"""Phase 4 — Hallucination Firewall.

Wraps the ScribeAgent + VerifierAgent + ConsensusEngine from `agents/`.
Provides the same public interface (`scribe_narrative`, `verify_block`) that
`report_builder/pipeline.py` calls, now backed by the full consensus loop.

Additions over the original implementation:
  - MoSPI dataset-type vocabulary applied by ScribeAgent
  - Multi-pass verification with retry (ConsensusEngine)
  - Reflection ledger consulted before generation
  - Block-level fallback_used flag propagated to canvas
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from agents.scribe_agent import ScribeAgent, _deterministic_narrative
from agents.verifier_agent import VerifierAgent, VerifierVerdict
from agents.consensus_engine import ConsensusEngine, ConsensuResult
from report_builder import kernel as kx

logger = logging.getLogger(__name__)

# Singletons (one per worker process)
_scribe = ScribeAgent()
_verifier = VerifierAgent()
_consensus = ConsensusEngine(scribe=_scribe, verifier=_verifier)


# ---------------------------------------------------------------------------
# Public interface (backward-compatible with pipeline.py)
# ---------------------------------------------------------------------------

def scribe_narrative(
    *,
    block_id: str,
    block_title: str,
    block_section: str,
    hints: dict[str, Any],
    facts: dict[str, Any],
    reflections: list[dict[str, Any]] | None = None,
    dataset_type: str | None = None,
) -> str:
    """Generate a grounded narrative. Delegates to ConsensusEngine."""
    _dt = dataset_type or str(facts.get("dataset_type") or "unknown")
    result: ConsensuResult = _consensus.run(
        block_id=block_id,
        block_title=block_title,
        block_section=block_section,
        hints=hints,
        facts=facts,
        reflections=reflections,
        dataset_type=_dt,
    )
    if result.fallback_used:
        logger.warning(
            "[%s] Fallback narrative used after %s attempts", block_id, result.attempts
        )
    return result.narrative


def verify_block(
    *,
    block_id: str,
    narrative: str,
    df: pd.DataFrame | None,
    expected_facts: dict[str, Any],
) -> VerifierVerdict:
    """Verify all numeric claims in a narrative block."""
    return _verifier.verify(
        block_id=block_id,
        narrative=narrative,
        facts=expected_facts,
        df=df,
    )


# ---------------------------------------------------------------------------
# Re-export VerifierVerdict so callers can import it from here
# ---------------------------------------------------------------------------

__all__ = [
    "scribe_narrative",
    "verify_block",
    "VerifierVerdict",
]
