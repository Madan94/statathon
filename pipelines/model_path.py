"""Bootstrap sys.path so `model/` and API packages resolve from orchestrator."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MODEL_ROOT = _REPO_ROOT / "model"
_API_ROOT = _REPO_ROOT / "api"


def ensure_paths() -> Path:
    for p in (_REPO_ROOT, _MODEL_ROOT, _API_ROOT):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    return _REPO_ROOT


def repo_root() -> Path:
    return _REPO_ROOT
