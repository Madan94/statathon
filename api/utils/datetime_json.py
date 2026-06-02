"""Serialize DB datetimes (stored as naive UTC) for JSON clients."""
from __future__ import annotations

from datetime import datetime, timezone


def isoformat_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
