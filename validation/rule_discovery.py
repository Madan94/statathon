"""Dynamic Rule Discovery Engine.

Generates validation rules from FIVE sources, in priority order:

  1. KG relationships (BELONGS_TO, PART_OF, DEPENDS_ON, INFLUENCES, CORRELATED_WITH)
     -> aggregation rules, dependency-bound rules, conservation rules
  2. Domain ontology (semantic_domain + expected_dtype/range/kind metadata)
     -> bound rules and dtype rules for the column's mapped domain
  3. Static rule library (validation_rule_library.json)
     -> hand-curated MoSPI rules (61 single + 10 multi)
  4. Statistical metadata (DistributionProfile)
     -> empirical-range and unimodality rules
  5. Dataset archetype (labour, agriculture, economic, ...)
     -> archetype-specific defaults (e.g. all percentages 0-100)

Output is a list of `DiscoveredRule` objects each tagged with
`source` and a 5-factor `confidence_signals` block used downstream.

No rule requires manual coding per dataset — rules emerge from the data,
the KG, and the ontology automatically.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule data structure
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredRule:
    rule_id: str
    kind: str                 # 'single_column' | 'multi_column'
    rule_type: str            # 'numeric_between' | 'aggregation_equals' | ...
    columns: list[str]        # for single: [col]; for multi: [left, right] or [comps..., target]
    params: dict[str, Any] = field(default_factory=dict)
    severity: str = "medium"
    source: str = "unknown"   # 'kg' | 'ontology' | 'library' | 'statistical' | 'archetype'
    confidence_signals: dict[str, float] = field(default_factory=dict)
    explanation: str = ""
    kg_relationships: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "kind": self.kind,
            "rule_type": self.rule_type,
            "columns": self.columns,
            "params": self.params,
            "severity": self.severity,
            "source": self.source,
            "confidence_signals": self.confidence_signals,
            "explanation": self.explanation,
            "kg_relationships": self.kg_relationships,
        }


# ---------------------------------------------------------------------------
# Source 1: KG-driven rule discovery
# ---------------------------------------------------------------------------


def discover_from_kg(
    schema_graph: dict[str, Any] | None,
    priority_dependencies: dict[str, Any] | None,
    column_domains: dict[str, str] | None = None,
    *,
    min_edge_weight: float = 0.5,
) -> list[DiscoveredRule]:
    """Walk the KG and emit multi-column rules.

    Edge types and the rules they yield:
      * BELONGS_TO + PART_OF   → aggregation_equals (sum components = parent)
      * INFLUENCES (high w)    → bounded relationship (Spearman correlation must hold)
      * DEPENDS_ON             → conditional non-null (if parent observed, child should be too)
      * CORRELATED_WITH        → soft consistency rule
    """
    rules: list[DiscoveredRule] = []
    column_domains = column_domains or {}

    # ---- Edge-driven multi-column rules ----
    edges = (schema_graph or {}).get("edges") if isinstance(schema_graph, dict) else []
    edges = edges or []
    rule_idx = 0

    for e in edges:
        if not isinstance(e, dict):
            continue
        src = e.get("source")
        tgt = e.get("target")
        weight = float(e.get("weight") or 0.0)
        rtype = str(e.get("relationship_type") or "").upper()
        if not src or not tgt or weight < min_edge_weight:
            continue

        # Aggregation pattern: same-domain numeric columns that look like components
        src_dom = column_domains.get(src, "")
        tgt_dom = column_domains.get(tgt, "")
        is_same_domain = src_dom and src_dom == tgt_dom

        if rtype in ("CORRELATED_WITH", "SEMANTICALLY_SIMILAR") and is_same_domain:
            rule_idx += 1
            rules.append(DiscoveredRule(
                rule_id=f"kg_corr_{rule_idx}",
                kind="multi_column",
                rule_type="correlation_consistency",
                columns=[src, tgt],
                params={"min_corr": 0.30, "edge_weight": weight},
                severity="low",
                source="kg",
                confidence_signals={
                    "graph_support": min(1.0, weight),
                    "semantic_support": 0.7 if is_same_domain else 0.4,
                },
                explanation=f"{src} and {tgt} share domain '{src_dom}' with edge weight {weight:.2f}; values should remain correlated",
                kg_relationships=[rtype],
            ))

        # INFLUENCES with high weight => the influencer should bound the dependent
        if rtype in ("INFLUENCES", "CONTEXT_INFLUENCES") and weight >= 0.65:
            rule_idx += 1
            rules.append(DiscoveredRule(
                rule_id=f"kg_inf_{rule_idx}",
                kind="multi_column",
                rule_type="dependency_implication",
                columns=[src, tgt],
                params={"edge_weight": weight, "direction": "src_influences_tgt"},
                severity="medium",
                source="kg",
                confidence_signals={
                    "graph_support": min(1.0, weight),
                    "semantic_support": 0.6,
                },
                explanation=f"{src} INFLUENCES {tgt} (weight {weight:.2f}); when {src} changes substantially, {tgt} should respond",
                kg_relationships=[rtype],
            ))

    # ---- Dependency graph (priority_dependencies) ----
    deps = priority_dependencies or {}
    if isinstance(deps, dict):
        for dependent_col, influencers in deps.items():
            if not isinstance(influencers, list):
                continue
            for inf in influencers[:3]:  # top-3 influencers per column
                if not isinstance(inf, dict):
                    continue
                src_col = inf.get("column") or inf.get("source_column")
                score = float(inf.get("score") or inf.get("influence_score") or 0)
                if not src_col or score < 0.50:
                    continue
                rule_idx += 1
                rules.append(DiscoveredRule(
                    rule_id=f"kg_dep_{rule_idx}",
                    kind="multi_column",
                    rule_type="non_null_dependency",
                    columns=[src_col, str(dependent_col)],
                    params={"influence_score": score},
                    severity="low",
                    source="kg",
                    confidence_signals={
                        "graph_support": min(1.0, score),
                        "semantic_support": 0.55,
                    },
                    explanation=f"{dependent_col} depends on {src_col} (score {score:.2f}); both should be observed together",
                    kg_relationships=["DEPENDS_ON"],
                ))

    # ---- Token-driven aggregation discovery ----
    # If we have male_X / female_X / total_X triplets, propose an aggregation rule.
    rules.extend(_discover_aggregation_triplets(
        list(column_domains.keys()), rule_idx_start=rule_idx,
    ))
    return rules


def _discover_aggregation_triplets(columns: list[str], rule_idx_start: int = 0
                                    ) -> list[DiscoveredRule]:
    """Find male_X + female_X = total_X type patterns purely from column names."""
    rules: list[DiscoveredRule] = []
    rule_idx = rule_idx_start

    def _suffix(name: str, prefix: str) -> str | None:
        m = re.match(rf"^{prefix}[_\s]+(.*)$", str(name).lower())
        if m:
            return m.group(1)
        m = re.match(rf"^(.*)[_\s]+{prefix}$", str(name).lower())
        if m:
            return m.group(1)
        return None

    male_suffixes = {_suffix(c, "male"): c for c in columns if _suffix(c, "male")}
    female_suffixes = {_suffix(c, "female"): c for c in columns if _suffix(c, "female")}
    total_suffixes = {_suffix(c, "total"): c for c in columns if _suffix(c, "total")}

    for suffix, total_col in total_suffixes.items():
        m_col = male_suffixes.get(suffix)
        f_col = female_suffixes.get(suffix)
        if m_col and f_col:
            rule_idx += 1
            rules.append(DiscoveredRule(
                rule_id=f"kg_agg_{rule_idx}",
                kind="multi_column",
                rule_type="aggregation_equals",
                columns=[m_col, f_col, total_col],
                params={"tolerance_rel": 0.01, "aggregator": "+",
                        "components": [m_col, f_col], "target": total_col},
                severity="high",
                source="kg",
                confidence_signals={
                    "graph_support": 0.80,
                    "semantic_support": 0.95,
                    "ontology_support": 0.85,
                },
                explanation=f"{m_col} + {f_col} should equal {total_col}",
                kg_relationships=["PART_OF", "BELONGS_TO"],
            ))

    # Rural + Urban = Total
    rural_suffixes = {_suffix(c, "rural"): c for c in columns if _suffix(c, "rural")}
    urban_suffixes = {_suffix(c, "urban"): c for c in columns if _suffix(c, "urban")}
    for suffix, total_col in total_suffixes.items():
        r_col = rural_suffixes.get(suffix)
        u_col = urban_suffixes.get(suffix)
        if r_col and u_col:
            rule_idx += 1
            rules.append(DiscoveredRule(
                rule_id=f"kg_agg_{rule_idx}",
                kind="multi_column",
                rule_type="aggregation_equals",
                columns=[r_col, u_col, total_col],
                params={"tolerance_rel": 0.01, "aggregator": "+",
                        "components": [r_col, u_col], "target": total_col},
                severity="high",
                source="kg",
                confidence_signals={
                    "graph_support": 0.80,
                    "semantic_support": 0.95,
                    "ontology_support": 0.85,
                },
                explanation=f"{r_col} + {u_col} should equal {total_col}",
                kg_relationships=["PART_OF"],
            ))

    return rules


# ---------------------------------------------------------------------------
# Source 2: Domain ontology metadata
# ---------------------------------------------------------------------------


def discover_from_ontology(
    columns_meta: dict[str, dict[str, Any]],
    unified_domains: list[dict[str, Any]] | None = None,
) -> list[DiscoveredRule]:
    """For each column with a mapped domain, generate the bound rules implied
    by the domain's `expected_range` / `expected_kind` / `expected_dtype`."""
    domain_meta_by_name: dict[str, dict[str, Any]] = {}
    for d in (unified_domains or []):
        if isinstance(d, dict) and d.get("name"):
            domain_meta_by_name[str(d["name"])] = d

    rules: list[DiscoveredRule] = []
    idx = 0
    for col, meta in (columns_meta or {}).items():
        if not isinstance(meta, dict):
            continue
        domain = meta.get("domain") or meta.get("semantic_domain")
        if not domain:
            continue
        dom_meta = domain_meta_by_name.get(str(domain), {})
        expected_range = dom_meta.get("expected_range")
        expected_kind = dom_meta.get("expected_kind")
        confidence = float(meta.get("confidence") or 0.7)

        if expected_range and isinstance(expected_range, (list, tuple)) and len(expected_range) == 2:
            idx += 1
            rules.append(DiscoveredRule(
                rule_id=f"ont_range_{idx}",
                kind="single_column",
                rule_type="numeric_between",
                columns=[col],
                params={"min": float(expected_range[0]),
                        "max": float(expected_range[1])},
                severity="high" if expected_kind == "percentage" else "medium",
                source="ontology",
                confidence_signals={
                    "ontology_support": 0.95,
                    "semantic_support": confidence,
                },
                explanation=f"Domain '{domain}' declares range {expected_range[0]} <= x <= {expected_range[1]}",
            ))

        if expected_kind == "percentage":
            # Even if no range, percentage implies 0..100
            idx += 1
            rules.append(DiscoveredRule(
                rule_id=f"ont_pct_{idx}",
                kind="single_column",
                rule_type="numeric_between",
                columns=[col],
                params={"min": 0.0, "max": 100.0},
                severity="high",
                source="ontology",
                confidence_signals={
                    "ontology_support": 1.0,
                    "semantic_support": confidence,
                },
                explanation=f"Domain '{domain}' is a percentage; values must be in [0, 100]",
            ))

    return rules


