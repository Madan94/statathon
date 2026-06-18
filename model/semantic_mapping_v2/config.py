"""
Configuration for Semantic Mapping & Domain Clustering V2.

Vector backbone: Qdrant (embedded-local by default via on-disk path; an external
Qdrant server/cloud is used automatically when QDRANT_URL is set). Embeddings:
BGE-M3. Clustering: scikit-learn native HDBSCAN. LLM: OpenRouter (primary),
Gemini/Groq fallback via ``SEMV2_LLM_PRIMARY``.

Independent of model/semantic_mapping/ — reads env and repo paths only.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

# Corporate networks (MITM SSL) break HuggingFace/pip TLS with certifi's bundle.
# truststore makes Python trust the OS certificate store, including the
# enterprise root CA. Best-effort: a no-op if truststore is unavailable.
try:  # pragma: no cover - environment dependent
    import truststore as _truststore

    _truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 - never block import on SSL shimming
    pass

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

# --------------------------------------------------------------------------
# Paths: curated static domain packs (STEP 2), one JSON per usecase
# --------------------------------------------------------------------------
DOMAIN_REGISTRY_DIR = Path(__file__).resolve().parent / "domain_registry"
MOSPI_DICTIONARY_PATH = REPO_ROOT / "model" / "config" / "mospi_dictionary.json"
DOMAIN_DEFINITIONS_PATH = REPO_ROOT / "model" / "config" / "domain_definitions.json"

# --------------------------------------------------------------------------
# Embeddings (BGE-M3 by default; override with SEMANTIC_EMBEDDING_MODEL)
# --------------------------------------------------------------------------
EMBEDDING_MODEL = os.getenv("SEMANTIC_EMBEDDING_MODEL", "BAAI/bge-m3")
EMBED_BATCH_SIZE = int(os.getenv("SEMANTIC_V2_EMBED_BATCH_SIZE", "16"))
EMBED_DIM = int(os.getenv("SEMANTIC_V2_EMBED_DIM", "1024"))

# BGE asymmetric prefixes: queries (columns) vs documents (domain definitions).
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
BGE_DOCUMENT_PREFIX = "Represent this document for retrieval: "

# --------------------------------------------------------------------------
# Qdrant vector store
#   * Default: embedded-local (on-disk) — the real Qdrant engine in-process,
#     no server required. Path under model/storage/.
#   * Set QDRANT_URL (e.g. http://localhost:6333 or a Qdrant Cloud URL) to use
#     an external server instead; QDRANT_API_KEY is sent when present.
# --------------------------------------------------------------------------
QDRANT_URL = os.getenv("QDRANT_URL") or None
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
QDRANT_LOCAL_PATH = os.getenv(
    "QDRANT_LOCAL_PATH", str(REPO_ROOT / "model" / "storage" / "qdrant_local")
)
QDRANT_TIMEOUT_SEC = float(os.getenv("QDRANT_TIMEOUT_SEC", "30"))
QDRANT_UPSERT_BATCH_SIZE = int(os.getenv("QDRANT_UPSERT_BATCH_SIZE", "128"))

# Collections (static domains shared; dynamic domains + columns are per-dataset).
STATIC_DOMAINS_COLLECTION = os.getenv("SEMANTIC_V2_STATIC_COLLECTION", "static_domains")
DYNAMIC_DOMAINS_PREFIX = os.getenv("SEMANTIC_V2_DYNAMIC_PREFIX", "dynamic_domains")
COLUMNS_PREFIX = os.getenv("SEMANTIC_V2_COLUMNS_PREFIX", "columns")


def _safe_id(dataset_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(dataset_id))


def dynamic_domains_collection(dataset_id: str) -> str:
    return f"{DYNAMIC_DOMAINS_PREFIX}_{_safe_id(dataset_id)}"


def columns_collection(dataset_id: str) -> str:
    return f"{COLUMNS_PREFIX}_{_safe_id(dataset_id)}"

# --------------------------------------------------------------------------
# STEP 1 — Usecases supported by the platform
# --------------------------------------------------------------------------
USECASES: list[str] = [
    "labour",
    "consumption",
    "education",
    "health",
    "agriculture",
    "energy",
    "industry",
    "demography",
    "infrastructure",
    "environment",
]

# --------------------------------------------------------------------------
# STEP 6 — Domain Matching Engine score weights (must sum to 1.0)
# --------------------------------------------------------------------------
MATCH_WEIGHTS = {
    "embedding": float(os.getenv("SEMV2_W_EMBEDDING", "0.40")),
    "sample_values": float(os.getenv("SEMV2_W_SAMPLES", "0.20")),
    "domain_context": float(os.getenv("SEMV2_W_CONTEXT", "0.15")),
    "statistics": float(os.getenv("SEMV2_W_STATS", "0.15")),
    "keyword": float(os.getenv("SEMV2_W_KEYWORD", "0.10")),
}

# STEP 7 — LLM fallback trigger. Columns scoring below this go to the LLM.
LLM_FALLBACK_THRESHOLD = float(os.getenv("SEMV2_LLM_THRESHOLD", "0.80"))

# Absolute floor: below this, even after LLM, a column is "uncorrelated".
UNCORRELATED_THRESHOLD = float(os.getenv("SEMV2_UNCORRELATED_THRESHOLD", "0.35"))

# --------------------------------------------------------------------------
# STEP 9 — Domain Clustering feature-vector block weights (must sum to 1.0)
# --------------------------------------------------------------------------
CLUSTER_FEATURE_WEIGHTS = {
    "embedding": float(os.getenv("SEMV2_CW_EMBEDDING", "0.35")),
    "domain": float(os.getenv("SEMV2_CW_DOMAIN", "0.22")),
    "sample_values": float(os.getenv("SEMV2_CW_SAMPLES", "0.13")),
    "statistics": float(os.getenv("SEMV2_CW_STATS", "0.10")),
    "column_type": float(os.getenv("SEMV2_CW_TYPE", "0.10")),
    "graph_affinity": float(os.getenv("SEMV2_CW_GRAPH", "0.05")),
    "correlation": float(os.getenv("SEMV2_CW_CORRELATION", "0.05")),
}

# HDBSCAN sizing (uses scikit-learn's native HDBSCAN; no external package).
HDBSCAN_MIN_CLUSTER_SIZE = int(os.getenv("SEMV2_HDBSCAN_MIN_CLUSTER", "2"))
HDBSCAN_MIN_SAMPLES = int(os.getenv("SEMV2_HDBSCAN_MIN_SAMPLES", "1"))

# STEP 11 — Cluster validation purity bar; below this we attempt a re-cluster.
CLUSTER_PURITY_THRESHOLD = float(os.getenv("SEMV2_CLUSTER_PURITY", "0.75"))

# Feature sampling.
MAX_SAMPLE_VALUES = int(os.getenv("SEMV2_MAX_SAMPLES", "8"))


def validate_weights() -> dict[str, float]:
    """Return any weight groups whose totals deviate from 1.0 (diagnostics)."""
    issues: dict[str, float] = {}
    for name, group in (("match", MATCH_WEIGHTS), ("cluster", CLUSTER_FEATURE_WEIGHTS)):
        total = round(sum(group.values()), 6)
        if abs(total - 1.0) > 1e-6:
            issues[name] = total
    return issues
