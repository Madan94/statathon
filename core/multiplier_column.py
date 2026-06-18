"""Survey multiplier columns — exact-name match, detach for pipeline, reattach on final export."""
from __future__ import annotations

from typing import Any

import pandas as pd

# Exact header match only (case-sensitive).
MULTIPLIER_EXACT_NAMES: frozenset[str] = frozenset(
    {"MULT", "Multiplier", "mult", "MULTIPLIER", "multiplier"}
)


def is_multiplier_column(name: str | None) -> bool:
    if not name:
        return False
    return str(name) in MULTIPLIER_EXACT_NAMES


def find_multiplier_columns(df: pd.DataFrame) -> list[str]:
    return [str(c) for c in df.columns if is_multiplier_column(str(c))]


def filter_rename_map(rename: dict[str, str]) -> dict[str, str]:
    """Drop renames that touch survey multiplier headers (preserve upload names)."""
    return {
        k: v
        for k, v in rename.items()
        if not is_multiplier_column(k) and not is_multiplier_column(v)
    }


def extract_multiplier_sidecar(df: pd.DataFrame) -> pd.DataFrame | None:
    """Copy multiplier columns from upload using exact header names and raw values."""
    _, sidecar = detach_multiplier_columns(df)
    return sidecar


def detach_multiplier_columns(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Split multiplier columns out of the working frame (row-aligned)."""
    cols = find_multiplier_columns(df)
    if not cols:
        return df.copy(), None
    sidecar = df[cols].copy().reset_index(drop=True)
    work = df.drop(columns=cols).reset_index(drop=True)
    return work, sidecar


def resolve_column_order_with_multipliers(
    df: pd.DataFrame,
    original_column_order: list[str],
    upload_to_processed: dict[str, str] | None = None,
) -> list[str]:
    """Restore upload column order, placing multiplier headers at their original indices."""
    if not original_column_order:
        return [str(c) for c in df.columns]

    available = set(str(c) for c in df.columns)
    mapping = upload_to_processed or {}
    non_mult_queue: list[str] = []
    queued: set[str] = set()

    for orig in original_column_order:
        orig_s = str(orig)
        if is_multiplier_column(orig_s):
            continue
        proc = str(mapping.get(orig_s, orig_s))
        for candidate in (proc, orig_s):
            if candidate in available and candidate not in queued:
                non_mult_queue.append(candidate)
                queued.add(candidate)
                break

    ordered: list[str] = []
    placed: set[str] = set()
    pending = list(non_mult_queue)

    for orig in original_column_order:
        orig_s = str(orig)
        if is_multiplier_column(orig_s):
            if orig_s in available and orig_s not in placed:
                ordered.append(orig_s)
                placed.add(orig_s)
        elif pending:
            col = pending.pop(0)
            ordered.append(col)
            placed.add(col)

    for col in df.columns:
        col_s = str(col)
        if col_s not in placed:
            ordered.append(col_s)
            placed.add(col_s)
    return ordered


def reattach_multiplier_columns(
    df: pd.DataFrame,
    sidecar: pd.DataFrame | None,
    *,
    original_column_order: list[str] | None = None,
    upload_to_processed: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Reattach detached multiplier columns at their original upload positions."""
    if sidecar is None or sidecar.empty:
        return df.copy()
    out = df.copy().reset_index(drop=True)
    side = sidecar.reset_index(drop=True)
    n = min(len(out), len(side))
    if n == 0:
        return out
    out = out.iloc[:n].copy()
    side = side.iloc[:n]
    for col in side.columns:
        out[col] = side[col].values

    if original_column_order:
        order = resolve_column_order_with_multipliers(
            out,
            original_column_order,
            upload_to_processed,
        )
        out = out[order]
    return out


def filter_sidecar_rows(sidecar: pd.DataFrame | None, keep_indices: list[int]) -> pd.DataFrame | None:
    if sidecar is None or not keep_indices:
        return sidecar
    return sidecar.iloc[keep_indices].reset_index(drop=True)


def row_indices_after_drops(n_rows: int, drop_indices: set[int]) -> list[int]:
    return [i for i in range(n_rows) if i not in drop_indices]


def validation_drop_indices(decisions: list[dict[str, Any]]) -> set[int]:
    drop: set[int] = set()
    for d in decisions:
        action = str(d.get("user_action") or d.get("decision") or "").upper()
        row_id = d.get("row_id")
        if action == "REMOVE_ROW" and isinstance(row_id, int):
            drop.add(int(row_id))
    return drop


def outlier_drop_indices(decisions: list[Any]) -> set[int]:
    drop: set[int] = set()
    for d in decisions:
        action = str(getattr(d, "decision", d.get("decision") if isinstance(d, dict) else "") or "").upper()
        row_index = getattr(d, "row_index", None)
        if row_index is None and isinstance(d, dict):
            row_index = d.get("row_index")
        if action == "DELETE_ROW" and isinstance(row_index, int):
            drop.add(int(row_index))
    return drop


def filter_candidate_rows(candidates: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not candidates:
        return []
    return [
        c
        for c in candidates
        if isinstance(c, dict) and not is_multiplier_column(str(c.get("column") or ""))
    ]


def filter_column_keys(block: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(block, dict):
        return {}
    return {k: v for k, v in block.items() if not is_multiplier_column(str(k))}
