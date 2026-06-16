"""Adapt SemanticPipelineV2 output to legacy AnalysisState bundle shape."""
from __future__ import annotations

from typing import Any

from analysis_state.cluster_utils import unify_cluster_record

# Validation rule discovery expects scored archetype dicts (not raw usecase strings).
_USECASE_TO_ARCHETYPE: dict[str, str] = {
    "industry": "economic",
    "labour": "labour",
    "consumption": "consumption",
    "energy": "energy",
}

# Persisted as dataset_context.dataset_type / inferred_context in DB.
_USECASE_TO_DATASET_TYPE: dict[str, str] = {
    "industry": "economic_survey",
    "labour": "labor",
    "consumption": "socioeconomic",
    "energy": "economic_survey",
    "demography": "census",
    "health": "health_survey",
    "education": "education_statistics",
    "agriculture": "agriculture",
    "infrastructure": "infrastructure",
    "environment": "economic_survey",
}


def _usecase_name(uc: Any) -> str:
    if isinstance(uc, dict):
        return str(uc.get("usecase") or "").strip()
    return str(uc or "").strip()


def _dataset_type_from_usecase(uc: Any) -> str:
    name = _usecase_name(uc)
    if not name:
        return ""
    return _USECASE_TO_DATASET_TYPE.get(name, name)


def _archetype_entries(uc: Any) -> list[dict[str, Any]]:
    if not uc:
        return []
    if isinstance(uc, dict):
        usecase_name = str(uc.get("usecase") or "").strip()
        confidence = float(uc.get("confidence") or 0.7)
    else:
        usecase_name = str(uc).strip()
        confidence = 0.7
    if not usecase_name:
        return []
    archetype = _USECASE_TO_ARCHETYPE.get(usecase_name, usecase_name)
    return [{"archetype": archetype, "score": confidence}]


def v2_to_legacy_bundle(v2: dict[str, Any]) -> dict[str, Any]:
    """Map V2 analyze() dict to keys expected by ``semantic_adapter`` / orchestrator."""
    column_cluster_map: dict[str, str] = {}
    clusters_list: list[dict[str, Any]] = []
    for cid, cl in (v2.get("clusters") or {}).items():
        if isinstance(cl, dict):
            unified = unify_cluster_record({**cl, "cluster_id": cl.get("cluster_id") or cid})
            clusters_list.append(unified)
            for col in unified.get("columns") or []:
                column_cluster_map[str(col)] = str(unified.get("cluster_id") or cid)

    uc = v2.get("usecase") or {}
    usecase_name = _usecase_name(uc)
    dataset_type = _dataset_type_from_usecase(uc)

    return {
        "semantic_mapping": v2.get("semantic_mapping") or {},
        "column_cluster_map": column_cluster_map,
        "clusters": clusters_list,
        "schema_graph": v2.get("schema_graph") or {},
        "knowledge_graph": v2.get("knowledge_graph") or {},
        "dataset_context": {
            "dataset_type": dataset_type,
            "usecase": usecase_name,
            "usecase_confidence": uc.get("confidence") if isinstance(uc, dict) else None,
            "archetypes": _archetype_entries(uc),
        },
        "domain_registry": v2.get("domains") or {},
        "unified_domains": list((v2.get("domains") or {}).values()),
        "priority_dependencies": {},
        "column_normalization": v2.get("column_normalization") or [],
        "audit_records": [],
        "semantic_v2_meta": v2.get("meta") or {},
        "semantic_v2_usecase": uc,
        "semantic_v2_dynamic_domains": v2.get("dynamic_domains") or {},
    }