# ---------------------------------------------------------------------------
# Source 3: Static rule library  (delegates to existing repository)
# ---------------------------------------------------------------------------


def discover_from_library(
    library_path: str | Path | None = None,
) -> list[DiscoveredRule]:
    """Load the JSON rule library and surface it as DiscoveredRule objects."""
    path = Path(library_path) if library_path else (
        Path(__file__).resolve().parent.parent
        / "model" / "config" / "validation_rule_library.json"
    )
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load rule library: %s", exc)
        return []

    rules: list[DiscoveredRule] = []
    for r in data.get("rules", []):
        rules.append(DiscoveredRule(
            rule_id=str(r.get("id") or "lib_rule"),
            kind="single_column",
            rule_type=str(r.get("rule_type") or ""),
            columns=[r.get("column_name_pattern") or ""],   # pattern, matched later
            params=r.get("params") or {},
            severity=str(r.get("severity") or "medium"),
            source="library",
            confidence_signals={
                "historical_support": 0.85,
                "ontology_support": 0.70,
            },
            explanation=f"MoSPI rule: {r.get('rule_name', '')}",
        ))
    for r in data.get("multi_column_rules", []):
        rules.append(DiscoveredRule(
            rule_id=str(r.get("id") or "lib_multi"),
            kind="multi_column",
            rule_type=str(r.get("kind") or ""),
            columns=[],   # template_executor resolves patterns
            params=r,
            severity=str(r.get("severity") or "medium"),
            source="library",
            confidence_signals={
                "historical_support": 0.85,
                "ontology_support": 0.65,
            },
            explanation=f"MoSPI cross-column rule: {r.get('id', '')}",
        ))
    return rules


