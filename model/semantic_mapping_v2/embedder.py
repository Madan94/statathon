"""
Pluggable embedder for Semantic Mapping V2.

Two providers behind one interface:

* ``local``  — SentenceTransformers BGE-M3 (the plan's default, 1024-dim).
               Requires the model to be available in the HF cache.
* ``gemini`` — Google ``gemini-embedding-001`` via the Generative AI API
               (3072-dim). Works on networks where HuggingFace model
               downloads are blocked but the Gemini API is reachable.

Provider selection (``SEMV2_EMBED_PROVIDER`` env, default ``auto``):
    auto   -> use ``local`` if the BGE-M3 snapshot is already cached,
              otherwise fall back to ``gemini`` when a key is configured.
    local  -> force SentenceTransformers.
    gemini -> force Gemini embeddings.

Queries (columns) and documents (domain definitions) use the BGE asymmetric
prefixes so retrieval geometry matches the model's training. ``.dim`` and
``.signature`` are exposed so Qdrant collections can be sized and namespaced
to the active provider.
"""
from __future__ import annotations

import logging
import os
import threading
import time
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

# One heavy model per name across the process.
_SHARED_MODELS: dict[str, Any] = {}
_MODEL_LOCK = threading.Lock()

GEMINI_EMBED_MODEL = os.getenv("SEMV2_GEMINI_EMBED_MODEL", "models/gemini-embedding-001")
GEMINI_EMBED_DIM = int(os.getenv("SEMV2_GEMINI_EMBED_DIM", "3072"))
BGE_DIM = int(os.getenv("SEMANTIC_V2_EMBED_DIM", "1024"))

AZURE_EMBED_DIM = int(os.getenv("SEMV2_AZURE_EMBED_DIM", "3072"))  # text-embedding-3-large default

# Gemini embedding throttling: batch to cut request count, retry on 429/quota.
GEMINI_EMBED_BATCH = int(os.getenv("SEMV2_GEMINI_EMBED_BATCH", "32"))
GEMINI_EMBED_MAX_RETRIES = int(os.getenv("SEMV2_GEMINI_EMBED_RETRIES", "6"))
GEMINI_EMBED_RETRY_BASE_SEC = float(os.getenv("SEMV2_GEMINI_EMBED_RETRY_BASE", "5"))
GEMINI_EMBED_RETRY_MAX_SEC = float(os.getenv("SEMV2_GEMINI_EMBED_RETRY_MAX", "60"))
_RETRIABLE = ("429", "resource exhausted", "quota", "rate limit", "503", "unavailable", "deadline")


def _gemini_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _resolve_provider() -> str:
    """Decide which embedding backend to use."""
    choice = (os.getenv("SEMV2_EMBED_PROVIDER", "auto") or "auto").strip().lower()
    if choice in {"local", "gemini", "azure_openai"}:
        return choice
    # auto: prefer azure_openai if configured (works on corporate network)
    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME"):
        logger.info("Embedder auto: BGE-M3 not cached + Azure configured -> using Azure OpenAI embeddings.")
        return "azure_openai"
    if hf_model_cache_status(EMBEDDING_MODEL).get("present"):
        return "local"
    if _gemini_key():
        logger.info("Embedder auto: BGE-M3 not cached -> using Gemini embeddings.")
        return "gemini"
    return "local"


