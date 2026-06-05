"""Template review engine — validates extraction output and flags issues.

Provides automated pre-review + hooks for human approval before commit.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ast_core.schema import TemplateBlueprintAST

logger = logging.getLogger(__name__)


class ReviewDecision(str, Enum):
    """Possible review outcomes."""
    APPROVE = "approve"       # Ready to commit
    REJECT = "reject"         # Must re-extract
    NEEDS_EDIT = "needs_edit" # Human must fix specific issues
    AUTO_PASS = "auto_pass"   # Passed all automated checks


@dataclass
class ReviewIssue:
    """A single issue found during review."""
    severity: str  # error, warning, info
    category: str  # entity, question, coverage, confidence
    message: str
    location: str = ""  # e.g., "topic[0].question[2]"
    suggestion: str = ""


@dataclass
class ReviewResult:
    """Outcome of automated review."""
    decision: ReviewDecision
    issues: list[ReviewIssue] = field(default_factory=list)
    confidence_score: float = 0.0  # 0-1 overall confidence
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.issues)


class TemplateReviewer:
    """Automated review of extracted template blueprints.

    Checks:
      - Minimum topic/question coverage
      - Entity completeness (no orphaned bindings)
      - Confidence thresholds
      - Structural integrity (no empty answer structures)
    """

    def __init__(
        self,
        min_topics: int = 2,
        min_questions: int = 3,
        min_entities: int = 5,
        min_confidence: float = 0.4,
    ):
        self._min_topics = min_topics
        self._min_questions = min_questions
        self._min_entities = min_entities
        self._min_confidence = min_confidence

    def review(self, ast: TemplateBlueprintAST) -> ReviewResult:
        """Run automated review on a template blueprint AST."""
        issues: list[ReviewIssue] = []

        # Coverage checks
        if len(ast.topics) < self._min_topics:
            issues.append(ReviewIssue(
                severity="warning",
                category="coverage",
                message=f"Only {len(ast.topics)} topics (min: {self._min_topics})",
            ))

        total_questions = len(ast.all_questions())
        if total_questions < self._min_questions:
            issues.append(ReviewIssue(
                severity="warning",
                category="coverage",
                message=f"Only {total_questions} questions (min: {self._min_questions})",
            ))

        if len(ast.entities) < self._min_entities:
            issues.append(ReviewIssue(
                severity="warning",
                category="coverage",
                message=f"Only {len(ast.entities)} entities (min: {self._min_entities})",
            ))

        # Entity integrity
        entity_ids = {e.entityId for e in ast.entities}
        for ti, topic in enumerate(ast.topics):
            for qi, question in enumerate(topic.questions):
                for binding in question.requiredEntities:
                    if binding.entityId not in entity_ids:
                        issues.append(ReviewIssue(
                            severity="error",
                            category="entity",
                            message=f"Orphaned entity binding: {binding.entityId}",
                            location=f"topic[{ti}].question[{qi}]",
                        ))

        # Empty answer structures
        for ti, topic in enumerate(ast.topics):
            for qi, question in enumerate(topic.questions):
                if not question.answerStructure.components:
                    issues.append(ReviewIssue(
                        severity="warning",
                        category="question",
                        message="Empty answer structure (no components)",
                        location=f"topic[{ti}].question[{qi}]",
                    ))

        # Confidence check (from extractionMeta)
        avg_confidence = ast.extractionMeta.get("avg_page_confidence", 0)
        if avg_confidence < self._min_confidence:
            issues.append(ReviewIssue(
                severity="warning",
                category="confidence",
                message=f"Low average confidence: {avg_confidence:.2f}",
            ))

        # Determine decision
        confidence_score = min(1.0, (
            (len(ast.topics) / max(self._min_topics, 1)) * 0.3 +
            (total_questions / max(self._min_questions, 1)) * 0.3 +
            (len(ast.entities) / max(self._min_entities, 1)) * 0.2 +
            avg_confidence * 0.2
        ))

        if any(i.severity == "error" for i in issues):
            decision = ReviewDecision.NEEDS_EDIT
        elif len(issues) > 3:
            decision = ReviewDecision.NEEDS_EDIT
        elif len(issues) == 0:
            decision = ReviewDecision.AUTO_PASS
        else:
            decision = ReviewDecision.APPROVE

        return ReviewResult(
            decision=decision,
            issues=issues,
            confidence_score=confidence_score,
            stats={
                "topics": len(ast.topics),
                "questions": total_questions,
                "entities": len(ast.entities),
                "pages": ast.pageCount,
            },
        )
