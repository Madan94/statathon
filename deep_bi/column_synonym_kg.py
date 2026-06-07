"""Column Synonym Knowledge Graph.

Maps a concept (e.g. 'labour_force') to the columns of an arbitrary dataset
that mean the same thing semantically, even when their names look different
(LFPR_Female, ParticipationRateWomen, Women_Workforce all -> labour_force).

Pure-Python, no embeddings required (works offline). When the BERT embedder
is available it ALSO scores candidates by cosine similarity for a stronger
match. The pure-Python path uses token overlap + alias matching against an
extensible synonym dictionary.

Resolution returns ranked ColumnMatch objects so the caller can pick the top-k
matches without losing the alternatives.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger(__name__)


# Domain-agnostic synonym dictionary keyed by concept slug.
# Each entry is a list of phrases / tokens that mean the same concept.
DEFAULT_SYNONYMS: dict[str, list[str]] = {
    "labour_force":  ["lfpr", "labour force", "labor force", "labour_force",
                      "labor_force", "participation", "workforce", "work participation",
                      "employed", "employment_rate", "employment rate",
                      "wpr", "worker_population"],
    "unemployment":  ["unemployment", "ur", "joblessness"],
    "income":        ["income", "salary", "wage", "earning", "pay",
                      "compensation", "monthly_income", "annual_income"],
    "expenditure":   ["expenditure", "expense", "spending", "consumption",
                      "outlay"],
    "education":     ["education", "schooling", "qualification", "degree",
                      "literacy"],
    "literacy":      ["literacy", "literate", "literacy_rate"],
    "health":        ["health", "imr", "infant_mortality", "fertility",
                      "mortality", "morbidity", "bmi"],
    "demographic":   ["age", "gender", "sex", "household", "marital",
                      "population", "members"],
    "geography":     ["state", "district", "region", "country", "pincode",
                      "postal", "block", "ward"],
    "agriculture":   ["yield", "crop", "wheat", "rice", "paddy", "maize",
                      "harvest", "harvested", "sown", "rainfall", "soil",
                      "fertilizer", "irrigation"],
    "industrial":    ["iip", "factory", "factories", "production", "output",
                      "capacity", "utilization", "kwh", "energy"],
    "energy":        ["reserves", "proved", "indicated", "inferred",
                      "potential", "mw", "tonnes", "billion tonnes",
                      "capacity_mw", "coal", "petroleum", "natural_gas",
                      "renewable", "wind", "solar", "biomass"],
    "time":          ["year", "month", "quarter", "fiscal_year", "fy",
                      "reporting", "date"],
    "growth":        ["growth", "delta", "change", "yoy", "yoy_change"],
    "ratio":         ["ratio", "rate", "pct", "percentage", "share"],
    "ranking":       ["rank", "top", "bottom"],
    "vulnerability": ["vulnerable", "exposure", "risk"],
    "economic_shock":["shock", "downturn", "recession", "crisis", "stress"],
}


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------


_SPLIT = re.compile(r"[^a-z0-9]+")


def _tokens(s: str) -> list[str]:
    return [t for t in _SPLIT.split(str(s).lower()) if t]


# ---------------------------------------------------------------------------
# Match dataclass
# ---------------------------------------------------------------------------


@dataclass
class ColumnMatch:
    column: str
    score: float
    signals: dict[str, float] = field(default_factory=dict)
    matched_phrases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"column": self.column, "score": round(self.score, 4),
                "signals": self.signals, "matched_phrases": self.matched_phrases}


# ---------------------------------------------------------------------------
# KG
# ---------------------------------------------------------------------------


class ColumnSynonymKG:
    """Concept ↔ columns resolver.

    Construction:
        ColumnSynonymKG(columns=df.columns,
                         column_domains={col: 'labour_force', ...})  # optional
    """

    def __init__(
        self,
        columns: Iterable[str],
        *,
        column_domains: dict[str, str] | None = None,
        synonyms: dict[str, list[str]] | None = None,
        bert_embedder=None,
    ):
        self.columns = list(columns)
        self.column_domains = column_domains or {}
        self.synonyms = dict(DEFAULT_SYNONYMS)
        if synonyms:
            for k, v in synonyms.items():
                self.synonyms.setdefault(k, []).extend(v)
        # Lower-case index of column tokens for fast lookup
        self._col_tokens = {c: set(_tokens(c)) for c in self.columns}
        self._embedder = bert_embedder

    # ---------------- Public ----------------

    def resolve(self, concept: str, *, top_k: int = 5,
                 min_score: float = 0.20) -> list[ColumnMatch]:
        """Return ranked columns that match this concept."""
        concept_key = concept.lower().replace(" ", "_")
        phrases = self.synonyms.get(concept_key, [concept])
        # Add the concept itself as a phrase
        phrases = list({*phrases, concept_key, concept.lower()})

        matches: list[ColumnMatch] = []
        for col in self.columns:
            score, signals, matched = self._score_column(col, phrases,
                                                            concept_key)
            if score >= min_score:
                matches.append(ColumnMatch(column=col, score=score,
                                             signals=signals,
                                             matched_phrases=matched))
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:top_k]

    def resolve_all(self, concepts: list[str], *, top_k_per_concept: int = 5
                     ) -> dict[str, list[ColumnMatch]]:
        return {c: self.resolve(c, top_k=top_k_per_concept) for c in concepts}

    def best_columns_for(self, concepts: list[str], *, min_score: float = 0.30
                          ) -> list[str]:
        """Convenience: top column per concept (deduped, ordered by best score)."""
        ranked: list[tuple[float, str]] = []
        seen: set[str] = set()
        for c in concepts:
            hits = self.resolve(c, top_k=3, min_score=min_score)
            for m in hits:
                if m.column not in seen:
                    seen.add(m.column)
                    ranked.append((m.score, m.column))
        ranked.sort(key=lambda kv: kv[0], reverse=True)
        return [c for _, c in ranked]

    # ---------------- Scoring ----------------

    def _score_column(self, column: str, phrases: list[str],
                       concept_key: str) -> tuple[float, dict[str, float], list[str]]:
        col_tok = self._col_tokens.get(column, set())
        col_norm = "_".join(sorted(col_tok))

        matched_phrases: list[str] = []
        signals: dict[str, float] = {
            "alias_exact": 0.0,
            "alias_contains": 0.0,
            "token_overlap": 0.0,
            "domain_match": 0.0,
            "embedding": 0.0,
        }

        # Alias-exact / contains
        for ph in phrases:
            ph_tok = set(_tokens(ph))
            ph_norm = "_".join(sorted(ph_tok))
            if not ph_tok:
                continue
            if ph_norm == col_norm:
                signals["alias_exact"] = max(signals["alias_exact"], 1.0)
                matched_phrases.append(ph)
                continue
            # Strong containment
            if ph_norm and (ph_norm in column.lower().replace(" ", "_")
                             or column.lower().replace(" ", "_") in ph_norm):
                if len(ph_norm) >= 3:
                    signals["alias_contains"] = max(signals["alias_contains"], 0.80)
                    matched_phrases.append(ph)
                    continue
            # Token overlap
            inter = col_tok & ph_tok
            if inter:
                jaccard = len(inter) / max(1, len(col_tok | ph_tok))
                signals["token_overlap"] = max(signals["token_overlap"], jaccard)
                if jaccard >= 0.40:
                    matched_phrases.append(ph)

        # Domain alignment
        dom = self.column_domains.get(column, "").lower()
        if dom and (dom == concept_key or concept_key in dom or dom in concept_key):
            signals["domain_match"] = 1.0

        # Embedding similarity (optional)
        if self._embedder is not None and phrases:
            try:
                col_v = self._embedder.embed_text(column.replace("_", " "))
                ph_v = self._embedder.embed_text(phrases[0])
                from numpy import dot
                from numpy.linalg import norm
                denom = norm(col_v) * norm(ph_v)
                if denom > 0:
                    signals["embedding"] = float(dot(col_v, ph_v) / denom)
            except Exception:
                pass

        # Weighted blend with consensus boost
        weights = {
            "alias_exact":    0.42,
            "alias_contains": 0.20,
            "token_overlap":  0.18,
            "domain_match":   0.15,
            "embedding":      0.05,
        }
        score = sum(weights[k] * signals[k] for k in weights)
        # Consensus: at least two signals > 0.5 -> +0.05
        if sum(1 for v in signals.values() if v > 0.5) >= 2:
            score = min(1.0, score + 0.05)
        return score, signals, matched_phrases
