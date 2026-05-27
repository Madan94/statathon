"""Remote GPU worker client for heavy analysis execution."""

from __future__ import annotations

import os
from typing import Any

import httpx

from database.models import Dataset


def _worker_base() -> str:
    endpoint = os.getenv("GPU_WORKER_ENDPOINT", "").strip()
    if not endpoint:
        raise RuntimeError("GPU_WORKER_ENDPOINT is required when INFERENCE_MODE=remote")
    return endpoint.rstrip("/")


def _timeout_seconds() -> int:
    raw = os.getenv("GPU_WORKER_TIMEOUT_SECONDS", "900").strip()
    try:
        return max(30, int(raw))
    except Exception:
        return 900


def run_remote_analysis(*, dataset: Dataset, dataset_id: int, analysis_id: int) -> dict[str, Any]:
    """
    Delegates heavy pipeline execution to the GPU worker.
    Worker contract: POST /v1/analyze -> returns JSON with at least optional content_hash.
    """
    payload = {
        "dataset_id": dataset_id,
        "analysis_id": analysis_id,
        "filename": dataset.filename,
        "storage_path": dataset.storage_path,
        "object_key": dataset.object_key,
        "storage_provider": dataset.storage_provider,
    }

    with httpx.Client(timeout=_timeout_seconds()) as client:
        resp = client.post(f"{_worker_base()}/v1/analyze", json=payload)
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise RuntimeError(f"GPU worker returned {resp.status_code}: {detail}")
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("GPU worker response must be a JSON object")
        return data
