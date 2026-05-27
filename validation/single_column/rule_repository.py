"""Load declarative validation rules."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_LIBRARY = Path(__file__).resolve().parents[2] / "model" / "config" / "validation_rule_library.json"


@dataclass(frozen=True)
class CompiledRule:
    rule_id: str
    domain: str
    subdomain: str | None
    column_name_pattern: str
    compiled_pattern: re.Pattern[str]
    rule_name: str
    rule_type: str
    params: dict[str, Any]
    severity: str


def load_rule_library(path: Path | None = None) -> list[CompiledRule]:
    p = path or DEFAULT_LIBRARY
    raw = json.loads(Path(p).read_text(encoding="utf-8"))
    out: list[CompiledRule] = []
    for r in raw.get("rules") or []:
        pat = str(r.get("column_name_pattern", "")).strip()
        try:
            cpat = re.compile(pat, re.IGNORECASE)
        except re.error:
            continue
        out.append(
            CompiledRule(
                rule_id=str(r["id"]),
                domain=str(r.get("domain") or ""),
                subdomain=r.get("subdomain"),
                column_name_pattern=pat,
                compiled_pattern=cpat,
                rule_name=str(r.get("rule_name") or r["id"]),
                rule_type=str(r.get("rule_type") or "unknown"),
                params=dict(r.get("params") or {}),
                severity=str(r.get("severity") or "medium"),
            )
        )
    return out


def rules_for_column(
    compiled: list[CompiledRule],
    column_name: str,
    semantic_domain: str | None,
    semantic_subdomain: str | None = None,
) -> list[CompiledRule]:
    col = column_name or ""
    dom = (semantic_domain or "").lower()
    sub = (semantic_subdomain or "").lower() if semantic_subdomain else None
    matched: list[CompiledRule] = []
    for rule in compiled:
        if rule.compiled_pattern.search(col):
            rd = rule.domain.lower() if rule.domain else ""
            if rd and rd != dom:
                continue
            if rule.subdomain and sub and rule.subdomain.lower() != sub:
                continue
            matched.append(rule)
    return matched
