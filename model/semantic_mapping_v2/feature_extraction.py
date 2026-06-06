"""
STEP 5 — Column Feature Generation.

For every column build a compact, model-ready feature record:
  * column name (raw + normalized sentence)
  * sample values (deduped, truncated)
  * data type (numeric / categorical / datetime / boolean / text / id)
  * statistics (numeric: mean/std/skew/min/max; categorical: cardinality, top)
  * a single ``representation`` string fed to the embedder

The representation fuses the normalized name with literal value/type signals so
embeddings are grounded in the data, not just the header text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from semantic_mapping_v2.config import MAX_SAMPLE_VALUES
from semantic_mapping_v2.normalization import ColumnPreprocessorV2

_ID_NAME_RE = re.compile(r"(_id|_code|_no|_num|uid|uuid|^id$|serial|key)$", re.IGNORECASE)


@dataclass
class ColumnFeature:
    name: str
    normalized: str
    dtype: str
    samples: list[Any] = field(default_factory=list)
    statistics: dict[str, float] = field(default_factory=dict)
    cardinality: int = 0
    missing_ratio: float = 0.0
    representation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "normalized": self.normalized,
            "dtype": self.dtype,
            "samples": self.samples,
            "statistics": self.statistics,
            "cardinality": self.cardinality,
            "missing_ratio": round(self.missing_ratio, 4),
            "representation": self.representation,
        }


class FeatureExtractor:
    """Builds :class:`ColumnFeature` records from a DataFrame or raw metadata."""

    def __init__(self, preprocessor: ColumnPreprocessorV2 | None = None):
        self.pre = preprocessor or ColumnPreprocessorV2()

    # -- public --------------------------------------------------------------
    def from_dataframe(self, df: pd.DataFrame) -> dict[str, ColumnFeature]:
        out: dict[str, ColumnFeature] = {}
        for col in df.columns:
            out[str(col)] = self._feature_for_series(str(col), df[col])
        return out

    def from_metadata(
        self,
        columns: list[str],
        datatypes: dict[str, str] | None = None,
        samples: dict[str, list[Any]] | None = None,
    ) -> dict[str, ColumnFeature]:
        """Build features without a DataFrame (header + optional samples/types)."""
        datatypes = datatypes or {}
        samples = samples or {}
        out: dict[str, ColumnFeature] = {}
        for col in columns:
            col = str(col)
            sample_vals = list(samples.get(col, []))[:MAX_SAMPLE_VALUES]
            dtype = self._coerce_dtype(col, datatypes.get(col), sample_vals)
            feat = ColumnFeature(
                name=col,
                normalized=self.pre.to_sentence(col),
                dtype=dtype,
                samples=sample_vals,
                cardinality=len(set(map(str, sample_vals))),
            )
            feat.representation = self._representation(feat)
            out[col] = feat
        return out

    # -- internals -----------------------------------------------------------
    def _feature_for_series(self, name: str, series: pd.Series) -> ColumnFeature:
        non_null = series.dropna()
        total = len(series)
        missing_ratio = (total - len(non_null)) / total if total else 0.0
        dtype = self._infer_dtype(name, series)

        samples = self._samples(non_null)
        statistics: dict[str, float] = {}
        if dtype == "numeric":
            statistics = self._numeric_stats(non_null)

        feat = ColumnFeature(
            name=name,
            normalized=self.pre.to_sentence(name),
            dtype=dtype,
            samples=samples,
            statistics=statistics,
            cardinality=int(non_null.nunique()),
            missing_ratio=missing_ratio,
        )
        feat.representation = self._representation(feat)
        return feat

    def _samples(self, non_null: pd.Series) -> list[Any]:
        if non_null.empty:
            return []
        uniques = pd.unique(non_null)[:MAX_SAMPLE_VALUES]
        out: list[Any] = []
        for v in uniques:
            if isinstance(v, (np.integer,)):
                out.append(int(v))
            elif isinstance(v, (np.floating,)):
                out.append(round(float(v), 4))
            else:
                out.append(str(v)[:40])
        return out

    def _numeric_stats(self, non_null: pd.Series) -> dict[str, float]:
        try:
            numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        except Exception:
            return {}
        if numeric.empty:
            return {}
        stats = {
            "mean": float(numeric.mean()),
            "std": float(numeric.std(ddof=0)) if len(numeric) > 1 else 0.0,
            "min": float(numeric.min()),
            "max": float(numeric.max()),
        }
        try:
            stats["skew"] = float(numeric.skew()) if len(numeric) > 2 else 0.0
        except Exception:
            stats["skew"] = 0.0
        return {k: round(v, 4) for k, v in stats.items()}

    def _infer_dtype(self, name: str, series: pd.Series) -> str:
        non_null = series.dropna()
        if non_null.empty:
            return "text"
        if _ID_NAME_RE.search(name) and non_null.nunique() / max(len(non_null), 1) > 0.9:
            return "id"
        if pd.api.types.is_bool_dtype(series):
            return "boolean"
        if pd.api.types.is_datetime64_any_dtype(series):
            return "datetime"
        if pd.api.types.is_numeric_dtype(series):
            return "numeric"
        # Try coercions on object columns.
        coerced = pd.to_numeric(non_null, errors="coerce")
        if coerced.notna().mean() > 0.9:
            return "numeric"
        parsed = pd.to_datetime(non_null, errors="coerce")
        if parsed.notna().mean() > 0.9:
            return "datetime"
        uniq_ratio = non_null.nunique() / max(len(non_null), 1)
        if non_null.nunique() <= 50 or uniq_ratio < 0.5:
            return "categorical"
        return "text"

    def _coerce_dtype(self, name: str, declared: str | None, samples: list[Any]) -> str:
        if declared:
            d = declared.lower()
            if any(k in d for k in ("int", "float", "double", "numeric", "number")):
                return "numeric"
            if "bool" in d:
                return "boolean"
            if any(k in d for k in ("date", "time")):
                return "datetime"
            if any(k in d for k in ("str", "object", "category", "text")):
                if _ID_NAME_RE.search(name):
                    return "id"
                return "categorical"
        if _ID_NAME_RE.search(name):
            return "id"
        if samples and all(_is_number(s) for s in samples):
            return "numeric"
        return "categorical"

    def _representation(self, feat: ColumnFeature) -> str:
        parts = [feat.normalized]
        parts.append(f"type {feat.dtype}")
        if feat.samples:
            sample_str = ", ".join(str(s) for s in feat.samples[:5])
            parts.append(f"values {sample_str}")
        if feat.statistics:
            mean = feat.statistics.get("mean")
            mn = feat.statistics.get("min")
            mx = feat.statistics.get("max")
            if mean is not None:
                parts.append(f"mean {mean}")
            if mn is not None and mx is not None:
                parts.append(f"range {mn} to {mx}")
        return ". ".join(parts)


def _is_number(value: Any) -> bool:
    if isinstance(value, (int, float, np.integer, np.floating)):
        return True
    try:
        float(str(value))
        return True
    except (TypeError, ValueError):
        return False
