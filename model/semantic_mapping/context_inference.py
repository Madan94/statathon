import numpy as np


class ContextInference:

    DATASET_CONTEXTS = {
        "socioeconomic": "socioeconomic survey income education employment demographic household population",
        "census": "census population count demographic age gender household district state region",
        "health": "health survey medical hospital disease treatment insurance mortality morbidity",
        "education": "education survey school enrollment literacy qualification graduation",
        "infrastructure": "infrastructure access electricity water internet mobile road transport facility",
        "labor": "labor workforce employment occupation wages salary industry sector",
    }

    def __init__(self, embedder):
        self.embedder = embedder
        self._context_embeddings = None

    def _get_context_embeddings(self):
        if self._context_embeddings is None:
            self._context_embeddings = {}
            for ctx, desc in self.DATASET_CONTEXTS.items():
                self._context_embeddings[ctx] = self.embedder.embed_text(desc)
        return self._context_embeddings

    def infer_dataset_context(self, column_texts: list) -> dict:
        combined = " ".join(column_texts)
        dataset_emb = self.embedder.embed_text(combined)

        context_embs = self._get_context_embeddings()
        from semantic_mapping.similarity_engine import SimilarityEngine

        scores = {}
        for ctx, emb in context_embs.items():
            scores[ctx] = SimilarityEngine.compute_similarity(dataset_emb, emb)

        return scores

    def get_context_boost(self, column_tokens: list, dataset_context: str) -> float:
        context_words = self.DATASET_CONTEXTS.get(dataset_context, "").split()
        if not context_words or not column_tokens:
            return 0.0
        matches = sum(1 for t in column_tokens if t in context_words)
        return min(matches / max(len(column_tokens), 1), 1.0)

    def compute_domain_scores_with_context(
        self,
        embedding_scores: dict,
        keyword_boost: dict,
        context_boost: float
    ) -> dict:
        combined = {}
        for domain in embedding_scores:
            emb = embedding_scores[domain]
            kw = keyword_boost.get(domain, 0.0)
            combined[domain] = (
                0.50 * emb
                + 0.20 * kw
                + 0.20 * context_boost
                + 0.10 * max(emb, kw)
            )
        return combined
