"""Deterministic enterprise contract enrichment for extracted templates."""
from __future__ import annotations

import copy
import re
from typing import Any

from report_builder.template_traversal import iter_components, iter_question_contexts, iter_questions


def _slug(value: Any, fallback: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:80] or fallback


def _blueprint_text(blueprint: dict[str, Any]) -> str:
    parts: list[str] = []
    meta = blueprint.get("templateMeta") or {}
    if isinstance(meta, dict):
        parts.extend(str(meta.get(k) or "") for k in ("name", "domain", "sourceDocument"))
    for ent in blueprint.get("entities") or []:
        if isinstance(ent, dict):
            parts.append(str(ent.get("name") or ent.get("canonicalName") or ""))
    for q in iter_questions(blueprint):
        parts.append(str(q.get("intent") or q.get("questionText") or ""))
    return " ".join(parts).lower()


def infer_domain(blueprint: dict[str, Any]) -> str:
    text = _blueprint_text(blueprint)
    if any(t in text for t in ("energy", "coal", "lignite", "crude oil", "natural gas", "hydro", "renewable", "reserve", "reserves", "potential", "mw")):
        return "energy"
    if any(t in text for t in ("plfs", "labour", "labor", "lfpr", "wpr", "unemployment", "worker population", "employment")):
        return "labour"
    return "generic"


def _domain_units(domain: str) -> list[dict[str, Any]]:
    if domain == "energy":
        return [
            {"unitId": "million_tonnes", "label": "Million tonnes", "appliesTo": ["coal", "lignite", "reserves"]},
            {"unitId": "billion_cubic_metres", "label": "Billion cubic metres", "appliesTo": ["natural_gas"]},
            {"unitId": "million_tonnes_oil_equivalent", "label": "Million tonnes of oil equivalent", "appliesTo": ["crude_oil", "energy_balance"]},
            {"unitId": "mw", "label": "MW", "appliesTo": ["capacity", "potential", "renewable_energy", "hydro"]},
            {"unitId": "percent", "label": "Percent", "appliesTo": ["share", "growth", "composition"]},
        ]
    if domain == "labour":
        return [
            {"unitId": "percent", "label": "Percent", "appliesTo": ["lfpr", "wpr", "unemployment_rate", "share"]},
            {"unitId": "persons", "label": "Persons", "appliesTo": ["population", "workers"]},
            {"unitId": "rupees", "label": "Rupees", "appliesTo": ["earnings", "wages"]},
        ]
    return [{"unitId": "reported_value", "label": "Reported value", "appliesTo": ["measure"]}, {"unitId": "percent", "label": "Percent", "appliesTo": ["rate", "share", "growth"]}]


def _domain_controls(domain: str) -> list[dict[str, Any]]:
    if domain == "energy":
        return [
            {"controlId": "fuel_family", "label": "Fuel family", "type": "multi_select", "options": ["coal", "lignite", "crude_oil", "natural_gas", "hydro", "renewable_energy"]},
            {"controlId": "reserve_class", "label": "Reserve class", "type": "multi_select", "options": ["proved", "indicated", "inferred", "potential"]},
            {"controlId": "geography_level", "label": "Geography level", "type": "single_select", "options": ["india", "state", "region"]},
            {"controlId": "comparison_years", "label": "Comparison years", "type": "year_range", "default": "latest_available"},
            {"controlId": "include_source_notes", "label": "Include source notes", "type": "boolean", "default": True},
        ]
    if domain == "labour":
        return [
            {"controlId": "sector", "label": "Sector", "type": "multi_select", "options": ["rural", "urban", "all"]},
            {"controlId": "sex", "label": "Sex", "type": "multi_select", "options": ["male", "female", "person"]},
            {"controlId": "age_group", "label": "Age group", "type": "multi_select", "options": ["15_plus", "all_ages"]},
            {"controlId": "comparison_years", "label": "Comparison years", "type": "year_range", "default": "latest_available"},
        ]
    return [
        {"controlId": "geography_level", "label": "Geography level", "type": "single_select", "options": ["india", "state", "district", "reported"]},
        {"controlId": "comparison_years", "label": "Comparison years", "type": "year_range", "default": "latest_available"},
        {"controlId": "include_source_notes", "label": "Include source notes", "type": "boolean", "default": True},
    ]


