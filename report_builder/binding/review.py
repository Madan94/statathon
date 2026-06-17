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
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from report_builder.binding.schema import BindingAST, BoundColumn, DatasetAST, EntityBinding

logger = logging.getLogger(__name__)

_PENDING_STATUSES = ("proposed", "unresolved")
_DEFAULT_STORE = Path(__file__).resolve().parents[2] / "storage" / "bindings"


class ColumnOwnershipConflict(ValueError):
    """Raised when an exclusive column assignment would duplicate ownership."""

    def __init__(self, conflicts: list[dict[str, Any]]):
        self.conflicts = conflicts
        super().__init__("column is already assigned to another exclusive entity")


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
            sharePolicy=str(d.get("sharePolicy") or "exclusive"),
            shareReason=str(d.get("shareReason") or ""),
        )


@dataclass
class ColumnDecision:
    """One officer decision about a dataset column's binder usage."""

    column: str
    status: str                      # matched | added_as_entity | ignored_metadata | ignored_duplicate | ignored_out_of_scope | needs_question
    entityId: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"column": self.column, "status": self.status}
        if self.entityId:
            out["entityId"] = self.entityId
        if self.note:
            out["note"] = self.note
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ColumnDecision":
        return cls(
            column=str(d.get("column") or ""),
            status=str(d.get("status") or "needs_question"),
            entityId=str(d.get("entityId") or d.get("entity_id") or ""),
            note=str(d.get("note") or ""),
        )