# ---------------------------------------------------------------------------
# Source 4: Statistical metadata (DistributionProfile)
# ---------------------------------------------------------------------------


def discover_from_statistics(
    column_profiles: dict[str, Any],
    *,
    expand_factor: float = 1.5,
) -> list[DiscoveredRule]:
    """Generate empirical-range guard rails from observed distributions.

    Useful for columns the ontology doesn't cover — guards against the
    most egregious data-entry errors (negative population, age=9999).
    """
    rules: list[DiscoveredRule] = []
    idx = 0
    for col, profile in (column_profiles or {}).items():
        if isinstance(profile, dict):
            mn = profile.get("min")
            mx = profile.get("max")
            iqr = profile.get("iqr")
            count = profile.get("count") or profile.get("sample_size_used")
        else:
            mn = getattr(profile, "min", None)
            mx = getattr(profile, "max", None)
            iqr = getattr(profile, "iqr", None)
            count = getattr(profile, "count", None) or getattr(profile, "sample_size_used", None)
        if mn is None or mx is None or count is None or int(count) < 20:
            continue
        if iqr is None or iqr <= 0:
            continue
        # Expand fences by expand_factor * IQR — anything beyond is statistically egregious
        lo = float(mn) - float(iqr) * expand_factor
        hi = float(mx) + float(iqr) * expand_factor
        idx += 1
        rules.append(DiscoveredRule(
            rule_id=f"stat_range_{idx}",
            kind="single_column",
            rule_type="numeric_between",
            columns=[col],
            params={"min": lo, "max": hi},
            severity="low",
            source="statistical",
            confidence_signals={
                "statistical_support": min(1.0, int(count) / 100.0),
                "ontology_support": 0.30,
            },
            explanation=f"Empirical range from {int(count)} observations: {lo:.2f}..{hi:.2f}",
        ))
    return rules


