"""Classify columns as identifier (design/code) vs variable (measured outcome)."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from semantic_mapping_v2.feature_extraction import ColumnFeature
from semantic_mapping_v2.llm_client import generate_text, llm_configured, strip_json_fence
from semantic_mapping_v2.matching_engine import ColumnMapping

logger = logging.getLogger(__name__)

ANALYSIS_ROLES = frozenset({"identifier", "variable"})

_IDENTIFIER_DOMAINS = frozenset(
    {
        "identifier",
        "survey_metadata",
        "geography",
        "geographic",
        "location",
    }
)
_VARIABLE_DOMAINS = frozenset(
    {
        "food_expenditure",
        "labour",
        "employment",
        "income",
        "wage",
        "demographic",
        "health",
        "education",
        "economic",
        "consumption",
        "expenditure",
    }
)
_IDENTIFIER_NAME_TOKENS = frozenset(
    {
        "district",
        "stratum",
        "region",
        "state",
        "sector",
        "schedule",
        "sample",
        "round",
        "serial",
        "psu",
        "fsu",
        "block",
        "village",
        "household",
        "hh",
        "identifier",
        "id",
        "code",
        "nss",
        "centre",
        "center",
        "division",
        "subdivision",
        "tehsil",
        "ward",
    }
)


@dataclass
class ColumnRoleResult:
    column: str
    analysis_role: str
    role_confidence: float
    role_source: str
    role_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_role": self.analysis_role,
            "role_confidence": round(self.role_confidence, 4),
            "role_source": self.role_source,
            "role_reason": self.role_reason,
        }


def _role_llm_enabled() -> bool:
    if os.getenv("SEMV2_ROLE_HEURISTIC_ONLY", "").lower() in ("1", "true", "yes"):
        return False
    if os.getenv("SEMV2_ROLE_LLM_ENABLED", "1").lower() in ("0", "false", "no"):
        return False
    return llm_configured()


def _name_tokens(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(name or "").lower()))


def _heuristic_role(
    feat: ColumnFeature,
    mapping: ColumnMapping | None,
) -> ColumnRoleResult | None:
    col = feat.name
    domain = str(mapping.domain if mapping else "").lower()
    tokens = _name_tokens(feat.name) | _name_tokens(feat.original_name or "")

    if feat.dtype == "id":
        return ColumnRoleResult(
            col,
            "identifier",
            0.92,
            "heuristic",
            "High-uniqueness ID-like column name and values.",
        )

    if domain in _IDENTIFIER_DOMAINS and feat.dtype in {"categorical", "numeric", "id", "text"}:
        if tokens & _IDENTIFIER_NAME_TOKENS or (feat.cardinality and feat.cardinality <= 500):
            return ColumnRoleResult(
                col,
                "identifier",
                0.88,
                "heuristic",
                f"Survey design / geography domain ({domain}) with coded values.",
            )

    if domain in _VARIABLE_DOMAINS and feat.dtype == "numeric":
        return ColumnRoleResult(
            col,
            "variable",
            0.85,
            "heuristic",
            f"Measured outcome domain ({domain}) with numeric values.",
        )

    if tokens & _IDENTIFIER_NAME_TOKENS:
        if feat.dtype in {"categorical", "text", "boolean"} or (
            feat.dtype == "numeric" and feat.cardinality and feat.cardinality <= 200
        ):
            return ColumnRoleResult(
                col,
                "identifier",
                0.82,
                "heuristic",
                "Column name indicates survey design / geography code.",
            )

    if feat.dtype == "numeric" and domain in _VARIABLE_DOMAINS:
        return ColumnRoleResult(
            col,
            "variable",
            0.8,
            "heuristic",
            f"Numeric measure in domain {domain}.",
        )

    return None


def _llm_classify_batch(
    *,
    usecase: str,
    dataset_name: str,
    pending: dict[str, tuple[ColumnFeature, ColumnMapping | None]],
) -> dict[str, ColumnRoleResult]:
    out: dict[str, ColumnRoleResult] = {}
    if not pending or not _role_llm_enabled():
        return out

    chunk_size = max(1, int(os.getenv("SEMV2_LLM_BATCH_SIZE", "8")))
    chunk_delay = float(os.getenv("SEMV2_LLM_CHUNK_DELAY", "2.5"))
    pending_list = list(pending.items())

    for start in range(0, len(pending_list), chunk_size):
        if start > 0:
            time.sleep(chunk_delay)
        chunk = pending_list[start : start + chunk_size]
        items = []
        for col, (feat, mapping) in chunk:
            items.append(
                {
                    "column_name": feat.name,
                    "original_name": feat.original_name or feat.name,
                    "domain": mapping.domain if mapping else "",
                    "dtype": feat.dtype,
                    "samples": [str(v)[:24] for v in feat.samples[:5]],
                    "cardinality": feat.cardinality,
                    "missing_ratio": feat.missing_ratio,
                }
            )
        prompt = f"""Classify each column for a '{usecase}' survey dataset '{dataset_name}'.

