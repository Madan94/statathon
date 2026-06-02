"""Materialize filtered datasets for external OLAP tools."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def write_parquet_snapshot(
    df: pd.DataFrame,
    analysis_id: int,
    out_root: Path,
) -> str | None:
    if df is None or df.empty:
        return None
    out_root.mkdir(parents=True, exist_ok=True)
    path = out_root / f"analysis_{analysis_id}.parquet"
    try:
        df.to_parquet(path, index=False)
        return str(path)
    except Exception:
        csv_path = out_root / f"analysis_{analysis_id}.csv"
        try:
            df.to_csv(csv_path, index=False)
            return str(csv_path)
        except Exception as exc:
            logger.warning("Analytics snapshot failed: %s", exc)
            return None
