"""
STEP 1 — Usecase Detection.

Immediately after upload, infer which statistical *usecase* a dataset belongs
to (labour, consumption, energy, ...). Detection fuses two signals:

  * Lexical: overlap between column/metadata tokens and each usecase's curated
    keyword set (fast, deterministic).
  * Semantic: cosine similarity between the dataset's column representations and
    each usecase's description embedding (robust to vocabulary drift).

A user-selected usecase, when provided, is honoured with a confidence boost but
still validated against the data so an obviously wrong choice is flagged.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from semantic_mapping_v2.config import USECASES
from semantic_mapping_v2.domain_loader import DomainRegistryLoader
from semantic_mapping_v2.embedder import SemanticEmbedder

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class UsecaseResult:
    usecase: str
    confidence: float
    scores: dict[str, float]
    source: str  # 'semantic' | 'lexical' | 'user' | 'fallback'

    def to_dict(self) -> dict[str, Any]:
        return {
            "usecase": self.usecase,
            "confidence": round(self.confidence, 4),
            "scores": {k: round(v, 4) for k, v in self.scores.items()},
            "source": self.source,
        }


def _tokens(*texts: str) -> set[str]:
    out: set[str] = set()
    for t in texts:
        if not t:
            continue
        out.update(_TOKEN_RE.findall(str(t).lower()))
    return out


class UsecaseDetector:
    def __init__(
        self,
        embedder: SemanticEmbedder | None = None,
        loader: DomainRegistryLoader | None = None,
    ):
        self.embedder = embedder or SemanticEmbedder()
        self.loader = loader or DomainRegistryLoader()

    def detect(
        self,
        *,
        column_names: list[str],
        dataset_name: str = "",
        file_name: str = "",
        sheet_names: list[str] | None = None,
        sample_values: dict[str, list[Any]] | None = None,
        user_usecase: str | None = None,
    ) -> UsecaseResult:
        sheet_names = sheet_names or []
        sample_values = sample_values or {}

        lexical = self._lexical_scores(
            column_names, dataset_name, file_name, sheet_names, sample_values
        )
        semantic = self._semantic_scores(column_names, dataset_name)

        # Blend: semantic is primary, lexical disambiguates close calls.
        scores: dict[str, float] = {}
        for uc in USECASES:
            scores[uc] = round(0.6 * semantic.get(uc, 0.0) + 0.4 * lexical.get(uc, 0.0), 4)

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_uc, best_score = ranked[0]
        source = "semantic" if semantic.get(best_uc, 0) >= lexical.get(best_uc, 0) else "lexical"

        # Honour a valid user selection, but keep evidence visible.
        if user_usecase:
            uc_norm = user_usecase.strip().lower()
            if uc_norm in scores:
                data_conf = scores[uc_norm]
                # Boost, but if data strongly disagrees keep it honest.
                boosted = max(data_conf, 0.85) if data_conf >= 0.2 else data_conf + 0.5
                scores[uc_norm] = round(min(boosted, 0.99), 4)
                return UsecaseResult(uc_norm, scores[uc_norm], scores, "user")

        # Margin-aware confidence.
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = best_score - runner_up
        confidence = round(min(0.99, best_score + 0.5 * margin), 4)
        if best_score <= 0.01:
            return UsecaseResult(USECASES[0], 0.0, scores, "fallback")
        return UsecaseResult(best_uc, confidence, scores, source)

    # -- signals -------------------------------------------------------------
    def _lexical_scores(
        self,
        column_names: list[str],
        dataset_name: str,
        file_name: str,
        sheet_names: list[str],
        sample_values: dict[str, list[Any]],
    ) -> dict[str, float]:
        sample_tokens: set[str] = set()
        for vals in sample_values.values():
            sample_tokens |= _tokens(*[str(v) for v in vals[:5]])
        ds_tokens = _tokens(
            " ".join(column_names),
            dataset_name,
            file_name,
            " ".join(sheet_names),
        ) | sample_tokens
        if not ds_tokens:
            return {uc: 0.0 for uc in USECASES}

        scores: dict[str, float] = {}
        for uc in USECASES:
            kw = self.loader.keyword_tokens(uc)
            if not kw:
                scores[uc] = 0.0
                continue
            overlap = len(ds_tokens & kw)
            scores[uc] = overlap / (len(kw) ** 0.5)  # length-normalised
        # Normalise to [0, 1].
        mx = max(scores.values()) or 1.0
        return {uc: v / mx for uc, v in scores.items()}

    def _semantic_scores(self, column_names: list[str], dataset_name: str) -> dict[str, float]:
        try:
            col_text = ", ".join(column_names[:60])
            query = f"{dataset_name}. columns: {col_text}" if dataset_name else col_text
            qvec = self.embedder.embed_query(query)
            uc_vecs = self._usecase_vectors()
            scores: dict[str, float] = {}
            for uc, vec in uc_vecs.items():
                scores[uc] = float(np.dot(qvec, vec))
            # Min-max to [0, 1].
            vals = list(scores.values())
            lo, hi = min(vals), max(vals)
            span = (hi - lo) or 1.0
            return {uc: (v - lo) / span for uc, v in scores.items()}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Usecase semantic scoring failed: %s", exc)
            return {uc: 0.0 for uc in USECASES}

    def _usecase_vectors(self) -> dict[str, np.ndarray]:
        texts, keys = [], []
        for uc in USECASES:
            keys.append(uc)
            texts.append(self.loader.usecase_description(uc))
        vecs = self.embedder.embed_documents_batch(texts)
        return dict(zip(keys, vecs))
