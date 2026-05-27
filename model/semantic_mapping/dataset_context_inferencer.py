"""
Dataset-wide semantic context for official statistics tables.
Deterministic embedding similarity against canonical survey archetypes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from semantic_mapping.similarity_engine import SimilarityEngine


@dataclass(frozen=True)
class DatasetContextResult:
    dataset_type: str
    domain_scores: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {"dataset_type": self.dataset_type, "domain_scores": dict(self.domain_scores)}


class DatasetContextInferencer:
    """
    Maps concatenated column semantics to high-level dataset archetypes
    (census, health survey, labor, education, agriculture, economic, ...).
    """

    CONTEXT_PROTOTYPES: dict[str, str] = {
        "census": "official census enumeration household roster demographic population count geography administrative unit sampling weight",
        "health_survey": "health insurance hospital disease treatment vaccination disability mortality maternal child nutrition screening outpatient inpatient chronic condition diagnostic",
        "labor": "labor force employment occupation wages salary industry sector workforce informal formal casual employer employee hours worked",
        "education_statistics": "education enrollment literacy qualification school attendance graduation dropout teacher pupil student classroom curriculum assessment",
        "agriculture": "agriculture crop livestock irrigation yield land holding cultivation MSP mandi cooperative hectare acre rainfall tenancy horticulture fishery",
        "economic_survey": "GDP national accounts enterprise establishment informal sector investment consumption CPI inflation credit banking fiscal revenue expenditure trade forex productivity ASI",
        "infrastructure": "infrastructure electricity water sanitation road transport connectivity internet mobile facility access distance nearest amenity",
        "socioeconomic": "socioeconomic household consumption expenditure asset demographic income employment education multipurpose integrated survey",
        "survey_metadata": "survey wave round questionnaire version interviewer batch timestamp replicate weight calibration sampling psu stratum",
    }

    def __init__(self, embedder):
        self.embedder = embedder
        self._prototype_embeddings: dict[str, np.ndarray] | None = None

    def _ensure_prototypes(self) -> dict[str, np.ndarray]:
        if self._prototype_embeddings is None:
            texts = list(self.CONTEXT_PROTOTYPES.values())
            keys = list(self.CONTEXT_PROTOTYPES.keys())
            batch = self.embedder.embed_batch(texts)
            self._prototype_embeddings = {k: batch[t] for k, t in zip(keys, texts)}
        return self._prototype_embeddings

    def infer_domain_scores(self, column_texts: list[str]) -> dict[str, float]:
        combined = " ".join(column_texts) if column_texts else "unknown statistical column"
        dataset_emb = self.embedder.embed_text(combined)
        protos = self._ensure_prototypes()
        scores: dict[str, float] = {}
        for ctx, emb in protos.items():
            scores[ctx] = SimilarityEngine.compute_similarity(dataset_emb, emb)
        return scores

    def infer(self, column_texts: list[str]) -> DatasetContextResult:
        scores = self.infer_domain_scores(column_texts)
        best = max(scores, key=scores.get)
        return DatasetContextResult(dataset_type=best, domain_scores=scores)
