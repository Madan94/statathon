"""Phase chain state: raw schema → normalized → semantic → clusters → KG."""
from __future__ import annotations

from typing import Any


def _column_records_as_dicts(columns: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for col in columns:
        if hasattr(col, "name"):
            out.append(
                {
                    "id": col.id,
                    "name": col.name,
                    "normalized_name": col.normalized_name or col.name,
                    "is_deleted": bool(col.is_deleted),
                    "is_excluded": bool(col.is_excluded),
                    "is_active": bool(col.is_active),
                }
            )
        elif isinstance(col, dict):
            out.append(col)
    return out


def build_effective_schema(column_records: list[Any]) -> list[str]:
    """Active normalized column names for downstream phases."""
    effective: list[str] = []
    for col in _column_records_as_dicts(column_records):
        if col.get("is_deleted") or col.get("is_excluded"):
            continue
        if col.get("is_active") is False:
            continue
        effective.append(str(col.get("normalized_name") or col.get("name")))
    return effective


def build_name_map(column_records: list[Any]) -> dict[str, str]:
    """Original column name → effective normalized name (only for active columns)."""
    mapping: dict[str, str] = {}
    for col in _column_records_as_dicts(column_records):
        orig = str(col.get("name"))
        if col.get("is_deleted") or col.get("is_excluded") or col.get("is_active") is False:
            continue
        mapping[orig] = str(col.get("normalized_name") or orig)
    return mapping


def build_active_original_names(column_records: list[Any]) -> set[str]:
    return set(build_name_map(column_records).keys())


def _remap_column_name(name: str, name_map: dict[str, str], active: set[str]) -> str | None:
    if name in name_map:
        return name_map[name]
    if name in active:
        return name
    return None


def filter_semantic_mapping(
    mapping: list[dict[str, Any]] | dict[str, Any],
    column_records: list[Any],
) -> list[dict[str, Any]]:
    name_map = build_name_map(column_records)
    active = build_active_original_names(column_records)
    rows: list[dict[str, Any]] = []
    if isinstance(mapping, dict):
        source = [{"column": k, **(v if isinstance(v, dict) else {"value": v})} for k, v in mapping.items()]
    else:
        source = list(mapping or [])

    for row in source:
        if not isinstance(row, dict):
            continue
        orig = str(row.get("column") or row.get("original_column") or "")
        if orig not in active:
            continue
        remapped = dict(row)
        remapped["original_column"] = orig
        remapped["column"] = name_map.get(orig, orig)
        rows.append(remapped)
    return rows


def filter_clusters(clusters: list[dict[str, Any]], column_records: list[Any]) -> list[dict[str, Any]]:
    name_map = build_name_map(column_records)
    active = build_active_original_names(column_records)
    filtered: list[dict[str, Any]] = []
    for cluster in clusters or []:
        if not isinstance(cluster, dict):
            continue
        cols = cluster.get("columns") or []
        new_cols = []
        for c in cols:
            cstr = str(c)
            if cstr not in active:
                continue
            new_cols.append(name_map.get(cstr, cstr))
        if not new_cols:
            continue
        item = dict(cluster)
        item["columns"] = new_cols
        filtered.append(item)
    return filtered


def filter_graph_nodes_edges(
    graph: dict[str, Any],
    column_records: list[Any],
) -> dict[str, Any]:
    name_map = build_name_map(column_records)
    active = build_active_original_names(column_records)
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    new_nodes = []
    for node in nodes:
        if isinstance(node, dict):
            nname = str(node.get("name") or node.get("id") or "")
            if nname in active:
                nn = dict(node)
                nn["name"] = name_map.get(nname, nname)
                if "id" in nn:
                    nn["id"] = nn["name"]
                new_nodes.append(nn)
        elif isinstance(node, str) and node in active:
            new_nodes.append(name_map.get(node, node))

    new_edges = []
    for edge in edges or []:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("source") or "")
        tgt = str(edge.get("target") or "")
        if src not in active or tgt not in active:
            continue
        ne = dict(edge)
        ne["source"] = name_map.get(src, src)
        ne["target"] = name_map.get(tgt, tgt)
        new_edges.append(ne)
    return {"nodes": new_nodes, "edges": new_edges}


def filter_column_profiles(
    profiles: dict[str, Any],
    column_records: list[Any],
) -> dict[str, Any]:
    name_map = build_name_map(column_records)
    active = build_active_original_names(column_records)
    out: dict[str, Any] = {}
    for orig, prof in (profiles or {}).items():
        if str(orig) not in active:
            continue
        out[name_map.get(str(orig), str(orig))] = prof
    return out


def filter_phase3_by_columns(phase3: dict[str, Any], column_records: list[Any]) -> dict[str, Any]:
    if not isinstance(phase3, dict):
        return {}
    active_effective = set(build_effective_schema(column_records))
    name_map = build_name_map(column_records)
    effective_from_orig = set(name_map.values())

    def _col_active(col: str) -> bool:
        c = str(col)
        return c in active_effective or c in effective_from_orig or c in build_active_original_names(column_records)

    out = dict(phase3)
    for key in ("anomaly_candidates", "validation_candidates", "imputation_candidates"):
        items = out.get(key)
        if not isinstance(items, list):
            continue
        out[key] = [i for i in items if isinstance(i, dict) and _col_active(str(i.get("column") or ""))]
    return out


def apply_effective_schema_to_payload(
    payload: dict[str, Any],
    column_records: list[Any],
    *,
    normalization_version: int | None = None,
) -> dict[str, Any]:
    """Filter/remap checkpoint payload to approved normalization output."""
    if not column_records:
        return payload
    version = normalization_version
    if version is None:
        version = payload.get("normalization_version")

    effective = build_effective_schema(column_records)
    if not effective and version is None:
        return payload

    out = dict(payload)
    out["effective_schema"] = effective
    out["normalization_version"] = version
    out["semantic_mapping"] = filter_semantic_mapping(
        out.get("semantic_mapping") or [], column_records
    )
    out["clusters"] = filter_clusters(out.get("clusters") or [], column_records)
    graph = out.get("schema_graph") or {}
    if isinstance(graph, dict):
        out["schema_graph"] = filter_graph_nodes_edges(graph, column_records)
    out["column_profiles"] = filter_column_profiles(out.get("column_profiles") or {}, column_records)
    phase3 = out.get("phase3")
    if isinstance(phase3, dict):
        out["phase3"] = filter_phase3_by_columns(phase3, column_records)
    return out


def build_phase_state_snapshot(
    raw_columns: list[str],
    column_records: list[Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    effective = build_effective_schema(column_records)
    return {
        "raw_schema": list(raw_columns),
        "normalized_schema": effective,
        "normalization_version": payload.get("normalization_version"),
        "semantic_mapping": payload.get("semantic_mapping"),
        "clusters": payload.get("clusters"),
    }
