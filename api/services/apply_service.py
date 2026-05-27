"""Apply user outlier/imputation decisions to a derived dataset (never overwrites raw upload)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from core.ingestion import dataframe_for_uploaded_dataset, infer_schema
from core.json_safe import make_json_safe
from core.rule_validator import normalize_schema
from database.models import Analysis, Dataset
from object_storage.object_store import try_build_default_store


def _derived_dir() -> Path:
    base = os.getenv("DERIVED_STORAGE_PATH", "./storage/derived")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def apply_analysis_decisions(db: Session, analysis_id: int) -> dict:
    an = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not an:
        raise ValueError("Analysis not found")
    if an.status != "complete":
        raise ValueError("Analysis not complete")

    ds = db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
    if not ds:
        raise ValueError("Dataset not found")

    store = try_build_default_store() if ds.object_key else None
    df = dataframe_for_uploaded_dataset(ds.storage_path, ds.object_key, ds.filename, store)
    schema = infer_schema(df)
    df = normalize_schema(df, schema)

    checkpoint = an.checkpoint if isinstance(an.checkpoint, dict) else {}
    phase3 = checkpoint.get("phase3") if isinstance(checkpoint.get("phase3"), dict) else {}
    decisions = phase3.get("user_decisions") if isinstance(phase3.get("user_decisions"), dict) else {}

    rows_to_drop: set[int] = set()
    for col, action in decisions.items():
        if str(action).lower() == "delete" and col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce")
            z = np.abs((s - s.mean()) / (s.std() + 1e-9))
            rows_to_drop.update(int(i) for i in s.index[z > 3].tolist())
        elif str(action).lower() == "normalize" and col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce")
            mu, sd = float(s.mean()), float(s.std() + 1e-9)
            df[col] = (s - mu) / sd

    if rows_to_drop:
        df = df.drop(index=sorted(rows_to_drop), errors="ignore").reset_index(drop=True)

    out_path = _derived_dir() / f"analysis_{analysis_id}_derived.csv"
    df.to_csv(out_path, index=False)

    summary = {
        "derived_path": str(out_path),
        "rows_after": len(df),
        "columns": list(df.columns),
        "rows_dropped": len(rows_to_drop),
        "decisions_applied": decisions,
    }

    checkpoint = dict(checkpoint)
    checkpoint["derived_dataset"] = make_json_safe(summary)
    an.checkpoint = checkpoint
    db.commit()

    return make_json_safe(summary)
