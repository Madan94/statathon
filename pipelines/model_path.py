"""Bootstrap sys.path so `model/` and API packages resolve from orchestrator."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MODEL_ROOT = _REPO_ROOT / "model"
_API_ROOT = _REPO_ROOT / "api"


def ensure_huggingface_hub_cache(repo_root: Path | None = None) -> Path:
    """Create cache dir from ``HUGGINGFACE_HUB_CACHE`` and pin ``HF_HOME`` for hub/transformers downloads."""
    root = repo_root or _REPO_ROOT
    raw = (os.getenv("HUGGINGFACE_HUB_CACHE") or "").strip() or "./model/cache"
    cache = Path(raw)
    if not cache.is_absolute():
        cache = (root / cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    # Hugging Face stack: hub + transformers use HF_HOME (subdirs hub/, datasets/, etc.)
    os.environ.setdefault("HF_HOME", str(cache))
    return cache


def ensure_paths() -> Path:
    for p in (_REPO_ROOT, _MODEL_ROOT, _API_ROOT):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    ensure_huggingface_hub_cache(_REPO_ROOT)
    return _REPO_ROOT


def repo_root() -> Path:
    return _REPO_ROOT
