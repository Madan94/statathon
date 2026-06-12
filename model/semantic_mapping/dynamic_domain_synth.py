"""Dynamic domain synthesis.

When the static MoSPI ontology doesn't cover a column well (low confidence
across all static domains), we *synthesise* a candidate domain from data:

  1. Take the column's name + the names of its k-nearest semantically-similar
     columns (within the same dataset).
  2. Extract a canonical name from the dominant token in that cluster.
  3. Optionally consult Gemini to refine the canonical name + a short
     description and a few aliases.
  4. Score the new domain with the same multi-signal pipeline used for
     static domains, so static and dynamic candidates compete on equal footing.

This module is intentionally cheap to run — it activates only when static
confidence < `DYNAMIC_DOMAIN_TRIGGER_CONFIDENCE` for a column.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


DYNAMIC_DOMAIN_TRIGGER_CONFIDENCE = float(
    os.getenv("STATATHON_DYNAMIC_DOMAIN_TRIGGER", "0.55")
)

_STOPWORDS = {
    "the", "of", "in", "for", "and", "or", "by", "to", "a", "an", "is", "are",
    "with", "on", "at", "from", "as", "this", "that", "value", "amount", "no",
    "code", "id", "key", "type",
}


@dataclass
class DynamicDomain:
    name: str                   # canonical name (snake_case)
    display_name: str           # human-readable
    aliases: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    member_columns: list[str] = field(default_factory=list)
    description: str = ""
    expected_dtype: str | None = None
    expected_range: list[float] | None = None
    source: str = "dynamic"     # 'dynamic' | 'dynamic_llm'
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "aliases": self.aliases,
            "keywords": self.keywords,
            "member_columns": self.member_columns,
            "description": self.description,
            "expected_dtype": self.expected_dtype,
            "expected_range": self.expected_range,
            "source": self.source,
            "confidence": float(self.confidence),
        }


def synthesise_dynamic_domains(
    *,
    columns: list[str],
    column_profiles: dict[str, Any] | None,
    similarity_matrix: dict[str, dict[str, float]] | None,
    static_best_per_column: dict[str, tuple[str, float]] | None,
    max_domains: int = 8,
) -> list[DynamicDomain]:
    """Generate at most `max_domains` candidate dynamic domains.

    Args:
      columns: column names in the dataset.
      column_profiles: optional `dict[col, DistributionProfile|dict]` for dtype/range hints.
      similarity_matrix: optional `dict[col, dict[other_col, sim]]` from SimilarityEngine.
      static_best_per_column: `dict[col, (best_static_domain, best_static_confidence)]`
        — only columns whose best static confidence is BELOW the trigger threshold
        are candidates for dynamic clustering.
      max_domains: cap on synthesised domains.
    """
    weak_cols = _weak_columns(columns, static_best_per_column)
    if not weak_cols:
        return []

    clusters = _greedy_token_clusters(
        weak_cols, similarity_matrix, column_profiles=column_profiles,
    )
    domains: list[DynamicDomain] = []
    for members in clusters:
        if not members:
            continue
        canonical = _canonical_name_from_members(members)
        display = canonical.replace("_", " ").title()
        keywords = sorted({tok for m in members for tok in _tokens(m)})
        keywords = [t for t in keywords if t not in _STOPWORDS][:12]
        dom = DynamicDomain(
            name=canonical,
            display_name=display,
            aliases=members[:5],
            keywords=keywords,
            member_columns=members,
            description=f"Auto-generated cluster of {len(members)} related columns",
            expected_dtype=_guess_dtype_from_profiles(members, column_profiles),
            expected_range=_guess_range_from_profiles(members, column_profiles),
            confidence=0.5,
        )
        # Optional LLM enrichment (no-op if no key available)
        _maybe_refine_with_llm(dom)
        domains.append(dom)
        if len(domains) >= max_domains:
            break
    return domains


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(name: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(str(name).lower()) if t]


def _weak_columns(columns: list[str],
                  static_best_per_column: dict[str, tuple[str, float]] | None
                  ) -> list[str]:
    if not static_best_per_column:
        return list(columns)
    weak = []
    for c in columns:
        best = static_best_per_column.get(c)
        if best is None:
            weak.append(c)
            continue
        if best[1] < DYNAMIC_DOMAIN_TRIGGER_CONFIDENCE:
            weak.append(c)
    return weak


def _greedy_token_clusters(
    columns: list[str],
    similarity_matrix: dict[str, dict[str, float]] | None,
    column_profiles: dict[str, Any] | None = None,
    min_cluster_size: int = 2,
    sim_threshold: float = 0.40,
    dist_threshold: float = 0.75,
) -> list[list[str]]:
    """Group columns by token overlap, embedding similarity, or distribution fingerprint.

    Score per (a, b) = max(jaccard(name_a, name_b),
                           cosine(embedding_a, embedding_b),
                           distribution_similarity(profile_a, profile_b))

    Columns join a cluster when at least one similarity metric clears its
    threshold. This catches groups like {employment_rate, literacy_rate,
    enrollment_rate} that share "rate" tokens, AND groups like
    {height_cm, weight_kg, bmi} that share distributional shape (numeric,
    normal-ish, positive).
    """
    if not columns:
        return []
    visited: set[str] = set()
    clusters: list[list[str]] = []
    for col in columns:
        if col in visited:
            continue
        members = [col]
        tok = set(_tokens(col))
        for other in columns:
            if other == col or other in visited:
                continue
            other_tok = set(_tokens(other))
            union = tok | other_tok
            jacc = len(tok & other_tok) / len(union) if union else 0.0
            sim = 0.0
            if similarity_matrix:
                sim = float(similarity_matrix.get(col, {}).get(other, 0.0))
            dist = _distribution_similarity(
                (column_profiles or {}).get(col),
                (column_profiles or {}).get(other),
            )
            score = max(jacc, sim)
            joined = score >= sim_threshold or dist >= dist_threshold
            if joined:
                members.append(other)
        if len(members) >= min_cluster_size:
            visited.update(members)
            clusters.append(members)
    return clusters


def _distribution_similarity(p_a: Any, p_b: Any) -> float:
    """0..1 — how similar two columns' distribution fingerprints are."""
    if p_a is None or p_b is None:
        return 0.0
    # Accept both dict and DistributionProfile
    def _g(p, key):
        if isinstance(p, dict):
            return p.get(key)
        return getattr(p, key, None)

    a_mean, b_mean = _g(p_a, "mean"), _g(p_b, "mean")
    if a_mean is None or b_mean is None:
        # Categorical or non-numeric — fallback on dtype match
        a_dtype = str(_g(p_a, "dtype") or "")
        b_dtype = str(_g(p_b, "dtype") or "")
        return 0.6 if a_dtype == b_dtype else 0.0

    score = 0.0
    components = 0
    # Same dtype
    score += 0.25; components += 1

    # Range overlap
    a_min, a_max = _g(p_a, "min"), _g(p_a, "max")
    b_min, b_max = _g(p_b, "min"), _g(p_b, "max")
    if all(v is not None for v in (a_min, a_max, b_min, b_max)):
        lo, hi = max(a_min, b_min), min(a_max, b_max)
        union_lo, union_hi = min(a_min, b_min), max(a_max, b_max)
        overlap = max(0.0, hi - lo)
        union_span = max(1e-9, union_hi - union_lo)
        score += 0.30 * (overlap / union_span)
        components += 1

    # Skew similarity
    a_sk, b_sk = _g(p_a, "robust_skew") or _g(p_a, "skew"), _g(p_b, "robust_skew") or _g(p_b, "skew")
    if a_sk is not None and b_sk is not None:
        diff = abs(float(a_sk) - float(b_sk))
        score += 0.25 * max(0.0, 1.0 - diff / 2.0)
        components += 1

    # Normality alignment
    a_norm = _g(p_a, "is_normal_5pct")
    b_norm = _g(p_b, "is_normal_5pct")
    if a_norm is not None and b_norm is not None:
        score += 0.20 if a_norm == b_norm else 0.0
        components += 1

    if components == 0:
        return 0.0
    return min(1.0, score)


