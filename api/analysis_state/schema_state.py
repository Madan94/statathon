"""Phase chain state: raw schema → normalized → semantic → clusters → KG."""
from __future__ import annotations

import re
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


def resolve_active_original_column(
    col_name: str,
    name_map: dict[str, str],
    active: set[str],
    *,
    canon_to_orig: dict[str, str] | None = None,
) -> str | None:
    """Map a row/graph column label to its active upload header (handles V2 canonical keys)."""
    c = str(col_name or "")
    if not c:
        return None
    if c in active:
        return c
    if canon_to_orig:
        mapped = canon_to_orig.get(c) or canon_to_orig.get(c.lower())
        if mapped and mapped in active:
            return mapped
    effective = set(name_map.values())
    if c in effective or c in name_map:
        for orig, norm in name_map.items():
            if orig == c or norm == c:
                return orig
    return None


def _build_canon_to_orig(column_normalization: list[Any] | None) -> dict[str, str]:
    canon_to_orig: dict[str, str] = {}
    for row in column_normalization or []:
        if not isinstance(row, dict):
            continue
        orig = str(row.get("original_name") or row.get("column") or "")
        canon = str(
            row.get("canonical_name")
            or row.get("normalized_name")
            or row.get("display_name")
            or ""
        )
        if orig and canon:
            canon_to_orig[canon] = orig
            canon_to_orig[canon.lower()] = orig
    return canon_to_orig


def _remap_column_name(
    name: str,
    name_map: dict[str, str],
    active: set[str],
    *,
    canon_to_orig: dict[str, str] | None = None,
) -> str | None:
    orig = resolve_active_original_column(name, name_map, active, canon_to_orig=canon_to_orig)
    if orig is None:
        return None
    return name_map.get(orig, orig)


def filter_semantic_mapping(
    mapping: list[dict[str, Any]] | dict[str, Any],
    column_records: list[Any],
    *,
    column_normalization: list[Any] | None = None,
) -> list[dict[str, Any]]:
    name_map = build_name_map(column_records)
    active = build_active_original_names(column_records)
    canon_to_orig = _build_canon_to_orig(column_normalization)
    rows: list[dict[str, Any]] = []
    if isinstance(mapping, dict):
        source = [{"column": k, **(v if isinstance(v, dict) else {"value": v})} for k, v in mapping.items()]
    else:
        source = list(mapping or [])

    for row in source:
        if not isinstance(row, dict):
            continue
        orig: str | None = None
        for key in ("original_name", "original_column", "column"):
            candidate = str(row.get(key) or "")
            if not candidate:
                continue
            resolved = resolve_active_original_column(candidate, name_map, active, canon_to_orig=canon_to_orig)
            if resolved:
                orig = resolved
                break
        if not orig:
            continue
        remapped = dict(row)
        remapped["original_column"] = orig
        if not remapped.get("original_name"):
            remapped["original_name"] = orig
        remapped["column"] = name_map.get(orig, orig)
        rows.append(remapped)
    return rows


def filter_clusters(
    clusters: list[dict[str, Any]],
    column_records: list[Any],
    *,
    column_normalization: list[Any] | None = None,
) -> list[dict[str, Any]]:
    name_map = build_name_map(column_records)
    active = build_active_original_names(column_records)
    canon_to_orig = _build_canon_to_orig(column_normalization)
    filtered: list[dict[str, Any]] = []
    for cluster in clusters or []:
        if not isinstance(cluster, dict):
            continue
        cols = cluster.get("columns") or []
        new_cols = []
        for c in cols:
            orig = resolve_active_original_column(str(c), name_map, active, canon_to_orig=canon_to_orig)
            if orig is None:
                continue
            new_cols.append(name_map.get(orig, orig))
        if not new_cols:
            continue
        item = dict(cluster)
        item["columns"] = new_cols
        filtered.append(item)
    return filtered


def filter_graph_nodes_edges(
    graph: dict[str, Any],
    column_records: list[Any],
    *,
    column_normalization: list[Any] | None = None,
) -> dict[str, Any]:
    name_map = build_name_map(column_records)
    active = build_active_original_names(column_records)
    canon_to_orig = _build_canon_to_orig(column_normalization)
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    new_nodes = []
    for node in nodes:
        if isinstance(node, dict):
            nname = str(node.get("name") or node.get("id") or "")
            orig = resolve_active_original_column(nname, name_map, active, canon_to_orig=canon_to_orig)
            if orig is None:
                continue
            nn = dict(node)
            nn["name"] = name_map.get(orig, orig)
            if "id" in nn:
                nn["id"] = nn["name"]
            new_nodes.append(nn)
        elif isinstance(node, str):
            orig = resolve_active_original_column(node, name_map, active, canon_to_orig=canon_to_orig)
            if orig is not None:
                new_nodes.append(name_map.get(orig, orig))

    new_edges = []
    for edge in edges or []:
        if not isinstance(edge, dict):
            continue
        src_orig = resolve_active_original_column(str(edge.get("source") or ""), name_map, active, canon_to_orig=canon_to_orig)
        tgt_orig = resolve_active_original_column(str(edge.get("target") or ""), name_map, active, canon_to_orig=canon_to_orig)
        if src_orig is None or tgt_orig is None:
            continue
        ne = dict(edge)
        ne["source"] = name_map.get(src_orig, src_orig)
        ne["target"] = name_map.get(tgt_orig, tgt_orig)
        new_edges.append(ne)
    return {"nodes": new_nodes, "edges": new_edges}


