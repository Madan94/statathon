"""Multi-signal similarity for semantic domain mapping.

Backwards-compatible: the original `compute_similarity` / `compute_domain_similarity`
/ `compute_similarity_matrix` / `compute_keyword_boost` methods continue to work.

New methods:
  * jaccard_token_similarity     (set overlap on tokenised column names)
  * structural_similarity         (snake_case prefix/suffix patterns)
  * dtype_alignment              (numeric column vs numeric-domain marker)
  * distribution_fingerprint_match (skew/range alignment with domain expectations)
  * compose_signals              (collapse all five signals into a CalibratedScore)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from analytics import default_calibrator
from analytics.distribution import DistributionProfile


_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _tokens(text: str | None) -> list[str]:
    if not text:
        return []
    return [t for t in _TOKEN_SPLIT.split(str(text).lower()) if t]


# Convenience markers that domain definitions may carry. The semantic_pipeline
# already passes the domain payload through `compose_signals`, so this is just
# a stable interface contract.
DOMAIN_NUMERIC_HINTS = {
    "rate", "ratio", "amount", "price", "value", "count", "income", "expenditure",
    "salary", "tax", "gdp", "production", "yield", "area", "population",
}
DOMAIN_CATEGORICAL_HINTS = {
    "type", "category", "status", "code", "region", "state", "district",
    "gender", "sex", "religion", "occupation",
}


class SimilarityEngine:
    # ---------------- legacy methods (kept) ----------------

    @staticmethod
    def compute_similarity(vec1, vec2) -> float:
        vec1 = np.asarray(vec1).reshape(1, -1)
        vec2 = np.asarray(vec2).reshape(1, -1)
        return float(cosine_similarity(vec1, vec2)[0][0])

    @staticmethod
    def compute_domain_similarity(column_embedding, domain_embeddings: dict) -> dict[str, float]:
        return {
            domain: SimilarityEngine.compute_similarity(column_embedding, emb)
            for domain, emb in domain_embeddings.items()
        }

    @staticmethod
    def compute_similarity_matrix(embeddings: dict) -> dict:
        columns = list(embeddings.keys())
        if not columns:
            return {}
        vecs = np.array([embeddings[c] for c in columns])
        sim_matrix = cosine_similarity(vecs)
        result: dict[str, dict[str, float]] = {}
        for i, col1 in enumerate(columns):
            result[col1] = {}
            for j, col2 in enumerate(columns):
                if i != j:
                    result[col1][col2] = float(sim_matrix[i][j])
        return result

    @staticmethod
    def compute_keyword_boost(column_tokens: list, domain_keywords: list) -> float:
        if not domain_keywords or not column_tokens:
            return 0.0
        matches = sum(1 for t in column_tokens if t in domain_keywords)
        return min(matches / max(len(column_tokens), 1), 1.0)

    # ---------------- new multi-signal methods ----------------

    @staticmethod
    def jaccard_token_similarity(column_name: str, domain_name: str,
                                 domain_aliases: list[str] | None = None) -> float:
        col_tokens = set(_tokens(column_name))
        if not col_tokens:
            return 0.0
        domain_tokens = set(_tokens(domain_name))
        for alias in (domain_aliases or []):
            domain_tokens.update(_tokens(alias))
        if not domain_tokens:
            return 0.0
        inter = col_tokens & domain_tokens
        union = col_tokens | domain_tokens
        return float(len(inter) / len(union)) if union else 0.0

    @staticmethod
    def structural_similarity(column_name: str, domain_name: str) -> float:
        """Match prefix/suffix patterns: e.g. 'gdp_per_capita' vs domain 'gdp' or 'per_capita'."""
        col_tokens = _tokens(column_name)
        dom_tokens = _tokens(domain_name)
        if not col_tokens or not dom_tokens:
            return 0.0
        score = 0.0
        # Prefix match
        if col_tokens[0] == dom_tokens[0]:
            score += 0.5
        # Suffix match
        if col_tokens[-1] == dom_tokens[-1]:
            score += 0.3
        # Substring containment (one is part of the other)
        joined_col = "_".join(col_tokens)
        joined_dom = "_".join(dom_tokens)
        if joined_dom in joined_col or joined_col in joined_dom:
            score += 0.2
        return float(min(score, 1.0))

    @staticmethod
    def dtype_alignment(column_dtype: str | None,
                        domain_name: str,
                        domain_metadata: dict[str, Any] | None = None) -> float:
        """Does the column's dtype align with what the domain expects?

        Returns 1.0 for clean alignment, 0.5 for ambiguous, 0.0 for mismatch.
        """
        if not column_dtype:
            return 0.5
        is_numeric = any(t in column_dtype.lower() for t in ("int", "float", "number", "numeric"))
        is_categorical_dtype = any(t in column_dtype.lower() for t in ("object", "string", "category", "bool"))

        # Explicit hint in domain metadata
        meta = domain_metadata or {}
        expected = meta.get("expected_dtype")
        if expected:
            if expected.startswith("num") and is_numeric:
                return 1.0
            if expected.startswith(("cat", "str", "obj")) and is_categorical_dtype:
                return 1.0
            return 0.2

        # Heuristic via domain name tokens
        dom_tokens = set(_tokens(domain_name))
        if dom_tokens & DOMAIN_NUMERIC_HINTS:
            return 1.0 if is_numeric else (0.6 if is_categorical_dtype else 0.4)
        if dom_tokens & DOMAIN_CATEGORICAL_HINTS:
            return 1.0 if is_categorical_dtype else (0.6 if is_numeric else 0.4)
        return 0.6  # No strong opinion; neutral

    @staticmethod
    def distribution_fingerprint_match(
        profile: DistributionProfile | None,
        domain_metadata: dict[str, Any] | None,
    ) -> float:
        """0..1 — how well the column's distribution matches the domain's expectations.

        domain_metadata may declare:
          * expected_range: [min, max]
          * expected_skew_sign: '+' | '-' | '~0'
          * expected_unimodal: True
          * expected_kind: 'percentage' | 'count' | 'monetary' | 'ratio' | 'category'
        """
        if profile is None or not profile.is_numeric:
            return 0.5
        meta = domain_metadata or {}
        if not meta:
            return 0.55

        score = 0.5
        signals_used = 0

        rng = meta.get("expected_range")
        if isinstance(rng, (list, tuple)) and len(rng) == 2 and profile.min is not None:
            lo, hi = float(rng[0]), float(rng[1])
            if profile.min >= lo and profile.max <= hi:
                score += 0.25
            elif profile.min >= lo * 0.9 and profile.max <= hi * 1.1:
                score += 0.15
            else:
                score -= 0.15
            signals_used += 1

        sk_sign = meta.get("expected_skew_sign")
        if sk_sign and profile.robust_skew is not None:
            sk = profile.robust_skew
            if sk_sign == "+" and sk > 0:
                score += 0.15
            elif sk_sign == "-" and sk < 0:
                score += 0.15
            elif sk_sign == "~0" and abs(sk) < 0.2:
                score += 0.15
            else:
                score -= 0.1
            signals_used += 1

        if meta.get("expected_unimodal") and profile.is_multimodal:
            score -= 0.2
            signals_used += 1

        kind = meta.get("expected_kind")
        if kind == "percentage" and profile.min is not None:
            if 0 <= profile.min and profile.max <= 100:
                score += 0.2
            else:
                score -= 0.1
            signals_used += 1

        if signals_used == 0:
            return 0.55
        return float(max(0.0, min(1.0, score)))

    # ---------------- aggregator ----------------

    @staticmethod
    def alias_exact_match(column_name: str,
                          domain_name: str,
                          domain_aliases: list[str] | None) -> float:
        """1.0 if the column name (normalised) IS the domain or an alias verbatim."""
        col_norm = "_".join(_tokens(column_name))
        if not col_norm:
            return 0.0
        candidates = {"_".join(_tokens(domain_name))}
        for a in domain_aliases or []:
            candidates.add("_".join(_tokens(a)))
        if col_norm in candidates:
            return 1.0
        # Strong containment (e.g. "employment_rate_male" contains alias "employment_rate")
        for c in candidates:
            if c and (c in col_norm or col_norm in c):
                short, long = sorted([c, col_norm], key=len)
                if len(short) >= 4 and short in long:
                    return 0.85
        return 0.0

    @staticmethod
    def compose_signals(
        *,
        cosine: float,
        column_name: str,
        domain_name: str,
        domain_aliases: list[str] | None = None,
        domain_keywords: list[str] | None = None,
        domain_metadata: dict[str, Any] | None = None,
        column_dtype: str | None = None,
        column_profile: DistributionProfile | None = None,
        cluster_support: float = 0.0,
        graph_consistency: float = 0.0,
        cluster_support_applicable: bool | None = None,
        graph_consistency_applicable: bool | None = None,
    ) -> dict[str, Any]:
        """Return a `CalibratedScore.to_dict()` blending the multi-signal similarity.

        Each signal carries an `applicable` flag — if a signal cannot be
        meaningfully computed for this (column, domain) pair (e.g. structural
        similarity when the tokens share nothing) it is dropped from the score
        rather than contributing a misleading zero.
        """
        col_tokens = _tokens(column_name)
        dom_tokens = _tokens(domain_name)

        # ---------------- compute signals + applicability ----------------
        alias_hit = SimilarityEngine.alias_exact_match(column_name, domain_name, domain_aliases)
        jaccard = SimilarityEngine.jaccard_token_similarity(
            column_name, domain_name, domain_aliases
        )
        structural = SimilarityEngine.structural_similarity(column_name, domain_name)
        keyword = SimilarityEngine.compute_keyword_boost(col_tokens, domain_keywords or [])
        dtype = SimilarityEngine.dtype_alignment(column_dtype, domain_name, domain_metadata)
        distribution = SimilarityEngine.distribution_fingerprint_match(
            column_profile, domain_metadata
        )

        # Applicability rules
        applicability = {
            "cosine": True,                                          # always applicable
            "alias_exact": alias_hit > 0.0,                          # only when there's a hit
            "jaccard": bool(set(col_tokens) & (set(dom_tokens) | _alias_token_set(domain_aliases))),
            "keyword_overlap": bool(domain_keywords),
            "structural": (len(col_tokens) > 0 and len(dom_tokens) > 0
                           and (col_tokens[0] == dom_tokens[0]
                                or col_tokens[-1] == dom_tokens[-1]
                                or _joined(col_tokens) in _joined(dom_tokens)
                                or _joined(dom_tokens) in _joined(col_tokens))),
            "dtype_alignment": column_dtype is not None or bool(domain_metadata),
            "distribution_fit": column_profile is not None and column_profile.is_numeric,
            "cluster_support": (cluster_support_applicable
                                if cluster_support_applicable is not None
                                else cluster_support > 0.0),
            "graph_consistency": (graph_consistency_applicable
                                  if graph_consistency_applicable is not None
                                  else graph_consistency > 0.0),
        }

        signals = {
            "cosine": float(cosine),
            "alias_exact": float(alias_hit),
            "jaccard": float(jaccard),
            "keyword_overlap": float(keyword),
            "structural": float(structural),
            "dtype_alignment": float(dtype),
            "distribution_fit": float(distribution),
            "cluster_support": float(cluster_support),
            "graph_consistency": float(graph_consistency),
        }

        score = default_calibrator.combine(
            "semantic_mapping", signals, applicability=applicability,
        )
        out = score.to_dict()
        out["applicability"] = applicability
        return out


def _alias_token_set(aliases: list[str] | None) -> set[str]:
    if not aliases:
        return set()
    out: set[str] = set()
    for a in aliases:
        out.update(_tokens(a))
    return out


def _joined(toks: list[str]) -> str:
    return "_".join(toks)
