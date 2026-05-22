"""Phase 1 — Dataset Intelligence Layer (column profiles + rollup)."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.ingestion import infer_schema


def _ontology_domain_slugs(ontology: dict[str, Any] | None) -> list[str]:
    out: list[str] = []
    if not ontology:
        return out
    for _, blob in (ontology.get("dataset_types") or {}).items():
        if not isinstance(blob, dict):
            continue
        for dom in blob.get("domains") or []:
            if isinstance(dom, str):
                out.append(dom)
        subs = blob.get("subdomains") or {}
        if isinstance(subs, dict):
            for _, children in subs.items():
                if isinstance(children, list):
                    out.extend(str(x) for x in children)
    return list(dict.fromkeys(out))


def scores_static_macro_type_from_columns(
    column_names: list[str],
    ontology: dict[str, Any] | None,
) -> dict[str, float]:
    """Token overlap between column names and static ontology domains/subdomains (cheap, no LLM)."""
    if not ontology:
        return {}
    blob = " ".join(column_names).lower().replace("_", " ")
    scores: dict[str, float] = {}
    for dtype, meta in (ontology.get("dataset_types") or {}).items():
        if not isinstance(meta, dict):
            continue
        domains = [str(d).lower() for d in (meta.get("domains") or []) if isinstance(d, str)]
        hits = 0.0
        for d in domains:
            if d in blob or d.replace("_", " ") in blob:
                hits += 1.0
        subs = meta.get("subdomains") or {}
        if isinstance(subs, dict):
            for children in subs.values():
                if not isinstance(children, list):
                    continue
                for child in children:
                    c = str(child).lower().replace("_", " ")
                    if c and c in blob:
                        hits += 0.35
        denom = max(float(len(domains)), 1.0)
        scores[str(dtype)] = round(min(hits / denom, 1.0), 4)
    return scores


def column_profile_embedding_snippet(profile: dict[str, Any] | None, max_len: int = 220) -> str:
    """Short text fused into column-name embedding for hybrid semantic hints (cheap, deterministic)."""
    if not isinstance(profile, dict) or not profile:
        return ""
    parts = [
        f"type={profile.get('datatype')}",
        f"missing={profile.get('missing_ratio')}",
        f"car={profile.get('cardinality')}",
        f"uniq_r={profile.get('unique_ratio')}",
    ]
    if profile.get("entropy") is not None:
        parts.append(f"H={profile.get('entropy')}")
    hints = profile.get("semantic_hints") or []
    if isinstance(hints, list) and hints:
        parts.append(f"hints={','.join(str(h) for h in hints[:6])}")
    tv = profile.get("top_values") or []
    if isinstance(tv, list) and tv:
        first = tv[0]
        if isinstance(first, dict) and first.get("value") is not None:
            parts.append(f"mode={first.get('value')}")
    raw = "; ".join(str(p) for p in parts if p)
    return raw[:max_len]


def _semantic_hints(column: str, domain_slugs: list[str]) -> list[str]:
    col_l = column.lower()
    hints: list[str] = []
    for d in domain_slugs:
        dl = d.lower().replace("_", " ")
        if dl in col_l or dl.replace(" ", "") in col_l.replace("_", ""):
            hints.append(d)
        elif dl.split() and any(tok in col_l for tok in dl.split()):
            hints.append(d)
    return hints[:24]


def _safe_skew(arr: np.ndarray) -> float | None:
    if arr.size < 3:
        return None
    try:
        from scipy.stats import skew

        return float(skew(arr, bias=False))
    except Exception:
        return None


def _histogram_entropy(series: pd.Series, bins: int = 24) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna().values.astype(float)
    if s.size < 2:
        return None
    hist, _ = np.histogram(s, bins=min(bins, max(8, int(math.sqrt(len(s))))))
    hist = hist.astype(float)
    tot = hist.sum()
    if tot <= 0:
        return None
    p = hist / tot
    return float(-np.sum(p[p > 0] * np.log(p[p > 0] + 1e-15)))


def _nominal_entropy(series: pd.Series) -> float | None:
    vc = series.dropna().astype(str).value_counts(normalize=True)
    if vc.empty:
        return None
    p = vc.values.astype(float)
    return float(-np.sum(p * np.log(p + 1e-15)))


def profile_column(
    series: pd.Series,
    column_name: str,
    inferred_type: str,
    ontology: dict[str, Any] | None,
) -> dict[str, Any]:
    n = len(series)
    if n == 0:
        return {
            "datatype": inferred_type,
            "missing_ratio": 1.0,
            "cardinality": 0,
            "unique_ratio": 0.0,
            "entropy": None,
            "skewness": None,
            "top_values": [],
            "sample_values": [],
            "semantic_hints": [],
        }

    nn = int(series.notna().sum())
    missing_ratio = float(1.0 - nn / n)
    cardinality = int(series.dropna().nunique()) if nn else 0
    unique_ratio = float(cardinality / nn) if nn else 0.0

    domain_slugs = _ontology_domain_slugs(ontology)
    hints = _semantic_hints(column_name, domain_slugs)

    profile: dict[str, Any] = {
        "datatype": inferred_type,
        "missing_ratio": round(missing_ratio, 6),
        "cardinality": cardinality,
        "unique_ratio": round(unique_ratio, 6),
        "entropy": None,
        "skewness": None,
        "top_values": [],
        "sample_values": [],
        "semantic_hints": hints,
        "mean_std": None,
        "min_max": None,
    }

    final_dtype = inferred_type

    if inferred_type == "numeric":
        num = pd.to_numeric(series, errors="coerce")
        nv = num.dropna()
        if len(nv) >= 2:
            arr = nv.values.astype(float)
            ew = _histogram_entropy(nv)
            profile["entropy"] = round(ew, 6) if ew is not None else None
            sk = _safe_skew(arr)
            profile["skewness"] = round(sk, 4) if sk is not None else None
            profile["mean_std"] = {
                "mean": float(arr.mean()),
                "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
            }
            profile["min_max"] = {"min": float(arr.min()), "max": float(arr.max())}
            top = nv.round(8).astype(str).value_counts().head(12)
            profile["top_values"] = [{"value": i, "count": int(c)} for i, c in top.items()]
            profile["sample_values"] = [float(nv.iloc[i]) for i in range(min(5, len(nv)))]
        else:
            final_dtype = "string"

    if final_dtype != "numeric" or not profile["top_values"]:
        str_s = series.dropna().astype(str)
        en = _nominal_entropy(str_s)
        if profile["entropy"] is None:
            profile["entropy"] = round(en, 6) if en is not None else None
        profile["skewness"] = None
        profile["mean_std"] = None
        profile["min_max"] = None
        tc = str_s.value_counts().head(12)
        profile["top_values"] = [{"value": str(i), "count": int(c)} for i, c in tc.items()]
        profile["sample_values"] = [str(str_s.iloc[i]) for i in range(min(5, len(str_s)))]
        if inferred_type == "numeric" and final_dtype == "string":
            final_dtype = "string_like"

    profile["datatype"] = final_dtype
    return profile


def build_dataset_intelligence_profiles(
    df: pd.DataFrame,
    ontology: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    schema = infer_schema(df)
    columns: dict[str, dict[str, Any]] = {}
    for col in df.columns:
        ckey = str(col)
        inferred = schema.get(ckey, "string")
        columns[ckey] = profile_column(df[col], ckey, inferred, ontology)

    total_cells = len(df) * max(len(df.columns), 1)
    missing_cells = int(df.isna().sum().sum())

    rollup = {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": [str(c) for c in df.columns],
        "global_missing_pct": round(missing_cells / total_cells * 100.0, 4) if total_cells else 0.0,
        "cardinality_heatmap_hints": [
            {"column": c, "cardinality": p["cardinality"], "entropy": p.get("entropy")}
            for c, p in sorted(columns.items(), key=lambda x: x[0])
        ],
    }

    rollup_cols = [str(c) for c in df.columns]
    macro_scores = scores_static_macro_type_from_columns(rollup_cols, ontology)
    rollup["static_macro_type_scores"] = macro_scores
    rollup["static_macro_type_best_hint"] = (
        max(macro_scores, key=macro_scores.get) if macro_scores else None
    )

    return columns, rollup


def load_default_ontology() -> dict[str, Any] | None:
    try:
        root = Path(__file__).resolve().parents[1]
        path = root / "model" / "config" / "mospi_ontology.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
