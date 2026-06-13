"""S2 — Binding review (human-in-the-loop confirm state machine).

S1 proposes; **nothing is auto-accepted**. S2 is where a human (dashboard or
headless ``--accept-proposed``) moves each :class:`EntityBinding` through:

    proposed ──confirm──▶ confirmed
             ──override─▶ overridden   (+ new columns)
             ──reject───▶ rejected
    unresolved ──map────▶ overridden   (human supplies the column)

Re-runs are cheap. Every dataset gets a **signature** = ``hash(sorted
"name:dtype")`` — stable across row-order and values. Confirmations are cached
per ``(templateId, signature)``; on a re-run with the same shape we re-apply the
saved decisions and only surface **deltas** (new / still-unresolved entities).

Deterministic, offline, filesystem-backed (no DB required).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from report_builder.binding.schema import BindingAST, BoundColumn, DatasetAST, EntityBinding

logger = logging.getLogger(__name__)

_PENDING_STATUSES = ("proposed", "unresolved")
_DEFAULT_STORE = Path(__file__).resolve().parents[2] / "storage" / "bindings"


# ─────────────────────────────────────────────────────────────────────────────
# Signature
# ─────────────────────────────────────────────────────────────────────────────


def dataset_signature(dataset: DatasetAST) -> str:
    """Stable cache key for a dataset *shape* — ``hash(sorted "name:dtype")``."""
    parts = sorted(f"{c.name}:{c.dtype}" for c in dataset.columns)
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# Confirmation records
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Confirmation:
    """One human decision about an entity binding."""

    entityId: str
    status: str                       # confirmed | overridden | rejected
    columns: list[str] | None = None  # override columns (overridden only)
    note: str = ""
    sharePolicy: str = "exclusive"    # exclusive | shared
    shareReason: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"entityId": self.entityId, "status": self.status}
        if self.columns is not None:
            out["columns"] = list(self.columns)
        if self.note:
            out["note"] = self.note
        if self.sharePolicy != "exclusive":
            out["sharePolicy"] = self.sharePolicy
        if self.shareReason:
            out["shareReason"] = self.shareReason
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Confirmation":
        cols = d.get("columns")
        return cls(
            entityId=str(d.get("entityId") or ""),
            status=str(d.get("status") or "confirmed"),
            columns=list(cols) if cols is not None else None,
            note=str(d.get("note") or ""),
            sharePolicy=str(d.get("sharePolicy") or d.get("share_policy") or "exclusive"),
            shareReason=str(d.get("shareReason") or d.get("share_reason") or ""),
        )


class ColumnOwnershipConflict(Exception):
    """Raised when an exclusive column assignment would steal another owner."""

    def __init__(self, conflicts: list[dict[str, Any]]) -> None:
        self.conflicts = conflicts
        cols = ", ".join(str(c.get("column") or "") for c in conflicts)
        super().__init__(f"column ownership conflict: {cols}")


@dataclass
class ReviewRecord:
    """Persisted review state for one ``(templateId, signature)`` pair."""

    templateId: str
    datasetSignature: str
    datasetId: str = ""
    proposals: list[dict[str, Any]] = field(default_factory=list)  # snapshot of S1
    confirmations: dict[str, Confirmation] = field(default_factory=dict)  # entityId → decision
    updatedAt: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "templateId": self.templateId,
            "datasetSignature": self.datasetSignature,
            "datasetId": self.datasetId,
            "proposals": list(self.proposals),
            "confirmations": {k: v.to_dict() for k, v in self.confirmations.items()},
            "updatedAt": self.updatedAt,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReviewRecord":
        return cls(
            templateId=str(d.get("templateId") or ""),
            datasetSignature=str(d.get("datasetSignature") or ""),
            datasetId=str(d.get("datasetId") or ""),
            proposals=list(d.get("proposals") or []),
            confirmations={
                k: Confirmation.from_dict(v) for k, v in (d.get("confirmations") or {}).items()
            },
            updatedAt=float(d.get("updatedAt") or 0.0),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────


def _store_dir(storage_dir: str | os.PathLike[str] | None) -> Path:
    return Path(storage_dir) if storage_dir is not None else _DEFAULT_STORE


def _record_path(template_id: str, signature: str, storage_dir: Path) -> Path:
    safe_tpl = template_id or "template"
    return storage_dir / f"{safe_tpl}__{signature}.json"


def load_record(
    template_id: str, signature: str, *, storage_dir: str | os.PathLike[str] | None = None
) -> ReviewRecord | None:
    """Load a saved review record for ``(templateId, signature)`` if present."""
    path = _record_path(template_id, signature, _store_dir(storage_dir))
    if not path.exists():
        return None
    try:
        return ReviewRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[review] failed to load %s: %s", path, exc)
        return None


def save_record(
    record: ReviewRecord, *, storage_dir: str | os.PathLike[str] | None = None
) -> Path:
    """Persist a review record atomically."""
    base = _store_dir(storage_dir)
    base.mkdir(parents=True, exist_ok=True)
    record.updatedAt = time.time()
    path = _record_path(record.templateId, record.datasetSignature, base)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# State machine
# ─────────────────────────────────────────────────────────────────────────────


def apply_confirmations(binding: BindingAST, record: ReviewRecord) -> BindingAST:
    """Apply saved confirmations onto a fresh proposal — the S2 transition.

    Entities not present in ``record.confirmations`` keep their proposed/unresolved
    status (these are the deltas a re-run must still surface).
    """
    for eb in binding.entityBindings:
        decision = record.confirmations.get(eb.entityId)
        if decision is None:
            continue
        if decision.status == "rejected":
            eb.status = "rejected"
        elif decision.status == "overridden":
            eb.status = "overridden"
            if decision.columns is not None:
                eb.columns = [BoundColumn(column=c) for c in decision.columns]
                eb.confidence = 1.0
                eb.method = "manual"
        elif decision.status == "confirmed":
            eb.status = "confirmed"
        if decision.note:
            eb.notes = [*eb.notes, decision.note]
    return binding


def _proposal_by_id(record: ReviewRecord, entity_id: str) -> dict[str, Any]:
    return next((p for p in record.proposals if str(p.get("entityId") or "") == entity_id), {})


def _proposal_columns(prop: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for col in prop.get("columns") or []:
        name = str(col.get("column") or "") if isinstance(col, dict) else str(col or "")
        if name and name not in out:
            out.append(name)
    return out


def _decision_columns(record: ReviewRecord, entity_id: str) -> list[str]:
    decision = record.confirmations.get(entity_id)
    if decision and decision.columns is not None:
        return [c for c in decision.columns if c]
    return _proposal_columns(_proposal_by_id(record, entity_id))


def _owner_for(record: ReviewRecord, entity_id: str, columns: list[str]) -> dict[str, Any] | None:
    prop = _proposal_by_id(record, entity_id)
    decision = record.confirmations.get(entity_id)
    status = decision.status if decision is not None else str(prop.get("status") or "")
    if status == "rejected" or not columns:
        return None
    return {
        "entityId": entity_id,
        "entityName": str(prop.get("entityName") or entity_id),
        "entityType": str(prop.get("entityType") or "dimension"),
        "cardinality": str(prop.get("cardinality") or "oneToOne"),
        "status": status or "proposed",
        "sharePolicy": decision.sharePolicy if decision is not None else "exclusive",
        "shareReason": decision.shareReason if decision is not None else "",
    }


def compute_column_ownership(record: ReviewRecord) -> dict[str, Any]:
    """Return live column ownership for the binder UI and conflict gate.

    Proposed S1 claims are visible, but only reviewed exclusive decisions
    (confirmed/overridden) lock a column or create blocking conflicts.
    """
    columns: dict[str, dict[str, Any]] = {}
    entity_ids = [str(p.get("entityId") or "") for p in record.proposals if p.get("entityId")]
    for entity_id in entity_ids:
        selected = _decision_columns(record, entity_id)
        owner = _owner_for(record, entity_id, selected)
        if owner is None:
            continue
        for column in selected:
            entry = columns.setdefault(column, {"column": column, "owners": [], "locked": False})
            entry["owners"].append(dict(owner))

    conflicts: list[dict[str, Any]] = []
    for column, entry in columns.items():
        exclusive = [
            o for o in entry["owners"]
            if o.get("sharePolicy") != "shared" and o.get("status") in ("confirmed", "overridden")
        ]
        entry["locked"] = bool(exclusive)
        if len(exclusive) > 1:
            conflicts.append({
                "column": column,
                "severity": "error",
                "code": "COLUMN_OWNERSHIP_CONFLICT",
                "message": f"Column '{column}' has multiple exclusive owners.",
                "owners": exclusive,
            })
    return {"columns": columns, "conflicts": conflicts}


def find_exclusive_column_conflicts(
    record: ReviewRecord,
    entity_id: str,
    columns: list[str],
) -> list[dict[str, Any]]:
    """Find existing exclusive owners for selected columns, excluding entity_id."""
    selected = {c for c in columns if c}
    if not selected:
        return []
    ownership = compute_column_ownership(record)
    conflicts: list[dict[str, Any]] = []
    for column in sorted(selected):
        owners = [
            o for o in (ownership.get("columns", {}).get(column, {}).get("owners") or [])
            if o.get("entityId") != entity_id and o.get("sharePolicy") != "shared"
            and o.get("status") in ("confirmed", "overridden")
        ]
        if owners:
            conflicts.append({
                "column": column,
                "severity": "error",
                "code": "COLUMN_ALREADY_OWNED",
                "message": f"Column '{column}' is already assigned to another exclusive entity.",
                "owners": owners,
            })
    return conflicts


def move_columns_from_entities(
    record: ReviewRecord,
    *,
    columns: list[str],
    from_entity_ids: list[str],
    note: str = "",
) -> ReviewRecord:
    """Remove columns from prior owners before a forced transfer."""
    selected = {c for c in columns if c}
    for entity_id in from_entity_ids:
        if not entity_id:
            continue
        current = _decision_columns(record, entity_id)
        remaining = [c for c in current if c not in selected]
        if remaining:
            record.confirmations[entity_id] = Confirmation(
                entityId=entity_id,
                status="overridden",
                columns=remaining,
                note=note,
            )
        else:
            record.confirmations[entity_id] = Confirmation(
                entityId=entity_id,
                status="rejected",
                columns=[],
                note=note,
            )
    return record


def _manual_entity_id(record: ReviewRecord, entity_name: str) -> str:
    base = "manual_" + hashlib.sha1(entity_name.strip().lower().encode("utf-8")).hexdigest()[:10]
    existing = {str(p.get("entityId") or "") for p in record.proposals}
    if base not in existing:
        return base
    i = 2
    while f"{base}_{i}" in existing:
        i += 1
    return f"{base}_{i}"


def add_manual_entity(
    record: ReviewRecord,
    *,
    entity_name: str,
    entity_type: str = "dimension",
    columns: list[str],
    cardinality: str = "oneToOne",
    note: str = "",
    share_policy: str = "exclusive",
    share_reason: str = "",
) -> ReviewRecord:
    """Add an officer-created entity and immediately record its reviewed mapping."""
    selected = [c for c in dict.fromkeys(columns) if c]
    if not selected:
        raise ValueError("manual entity requires at least one column")
    policy = share_policy if share_policy in ("exclusive", "shared") else "exclusive"
    if policy == "shared" and not share_reason.strip():
        raise ValueError("shared manual entity requires a share reason")
    if policy != "shared":
        conflicts = []
        for column in selected:
            owners = [
                o for o in (compute_column_ownership(record).get("columns", {}).get(column, {}).get("owners") or [])
                if o.get("sharePolicy") != "shared"
                and o.get("status") in ("confirmed", "overridden")
            ]
            if owners:
                conflicts.append({
                    "column": column,
                    "severity": "error",
                    "code": "COLUMN_ALREADY_OWNED",
                    "message": f"Column '{column}' is already assigned to another exclusive entity.",
                    "owners": owners,
                })
        if conflicts:
            raise ColumnOwnershipConflict(conflicts)

    entity_id = _manual_entity_id(record, entity_name)
    record.proposals.append({
        "entityId": entity_id,
        "entityName": entity_name,
        "entityType": entity_type,
        "cardinality": cardinality,
        "columns": [{"column": c, "confidence": 1.0, "method": "manual"} for c in selected],
        "combine": "none",
        "confidence": 1.0,
        "method": "manual",
        "status": "overridden",
        "alternatives": [],
        "notes": [note] if note else [],
        "evidence": [{
            "signal": "manual",
            "score": 1.0,
            "detail": "Officer-created entity mapping",
            "columns": list(selected),
        }],
        "risks": [],
    })
    record.confirmations[entity_id] = Confirmation(
        entityId=entity_id,
        status="overridden",
        columns=selected,
        note=note,
        sharePolicy=policy,
        shareReason=share_reason,
    )
    return record


def accept_all_proposed(binding: BindingAST, record: ReviewRecord) -> BindingAST:
    """Headless confirm (``--accept-proposed``): every *proposed* → *confirmed*.

    ``unresolved`` entities are NOT auto-accepted — they have no column to confirm.
    Writes the decisions into ``record.confirmations`` so the cache reflects them.
    """
    for eb in binding.entityBindings:
        if eb.status == "proposed":
            eb.status = "confirmed"
            record.confirmations[eb.entityId] = Confirmation(
                entityId=eb.entityId, status="confirmed", note="auto-accepted (--accept-proposed)"
            )
    return binding


def confirm(
    record: ReviewRecord,
    entity_id: str,
    *,
    columns: list[str] | None = None,
    note: str = "",
    share_policy: str = "exclusive",
    share_reason: str = "",
) -> ReviewRecord:
    """Record a single human decision (used by the REST POST handler)."""
    selected = columns if columns is not None else _decision_columns(record, entity_id)
    policy = share_policy if share_policy in ("exclusive", "shared") else "exclusive"
    if policy == "shared" and not share_reason.strip():
        raise ValueError("shared ownership requires a share reason")
    if policy != "shared":
        conflicts = find_exclusive_column_conflicts(record, entity_id, selected)
        if conflicts:
            raise ColumnOwnershipConflict(conflicts)
    status = "overridden" if columns else "confirmed"
    record.confirmations[entity_id] = Confirmation(
        entityId=entity_id,
        status=status,
        columns=columns,
        note=note,
        sharePolicy=policy,
        shareReason=share_reason,
    )
    return record


def reject(record: ReviewRecord, entity_id: str, *, note: str = "") -> ReviewRecord:
    record.confirmations[entity_id] = Confirmation(
        entityId=entity_id, status="rejected", note=note
    )
    return record


def reopen(record: ReviewRecord, entity_id: str) -> ReviewRecord:
    """Clear a prior human decision so the entity returns to proposal state."""
    record.confirmations.pop(entity_id, None)
    return record


def pending_review(binding: BindingAST) -> list[EntityBinding]:
    """Entities a human still needs to act on (proposed or unresolved)."""
    return [eb for eb in binding.entityBindings if eb.status in _PENDING_STATUSES]


# ─────────────────────────────────────────────────────────────────────────────
# High-level orchestration
# ─────────────────────────────────────────────────────────────────────────────


def open_review(
    binding: BindingAST,
    dataset: DatasetAST,
    *,
    storage_dir: str | os.PathLike[str] | None = None,
) -> tuple[BindingAST, ReviewRecord, list[EntityBinding]]:
    """Begin (or resume) a review for this binding+dataset.

    Stamps the dataset signature, loads any cached decisions, re-applies them, and
    returns ``(binding, record, deltas)`` where *deltas* are the entities still
    needing human attention. A fresh dataset shape yields all entities as deltas.
    """
    signature = dataset_signature(dataset)
    binding.datasetSignature = signature

    record = load_record(binding.templateId, signature, storage_dir=storage_dir)
    if record is None:
        record = ReviewRecord(
            templateId=binding.templateId,
            datasetSignature=signature,
            datasetId=binding.datasetId,
            proposals=[eb.to_dict() for eb in binding.entityBindings],
        )
    else:
        apply_confirmations(binding, record)
        logger.info(
            "[review] resumed cache %s__%s (%d prior confirmations)",
            binding.templateId, signature, len(record.confirmations),
        )

    deltas = pending_review(binding)
    return binding, record, deltas


def finalize_review(
    binding: BindingAST,
    record: ReviewRecord,
    *,
    accept_proposed: bool = False,
    storage_dir: str | os.PathLike[str] | None = None,
) -> tuple[BindingAST, Path]:
    """Apply decisions, optionally headless-accept, persist, return ``(binding, path)``."""
    if accept_proposed:
        accept_all_proposed(binding, record)
    else:
        apply_confirmations(binding, record)
    record.datasetId = binding.datasetId or record.datasetId
    path = save_record(record, storage_dir=storage_dir)
    logger.info(
        "[review] finalized %s (%d confirmed, %d pending) → %s",
        binding.templateId,
        sum(1 for e in binding.entityBindings if e.status in ("confirmed", "overridden")),
        len(pending_review(binding)),
        path.name,
    )
    return binding, path
