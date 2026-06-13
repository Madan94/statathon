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

# Adaptive retry budget based on priority
_PRIORITY_RETRY_MAP = {
    "high": 4,
    "medium": 3,
    "low": 2,
}


# ---------------------------------------------------------------------------
# Failure Classification
# ---------------------------------------------------------------------------

class FailureType:
    """Failure type classification for targeted repair."""
    ROUNDING = "rounding"          # numeric claims off by rounding
    HALLUCINATION = "hallucination"  # claimed number has no data source
    STALE_DATA = "stale_data"      # data exists but from wrong period
    LOGIC = "logic"                # incorrect comparison/trend direction


def _classify_failure(verdict: VerifierVerdict) -> dict[str, list]:
    """Classify each failed claim into failure categories.

    Returns dict mapping FailureType → list of failed claims.
    """
    classified: dict[str, list] = {
        FailureType.ROUNDING: [],
        FailureType.HALLUCINATION: [],
        FailureType.STALE_DATA: [],
        FailureType.LOGIC: [],
    }

    for c in verdict.checks:
        if c.status not in ("fail", "unverified"):
            continue

        if c.status == "fail" and c.computed_value is not None:
            # Has computed value — check if it's a rounding issue
            if c.claimed_value is not None:
                try:
                    claimed = float(c.claimed_value)
                    computed = float(c.computed_value)
                    # Within 0.5% → rounding error
                    if abs(claimed - computed) / max(abs(computed), 0.001) < 0.005:
                        classified[FailureType.ROUNDING].append(c)
                    else:
                        classified[FailureType.LOGIC].append(c)
                except (ValueError, TypeError):
                    classified[FailureType.LOGIC].append(c)
            else:
                classified[FailureType.LOGIC].append(c)
        elif c.status == "unverified":
            # No data source — hallucination
            classified[FailureType.HALLUCINATION].append(c)
        else:
            classified[FailureType.LOGIC].append(c)

    return classified


def _build_classified_repair(verdict: VerifierVerdict) -> str:
    """Build a repair prompt with failure-classified instructions."""
    classified = _classify_failure(verdict)
    lines: list[str] = ["CORRECTION REQUIRED — failures classified by type:"]

    if classified[FailureType.ROUNDING]:
        lines.append("\n[ROUNDING ERRORS] — Use exact computed values:")
        for c in classified[FailureType.ROUNDING]:
            lines.append(
                f"  • '{c.raw}' → Use {c.computed_value:.3f} "
                f"(was {c.claimed_value}, off by rounding)"
            )

    if classified[FailureType.HALLUCINATION]:
        lines.append("\n[HALLUCINATED DATA] — Remove claims without data source:")
        for c in classified[FailureType.HALLUCINATION]:
            lines.append(
                f"  • '{c.raw}' ({c.claimed_value}) has no supporting data. "
                "Remove or replace with '(data unavailable)'."
            )

    if classified[FailureType.STALE_DATA]:
        lines.append("\n[STALE DATA] — Update to current period:")
        for c in classified[FailureType.STALE_DATA]:
            lines.append(f"  • '{c.raw}' uses outdated data. Refresh from latest.")

    if classified[FailureType.LOGIC]:
        lines.append("\n[LOGIC ERRORS] — Correct the reasoning/comparison:")
        for c in classified[FailureType.LOGIC]:
            if c.computed_value is not None:
                lines.append(
                    f"  • '{c.raw}' claimed {c.claimed_value} but actual is "
                    f"{c.computed_value:.3f}. Correct the statement."
                )
            else:
                lines.append(f"  • '{c.raw}' — logic error, please fix.")

    return "\n".join(lines)


def _repair_context(verdict: VerifierVerdict) -> str:
    """Build a repair note for failed/unverified claims.

    Uses failure classification for targeted repair instructions.
    """
    # Use classified repair for better targeted fixes
    return _build_classified_repair(verdict)


@dataclass
class ConsensuResult:
    block_id: str
    narrative: str
    verdict: VerifierVerdict
    attempts: int
    accepted: bool
    fallback_used: bool = False
    failure_classification: dict[str, list] | None = None


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
        priority: str = "medium",
    ) -> ConsensuResult:
        """Generate + verify narrative, retrying on failure.

        Args:
            priority: "high" | "medium" | "low" — controls retry budget.
        """
        _reflections = list(reflections or [])
        max_words = int(hints.get("max_words", 250))
        max_retries = _PRIORITY_RETRY_MAP.get(priority, MAX_RETRIES)
        attempts = 0

        # Merge section-specific facts (e.g. energy section computed facts) into
        # the verify_facts dict so the Verifier can match section-level numbers.
        verify_facts = dict(facts)
        sec_facts = hints.get("_energy_section_facts")
        if isinstance(sec_facts, dict):
            # Flatten nested structures (top3_detail etc.) into scalar values
            for k, v in sec_facts.items():
                if isinstance(v, (int, float)):
                    verify_facts[f"_sec_{k}"] = v
                elif isinstance(v, dict):
                    for sk, sv in v.items():
                        if isinstance(sv, (int, float)):
                            verify_facts[f"_sec_{k}_{sk}"] = sv

        while attempts < max_retries:
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
                facts=verify_facts,
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
        logger.warning("[%s] consensus exhausted %s retries; using fallback", block_id, max_retries)
        fallback = _deterministic_narrative(
            block_title=block_title,
            block_section=block_section,
            facts=facts,
            max_words=max_words,
            dataset_type=dataset_type,
            hints=hints,
        )
        fallback_verdict = self._verifier.verify(
            block_id=block_id,
            narrative=fallback,
            facts=verify_facts,
            df=df,
        )
        return ConsensuResult(
            block_id=block_id,
            narrative=fallback,
            verdict=fallback_verdict,
            attempts=attempts,
            accepted=True,
            fallback_used=True,
            failure_classification=_classify_failure(fallback_verdict)
                if fallback_verdict.overall_status == "fail" else None,
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
