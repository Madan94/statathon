"""Citation Manager — inline superscript citations linking claims to data.

Provides evidence-based citations in generated narratives:
  - Extracts numeric claims from narrative text
  - Links each claim to its data source (column, row, computation)
  - Generates inline superscript markers [1], [2], etc.
  - Builds an evidence appendix with full source details

Output format:
  Narrative: "The LFPR was 42.3%[1] in Jan-Mar 2024..."
  Appendix:
    [1] LFPR = 42.3%, Source: dataset.csv, Column: lfpr_pct, Row: Q1-2024

Usage:
  manager = CitationManager()
  cited_text, appendix = manager.cite(narrative, facts, sources)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Pattern to find numeric claims in text
_NUMERIC_PATTERN = re.compile(
    r"(\d+\.?\d*)\s*(%|percentage points?|pp|crore|lakh|million|billion)?",
    re.IGNORECASE,
)


@dataclass
class Citation:
    """A single evidence citation."""
    index: int  # 1-based citation number
    claim: str  # the numeric claim as found in text
    value: float
    source_column: str = ""
    source_row: str = ""
    computation: str = ""  # e.g., "mean", "latest", "difference"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "claim": self.claim,
            "value": self.value,
            "sourceColumn": self.source_column,
            "sourceRow": self.source_row,
            "computation": self.computation,
            "confidence": self.confidence,
        }


@dataclass
class CitationResult:
    """Result of citation processing."""
    cited_narrative: str  # narrative with [n] markers inserted
    citations: list[Citation] = field(default_factory=list)
    appendix_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "citedNarrative": self.cited_narrative,
            "citations": [c.to_dict() for c in self.citations],
            "appendixText": self.appendix_text,
        }


class CitationManager:
    """Manages evidence citations for generated narratives."""

    def __init__(self, tolerance: float = 0.01):
        """
        Args:
            tolerance: relative tolerance for matching claims to facts
        """
        self._tolerance = tolerance

    def cite(
        self,
        narrative: str,
        facts: dict[str, Any],
        sources: dict[str, str] | None = None,
    ) -> CitationResult:
        """Add inline citations to a narrative.

        Args:
            narrative: Generated narrative text with numeric claims
            facts: Dict of fact_key → numeric value (from extraction)
            sources: Optional mapping fact_key → source description

        Returns:
            CitationResult with marked-up narrative and citation list
        """
        if not narrative or not facts:
            return CitationResult(cited_narrative=narrative)

        sources = sources or {}
        citations: list[Citation] = []
        cited_text = narrative
        citation_idx = 0

        # Find all numeric claims in the narrative
        matches = list(_NUMERIC_PATTERN.finditer(narrative))

        # Process in reverse order to preserve positions
        for match in reversed(matches):
            claim_text = match.group(0).strip()
            try:
                claim_value = float(match.group(1))
            except (ValueError, TypeError):
                continue

            # Try to match claim to a fact
            matched_fact = self._match_claim_to_fact(claim_value, facts)
            if matched_fact is None:
                continue

            citation_idx += 1
            fact_key, fact_value = matched_fact

            # Determine source info
            source_col = ""
            computation = ""
            if "_mean" in fact_key:
                source_col = fact_key.replace("_mean", "")
                computation = "mean"
            elif "_latest" in fact_key:
                source_col = fact_key.replace("_latest", "")
                computation = "latest value"
            elif "_max" in fact_key:
                source_col = fact_key.replace("_max", "")
                computation = "maximum"
            elif "_min" in fact_key:
                source_col = fact_key.replace("_min", "")
                computation = "minimum"
            else:
                source_col = fact_key

            citation = Citation(
                index=citation_idx,
                claim=claim_text,
                value=fact_value,
                source_column=source_col,
                source_row=sources.get(fact_key, ""),
                computation=computation,
                confidence=1.0 if claim_value == fact_value else 0.95,
            )
            citations.append(citation)

            # Insert citation marker after the claim
            insert_pos = match.end()
            cited_text = (
                cited_text[:insert_pos]
                + f"[{citation_idx}]"
                + cited_text[insert_pos:]
            )

        # Reverse citation list so indices are in order
        citations.reverse()
        # Re-number citations sequentially
        for i, c in enumerate(citations, 1):
            c.index = i

        # Build appendix
        appendix = self._build_appendix(citations)

        return CitationResult(
            cited_narrative=cited_text,
            citations=citations,
            appendix_text=appendix,
        )

    def _match_claim_to_fact(
        self, claim_value: float, facts: dict[str, Any]
    ) -> tuple[str, float] | None:
        """Find the best matching fact for a claimed numeric value."""
        best_match: tuple[str, float] | None = None
        best_distance = float("inf")

        for key, value in facts.items():
            if not isinstance(value, (int, float)):
                continue
            if value == 0 and claim_value == 0:
                return (key, float(value))

            # Check within tolerance
            if value != 0:
                rel_diff = abs(claim_value - value) / abs(value)
            else:
                rel_diff = abs(claim_value - value)

            if rel_diff <= self._tolerance:
                if rel_diff < best_distance:
                    best_distance = rel_diff
                    best_match = (key, float(value))

        return best_match

    def _build_appendix(self, citations: list[Citation]) -> str:
        """Build a text appendix listing all citations."""
        if not citations:
            return ""

        lines = ["", "--- Evidence Sources ---"]
        for c in citations:
            source_info = f"Column: {c.source_column}" if c.source_column else "Direct"
            if c.computation:
                source_info += f" ({c.computation})"
            if c.source_row:
                source_info += f", Row: {c.source_row}"
            lines.append(f"  [{c.index}] {c.claim} = {c.value} — {source_info}")

        return "\n".join(lines)

    def cite_latex(
        self,
        narrative: str,
        facts: dict[str, Any],
        sources: dict[str, str] | None = None,
    ) -> CitationResult:
        """Add LaTeX-formatted superscript citations."""
        result = self.cite(narrative, facts, sources)
        # Convert [n] to LaTeX \textsuperscript{n}
        cited = re.sub(
            r"\[(\d+)\]",
            r"\\textsuperscript{\\textit{\1}}",
            result.cited_narrative,
        )
        result.cited_narrative = cited
        return result
