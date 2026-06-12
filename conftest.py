"""Top-level conftest — ensures project import roots are on sys.path and .env loaded."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root/API/model roots on path (needed when pytest is run from outside repo root)
_ROOT = Path(__file__).resolve().parent
for _path in (_ROOT, _ROOT / "api", _ROOT / "model"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# Load .env if present
_env_file = _ROOT / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file, override=False)
    except ImportError:
        pass
