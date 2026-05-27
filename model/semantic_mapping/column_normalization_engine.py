"""
Dynamic column normalisation — ontology + RapidFuzz + pipeline routing metadata.
Works for any dataset archetype; no hardcoded column-name table.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rapidfuzz import distance

from semantic_mapping.column_preprocessor import ColumnPreprocessor


def _title(text: str) -> str:
    return " ".join(w.capitalize() for w in text.split() if w)


def _humanize_token(token: str) -> str:
    t = token.replace("_", " ").replace("-", " ").strip()
    return _title(t) if t else token


class ColumnNormalizationEngine:
    """Build per-column normalisation plan from live pipeline outputs."""

    def __init__(self, ontology_path: str | Path | None = None):
        repo_root = Path(__file__).resolve().parents[2]
        path = Path(ontology_path or repo_root / "model" / "config" / "domain_definitions.json")
        with open(path, encoding="utf-8") as f:
            self.ontology = json.load(f)

        self.preprocessor = ColumnPreprocessor()
        self._vocab: dict[str, str] = {}
        self._domain_labels: dict[str, str] = {}
        self._build_vocabulary()

    def _build_vocabulary(self) -> None:
        """Flatten all ontology subdomain keywords into a fuzzy lookup table."""
        for tier_name, tier_data in (self.ontology.get("dataset_types") or {}).items():
            self._domain_labels[tier_name] = str(tier_data.get("label") or _humanize_token(tier_name))
            for sub_name, keywords in (tier_data.get("subdomains") or {}).items():
                self._domain_labels[sub_name] = _humanize_token(sub_name)
                self._vocab[sub_name.lower()] = _humanize_token(sub_name)
                for kw in keywords or []:
                    key = str(kw).lower().strip()
                    if key:
                        self._vocab[key] = _humanize_token(str(kw).replace("_", " "))

    def _fuzzy_label(
        self, column_name: str, normalized: str, archetype: str | None
    ) -> tuple[str, float, str | None]:
        """Return (label, score, matched_keyword) from ontology vocabulary."""
        candidates: list[str] = []
        tier = (self.ontology.get("dataset_types") or {}).get(archetype or "", {})
        for keywords in (tier.get("subdomains") or {}).values():
            candidates.extend(str(k).lower() for k in keywords or [])
        if not candidates:
            candidates = list(self._vocab.keys())

        tokens = [t for t in re.split(r"[\s_]+", normalized.lower()) if len(t) >= 2]
        if not tokens:
            tokens = [column_name.lower()]

        best_score = 0.0
        best_keyword: str | None = None
        for token in tokens:
            for cand in candidates:
                # Skip prefix traps such as "month" matching inside "monthly"
                if len(cand) < len(token) and token.startswith(cand) and cand != token:
                    continue
                if len(token) < len(cand) and cand.startswith(token) and cand != token:
                    continue
                score = float(distance.JaroWinkler.normalized_similarity(token, cand))
                if score > best_score:
                    best_score = score
                    best_keyword = cand

        if best_keyword and best_score >= 0.88:
            label = self._vocab.get(best_keyword, _humanize_token(best_keyword))
            return label, best_score, best_keyword
        return _title(normalized), 0.0, None

    def _domain_display(self, domain: str | None) -> str | None:
        if not domain or domain in {"unknown", "uncorrelated", "uncorrelated_metadata"}:
            return None
        return self._domain_labels.get(domain, _humanize_token(domain))

    def _infer_method(self, routing: dict[str, Any] | None, meta: dict[str, Any] | None) -> str:
        if routing and routing.get("match_method"):
            return str(routing["match_method"])
        reason = ((meta or {}).get("explainability") or {}).get("matching_reason") or ""
        if "Static Ontology Lock" in reason:
            return "schema_ontology_lock"
        if "Dynamic Fallback" in reason:
            return "dynamic_cluster"
        return "embedding_similarity"

    def build_plan(
        self,
        *,
        columns: list[str],
        normalized_map: dict[str, str],
        semantic_results: dict[str, dict[str, Any]],
        routing_by_column: dict[str, dict[str, Any]] | None = None,
        column_profiles: dict[str, Any] | None = None,
        dataset_archetype: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Build the normalisation plan.

        The normalisation layer is purely about column-name expansion:
        abbreviation resolution, camelCase splitting, title-casing.
        Domain information is stored but the `display_name` shown to the
        user at this step is the plain expanded label WITHOUT any domain
        prefix (domain prefix is only applied downstream in the semantic
        mapping / Step 3 view).
        """
        routing_by_column = routing_by_column or {}
        column_profiles = column_profiles or {}
        plan: list[dict[str, Any]] = []

        for col in columns:
            normalized = normalized_map.get(col) or self.preprocessor.to_sentence(col)
            meta = semantic_results.get(col) or {}
            routing = routing_by_column.get(col) or {}

            fuzzy_label, fuzzy_score, matched_kw = self._fuzzy_label(col, normalized, dataset_archetype)
            method = routing.get("match_method")
            if method == "dynamic_cluster":
                base_label = _title(normalized)
            elif routing.get("display_label"):
                base_label = str(routing["display_label"])
            elif fuzzy_score >= 0.88:
                base_label = fuzzy_label
            else:
                base_label = _title(normalized)

            # domain info is stored for Step 3 use, but display_name here
            # is the plain label — no "Domain ·" prefix at normalization layer
            domain = str(meta.get("domain") or routing.get("predicted_domain") or "unknown")
            domain_prefix = self._domain_display(domain)
            display_name = base_label  # plain expanded name only

            profile = column_profiles.get(col) if isinstance(column_profiles, dict) else None
            hints = (profile or {}).get("semantic_hints") if isinstance(profile, dict) else None

            plan.append(
                {
                    "original_name": col,
                    "normalized_name": normalized,
                    "display_name": display_name,
                    # full_display_name is the Step-3 / report label with domain prefix
                    "full_display_name": f"{domain_prefix} · {base_label}" if domain_prefix else base_label,
                    "domain": domain,
                    "domain_prefix": domain_prefix,
                    "base_label": base_label,
                    "match_method": self._infer_method(routing, meta),
                    "match_confidence": meta.get("confidence"),
                    "fuzzy_score": round(fuzzy_score, 4) if fuzzy_score else None,
                    "matched_keyword": matched_kw or routing.get("matched_keyword"),
                    "routing_locked": bool(routing.get("is_locked") or meta.get("confidence") == 1.0),
                    "semantic_hints": hints if isinstance(hints, list) else [],
                    "matching_reason": ((meta.get("explainability") or {}).get("matching_reason")),
                    "dataset_archetype": dataset_archetype,
                }
            )
        return plan