def _canonical_name_from_members(members: list[str]) -> str:
    """Pick the most frequent non-stopword token across cluster member names."""
    counter: dict[str, int] = {}
    for m in members:
        for tok in _tokens(m):
            if tok in _STOPWORDS:
                continue
            counter[tok] = counter.get(tok, 0) + 1
    if not counter:
        return "_".join(_tokens(members[0]))[:60]
    best = max(counter.items(), key=lambda kv: kv[1])
    return best[0]


def _guess_dtype_from_profiles(members: list[str],
                                column_profiles: dict[str, Any] | None) -> str | None:
    if not column_profiles:
        return None
    is_numeric = 0
    total = 0
    for m in members:
        p = column_profiles.get(m)
        if p is None:
            continue
        # Accept either a dict (json-loaded) or a DistributionProfile-like obj
        if isinstance(p, dict):
            mean_v = p.get("mean")
        else:
            mean_v = getattr(p, "mean", None)
        total += 1
        if mean_v is not None:
            is_numeric += 1
    if total == 0:
        return None
    return "numeric" if is_numeric >= total / 2 else "categorical"


def _guess_range_from_profiles(members: list[str],
                                column_profiles: dict[str, Any] | None
                                ) -> list[float] | None:
    if not column_profiles:
        return None
    mins, maxs = [], []
    for m in members:
        p = column_profiles.get(m)
        if p is None:
            continue
        mn = p.get("min") if isinstance(p, dict) else getattr(p, "min", None)
        mx = p.get("max") if isinstance(p, dict) else getattr(p, "max", None)
        if mn is not None:
            mins.append(float(mn))
        if mx is not None:
            maxs.append(float(mx))
    if not mins or not maxs:
        return None
    return [min(mins), max(maxs)]


def _maybe_refine_with_llm(dom: DynamicDomain) -> None:
    """Use Gemini to refine name/description/aliases. Silently no-ops when offline."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return
    try:
        from core.gemini_client import get_generative_model
        import json as _json

        model = get_generative_model()
        if model is None:
            return
        prompt = (
            "You are naming a cluster of statistical columns. Given the members "
            f"below, produce a JSON object with keys: name (snake_case), "
            f"display_name (Title Case), description (one sentence), "
            f"aliases (list of 3-5 strings), keywords (list of 5-10).\n\n"
            f"Members: {dom.member_columns}\n"
            "Return ONLY the JSON object."
        )
        resp = model.generate_content(prompt)
        text = (resp.text or "").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        data = _json.loads(text)
        if isinstance(data, dict):
            if data.get("name"):
                dom.name = re.sub(r"[^a-z0-9_]+", "_", str(data["name"]).lower()).strip("_")
            if data.get("display_name"):
                dom.display_name = str(data["display_name"])
            if data.get("description"):
                dom.description = str(data["description"])
            if isinstance(data.get("aliases"), list):
                dom.aliases = [str(a) for a in data["aliases"][:5]]
            if isinstance(data.get("keywords"), list):
                dom.keywords = [str(k).lower() for k in data["keywords"][:12]]
            dom.source = "dynamic_llm"
    except Exception as exc:
        logger.debug("Dynamic domain LLM refinement skipped: %s", exc)