@dataclass
class ReviewRecord:
    """Persisted review state for one ``(templateId, signature)`` pair."""

    templateId: str
    datasetSignature: str
    datasetId: str = ""
    proposals: list[dict[str, Any]] = field(default_factory=list)  # snapshot of S1
    confirmations: dict[str, Confirmation] = field(default_factory=dict)  # entityId → decision
    columnDecisions: dict[str, "ColumnDecision"] = field(default_factory=dict)  # column → decision
    updatedAt: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "templateId": self.templateId,
            "datasetSignature": self.datasetSignature,
            "datasetId": self.datasetId,
            "proposals": list(self.proposals),
            "confirmations": {k: v.to_dict() for k, v in self.confirmations.items()},
            "columnDecisions": {k: v.to_dict() for k, v in self.columnDecisions.items()},
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
            columnDecisions={
                k: ColumnDecision.from_dict(v)
                for k, v in (d.get("columnDecisions") or d.get("column_decisions") or {}).items()
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


def _proposal_by_entity(record: ReviewRecord) -> dict[str, dict[str, Any]]:
    return {str(p.get("entityId") or ""): p for p in record.proposals if p.get("entityId")}


_COLUMN_DECISION_STATUSES = {
    "matched",
    "added_as_entity",
    "ignored_metadata",
    "ignored_duplicate",
    "ignored_out_of_scope",
    "needs_question",
}


def set_column_decision(
    record: ReviewRecord,
    *,
    column: str,
    status: str,
    entity_id: str = "",
    note: str = "",
) -> ReviewRecord:
    """Persist an officer decision for one dataset column."""
    clean_column = column.strip()
    if not clean_column:
        raise ValueError("column is required")
    clean_status = status.strip()
    if clean_status not in _COLUMN_DECISION_STATUSES:
        raise ValueError(f"unsupported column decision status '{status}'")
    if clean_status in {"matched", "added_as_entity"} and not entity_id.strip():
        raise ValueError(f"{clean_status} column decisions require entity_id")
    record.columnDecisions[clean_column] = ColumnDecision(
        column=clean_column,
        status=clean_status,
        entityId=entity_id.strip(),
        note=note.strip(),
    )
    return record


def mark_columns_matched(
    record: ReviewRecord,
    *,
    columns: list[str],
    entity_id: str,
    status: str = "matched",
    note: str = "",
) -> ReviewRecord:
    """Bulk-record a column→entity match decision (used when confirming an entity)."""
    for column in columns:
        if column:
            set_column_decision(record, column=column, status=status, entity_id=entity_id, note=note)
    return record


def _proposal_columns(prop: dict[str, Any] | None) -> list[str]:
    if not prop:
        return []
    cols: list[str] = []
    for c in prop.get("columns") or []:
        if isinstance(c, dict):
            name = str(c.get("column") or "")
        else:
            name = str(c or "")
        if name:
            cols.append(name)
    return cols


def _default_share_policy(prop: dict[str, Any] | None) -> str:
    """Recommended policy before an officer explicitly decides.

    Measures and one-to-one entities are exclusive by default; context-like
    dimensions/time/filter/metadata can be shared intentionally.
    """
    if not prop:
        return "exclusive"
    entity_type = str(prop.get("entityType") or "dimension")
    cardinality = str(prop.get("cardinality") or "oneToOne")
    if entity_type in ("time", "filter", "metadata"):
        return "shared"
    if entity_type == "dimension" and cardinality != "oneToOne":
        return "shared"
    return "exclusive"


def _effective_columns(record: ReviewRecord, entity_id: str) -> list[str]:
    decision = record.confirmations.get(entity_id)
    if decision and decision.status == "rejected":
        return []
    if decision and decision.columns is not None:
        return [c for c in decision.columns if c]
    return _proposal_columns(_proposal_by_entity(record).get(entity_id))


def _owner_status(record: ReviewRecord, entity_id: str, prop: dict[str, Any] | None) -> str:
    decision = record.confirmations.get(entity_id)
    if decision:
        return decision.status
    return str((prop or {}).get("status") or "proposed")


def _owner_share_policy(record: ReviewRecord, entity_id: str, prop: dict[str, Any] | None) -> str:
    decision = record.confirmations.get(entity_id)
    if decision:
        return decision.sharePolicy or "exclusive"
    return _default_share_policy(prop)


def compute_column_ownership(record: ReviewRecord) -> dict[str, Any]:
    """Build column -> owner map plus duplicate/conflict diagnostics.

    This is computed from the review record so there is no second source of truth.
    Confirmed/overridden exclusive owners lock a column; proposed ownership remains
    visible but not locked.
    """
    proposals = _proposal_by_entity(record)
    columns: dict[str, dict[str, Any]] = {}

    for entity_id, prop in proposals.items():
        status = _owner_status(record, entity_id, prop)
        if status == "rejected":
            continue
        share_policy = _owner_share_policy(record, entity_id, prop)
        for column in _effective_columns(record, entity_id):
            entry = columns.setdefault(column, {"column": column, "owners": [], "locked": False})
            owner = {
                "entityId": entity_id,
                "entityName": str(prop.get("entityName") or prop.get("canonicalName") or entity_id),
                "entityType": str(prop.get("entityType") or "dimension"),
                "cardinality": str(prop.get("cardinality") or "oneToOne"),
                "status": status,
                "sharePolicy": share_policy,
            }
            decision = record.confirmations.get(entity_id)
            if decision and decision.shareReason:
                owner["shareReason"] = decision.shareReason
            entry["owners"].append(owner)

    conflicts: list[dict[str, Any]] = []
    for column, entry in columns.items():
        confirmed = [
            o for o in entry["owners"]
            if o["status"] in ("confirmed", "overridden")
        ]
        exclusive_confirmed = [o for o in confirmed if o.get("sharePolicy") != "shared"]
        entry["locked"] = bool(exclusive_confirmed)
        if len(exclusive_confirmed) > 1:
            conflicts.append({
                "column": column,
                "severity": "error",
                "code": "DUPLICATE_EXCLUSIVE_COLUMN",
                "owners": exclusive_confirmed,
                "message": f"Column '{column}' is assigned exclusively to multiple entities.",
            })
        elif exclusive_confirmed and len(confirmed) > 1:
            shared_without_policy = [o for o in confirmed if o.get("sharePolicy") != "shared"]
            if len(shared_without_policy) > 1:
                conflicts.append({
                    "column": column,
                    "severity": "error",
                    "code": "COLUMN_SHARE_NOT_APPROVED",
                    "owners": confirmed,
                    "message": f"Column '{column}' is reused without an approved share policy.",
                })

    return {"columns": columns, "conflicts": conflicts}


def find_exclusive_column_conflicts(
    record: ReviewRecord,
    entity_id: str,
    columns: list[str],
) -> list[dict[str, Any]]:
    ownership = compute_column_ownership(record)
    conflicts: list[dict[str, Any]] = []
    for column in columns:
        entry = (ownership.get("columns") or {}).get(column)
        if not entry:
            continue
        owners = [
            o for o in (entry.get("owners") or [])
            if o.get("entityId") != entity_id
            and o.get("status") in ("confirmed", "overridden")
            and o.get("sharePolicy") != "shared"
        ]
        if owners:
            conflicts.append({
                "column": column,
                "owners": owners,
                "code": "COLUMN_ALREADY_OWNED",
                "message": f"Column '{column}' is already assigned to another exclusive entity.",
            })
    return conflicts


def move_columns_from_entities(
    record: ReviewRecord,
    *,
    columns: list[str],
    from_entity_ids: list[str],
    note: str = "",
) -> ReviewRecord:
    """Remove selected columns from previous owners and reopen empty entities."""
    column_set = set(columns)
    for from_entity_id in from_entity_ids:
        if not from_entity_id:
            continue
        current = _effective_columns(record, from_entity_id)
        remaining = [c for c in current if c not in column_set]
        reopen_note = note or "column moved to another entity"
        if remaining:
            record.confirmations[from_entity_id] = Confirmation(
                entityId=from_entity_id,
                status="overridden",
                columns=remaining,
                note=reopen_note,
            )
        else:
            record.confirmations.pop(from_entity_id, None)
    return record


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
    selected_columns = columns if columns is not None else _effective_columns(record, entity_id)
    conflicts = find_exclusive_column_conflicts(record, entity_id, selected_columns)
    if conflicts and share_policy != "shared":
        raise ColumnOwnershipConflict(conflicts)
    status = "overridden" if columns else "confirmed"
    record.confirmations[entity_id] = Confirmation(
        entityId=entity_id,
        status=status,
        columns=columns,
        note=note,
        sharePolicy=share_policy,
        shareReason=share_reason,
    )
    return record


def reject(record: ReviewRecord, entity_id: str, *, note: str = "") -> ReviewRecord:
    record.confirmations[entity_id] = Confirmation(
        entityId=entity_id, status="rejected", note=note
    )
    return record


def reopen(record: ReviewRecord, entity_id: str) -> ReviewRecord:
    """Remove a saved decision so the entity returns to proposed/unresolved review."""
    record.confirmations.pop(entity_id, None)
    return record


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")
    return slug or "entity"


def add_manual_entity(
    record: ReviewRecord,
    *,
    entity_name: str,
    entity_type: str,
    columns: list[str],
    cardinality: str = "oneToOne",
    note: str = "",
    share_policy: str = "exclusive",
    share_reason: str = "",
) -> ReviewRecord:
    """Add a column-first officer-created entity to the review record.

    The new entity is represented as a normal S1 proposal plus a manual S2
    confirmation, so finalize/question binding continues to use the existing path.
    """
    clean_columns = [c for c in columns if c]
    base_id = f"ent_manual_{_slug(entity_name)}"
    entity_id = base_id
    existing_ids = {str(p.get("entityId") or "") for p in record.proposals}
    suffix = 2
    while entity_id in existing_ids:
        entity_id = f"{base_id}_{suffix}"
        suffix += 1

    conflicts = find_exclusive_column_conflicts(record, entity_id, clean_columns)
    if conflicts and share_policy != "shared":
        raise ColumnOwnershipConflict(conflicts)

    prop = {
        "entityId": entity_id,
        "entityName": entity_name,
        "entityType": entity_type,
        "cardinality": cardinality,
        "columns": [{"column": c} for c in clean_columns],
        "combine": "none",
        "confidence": 1.0,
        "method": "manual",
        "status": "proposed",
        "alternatives": [],
        "notes": [note or "officer-created entity from dataset column"],
        "evidence": [{"signal": "manual_entity", "score": 1.0, "detail": "created by officer in binder"}],
    }
    record.proposals.append(prop)
    confirm(
        record,
        entity_id,
        columns=clean_columns,
        note=note or "officer-created entity from dataset column",
        share_policy=share_policy,
        share_reason=share_reason,
    )
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
