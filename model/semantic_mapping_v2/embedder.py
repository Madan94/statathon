"""BGE-M3 embedder with asymmetric query/document prefixes for V2."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from semantic_mapping_v2.config import (
    BGE_DOCUMENT_PREFIX,
    BGE_QUERY_PREFIX,
    EMBED_BATCH_SIZE,
    EMBEDDING_MODEL,
    clear_stale_hf_locks,
    hf_model_cache_status,
)

logger = logging.getLogger(__name__)

# One SentenceTransformer per model name — avoids reloading ~2GB weights per instance.
_SHARED_MODELS: dict[str, Any] = {}


class BgeM3Embedder:
    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or EMBEDDING_MODEL
        self._cache: dict[str, np.ndarray] = {}

    def _get_model(self):
        if self._model_name not in _SHARED_MODELS:
            from sentence_transformers import SentenceTransformer

            stale_locks = clear_stale_hf_locks()
            cache_info = hf_model_cache_status(self._model_name)
            if stale_locks:
                print(
                    f"      [embedder] Cleared {stale_locks} stale HF lock file(s) "
                    f"from interrupted download.",
                    flush=True,
                )
            if cache_info.get("present"):
                print(
                    f"      [embedder] Local cache found ({cache_info['size_mb']} MB) — "
                    f"loading weights into memory...",
                    flush=True,
                )
            else:
                print(
                    f"      [embedder] No local cache — downloading {self._model_name} "
                    f"(~2GB; progress bar should appear below)...",
                    flush=True,
                )

            logger.info("Loading embedding model %s", self._model_name)
            _SHARED_MODELS[self._model_name] = SentenceTransformer(self._model_name)
            print(f"      [embedder] Model {self._model_name} ready.", flush=True)
        return _SHARED_MODELS[self._model_name]

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed(f"{BGE_QUERY_PREFIX}{text}")

    def embed_document(self, text: str) -> np.ndarray:
        return self._embed(f"{BGE_DOCUMENT_PREFIX}{text}")

    def _embed(self, text: str) -> np.ndarray:
        if text in self._cache:
            return self._cache[text]
        vec = self._get_model().encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        self._cache[text] = np.asarray(vec, dtype=np.float32)
        return self._cache[text]

    def embed_documents_batch(self, texts: list[str]) -> list[np.ndarray]:
        prefixed = [f"{BGE_DOCUMENT_PREFIX}{t}" for t in texts]
        to_compute = [t for t in prefixed if t not in self._cache]
        if to_compute:
            vectors = self._get_model().encode(
                to_compute,
                convert_to_numpy=True,
                batch_size=EMBED_BATCH_SIZE,
                normalize_embeddings=True,
            )
            for t, v in zip(to_compute, vectors):
                self._cache[t] = np.asarray(v, dtype=np.float32)
        return [self._cache[f"{BGE_DOCUMENT_PREFIX}{t}"] for t in texts]
