"""ConsensusEngine — Scribe → Verifier loop until block passes or max retries.

Flow:
  1. ScribeAgent generates narrative from facts + reflections.
  2. VerifierAgent verifies all numeric claims.
  3. If verdict == 'fail':
       - Build a repair prompt listing failed claims + their computed values.
       - ScribeAgent regenerates with the correction context.
       - Repeat up to MAX_RETRIES times.
  4. If verdict == 'warn':
       - Accept but flag block as "soft warning" in the canvas.
  5. If verdict == 'pass':
       - Accept block.

After MAX_RETRIES, emit the deterministic fallback narrative.
This ensures every published block is deterministic and auditable even when
LLM generation fails repeatedly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from agents.scribe_agent import ScribeAgent, _deterministic_narrative
from agents.verifier_agent import VerifierAgent, VerifierVerdict

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


@dataclass
class ConsensuResult:
    block_id: str
    narrative: str
    verdict: VerifierVerdict
    attempts: int
    accepted: bool
    fallback_used: bool = False


def _repair_context(verdict: VerifierVerdict) -> str:
    """Build a repair note for failed/unverified claims."""
    lines: list[str] = [
        "CORRECTION REQUIRED — the following numeric claims were incorrect or unverified:"
    ]
    for c in verdict.checks:
        if c.status in ("fail", "unverified"):
            if c.status == "fail" and c.computed_value is not None:
                lines.append(
                    f"  • Claimed: '{c.raw}' ({c.claimed_value}) "
                    f"— Actual: {c.computed_value:.3f}. "
                    f"Use {c.computed_value:.3f} or remove this claim."
                )
            else:
                lines.append(
                    f"  • '{c.raw}' ({c.claimed_value}) has no data source. "
                    "Remove this number or replace with '(data unavailable)'."
                )
    return "\n".join(lines)


class ConsensusEngine:
    """Orchestrates Scribe + Verifier with retry loop."""

    def __init__(
        self,
        scribe: ScribeAgent | None = None,
        verifier: VerifierAgent | None = None,
    ):
        self._scribe = scribe or ScribeAgent()
        self._verifier = verifier or VerifierAgent()

    def run(
        self,
        *,
        block_id: str,
        block_title: str,
        block_section: str,
        hints: dict[str, Any],
        facts: dict[str, Any],
        reflections: list[dict[str, Any]] | None = None,
        df: pd.DataFrame | None = None,
        dataset_type: str = "unknown",
    ) -> ConsensuResult:
        """Generate + verify narrative, retrying on failure."""
        _reflections = list(reflections or [])
        max_words = int(hints.get("max_words", 250))
        attempts = 0

        while attempts < MAX_RETRIES:
            attempts += 1

            narrative = self._scribe.generate(
                block_id=block_id,
                block_title=block_title,
                block_section=block_section,
                hints=hints,
                facts=facts,
                reflections=_reflections,
                dataset_type=dataset_type,
            )

            verdict = self._verifier.verify(
                block_id=block_id,
                narrative=narrative,
                facts=facts,
                df=df,
            )

            if verdict.overall_status == "pass":
                logger.info("[%s] consensus pass on attempt %s", block_id, attempts)
                return ConsensuResult(
                    block_id=block_id,
                    narrative=narrative,
                    verdict=verdict,
                    attempts=attempts,
                    accepted=True,
                )

            if verdict.overall_status == "warn":
                logger.info("[%s] consensus warn on attempt %s (accepted)", block_id, attempts)
                return ConsensuResult(
                    block_id=block_id,
                    narrative=narrative,
                    verdict=verdict,
                    attempts=attempts,
                    accepted=True,
                )

            # verdict == 'fail': inject repair context and retry
            repair_note = _repair_context(verdict)
            logger.warning(
                "[%s] consensus fail on attempt %s; retrying with repair",
                block_id, attempts,
            )
            # Add repair note to reflections so scribe can see it
            _reflections.append({
                "context": f"attempt_{attempts}_failure",
                "before": narrative[:200],
                "after": repair_note,
            })

        # Exhausted retries: deterministic fallback
        logger.warning("[%s] consensus exhausted %s retries; using fallback", block_id, MAX_RETRIES)
        fallback = _deterministic_narrative(
            block_title=block_title,
            block_section=block_section,
            facts=facts,
            max_words=max_words,
            dataset_type=dataset_type,
        )
        fallback_verdict = self._verifier.verify(
            block_id=block_id,
            narrative=fallback,
            facts=facts,
            df=df,
        )
        return ConsensuResult(
            block_id=block_id,
            narrative=fallback,
            verdict=fallback_verdict,
            attempts=attempts,
            accepted=True,
            fallback_used=True,
        )


def run_consensus(
    *,
    block_id: str,
    block_title: str,
    block_section: str,
    hints: dict[str, Any],
    facts: dict[str, Any],
    reflections: list[dict[str, Any]] | None = None,
    df: pd.DataFrame | None = None,
    dataset_type: str = "unknown",
) -> ConsensuResult:
    """Module-level convenience function."""
    engine = ConsensusEngine()
    return engine.run(
        block_id=block_id,
        block_title=block_title,
        block_section=block_section,
        hints=hints,
        facts=facts,
        reflections=reflections,
        df=df,
        dataset_type=dataset_type,
    )