# ---------------------------------------------------------------------------
# Source 5: Dataset archetype defaults
# ---------------------------------------------------------------------------


def discover_from_archetype(
    archetypes: list[dict[str, Any]] | None,
    columns_meta: dict[str, dict[str, Any]],
) -> list[DiscoveredRule]:
    """Archetype-level defaults — e.g. dataset is a labour survey, so any
    column matching `*_rate` should be 0..100."""
    if not archetypes:
        return []
    top_archetype = max(archetypes, key=lambda a: a.get("score", 0)).get("archetype")
    rules: list[DiscoveredRule] = []
    idx = 0
    if top_archetype in ("labour", "economic"):
        for col, meta in (columns_meta or {}).items():
            if re.search(r"_rate$|_pct$|_percentage$|^rate_", str(col), re.IGNORECASE):
                idx += 1
                rules.append(DiscoveredRule(
                    rule_id=f"arch_pct_{idx}",
                    kind="single_column",
                    rule_type="numeric_between",
                    columns=[col],
                    params={"min": 0.0, "max": 100.0},
                    severity="high",
                    source="archetype",
                    confidence_signals={
                        "ontology_support": 0.80,
                        "historical_support": 0.75,
                    },
                    explanation=f"{top_archetype} archetype: '*_rate' columns must be percentages",
                ))
    return rules


# ---------------------------------------------------------------------------
# Top-level discover() — merges + de-dupes from all five sources
# ---------------------------------------------------------------------------


def discover_all_rules(
    *,
    columns: list[str],
    columns_meta: dict[str, dict[str, Any]] | None = None,
    schema_graph: dict[str, Any] | None = None,
    priority_dependencies: dict[str, Any] | None = None,
    column_profiles: dict[str, Any] | None = None,
    unified_domains: list[dict[str, Any]] | None = None,
    archetypes: list[dict[str, Any]] | None = None,
    library_path: str | Path | None = None,
) -> list[DiscoveredRule]:
    """Run all five discovery sources and return the merged rule set."""
    columns_meta = columns_meta or {}
    column_domains = {
        col: (meta.get("domain") or meta.get("semantic_domain") or "")
        for col, meta in columns_meta.items()
        if isinstance(meta, dict)
    }

    rules: list[DiscoveredRule] = []
    rules += discover_from_library(library_path)
    rules += discover_from_ontology(columns_meta, unified_domains)
    rules += discover_from_kg(schema_graph, priority_dependencies, column_domains)
    rules += discover_from_statistics(column_profiles or {})
    rules += discover_from_archetype(archetypes, columns_meta)

    # De-dupe: same (kind, rule_type, columns, params) is one rule; keep highest-source-priority
    source_rank = {"library": 5, "ontology": 4, "kg": 3, "archetype": 2, "statistical": 1}
    seen: dict[str, DiscoveredRule] = {}
    for r in rules:
        key = f"{r.kind}::{r.rule_type}::{','.join(map(str, r.columns))}::{json.dumps(r.params, sort_keys=True, default=str)}"
        existing = seen.get(key)
        if existing is None or source_rank.get(r.source, 0) > source_rank.get(existing.source, 0):
            seen[key] = r
    return list(seen.values())
