import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


class SimilarityEngine:

    @staticmethod
    def compute_similarity(vec1, vec2):
        vec1 = np.asarray(vec1).reshape(1, -1)
        vec2 = np.asarray(vec2).reshape(1, -1)
        sim = cosine_similarity(vec1, vec2)[0][0]
        return float(sim)

    @staticmethod
    def compute_domain_similarity(column_embedding, domain_embeddings):
        scores = {}
        for domain, emb in domain_embeddings.items():
            scores[domain] = SimilarityEngine.compute_similarity(column_embedding, emb)
        return scores

    @staticmethod
    def compute_similarity_matrix(embeddings: dict) -> dict:
        columns = list(embeddings.keys())
        vecs = np.array([embeddings[c] for c in columns])
        sim_matrix = cosine_similarity(vecs)
        result = {}
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