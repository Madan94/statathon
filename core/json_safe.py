"""Convert numpy/pandas scalars to JSON-serializable Python types for SQLAlchemy JSON columns."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def make_json_safe(obj: Any) -> Any:
    """Recursively coerce values for ``json.dumps`` / SQLAlchemy JSON columns."""
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return obj

    # numpy / pandas scalars (optional deps at runtime)
    try:
        import numpy as np

        if isinstance(obj, np.generic):
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.bool_):
                return bool(obj)
            return obj.item()
    except ImportError:
        pass

    try:
        import pandas as pd

        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        if obj is pd.NA:
            return None
    except ImportError:
        pass

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [make_json_safe(v) for v in obj]
    return str(obj)
