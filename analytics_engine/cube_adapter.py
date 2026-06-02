"""CubeJS REST load API adapter."""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def load_query(query: dict[str, Any]) -> dict[str, Any] | None:
    base = os.getenv("CUBEJS_API_URL", "").rstrip("/")
    if not base:
        return None
    secret = os.getenv("CUBEJS_API_SECRET", "")
    headers = {"Authorization": secret} if secret else {}
    url = f"{base}/cubejs-api/v1/load"
    try:
        resp = httpx.post(url, json={"query": query}, headers=headers, timeout=45.0)
        resp.raise_for_status()
        data = resp.json()
        rows = []
        for row in data.get("data") or []:
            if isinstance(row, dict):
                rows.append(row)
        if not rows:
            return {"columns": [], "rows": []}
        cols = list(rows[0].keys())
        return {"columns": cols, "rows": rows[:200]}
    except Exception as exc:
        logger.warning("CubeJS load failed: %s", exc)
        return {"error": str(exc), "columns": [], "rows": []}
