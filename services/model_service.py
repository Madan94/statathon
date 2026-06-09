import os
from functools import lru_cache

SENTENCE_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

@lru_cache(maxsize=1)
def get_embedder():
    from sentence_transformers import SentenceTransformer
    cache = os.getenv("HUGGINGFACE_HUB_CACHE", "./model/cache")
    return SentenceTransformer(SENTENCE_MODEL, cache_folder=cache)

def embed_texts(texts: list[str]) -> list[list[float]]:
    m = get_embedder()
    return m.encode(texts, convert_to_numpy=True).tolist()

def similarity(a: str, b: str) -> float:
    from numpy import dot
    from numpy.linalg import norm
    e = get_embedder()
    va, vb = e.encode([a, b])
    return float(dot(va, vb) / (norm(va) * norm(vb) + 1e-9))