def _snake_key(name: str) -> str:
    t = re.sub(r"[^\w]+", "_", str(name).strip())
    return re.sub(r"_+", "_", t).strip("_").lower()


def _build_profile_key_aliases(column_records: list[Any]) -> dict[str, str]:
    """Map profile keys (raw, normalized, snake_case) → active original column name."""
    aliases: dict[str, str] = {}
    for col in _column_records_as_dicts(column_records):
        if col.get("is_deleted") or col.get("is_excluded") or col.get("is_active") is False:
            continue
        orig = str(col.get("name"))
        norm = str(col.get("normalized_name") or orig)
        for key in {orig, norm, _snake_key(orig), _snake_key(norm)}:
            if key:
                aliases[key] = orig
                aliases[key.lower()] = orig
    return aliases


def filter_column_profiles(
    profiles: dict[str, Any],
    column_records: list[Any],
    *,
    column_normalization: list[Any] | None = None,
) -> dict[str, Any]:
    name_map = build_name_map(column_records)
    active = build_active_original_names(column_records)
    canon_to_orig = _build_canon_to_orig(column_normalization)
    canon_to_orig.update(_build_profile_key_aliases(column_records))
    out: dict[str, Any] = {}
    for key, prof in (profiles or {}).items():
        orig = resolve_active_original_column(
            str(key),
            name_map,
            active,
            canon_to_orig=canon_to_orig,
        )
        if orig is None:
            continue
        out[name_map.get(orig, orig)] = prof
    return out


def filter_phase3_by_columns(
    phase3: dict[str, Any],
    column_records: list[Any],
    *,
    column_normalization: list[Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(phase3, dict):
        return {}
    name_map = build_name_map(column_records)
    active = build_active_original_names(column_records)
    canon_to_orig = _build_canon_to_orig(column_normalization)
    canon_to_orig.update(_build_profile_key_aliases(column_records))

    def _remap_col_name(col: str) -> str | None:
        return _remap_column_name(col, name_map, active, canon_to_orig=canon_to_orig)

    out = dict(phase3)
    for key in ("anomaly_candidates", "validation_candidates", "imputation_candidates"):
        items = out.get(key)
        if not isinstance(items, list):
            continue
        remapped: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            col = str(item.get("column") or "")
            new_col = _remap_col_name(col)
            if new_col is None:
                continue
            row = dict(item)
            row["column"] = new_col
            if new_col != col:
                row["original_column"] = col
            remapped.append(row)
        out[key] = remapped

    anomaly_results = out.get("anomaly_results")
    if isinstance(anomaly_results, list):
        remapped_results: list[dict[str, Any]] = []
        for block in anomaly_results:
            if not isinstance(block, dict):
                continue
            col = str(block.get("column") or "")
            new_col = _remap_col_name(col)
            if new_col is None:
                continue
            nb = dict(block)
            nb["column"] = new_col
            if new_col != col:
                nb["original_column"] = col
            remapped_results.append(nb)
        out["anomaly_results"] = remapped_results

    gof = out.get("goodness_of_fit")
    if isinstance(gof, list):
        remapped_gof: list[dict[str, Any]] = []
        for row in gof:
            if not isinstance(row, dict):
                continue
            col = str(row.get("column") or "")
            new_col = _remap_col_name(col)
            if new_col is None:
                continue
            gr = dict(row)
            gr["column"] = new_col
            remapped_gof.append(gr)
        out["goodness_of_fit"] = remapped_gof

    method_selections = out.get("method_selections")
    if isinstance(method_selections, dict):
        remapped_sel: dict[str, str] = {}
        for col, method in method_selections.items():
            new_col = _remap_col_name(str(col))
            if new_col is not None:
                remapped_sel[new_col] = method
        out["method_selections"] = remapped_sel

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
    col_norm = out.get("column_normalization") or []
    out["semantic_mapping"] = filter_semantic_mapping(
        out.get("semantic_mapping") or [], column_records, column_normalization=col_norm
    )
    out["clusters"] = filter_clusters(out.get("clusters") or [], column_records, column_normalization=col_norm)
    graph = out.get("schema_graph") or {}
    if isinstance(graph, dict):
        out["schema_graph"] = filter_graph_nodes_edges(graph, column_records, column_normalization=col_norm)
    out["column_profiles"] = filter_column_profiles(
        out.get("column_profiles") or {},
        column_records,
        column_normalization=col_norm if isinstance(col_norm, list) else None,
    )
    if isinstance(profiling := out.get("profiling_summary"), dict):
        prof_profiles = profiling.get("column_profiles")
        if isinstance(prof_profiles, dict):
            profiling = dict(profiling)
            profiling["column_profiles"] = filter_column_profiles(
                prof_profiles,
                column_records,
                column_normalization=col_norm if isinstance(col_norm, list) else None,
            )
            out["profiling_summary"] = profiling
    profiling = out.get("profiling_summary")
    if isinstance(profiling, dict) and isinstance(profiling.get("schema"), dict):
        prof_schema = profiling["schema"]
        remapped_schema: dict[str, str] = {}
        name_map = build_name_map(column_records)
        for orig, dtype in prof_schema.items():
            if str(orig) not in build_active_original_names(column_records):
                continue
            remapped_schema[name_map.get(str(orig), str(orig))] = dtype
        profiling = dict(profiling)
        profiling["schema"] = remapped_schema
        out["profiling_summary"] = profiling
    phase3 = out.get("phase3")
    if isinstance(phase3, dict):
        out["phase3"] = filter_phase3_by_columns(
            phase3,
            column_records,
            column_normalization=col_norm if isinstance(col_norm, list) else None,
        )
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
