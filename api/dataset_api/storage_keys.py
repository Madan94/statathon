"""Generate deterministic S3 object keys for presigned uploads."""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone


def _safe_slug(name: str, max_len: int = 200) -> str:
    base = os.path.basename(name) or "file"
    slug = re.sub(r"[^a-zA-Z0-9._-]", "_", base)
    return slug[:max_len] if slug else "file"


def generate_object_key(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    uid = uuid.uuid4().hex
    day = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    prefix = (os.getenv("S3_UPLOAD_PREFIX") or "datasets").strip().strip("/")
    slug = _safe_slug(filename)
    return f"{prefix}/{day}/{uid}-{slug}"
