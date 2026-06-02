"""Convert numpy/pandas scalars to JSON-serializable Python types for SQLAlchemy JSON columns."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def _finite_float(value: float) -> float | None:
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def make_json_safe(obj: Any) -> Any:
    """Recursively coerce values for ``json.dumps`` / SQLAlchemy JSON columns."""
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return _finite_float(obj)
    if isinstance(obj, int):
        return obj

    # numpy / pandas scalars (optional deps at runtime)
    try:
        import numpy as np

        if isinstance(obj, np.generic):
            if isinstance(obj, np.floating):
                return _finite_float(float(obj))
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.bool_):
                return bool(obj)
            item = obj.item()
            if isinstance(item, float):
                return _finite_float(item)
            return item
    except ImportError:
        pass

    try:
        import pandas as pd

        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        if obj is pd.NA:
            return None
        if not isinstance(obj, (dict, list, tuple, set)):
            try:
                if pd.isna(obj):
                    return None
            except (TypeError, ValueError):
                pass
    except ImportError:
        pass

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        fin = _finite_float(float(obj))
        return fin if fin is not None else None
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [make_json_safe(v) for v in obj]
    return str(obj)