IDENTIFIER columns: survey design / geography / strata / PSU / round / schedule / serial / household id codes.
They label rows but are NOT measured outcomes (even when numeric like 1,2,3).

VARIABLE columns: measured quantities, expenditures, counts, durations, rates — subject to plausibility rules.

COLUMNS:
{json.dumps(items, ensure_ascii=True)}

Return JSON only:
{{"columns":[{{"column_name":"...","analysis_role":"identifier|variable","confidence":0.0,"reason":"..."}}]}}"""
        try:
            raw = generate_text(prompt, system="Return valid JSON only.")
            data = json.loads(strip_json_fence(raw))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Role LLM chunk failed (%d cols): %s", len(chunk), exc)
            continue

        if isinstance(data, dict):
            data = data.get("columns") or data.get("results") or [data]
        if not isinstance(data, list):
            continue

        by_name = {
            str(d.get("column_name", "")).strip(): d
            for d in data
            if isinstance(d, dict)
        }
        for col, (feat, _mapping) in chunk:
            entry = by_name.get(col) or by_name.get(feat.name)
            if not entry:
                continue
            role = str(entry.get("analysis_role") or entry.get("role") or "").lower()
            if role not in ANALYSIS_ROLES:
                continue
            conf = float(entry.get("confidence") or entry.get("role_confidence") or 0.75)
            reason = str(entry.get("reason") or entry.get("role_reason") or "LLM classification")
            out[col] = ColumnRoleResult(col, role, conf, "llm", reason)
    return out


def classify_column_roles(
    *,
    features: dict[str, ColumnFeature],
    mappings: dict[str, ColumnMapping],
    usecase: str,
    dataset_name: str,
    use_llm: bool = True,
) -> tuple[dict[str, ColumnRoleResult], dict[str, int]]:
    """Return per-column role results and stats counters."""
    results: dict[str, ColumnRoleResult] = {}
    pending: dict[str, tuple[ColumnFeature, ColumnMapping | None]] = {}

    for col, feat in features.items():
        mapping = mappings.get(col)
        heuristic = _heuristic_role(feat, mapping)
        if heuristic is not None:
            results[col] = heuristic
        else:
            pending[col] = (feat, mapping)

    llm_results: dict[str, ColumnRoleResult] = {}
    if use_llm and pending:
        llm_results = _llm_classify_batch(
            usecase=usecase,
            dataset_name=dataset_name,
            pending=pending,
        )

    for col in pending:
        if col in llm_results:
            results[col] = llm_results[col]
        else:
            feat, mapping = pending[col]
            domain = str(mapping.domain if mapping else "").lower()
            default_role = "variable" if feat.dtype == "numeric" and domain in _VARIABLE_DOMAINS else "identifier"
            if feat.dtype == "numeric" and domain not in _IDENTIFIER_DOMAINS:
                default_role = "variable"
            results[col] = ColumnRoleResult(
                col,
                default_role,
                0.55,
                "heuristic",
                "Default fallback when LLM unavailable or inconclusive.",
            )

    stats = {
        "role_heuristic_count": sum(1 for r in results.values() if r.role_source == "heuristic"),
        "role_llm_count": sum(1 for r in results.values() if r.role_source == "llm"),
        "role_identifier_count": sum(1 for r in results.values() if r.analysis_role == "identifier"),
        "role_variable_count": sum(1 for r in results.values() if r.analysis_role == "variable"),
    }
    return results, stats


def apply_roles_to_mappings(
    mappings: dict[str, ColumnMapping],
    roles: dict[str, ColumnRoleResult],
) -> None:
    """Mutate mapping entries in-place (via semantic_mapping assembly)."""
    for col, role in roles.items():
        if col not in mappings:
            continue
        mapping = mappings[col]
        mapping.signals = dict(mapping.signals or {})
        mapping.signals["analysis_role"] = role.analysis_role
