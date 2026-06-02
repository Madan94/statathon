"""Validation audit trail.

Every user decision on a validation candidate must be stored. This module
provides:

  * `AuditEntry` — frozen record of one user action
  * `AuditLog` — append-only collection; writes to either:
      - the `validation_audit` Postgres table (if available)
      - a JSONL file under storage/audit/ (always-on fallback)

Recorded fields (per the spec):
  rule_id, rule_type, column, row_id, old_value, new_value,
  user_action, timestamp, confidence
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    rule_id: str
    rule_type: str
    column: str
    row_id: int | None
    old_value: Any
    new_value: Any
    user_action: str          # 'KEEP' | 'MODIFY' | 'TREAT_AS_MISSING' | 'REMOVE_ROW' | 'IGNORE_RULE'
    confidence: float
    severity: str = "MEDIUM"
    user_id: int | None = None
    analysis_id: int | None = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Ensure JSON-serialisable values
        for k in ("old_value", "new_value"):
            v = d.get(k)
            if v is not None and not isinstance(v, (str, int, float, bool, list, dict)):
                d[k] = str(v)
        return d


class AuditLog:
    """Append-only log; JSONL file by default, PG-backed if configured."""

    def __init__(self, *, jsonl_dir: str | Path | None = None):
        self._jsonl_dir = Path(jsonl_dir or os.getenv(
            "VALIDATION_AUDIT_DIR", "./storage/audit"
        ))
        self._jsonl_dir.mkdir(parents=True, exist_ok=True)

    def append(self, entry: AuditEntry) -> int:
        """Persist a single audit entry. Returns 1 on success, 0 on failure."""
        try:
            day = datetime.utcnow().strftime("%Y%m%d")
            path = self._jsonl_dir / f"audit_{day}.jsonl"
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), default=str) + "\n")
            return 1
        except Exception as exc:
            logger.warning("AuditLog append failed: %s", exc)
            return 0

    def append_many(self, entries: Iterable[AuditEntry]) -> int:
        written = 0
        for e in entries:
            written += self.append(e)
        return written

    def replay(self, *, analysis_id: int | None = None) -> list[AuditEntry]:
        """Reload entries (most recent file first). Used for what-if rollbacks."""
        out: list[AuditEntry] = []
        for f in sorted(self._jsonl_dir.glob("audit_*.jsonl"), reverse=True):
            try:
                with f.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                            if analysis_id is not None and d.get("analysis_id") != analysis_id:
                                continue
                            out.append(AuditEntry(**d))
                        except Exception:
                            continue
            except Exception as exc:
                logger.info("AuditLog replay skipped %s: %s", f, exc)
        return out