class SemanticEmbedder:
    """Asymmetric query/document embedder with a pluggable backend."""

    def __init__(self, provider: str | None = None):
        self.provider = (provider or _resolve_provider()).lower()
        self._cache: dict[str, np.ndarray] = {}
        if self.provider == "gemini":
            self.model_name = GEMINI_EMBED_MODEL
            self.dim = GEMINI_EMBED_DIM
            self.signature = f"gem{self.dim}"
        elif self.provider == "azure_openai":
            self.model_name = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-large")
            self.dim = AZURE_EMBED_DIM
            self.signature = f"az{self.dim}"
        else:
            self.model_name = EMBEDDING_MODEL
            self.dim = BGE_DIM
            self.signature = "bgem3" if "bge-m3" in self.model_name.lower() else (
                self.model_name.replace("/", "_")
            )

    # -- backends ------------------------------------------------------------
    def _get_local_model(self):
        if self.model_name not in _SHARED_MODELS:
            with _MODEL_LOCK:
                if self.model_name not in _SHARED_MODELS:
                    from sentence_transformers import SentenceTransformer

                    clear_stale_hf_locks()
                    cache_info = hf_model_cache_status(self.model_name)
                    if not cache_info.get("present"):
                        logger.warning(
                            "BGE-M3 not in local cache; load may fail if HF is unreachable."
                        )
                    logger.info("Loading local embedding model %s", self.model_name)
                    _SHARED_MODELS[self.model_name] = SentenceTransformer(self.model_name)
        return _SHARED_MODELS[self.model_name]

    def _embed_local(self, texts: list[str]) -> list[np.ndarray]:
        model = self._get_local_model()
        vectors = model.encode(
            texts,
            convert_to_numpy=True,
            batch_size=EMBED_BATCH_SIZE,
            normalize_embeddings=True,
        )
        return [np.asarray(v, dtype=np.float32) for v in vectors]

    def _embed_azure_openai(self, texts: list[str]) -> list[np.ndarray]:
        """Embed via Azure OpenAI Embeddings API (text-embedding-3-large)."""
        import requests as _req

        api_key = os.getenv("AZURE_OPENAI_API_KEY") or ""
        endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
        deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-large")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
        if not api_key or not endpoint:
            raise RuntimeError("AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT not set")
        url = f"{endpoint}/openai/deployments/{deployment}/embeddings?api-version={api_version}"
        headers = {"Content-Type": "application/json", "api-key": api_key}
        out: list[np.ndarray] = []
        # Azure embeddings: max 2048 items or 8192 tokens per batch; use 64 to be safe
        batch_size = int(os.getenv("SEMV2_AZURE_EMBED_BATCH", "64"))
        for start in range(0, len(texts), batch_size):
            chunk = texts[start : start + batch_size]
            payload = {"input": chunk}
            resp = _req.post(url, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()["data"]
            for item in sorted(data, key=lambda x: x["index"]):
                vec = np.asarray(item["embedding"], dtype=np.float32)
                norm = float(np.linalg.norm(vec))
                if norm > 0:
                    vec = vec / norm
                out.append(vec)
        return out

    def _embed_gemini(self, texts: list[str], task_type: str) -> list[np.ndarray]:
        import google.generativeai as genai

        key = _gemini_key()
        if not key:
            raise RuntimeError("GEMINI_API_KEY not set for gemini embedding provider")
        genai.configure(api_key=key)

        out: list[np.ndarray] = []
        batch = max(1, GEMINI_EMBED_BATCH)
        for start in range(0, len(texts), batch):
            chunk = texts[start : start + batch]
            embeddings = self._gemini_call(genai, chunk, task_type)
            for emb in embeddings:
                vec = np.asarray(emb, dtype=np.float32)
                norm = float(np.linalg.norm(vec))
                if norm > 0:
                    vec = vec / norm
                out.append(vec)
        return out

    def _gemini_call(self, genai, chunk: list[str], task_type: str) -> list[Any]:
        """One embed request for a chunk, with backoff; falls back to per-item."""
        delay = GEMINI_EMBED_RETRY_BASE_SEC
        for attempt in range(GEMINI_EMBED_MAX_RETRIES):
            try:
                resp = genai.embed_content(
                    model=self.model_name,
                    content=chunk if len(chunk) > 1 else chunk[0],
                    task_type=task_type,
                )
                emb = resp["embedding"]
                # Single-item requests return a flat vector; lists return a list.
                if chunk and emb and not isinstance(emb[0], (list, tuple, np.ndarray)):
                    emb = [emb]
                return emb
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).lower()
                retriable = any(k in msg for k in _RETRIABLE)
                # If a batch is rejected for size, drop to per-item once.
                if len(chunk) > 1 and ("invalid" in msg or "batch" in msg or "size" in msg):
                    out: list[Any] = []
                    for t in chunk:
                        out.extend(self._gemini_call(genai, [t], task_type))
                    return out
                if not retriable or attempt == GEMINI_EMBED_MAX_RETRIES - 1:
                    raise
                logger.warning(
                    "Gemini embed retry %d/%d in %.0fs: %s",
                    attempt + 1, GEMINI_EMBED_MAX_RETRIES, delay, str(exc)[:100],
                )
                time.sleep(delay)
                delay = min(delay * 2, GEMINI_EMBED_RETRY_MAX_SEC)
        raise RuntimeError("unreachable")

    # -- public API ----------------------------------------------------------
    def _embed_batch(self, texts: list[str], *, is_query: bool) -> list[np.ndarray]:
        prefix = BGE_QUERY_PREFIX if is_query else BGE_DOCUMENT_PREFIX
        keys = [f"{self.provider}:{'q' if is_query else 'd'}:{t}" for t in texts]
        missing_idx = [i for i, k in enumerate(keys) if k not in self._cache]
        if missing_idx:
            to_embed = [f"{prefix}{texts[i]}" for i in missing_idx]
            if self.provider == "gemini":
                task = "retrieval_query" if is_query else "retrieval_document"
                vectors = self._embed_gemini(to_embed, task)
            elif self.provider == "azure_openai":
                vectors = self._embed_azure_openai(to_embed)
            else:
                vectors = self._embed_local(to_embed)
            for slot, vec in zip(missing_idx, vectors):
                self._cache[keys[slot]] = vec
        return [self._cache[k] for k in keys]

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed_batch([text], is_query=True)[0]

    def embed_document(self, text: str) -> np.ndarray:
        return self._embed_batch([text], is_query=False)[0]

    def embed_queries_batch(self, texts: list[str]) -> list[np.ndarray]:
        return self._embed_batch(list(texts), is_query=True)

    def embed_documents_batch(self, texts: list[str]) -> list[np.ndarray]:
        return self._embed_batch(list(texts), is_query=False)
