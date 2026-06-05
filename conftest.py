"""Top-level conftest — ensures repo root is on sys.path and .env loaded."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root on path (needed when pytest is run from outside repo root)
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Load .env if present
_env_file = _ROOT / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file, override=False)
    except ImportError:
        pass