def _officer_customization(domain: str) -> dict[str, Any]:
    return {"schema": "bharatstat/officer-customization/v1", "domain": domain, "controls": _domain_controls(domain), "defaults": {"narrativeDepth": "officer_briefing", "tableDensity": "publication", "chartDensity": "balanced", "sourceNoteMode": "required"}}


def _data_contract(domain: str) -> dict[str, Any]:
    return {"schema": "bharatstat/data-contract/v1", "domain": domain, "unitRegistry": _domain_units(domain), "requiredEvidence": ["page", "sourceType", "confidence"], "valuePolicy": {"observedValuesInTemplate": False, "missingEvidenceAction": "block_or_review", "reportedValuePolicy": "single_equal_or_weighted_else_ambiguous"}}


def _binder_deliverable_contract(domain: str) -> dict[str, Any]:
    return {"schema": "bharatstat/binder-deliverable/v1", "domain": domain, "requiredStages": ["S1_entity_review", "S2_question_review", "S3_binding", "S3_5_readiness"], "readinessGates": {"noBrokenSlotRefs": True, "allQuestionsHaveComponents": True, "allEntitiesHaveEvidence": True, "formulaSpecsStructured": True, "provenanceComponentsRequired": True}}


def _publication_contract(domain: str) -> dict[str, Any]:
    return {"schema": "bharatstat/publication-contract/v1", "domain": domain, "targetPageRange": {"min": 40, "max": 80}, "requiredMatter": ["title_page", "table_of_contents", "executive_summary", "methodology_notes", "source_notes", "glossary"], "layoutProfile": {"pageSize": "A4", "columns": 1, "chartPlacement": "near_question", "tablePlacement": "near_question"}}


def _formula_catalog(domain: str) -> dict[str, Any]:
    formulas = [
        {"type": "REPORTED_VALUE", "description": "Use reported value when deterministic and non-conflicting."},
        {"type": "SHARE", "description": "Aggregate numerator and denominator at the same grain, then divide."},
        {"type": "RATE", "description": "Use structured numerator, denominator, multiplier, and unit."},
        {"type": "RATIO", "description": "Compare two compatible measures at the same grain."},
        {"type": "GROWTH", "description": "Compare values across a declared time window."},
        {"type": "INDEX", "description": "Use declared base value/base period before execution."},
    ]
    if domain == "energy":
        formulas.append({"type": "COMPOSITION", "description": "Energy-source composition using fuel-family numerator over total energy denominator."})
    return {"schema": "bharatstat/formula-catalog/v1", "domain": domain, "formulas": formulas}


def _quality_gate_profile(domain: str) -> dict[str, Any]:
    return {"schema": "bharatstat/quality-gate-profile/v1", "domain": domain, "gates": [{"gateId": "entity_evidence", "severity": "block", "rule": "every_entity_has_sourceRefs_and_evidence"}, {"gateId": "question_contract", "severity": "block", "rule": "every_question_has_binder_fields"}, {"gateId": "slot_integrity", "severity": "block", "rule": "no_broken_fillFrom_or_missing_componentId"}, {"gateId": "schema_enforcement", "severity": "warn", "rule": "schema_required_calls_should_be_enforced_when_provider_supports_it"}]}


def _officer_workbench(domain: str) -> dict[str, Any]:
    return {"schema": "bharatstat/officer-workbench/v1", "domain": domain, "reviewQueues": ["entity_evidence", "formula_readiness", "slot_lineage", "source_notes"], "actions": ["approve", "request_evidence", "edit_label", "lock_slot", "mark_not_ready"]}


def _entity_name(entity: dict[str, Any]) -> str:
    return str(entity.get("canonicalName") or entity.get("name") or entity.get("entityId") or "").strip()


def _source_refs(entity: dict[str, Any]) -> list[dict[str, Any]]:
    refs = entity.get("sourceRefs")
    if isinstance(refs, list):
        return [ref for ref in refs if isinstance(ref, dict)]
    if isinstance(refs, dict):
        return [refs]
    return []


