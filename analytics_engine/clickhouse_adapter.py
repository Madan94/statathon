"""ClickHouse HTTP query adapter."""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


def _auth() -> tuple[str, str] | None:
    user = os.getenv("CLICKHOUSE_USER", "").strip()
    password = os.getenv("CLICKHOUSE_PASSWORD", "")
    if user:
        return user, password
    return None


def run_query(sql: str) -> dict[str, Any] | None:
    base = os.getenv("CLICKHOUSE_URL", "").rstrip("/")
    if not base:
        return None
    database = os.getenv("CLICKHOUSE_DATABASE", "default")
    url = f"{base}/?database={quote(database)}"
    auth = _auth()
    try:
        resp = httpx.post(url, content=sql, auth=auth, timeout=45.0)
        resp.raise_for_status()
        lines = [ln for ln in resp.text.strip().split("\n") if ln]
        if not lines:
            return {"columns": [], "rows": []}
        cols = lines[0].split("\t")
        rows = []
        for ln in lines[1:]:
            parts = ln.split("\t")
            rows.append(dict(zip(cols, parts)))
        return {"columns": cols, "rows": rows[:200]}
    except Exception as exc:
        logger.warning("ClickHouse query failed: %s", exc)
        return {"error": str(exc), "columns": [], "rows": []}
