import hashlib
import numpy as np
import os


class VectorStore:

    def __init__(self, cache_dir="storage/vector_cache"):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self._mem_cache = {}

    # ---- key generation ----

    @staticmethod
    def generate_key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]

    def _path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.npy")

    # ---- single vector ops ----

    def has(self, key: str) -> bool:
        if key in self._mem_cache:
            return True
        return os.path.exists(self._path(key))

    def get(self, key: str):
        if key in self._mem_cache:
            return self._mem_cache[key]
        path = self._path(key)
        if os.path.exists(path):
            vec = np.load(path)
            self._mem_cache[key] = vec
            return vec
        return None

    def store(self, key: str, vector: np.ndarray):
        self._mem_cache[key] = vector
        np.save(self._path(key), vector)

    # ---- convenience helpers for text-based lookup ----

    def get_embedding(self, text: str):
        return self.get(self.generate_key(text))

    def store_embedding(self, text: str, vector: np.ndarray):
        self.store(self.generate_key(text), vector)

    def has_embedding(self, text: str) -> bool:
        return self.has(self.generate_key(text))

    # ---- batch ops ----

    def store_batch(self, embeddings: dict):
        for text, vec in embeddings.items():
            self.store_embedding(text, vec)

    def get_all_mem(self) -> dict:
        return dict(self._mem_cache)

    def clear(self):
        self._mem_cache.clear()
        for f in os.listdir(self.cache_dir):
            if f.endswith(".npy"):
                os.remove(os.path.join(self.cache_dir, f))
