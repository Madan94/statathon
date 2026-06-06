"""
Qdrant and V2 semantic mapping configuration.

Independent of model/semantic_mapping/ — reads env and repo paths only.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HF_CACHE_DIR = REPO_ROOT / "model" / "cache"


def _configure_hf_cache() -> None:
    """Resolve relative HF cache paths so model weights reuse across runs."""
    cache = os.getenv("HUGGINGFACE_HUB_CACHE") or os.getenv("HF_HOME")
    if not cache:
        cache = str(REPO_ROOT / "model" / "cache")
    path = Path(cache)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    resolved = str(path.resolve())
    os.environ.setdefault("HF_HOME", resolved)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", resolved)
    hf_token = os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HF_TOKEN")
    if hf_token:
        os.environ.setdefault("HF_TOKEN", hf_token)
    global HF_CACHE_DIR
    HF_CACHE_DIR = path.resolve()
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")


_configure_hf_cache()


def clear_stale_hf_locks(max_age_sec: int | None = None) -> int:
    """
    Remove Hugging Face .lock files left after Ctrl+C or crashed downloads.

    Safe to call before model load; only removes locks older than max_age_sec.
    """
    age = max_age_sec if max_age_sec is not None else int(
        os.getenv("HF_LOCK_MAX_AGE_SEC", "120")
    )
    locks_root = HF_CACHE_DIR / ".locks"
    if not locks_root.exists():
        return 0

    removed = 0
    now = time.time()
    for lock_file in locks_root.rglob("*.lock"):
        try:
            if now - lock_file.stat().st_mtime >= age:
                lock_file.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed


def hf_model_cache_status(model_id: str) -> dict[str, str | float | bool]:
    """Report whether a model snapshot appears present in the local HF cache."""
    folder = "models--" + model_id.replace("/", "--")
    model_dir = HF_CACHE_DIR / folder
    if not model_dir.exists():
        return {"present": False, "size_mb": 0.0, "path": str(model_dir)}

    total = sum(f.stat().st_size for f in model_dir.rglob("*") if f.is_file())
    return {
        "present": total > 0,
        "size_mb": round(total / (1024 * 1024), 1),
        "path": str(model_dir),
    }

# Qdrant
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
QDRANT_TIMEOUT_SEC = float(os.getenv("QDRANT_TIMEOUT_SEC", "30"))
QDRANT_UPSERT_BATCH_SIZE = int(os.getenv("QDRANT_UPSERT_BATCH_SIZE", "100"))

# Collections
STATIC_DOMAINS_COLLECTION = os.getenv("SEMANTIC_V2_STATIC_COLLECTION", "static_domains")
DYNAMIC_DOMAINS_PREFIX = os.getenv("SEMANTIC_V2_DYNAMIC_PREFIX", "dynamic_domains")
COLUMNS_PREFIX = os.getenv("SEMANTIC_V2_COLUMNS_PREFIX", "columns")

# Embeddings (BGE-M3)
EMBEDDING_MODEL = os.getenv("SEMANTIC_EMBEDDING_MODEL", "BAAI/bge-m3")
EMBED_BATCH_SIZE = int(os.getenv("SEMANTIC_V2_EMBED_BATCH_SIZE", "16"))
EMBED_DIM = int(os.getenv("SEMANTIC_V2_EMBED_DIM", "1024"))

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
BGE_DOCUMENT_PREFIX = "Represent this document for retrieval: "

# Gatekeeper
STRICT_THRESHOLD = float(os.getenv("SEMANTIC_V2_STRICT_THRESHOLD", "0.45"))

# Ontology
DOMAIN_DEFINITIONS_PATH = REPO_ROOT / "model" / "config" / "domain_definitions.json"
MOSPI_DICTIONARY_PATH = REPO_ROOT / "model" / "config" / "mospi_dictionary.json"


def dynamic_domains_collection(dataset_id: str) -> str:
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(dataset_id))
    return f"{DYNAMIC_DOMAINS_PREFIX}_{safe_id}"


def columns_collection(dataset_id: str) -> str:
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(dataset_id))
    return f"{COLUMNS_PREFIX}_{safe_id}"
