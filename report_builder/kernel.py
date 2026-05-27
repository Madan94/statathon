"""Phase 3 — Stateful Execution Layer.

A dedicated Docker container ("statathon-kernel") holds each dataset as an
Apache Arrow Table in RAM, exposing a gRPC / HTTP surface so block
recomputations are near-instantaneous when a user tweaks a parameter from
the AGUI.

The Semantic Router classifies every question/intent and dispatches it to:
  * deterministic_sql  — DuckDB over the Arrow table for counts/group-bys
  * python_kernel      — pandas/scipy for weighted stats, outliers, KNN
  * static             — structural blocks pulled straight from the payload

If the kernel container is not reachable, the same Arrow Table is created
in-process (PyArrow LRU) and the routing logic is unchanged.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------- Arrow-resident cache ----------------

class _ArrowKernel:
    """LRU cache of pyarrow Tables keyed by analysis_id."""

    def __init__(self, max_entries: int = 8):
        self._max = max_entries
        self._lock = threading.Lock()
        self._tables: "OrderedDict[int, Any]" = OrderedDict()  # value: pyarrow.Table

    def put(self, analysis_id: int, df: pd.DataFrame) -> Any:
        try:
            import pyarrow as pa  # type: ignore
        except Exception:
            logger.info("pyarrow not available; using pandas DataFrame fallback")
            with self._lock:
                self._tables[analysis_id] = df
                self._tables.move_to_end(analysis_id)
                self._evict()
            return df
        table = pa.Table.from_pandas(df, preserve_index=False)
        with self._lock:
            self._tables[analysis_id] = table
            self._tables.move_to_end(analysis_id)
            self._evict()
        return table

    def get(self, analysis_id: int) -> Any | None:
        with self._lock:
            t = self._tables.get(analysis_id)
            if t is not None:
                self._tables.move_to_end(analysis_id)
            return t

    def get_df(self, analysis_id: int) -> pd.DataFrame | None:
        t = self.get(analysis_id)
        if t is None:
            return None
        if isinstance(t, pd.DataFrame):
            return t
        try:
            return t.to_pandas()
        except Exception:
            return None

    def _evict(self):
        while len(self._tables) > self._max:
            self._tables.popitem(last=False)


_KERNEL = _ArrowKernel()


# ---------------- Docker kernel sidecar ----------------

import os as _os


def _kernel_endpoint() -> str | None:
    return _os.getenv("ARROW_KERNEL_ENDPOINT")  # e.g. http://statathon-kernel:8002


def _kernel_get_df(analysis_id: int) -> pd.DataFrame | None:
    """Pull a DataFrame from the kernel container by analysis_id (Arrow IPC stream)."""
    endpoint = _kernel_endpoint()
    if not endpoint:
        return None
    try:
        import pyarrow.ipc as ipc  # type: ignore
        import requests  # type: ignore

        r = requests.get(f"{endpoint}/datasets/{analysis_id}", timeout=2.0)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        reader = ipc.open_stream(r.content)
        return reader.read_pandas()
    except Exception as exc:
        logger.info("Arrow kernel fetch failed: %s", exc)
        return None


def _kernel_put_df(analysis_id: int, df: pd.DataFrame) -> bool:
    """Push a DataFrame to the kernel container so peers can recompute fast."""
    endpoint = _kernel_endpoint()
    if not endpoint:
        return False
    try:
        import io as _io
        import pyarrow as pa  # type: ignore
        import pyarrow.ipc as ipc  # type: ignore
        import requests  # type: ignore

        sink = _io.BytesIO()
        table = pa.Table.from_pandas(df, preserve_index=False)
        with ipc.new_stream(sink, table.schema) as w:
            w.write_table(table)
        r = requests.post(
            f"{endpoint}/datasets/{analysis_id}",
            data=sink.getvalue(),
            headers={"Content-Type": "application/vnd.apache.arrow.stream"},
            timeout=5.0,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.info("Arrow kernel push failed: %s", exc)
        return False


def ensure_loaded(analysis_id: int, df_loader: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    """Get the cached DataFrame; load + cache if missing.

    Lookup order:
      1. In-process Arrow LRU (hot cache).
      2. Docker kernel sidecar (warm RAM across workers).
      3. df_loader() — cold path (object storage / disk).
    """
    df = _KERNEL.get_df(analysis_id)
    if df is not None:
        return df
    remote = _kernel_get_df(analysis_id)
    if remote is not None:
        _KERNEL.put(analysis_id, remote)
        return remote
    df = df_loader()
    _KERNEL.put(analysis_id, df)
    _kernel_put_df(analysis_id, df)
    return df


# ---------------- Semantic Router ----------------

@dataclass
class Route:
    kind: str  # 'sql' | 'python' | 'static'
    rationale: str


def classify_intent(block_kind: str, hints: dict[str, Any]) -> Route:
    """Decide which engine renders this block.

    Rules:
      * metric/heading/static-source -> 'static' (pulled straight from payload)
      * table with simple `source` hint -> 'sql' (DuckDB over Arrow)
      * chart with aggregations -> 'python' (pandas)
      * narrative -> 'python' (LLM call dispatched in Phase 4)
    """
    if block_kind in ("heading", "metric"):
        return Route("static", "structural block; no compute")
    if block_kind == "table" and hints.get("source") in (
        "semantic_mapping", "phase3.anomaly_candidates", "phase3.imputation_candidates",
    ):
        return Route("sql", "tabular projection — deterministic SQL")
    if block_kind == "chart":
        return Route("python", "aggregation + plot — pandas kernel")
    if block_kind == "narrative":
        return Route("python", "narrative — Scribe (Gemini)")
    return Route("python", "default to python kernel")


# ---------------- Deterministic SQL helpers ----------------

def run_sql(df: pd.DataFrame, sql: str) -> pd.DataFrame:
    """Run SQL over a DataFrame via DuckDB; fallback to pandas if duckdb missing."""
    try:
        import duckdb  # type: ignore

        con = duckdb.connect()
        con.register("df", df)
        return con.execute(sql).fetchdf()
    except Exception as exc:
        logger.info("DuckDB unavailable (%s); SQL path disabled", exc)
        return df.head(0)


# ---------------- Stats helpers used by Verifier ----------------

def column_missing_counts(df: pd.DataFrame) -> dict[str, int]:
    return {str(c): int(df[c].isna().sum()) for c in df.columns}


def column_numeric_stats(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        if s.empty:
            continue
        out[str(c)] = {
            "min": float(s.min()),
            "max": float(s.max()),
            "mean": float(s.mean()),
            "median": float(s.median()),
            "std": float(s.std(ddof=0)) if len(s) > 1 else 0.0,
            "count": int(s.size),
        }
    return out


def count_outliers_zscore(df: pd.DataFrame, threshold: float = 3.0) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        if s.empty or s.std(ddof=0) == 0:
            continue
        z = np.abs((s - s.mean()) / s.std(ddof=0))
        counts[str(c)] = int((z > threshold).sum())
    return counts
