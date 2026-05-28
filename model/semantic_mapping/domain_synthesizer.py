"""Merge static (MoSPI ontology) + dynamic (synthesised) domains.

Output of this module is the unified domain candidate list that the
semantic pipeline ranks against each column. Both static and dynamic
domains compete on equal footing — the calibrated confidence formula
in `confidence_engine.py` decides the winner.

Public API:
  * unify_domains(static_domains, dynamic_domains) -> list[UnifiedDomain]
  * UnifiedDomain.to_dict()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dynamic_domain_synth import DynamicDomain


@dataclass
class UnifiedDomain:
    name: str                       # canonical key
    display_name: str
    aliases: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    description: str = ""
    expected_dtype: str | None = None
    expected_range: list[float] | None = None
    expected_kind: str | None = None
    expected_skew_sign: str | None = None
    expected_unimodal: bool | None = None
    parent: str | None = None       # for hierarchical roll-ups
    source: str = "static"          # 'static' | 'dynamic' | 'dynamic_llm'
    member_columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "aliases": self.aliases,
            "keywords": self.keywords,
            "description": self.description,
            "expected_dtype": self.expected_dtype,
            "expected_range": self.expected_range,
            "expected_kind": self.expected_kind,
            "expected_skew_sign": self.expected_skew_sign,
            "expected_unimodal": self.expected_unimodal,
            "parent": self.parent,
            "source": self.source,
            "member_columns": self.member_columns,
        }

    # Compatibility: SimilarityEngine.distribution_fingerprint_match consumes
    # `domain_metadata` so we expose the relevant fields as a dict.
    def metadata(self) -> dict[str, Any]:
        return {
            "expected_dtype": self.expected_dtype,
            "expected_range": self.expected_range,
            "expected_kind": self.expected_kind,
            "expected_skew_sign": self.expected_skew_sign,
            "expected_unimodal": self.expected_unimodal,
        }


def unify_domains(
    static_domains: dict[str, dict[str, Any]] | list[dict[str, Any]],
    dynamic_domains: list[DynamicDomain] | None = None,
) -> list[UnifiedDomain]:
    """Combine static + dynamic into a canonical list. De-dupes by canonical name.

    `static_domains` accepts either:
      * a flat list of dicts with at least {name, ...}
      * a nested dict {parent: {subdomain: {...}}} (the existing
        domain_definitions.json shape)
    """
    unified: dict[str, UnifiedDomain] = {}

    # Static
    flat = _flatten_static(static_domains)
    for entry in flat:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        canon = name.lower().replace(" ", "_")
        if canon in unified:
            continue
        unified[canon] = UnifiedDomain(
            name=canon,
            display_name=str(entry.get("display_name") or name.replace("_", " ").title()),
            aliases=list(entry.get("aliases") or []),
            keywords=list(entry.get("keywords") or []),
            description=str(entry.get("description") or ""),
            expected_dtype=entry.get("expected_dtype"),
            expected_range=entry.get("expected_range"),
            expected_kind=entry.get("expected_kind"),
            expected_skew_sign=entry.get("expected_skew_sign"),
            expected_unimodal=entry.get("expected_unimodal"),
            parent=entry.get("parent"),
            source="static",
        )

    # Dynamic
    for d in dynamic_domains or []:
        canon = d.name.lower().replace(" ", "_")
        if canon in unified:
            # If static already covers this canonical name we don't override,
            # but we DO merge member_columns so the static domain learns from
            # the cluster.
            unified[canon].member_columns = list(set(unified[canon].member_columns + d.member_columns))
            continue
        unified[canon] = UnifiedDomain(
            name=canon,
            display_name=d.display_name,
            aliases=list(d.aliases),
            keywords=list(d.keywords),
            description=d.description,
            expected_dtype=d.expected_dtype,
            expected_range=d.expected_range,
            source=d.source,
            member_columns=list(d.member_columns),
        )

    return list(unified.values())


def _flatten_static(static_domains: Any) -> list[dict[str, Any]]:
    """Normalise the static domain shape to a flat list."""
    if isinstance(static_domains, list):
        return [e for e in static_domains if isinstance(e, dict)]
    if not isinstance(static_domains, dict):
        return []

    out: list[dict[str, Any]] = []
    for parent_key, parent_val in static_domains.items():
        # If a dict has a 'name' at this level, treat it as one entry
        if isinstance(parent_val, dict) and "name" in parent_val:
            entry = dict(parent_val)
            entry.setdefault("parent", parent_key if not isinstance(parent_key, int) else None)
            out.append(entry)
            continue
        # Otherwise recurse one level — typical of MoSPI ontology nesting
        if isinstance(parent_val, dict):
            for sub_key, sub_val in parent_val.items():
                if isinstance(sub_val, dict):
                    entry = dict(sub_val)
                    entry.setdefault("name", sub_key)
                    entry.setdefault("parent", parent_key)
                    out.append(entry)
                elif isinstance(sub_val, list):
                    # subdomain list of keywords
                    out.append({
                        "name": sub_key,
                        "parent": parent_key,
                        "keywords": [str(x) for x in sub_val],
                    })
        elif isinstance(parent_val, list):
            out.append({
                "name": parent_key,
                "keywords": [str(x) for x in parent_val],
            })
    return out
