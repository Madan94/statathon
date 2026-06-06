import numpy as np


class BertEmbedder:

    def __init__(self, model=None, model_name="BAAI/bge-m3", vector_store=None):
        self._model = model
        self._model_name = model_name
        self._cache = {}            # fast in-memory cache (lives for one process)
        self._store = vector_store   # persistent on-disk cache (survives across runs)

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def set_vector_store(self, vector_store):
        self._store = vector_store

    # ---- single text ----

    def embed_text(self, text: str) -> np.ndarray:
        # 1. in-memory
        if text in self._cache:
            return self._cache[text]
        # 2. persistent store
        if self._store and self._store.has_embedding(text):
            vec = self._store.get_embedding(text)
            self._cache[text] = vec
            return vec
        # 3. compute (triggers model load if needed)
        vec = self._get_model().encode(text, convert_to_numpy=True, normalize_embeddings=True)
        self._cache[text] = vec
        if self._store:
            self._store.store_embedding(text, vec)
        return vec

    # ---- batch (list of texts) ----

    def embed_batch(self, texts: list) -> dict:
        result = {}
        to_compute = []
        for t in texts:
            if t in self._cache:
                result[t] = self._cache[t]
            elif self._store and self._store.has_embedding(t):
                vec = self._store.get_embedding(t)
                self._cache[t] = vec
                result[t] = vec
            else:
                to_compute.append(t)

        if to_compute:
            vectors = self._get_model().encode(to_compute, convert_to_numpy=True, batch_size=16, normalize_embeddings=True)
            for text, vec in zip(to_compute, vectors):
                self._cache[text] = vec
                if self._store:
                    self._store.store_embedding(text, vec)
                result[text] = vec

        return {t: result[t] for t in texts}

    # ---- dict  {key: text} → {key: embedding} ----

    def embed_dict(self, mapping: dict) -> dict:
        texts = list(set(mapping.values()))
        text_vecs = self.embed_batch(texts)
        return {k: text_vecs[mapping[k]] for k in mapping}

    def clear_cache(self):
        self._cache.clear()