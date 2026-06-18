"""Shared helpers for identifier vs variable column roles."""
from __future__ import annotations

from typing import Any

ANALYSIS_ROLE_IDENTIFIER = "identifier"
ANALYSIS_ROLE_VARIABLE = "variable"


def normalize_role(value: str | None) -> str | None:
    if not value:
        return None
    key = str(value).strip().lower()
    if key in (ANALYSIS_ROLE_IDENTIFIER, ANALYSIS_ROLE_VARIABLE):
        return key
    return None


def role_from_meta(meta: dict[str, Any] | None) -> str | None:
    if not isinstance(meta, dict):
        return None
    signals = meta.get("signals")
    signal_role = (
        (signals or {}).get("analysis_role") if isinstance(signals, dict) else None
    )
    return normalize_role(meta.get("analysis_role") or meta.get("role") or signal_role)


def build_column_roles(columns_meta: dict[str, dict[str, Any]] | None) -> dict[str, str]:
    """Map column name -> analysis_role (identifier|variable)."""
    out: dict[str, str] = {}
    for col, meta in (columns_meta or {}).items():
        role = role_from_meta(meta if isinstance(meta, dict) else None)
        if role:
            out[str(col)] = role
    return out


def is_identifier_column(
    column: str,
    column_roles: dict[str, str] | None = None,
    columns_meta: dict[str, dict[str, Any]] | None = None,
) -> bool:
    roles = column_roles or build_column_roles(columns_meta)
    role = roles.get(str(column))
    if role:
        return role == ANALYSIS_ROLE_IDENTIFIER
    meta = (columns_meta or {}).get(str(column))
    return role_from_meta(meta if isinstance(meta, dict) else None) == ANALYSIS_ROLE_IDENTIFIER


def variable_columns(
    columns: list[str],
    column_roles: dict[str, str] | None = None,
    columns_meta: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    roles = column_roles or build_column_roles(columns_meta)
    if not roles:
        return list(columns)
    return [c for c in columns if not is_identifier_column(c, roles, columns_meta)]


def identifier_columns(
    columns: list[str],
    column_roles: dict[str, str] | None = None,
    columns_meta: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    roles = column_roles or build_column_roles(columns_meta)
    if not roles:
        return []
    return [c for c in columns if is_identifier_column(c, roles, columns_meta)]


def rule_touches_identifier(
    rule_columns: list[str],
    df_columns: list[str],
    column_roles: dict[str, str] | None,
    columns_meta: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """True when any resolved rule column is an identifier."""
    roles = column_roles or build_column_roles(columns_meta)
    if not roles:
        return False
    for col in rule_columns:
        if col in df_columns and is_identifier_column(col, roles, columns_meta):
            return True
    return False


def is_auxiliary_profile(profile: dict[str, Any] | None) -> bool:
    """Column holds one distinct value across all rows (no missing)."""
    if not isinstance(profile, dict):
        return False
    if profile.get("is_auxiliary") is True:
        return True
    missing = float(profile.get("missing_ratio") or 0)
    cardinality = profile.get("cardinality")
    return missing <= 0 and cardinality == 1


def _profile_for_column(
    column: str,
    column_profiles: dict[str, Any] | None,
    alias_names: set[str] | None = None,
) -> dict[str, Any] | None:
    profiles = column_profiles or {}
    for name in alias_names or {str(column)}:
        prof = profiles.get(str(name))
        if isinstance(prof, dict):
            return prof
    return None


def should_review_column_analysis(
    column: str,
    columns_meta: dict[str, dict[str, Any]] | None = None,
    column_profiles: dict[str, Any] | None = None,
    column_roles: dict[str, str] | None = None,
    alias_names: set[str] | None = None,
) -> bool:
    """True when Step 7 should include this column (variable, not auxiliary)."""
    roles = column_roles or build_column_roles(columns_meta)
    names = alias_names or {str(column)}
    for name in names:
        if is_identifier_column(str(name), roles, columns_meta):
            return False
    profile = _profile_for_column(str(column), column_profiles, names)
    if is_auxiliary_profile(profile):
        return False
    return True
