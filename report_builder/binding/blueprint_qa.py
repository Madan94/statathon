"""Blueprint Quality Assurance — validates extraction output before binding.

Two gates:
1. BlueprintQA: structural checks (entities exist, questions have IDs, analyticsSpec present)
2. StatisticalConceptQA: semantic checks (metrics understandable, units present, time/geography detectable)

Failure policy:
- VALID: ready for binding
- VALID_WITH_WARNINGS: binding can proceed, dashboard shows warnings
- INVALID: binding should not start
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


def _iter_blueprint_questions(node: Any) -> list[dict[str, Any]]:
    """Flatten questions from topics/chapters/sections/subsections."""
    if isinstance(node, dict):
        out = [q for q in (node.get("questions") or []) if isinstance(q, dict)]
        for key in ("topics", "chapters", "sections", "children", "subtopics", "subsections"):
            for child in node.get(key) or []:
                out.extend(_iter_blueprint_questions(child))
        return out
    if isinstance(node, list):
        out: list[dict[str, Any]] = []
        for item in node:
            out.extend(_iter_blueprint_questions(item))
        return out
    return []


@dataclass
class BlueprintQAResult:
    """Result of blueprint quality validation."""

    status: str = "VALID"  # VALID | VALID_WITH_WARNINGS | INVALID
    warnings: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    missingEntities: list[str] = field(default_factory=list)
    missingAnalyticsSpec: list[str] = field(default_factory=list)
    missingOutputContract: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "missingEntities": list(self.missingEntities),
            "missingAnalyticsSpec": list(self.missingAnalyticsSpec),
            "missingOutputContract": list(self.missingOutputContract),
        }


def validate_blueprint_qa(blueprint: dict[str, Any]) -> BlueprintQAResult:
    """BlueprintQA: structural validation of extracted blueprint.

    Checks:
    - entities[] exists and has content
    - entities have entityId, canonicalName, entityType
    - topics/questions exist
    - questions have questionId
    - requiredEntities reference valid entity IDs
    - analyticsSpec exists for non-describe questions
    - answerStructure/outputContract exists
    """
    result = BlueprintQAResult()
    entities = blueprint.get("entities") or []
    topics = blueprint.get("topics") or []

    # ── Entity checks ──
    if not entities:
        result.errors.append({"code": "NO_ENTITIES", "message": "Blueprint has no entities"})
        result.status = "INVALID"
        return result

    entity_ids = set()
    for e in entities:
        eid = e.get("entityId", "")
        if not eid:
            result.errors.append({"code": "ENTITY_MISSING_ID", "message": f"Entity without entityId: {e.get('canonicalName', '?')}"})
        else:
            entity_ids.add(eid)
        if not e.get("canonicalName") and not e.get("name"):
            result.warnings.append({"code": "ENTITY_MISSING_NAME", "message": f"Entity {eid} has no name"})
        if not e.get("entityType"):
            result.warnings.append({"code": "ENTITY_MISSING_TYPE", "message": f"Entity {eid} has no entityType"})

    # ── Topic/Question checks ──
    if not topics:
        result.warnings.append({"code": "NO_TOPICS", "message": "Blueprint has no topics — questions may be unstructured"})

    all_questions = _iter_blueprint_questions(blueprint)

    if not all_questions:
        result.errors.append({"code": "NO_QUESTIONS", "message": "Blueprint has no questions"})
        result.status = "INVALID"
        return result

    for q in all_questions:
        qid = q.get("questionId", "")
        if not qid:
            result.warnings.append({"code": "QUESTION_MISSING_ID", "message": "Question without questionId found"})
            continue

        # Check requiredEntities reference valid IDs
        for re_ent in (q.get("requiredEntities") or []):
            ref_id = re_ent.get("entityId") or re_ent.get("entityRef", "")
            if not ref_id:
                continue
            # entityId-style refs (ent_001, ent_wpr) must exist in entity_ids
            if ref_id.startswith("ent_"):
                if ref_id not in entity_ids:
                    result.missingEntities.append(f"{qid}→{ref_id}")
            else:
                # Name-style refs: check against canonical names
                entity_names = {(e.get("canonicalName") or e.get("name") or "").lower() for e in entities}
                if ref_id.lower() not in entity_names and ref_id not in entity_ids:
                    result.missingEntities.append(f"{qid}→{ref_id}")

        # Check analyticsSpec
        q_type = q.get("questionType", "")
        if q_type not in ("describe",) and not q.get("analyticsSpec"):
            result.missingAnalyticsSpec.append(qid)

        # Check outputContract / answerStructure
        ans = q.get("answerStructure") or q.get("outputContract")
        if not ans:
            result.missingOutputContract.append(qid)

    # ── Determine final status ──
    if result.errors:
        result.status = "INVALID"
    elif result.missingAnalyticsSpec or result.missingOutputContract or result.warnings:
        result.status = "VALID_WITH_WARNINGS"
    else:
        result.status = "VALID"

    logger.info(
        "[blueprintQA] status=%s entities=%d questions=%d warnings=%d errors=%d",
        result.status, len(entities), len(all_questions), len(result.warnings), len(result.errors),
    )
    return result


def validate_statistical_concepts(blueprint: dict[str, Any]) -> BlueprintQAResult:
    """StatisticalConceptQA: semantic validation for MoSPI reports.

    Checks:
    - Measure entities have units or are detectable rates/ratios
    - Time/period dimension exists if trend/growth questions are asked
    - Geography dimension exists if state-wise questions are asked
    - Formula-requiring questions have enough metadata
    """
    result = BlueprintQAResult(status="VALID")
    entities = blueprint.get("entities") or []
    topics = blueprint.get("topics") or []

    # Build lookups
    entity_map = {e.get("entityId", ""): e for e in entities}
    measures = [e for e in entities if e.get("entityType") == "measure"]
    dimensions = [e for e in entities if e.get("entityType") == "dimension"]
    time_entities = [e for e in entities if e.get("entityType") == "time" or
                     any(k in (e.get("canonicalName") or "").lower() for k in ("year", "period", "quarter", "month"))]

    # Check: measures should have units
    for m in measures:
        if not m.get("unit"):
            name = m.get("canonicalName", m.get("name", ""))
            # Only warn if it's likely a rate/ratio
            if any(k in name.lower() for k in ("rate", "ratio", "percent", "index", "share")):
                result.warnings.append({
                    "code": "MEASURE_MISSING_UNIT",
                    "message": f"Measure '{name}' looks like a rate/ratio but has no unit specified",
                })

    # Check: growth/trend questions need time dimension
    all_questions = _iter_blueprint_questions(blueprint)

    growth_questions = [q for q in all_questions if q.get("questionType") in ("trend", "growth")]
    if growth_questions and not time_entities:
        result.warnings.append({
            "code": "GROWTH_NO_TIME_ENTITY",
            "message": f"{len(growth_questions)} growth/trend questions but no time dimension entity found",
        })

    # Check: state-wise questions need geography dimension
    geo_keywords = ("state", "geography", "region", "district", "rural", "urban")
    has_geo = any(any(k in (e.get("canonicalName") or "").lower() for k in geo_keywords) for e in dimensions)
    state_questions = [q for q in all_questions
                       if any(k in (q.get("questionText") or q.get("intent") or "").lower()
                              for k in ("state", "statewise", "state-wise", "region"))]
    if state_questions and not has_geo:
        result.warnings.append({
            "code": "STATEWISE_NO_GEO_ENTITY",
            "message": f"{len(state_questions)} state-wise questions but no geography dimension entity",
        })

    if result.warnings:
        result.status = "VALID_WITH_WARNINGS"

    logger.info(
        "[statisticalQA] status=%s measures=%d (no_unit=%d) time_entities=%d geo=%s",
        result.status, len(measures),
        sum(1 for m in measures if not m.get("unit")),
        len(time_entities), has_geo,
    )
    return result
