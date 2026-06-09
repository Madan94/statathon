"""S3 helper — filter value resolver (canonical member ↔ stored value).

A blueprint filter says *"sector = Rural"* but the dataset may store that value
as ``"R"``, ``"rural"`` or ``"Rural "``. This module maps a **canonical member
label** to the **actual stored value** in a column, using a short cascade:

    1. exact (case-insensitive, whitespace-trimmed)
    2. normalized (punctuation/space stripped)
    3. code / synonym expansion (Rural↔R, Urban↔U, Male↔M …)
    4. fuzzy (SequenceMatcher ≥ 0.85)

If nothing matches, the value is returned unchanged with ``applied=False`` — the
caller widens the filter (decision: *widen-on-missing-default*, never silently
drop rows). Deterministic and offline.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_FUZZY_FLOOR = 0.85

# Common survey codings (label → accepted stored codes/forms).
_CODE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "rural": ("r", "rur", "rural"),
    "urban": ("u", "urb", "urban"),
    "male": ("m", "male", "men", "1"),
    "female": ("f", "female", "women", "2"),
    "transgender": ("t", "tg", "transgender", "other", "3"),
    "yes": ("y", "yes", "true", "1"),
    "no": ("n", "no", "false", "0"),
    "total": ("total", "all", "both", "t"),
}


def _norm(v: Any) -> str:
    return "".join(_SPLIT_RE.split(str(v).strip().lower()))


def _synonym_forms(label: str) -> set[str]:
    key = str(label).strip().lower()
    forms = {key, _norm(label)}
    if key in _CODE_SYNONYMS:
        forms.update(_CODE_SYNONYMS[key])
    # reverse lookup: a code that maps to a canonical label
    for canon, codes in _CODE_SYNONYMS.items():
        if key in codes:
            forms.add(canon)
            forms.update(codes)
    return {f for f in forms if f}


def resolve_filter_value(
    canonical_value: Any,
    distinct_values: list[Any],
) -> tuple[Any, bool]:
    """Map a canonical member label to the actual stored value in a column.

    Returns ``(resolved_value, applied)``. ``applied=False`` means the value was
    not found among ``distinct_values`` — the caller should widen the filter.
    """
    if canonical_value is None:
        return None, False
    if not distinct_values:
        return canonical_value, False

    target_norm = _norm(canonical_value)
    by_norm = {_norm(v): v for v in distinct_values}

    # 1. exact (normalized)
    if target_norm in by_norm:
        return by_norm[target_norm], True

    # 2. code / synonym expansion (both directions)
    forms = _synonym_forms(canonical_value)
    for form in forms:
        fn = _norm(form)
        if fn in by_norm:
            return by_norm[fn], True

    # 3. fuzzy
    best_v, best_score = None, 0.0
    for vn, original in by_norm.items():
        score = SequenceMatcher(None, target_norm, vn).ratio()
        if score > best_score:
            best_v, best_score = original, score
    if best_v is not None and best_score >= _FUZZY_FLOOR:
        return best_v, True

    # 4. not found → widen
    return canonical_value, False