def _evidence_from_refs(entity_id: str, refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for index, ref in enumerate(refs, start=1):
        item: dict[str, Any] = {"evidenceId": f"ev_{entity_id}_{index}", "sourceType": ref.get("sourceType") or ref.get("source") or "unknown", "confidence": ref.get("confidence", 0.75)}
        for key in ("page", "tableId", "figureId", "regionRef", "bbox", "headerPath", "physicalColumn"):
            if key in ref and ref.get(key) is not None:
                item[key] = ref.get(key)
        evidence.append(item)
    return evidence


def _aggregation_policy(entity: dict[str, Any]) -> dict[str, Any]:
    name = _entity_name(entity).lower()
    etype = str(entity.get("entityType") or "").lower()
    if any(term in name for term in ("rate", "percent", "percentage", "share", "ratio", "index")):
        method = "weighted_mean_or_reported_value"
    elif etype in ("measure", "metric") and any(term in name for term in ("count", "total", "reserve", "reserves", "capacity", "potential", "production")):
        method = "sum"
    elif etype in ("measure", "metric"):
        method = "reported_value_review_required"
    else:
        method = "not_applicable"
    return {"method": method, "grain": "same_as_question_plan", "missingWeightAction": "review_required" if method == "weighted_mean_or_reported_value" else "not_required"}


def enrich_entities(blueprint: dict[str, Any], domain: str) -> None:
    entities = blueprint.get("entities")
    if not isinstance(entities, list):
        blueprint["entities"] = []
        return
    for index, entity in enumerate(entities, start=1):
        if not isinstance(entity, dict):
            continue
        entity_id = str(entity.get("entityId") or _slug(entity.get("name"), f"ent_{index}"))
        name = _entity_name(entity) or entity_id
        entity["entityId"] = entity_id
        entity.setdefault("name", name)
        entity.setdefault("canonicalName", name)
        entity.setdefault("entityType", "dimension")
        aliases = entity.get("aliases") if isinstance(entity.get("aliases"), list) else []
        entity["aliases"] = [name, *[str(a) for a in aliases if str(a) and str(a) != name]]
        refs = _source_refs(entity)
        entity["sourceRefs"] = refs
        if not isinstance(entity.get("evidence"), list) or not entity.get("evidence"):
            entity["evidence"] = _evidence_from_refs(entity_id, refs)
        entity.setdefault("aggregationPolicy", _aggregation_policy(entity))
        entity.setdefault("binderHints", {"domain": domain, "preferredRole": str(entity.get("entityType") or "dimension"), "requiresOfficerReview": not bool(refs)})
        entity.setdefault("qualityRules", [{"ruleId": "entity_has_evidence", "severity": "block", "required": True}, {"ruleId": "entity_has_alias", "severity": "warn", "required": True}])
        entity.setdefault("officerReview", {"status": "needs_review" if not refs else "ready_for_review", "checklist": ["confirm_label", "confirm_unit", "confirm_source_evidence"]})
        risk_flags = entity.get("riskFlags") if isinstance(entity.get("riskFlags"), list) else []
        if not refs and "missing_source_refs" not in risk_flags:
            risk_flags.append("missing_source_refs")
        entity["riskFlags"] = risk_flags


def _entity_lookup(blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(ent.get("entityId") or ""): ent for ent in blueprint.get("entities") or [] if isinstance(ent, dict) and ent.get("entityId")}


def _required_entity_ids(question: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for ref in question.get("requiredEntities") or []:
        eid = str((ref.get("entityId") or ref.get("entityRef")) if isinstance(ref, dict) else ref or "")
        if eid and eid not in ids:
            ids.append(eid)
    return ids


def _entity_role(question: dict[str, Any], entity_id: str, entities: dict[str, dict[str, Any]]) -> str:
    for ref in question.get("requiredEntities") or []:
        if isinstance(ref, dict) and entity_id in (ref.get("entityId"), ref.get("entityRef")):
            role = str(ref.get("role") or "").lower()
            if role:
                return role
    return str((entities.get(entity_id) or {}).get("entityType") or "").lower()


def _formula_type(question: dict[str, Any]) -> str:
    text = f"{question.get('questionType') or ''} {question.get('intent') or ''} {question.get('questionText') or ''}".lower()
    if any(t in text for t in ("share", "composition", "distribution", "percentage distribution")):
        return "SHARE"
    if "ratio" in text:
        return "RATIO"
    if any(t in text for t in ("rate", "percent", "percentage")):
        return "RATE"
    if any(t in text for t in ("growth", "trend", "change", "increase", "decrease")):
        return "GROWTH"
    if "index" in text:
        return "INDEX"
    if any(t in text for t in ("describe", "summary", "key finding", "overview")):
        return "DESCRIPTIVE"
    return "REPORTED_VALUE"


def _build_formula_spec(question: dict[str, Any], entities: dict[str, dict[str, Any]]) -> dict[str, Any]:
    measure_ids: list[str] = []
    dimension_ids: list[str] = []
    time_ids: list[str] = []
    for eid in _required_entity_ids(question):
        role = _entity_role(question, eid, entities)
        if role in ("measure", "metric", "numerator", "denominator", "value"):
            measure_ids.append(eid)
        elif role == "time":
            time_ids.append(eid)
        else:
            dimension_ids.append(eid)
    ftype = _formula_type(question)
    blocked = []
    if ftype in ("GROWTH", "INDEX") and not time_ids:
        blocked.append("missing_time_entity")
    if ftype in ("SHARE", "RATE", "RATIO") and not measure_ids:
        blocked.append("missing_measure_entity")
    return {"type": ftype, "measureEntityIds": measure_ids, "dimensionEntityIds": dimension_ids, "timeEntityIds": time_ids, "weightColumn": None, "multiplier": 100 if ftype in ("SHARE", "RATE") else 1, "readiness": "BLOCKED" if blocked else "READY", "blockedReasons": blocked}


def _component_id(question_id: str, suffix: str) -> str:
    return f"{question_id}__{suffix}"


def _normalize_component(comp: dict[str, Any], question_id: str, order: int) -> dict[str, Any]:
    kind = str(comp.get("kind") or comp.get("type") or comp.get("componentKind") or "narrative").strip().lower()
    if kind in ("paragraph", "text", "prose", "narrative_paragraph"):
        kind = "narrative"
    if kind in ("metric", "metric_card", "formula_metric", "kpi", "stat"):
        kind = "formula_metric"
    if kind in ("source_note", "evidence", "lineage"):
        kind = "provenance"
    out = dict(comp)
    out["kind"] = kind
    out["componentKind"] = kind
    out["componentId"] = str(out.get("componentId") or _component_id(question_id, kind))
    out["order"] = int(out.get("order") or out.get("renderOrder") or order)
    out.pop("type", None)
    out.pop("renderOrder", None)
    out.setdefault("refs", {})
    out.setdefault("outputContract", {"type": "provenance" if kind == "provenance" else kind})
    return out


def _ensure_components(question: dict[str, Any], formula_type: str) -> None:
    qid = str(question.get("questionId") or question.get("id") or _slug(question.get("intent"), "question"))
    question["questionId"] = qid
    existing = [_normalize_component(comp, qid, i) for i, comp in enumerate(iter_components(question), start=1)]
    by_kind = {str(comp.get("kind") or ""): comp for comp in existing}
    ordered: list[dict[str, Any]] = []
    if "narrative" not in by_kind:
        ordered.append({"componentId": _component_id(qid, "narrative"), "kind": "narrative", "componentKind": "narrative", "order": 1, "outputContract": {"type": "prose", "minWords": 60, "maxWords": 140}, "refs": {}})
    metric_kind = "metric_card" if formula_type == "DESCRIPTIVE" else "formula_metric"
    if "formula_metric" not in by_kind and "metric_card" not in by_kind:
        ordered.append({"componentId": _component_id(qid, metric_kind), "kind": metric_kind, "componentKind": metric_kind, "order": 2, "outputContract": {"type": "metric", "formulaType": formula_type}, "refs": {}})
    ordered.extend(existing)
    if "provenance" not in by_kind:
        ordered.append({"componentId": _component_id(qid, "provenance"), "kind": "provenance", "componentKind": "provenance", "order": 99, "outputContract": {"type": "provenance", "requiresEvidence": True}, "refs": {}})
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for index, comp in enumerate(ordered, start=1):
        cid = str(comp.get("componentId") or _component_id(qid, f"component_{index}"))
        if cid in seen:
            cid = f"{cid}_{index}"
            comp["componentId"] = cid
        seen.add(cid)
        deduped.append(comp)
    deduped.sort(key=lambda item: int(item.get("order") or 999))
    question["answerStructure"] = {**(question.get("answerStructure") if isinstance(question.get("answerStructure"), dict) else {}), "components": deduped}


def enrich_questions(blueprint: dict[str, Any], domain: str) -> None:
    entities = _entity_lookup(blueprint)
    for question in iter_questions(blueprint):
        qid = str(question.get("questionId") or question.get("id") or _slug(question.get("intent"), "question"))
        question["questionId"] = qid
        question.setdefault("intent", question.get("questionText") or qid)
        question.setdefault("questionText", question.get("intent") or qid)
        question.setdefault("questionType", "describe")
        if not isinstance(question.get("formulaSpec"), dict):
            question["formulaSpec"] = _build_formula_spec(question, entities)
        formula_spec = question["formulaSpec"]
        question.setdefault("binderContract", {"schema": "bharatstat/question-binder-contract/v1", "questionId": qid, "domain": domain, "requiredBeforeS3_5": ["formulaSpec", "answerStructure.components", "provenanceRequirements"], "readiness": formula_spec.get("readiness") or "READY"})
        question.setdefault("qualityGates", [{"gateId": "formula_spec_structured", "severity": "block", "required": True}, {"gateId": "answer_components_wired", "severity": "block", "required": True}, {"gateId": "provenance_component_present", "severity": "block", "required": True}])
        question.setdefault("provenanceRequirements", {"required": True, "minimumEvidenceRefs": 1, "acceptedEvidence": ["sourceRefs", "table_header", "layout_region", "figure_region"]})
        question.setdefault("customization", {"officerEditable": ["questionText", "narrativeDepth", "chartType", "tableDensity"], "lockedFields": ["questionId", "formulaSpec.type"]})
        question.setdefault("answerPlan", {"structure": ["narrative", "metric", "visual_or_table_if_available", "provenance"], "valuePolicy": "value_free_template_only"})
        question.setdefault("reviewChecklist", ["confirm_required_entities", "confirm_formula_type", "confirm_output_components", "confirm_source_evidence"])
        _ensure_components(question, str(formula_spec.get("type") or "REPORTED_VALUE"))


def enrich_enterprise_ast(ast: dict[str, Any], blueprint: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(ast if isinstance(ast, dict) else {})
    controls = (blueprint.get("officerCustomization") or {}).get("controls") if isinstance(blueprint, dict) else []
    publication = blueprint.get("publicationContract") if isinstance(blueprint, dict) else {}
    questions = iter_question_contexts(blueprint if isinstance(blueprint, dict) else {})
    out.setdefault("customizationAST", {"schema": "bharatstat/customization-ast/v1", "controls": controls if isinstance(controls, list) else [], "defaultMode": "officer_review"})
    out.setdefault("publicationAST", {"schema": "bharatstat/publication-ast/v1", "targetPageRange": (publication or {}).get("targetPageRange") or {"min": 40, "max": 80}, "matter": (publication or {}).get("requiredMatter") or ["title_page", "toc", "source_notes"], "sectionCount": len({ctx.get("sectionId") for ctx in questions if ctx.get("sectionId")}), "questionCount": len(questions)})
    out.setdefault("officerGuideAST", {"schema": "bharatstat/officer-guide-ast/v1", "reviewChecklist": ["review_entity_evidence", "review_formula_readiness", "review_slot_lineage", "approve_publication_controls"], "blockingDecisions": ["missing_source_refs", "blocked_formula_spec", "broken_slot_lineage"]})
    return out


def enrich_enterprise_blueprint(blueprint: dict[str, Any], *, domain: str | None = None) -> dict[str, Any]:
    out = copy.deepcopy(blueprint if isinstance(blueprint, dict) else {})
    resolved_domain = domain or infer_domain(out)
    out.setdefault("enterprisePlan", {"schema": "bharatstat/enterprise-template-plan/v1", "domain": resolved_domain, "templateStyle": "domain_adaptive_officer_publication", "contentSourcePolicy": "structure_only_no_observed_values"})
    out.setdefault("officerCustomization", _officer_customization(resolved_domain))
    out.setdefault("dataContract", _data_contract(resolved_domain))
    out.setdefault("binderDeliverableContract", _binder_deliverable_contract(resolved_domain))
    out.setdefault("publicationContract", _publication_contract(resolved_domain))
    out.setdefault("formulaCatalog", _formula_catalog(resolved_domain))
    out.setdefault("qualityGateProfile", _quality_gate_profile(resolved_domain))
    out.setdefault("officerWorkbench", _officer_workbench(resolved_domain))
    meta = out.setdefault("templateMeta", {})
    if isinstance(meta, dict):
        meta.setdefault("domain", resolved_domain)
        meta.setdefault("enterpriseReady", True)
        meta.setdefault("enterpriseContractVersion", "binding.template.enterprise.v1")
        meta.setdefault("templateId", _slug(meta.get("name") or "extracted_template", "extracted_template"))
    enrich_entities(out, resolved_domain)
    enrich_questions(out, resolved_domain)
    return out
