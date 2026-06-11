"""R6 — officer report lifecycle: publish status, block locks, version restore.

Generation (S4–S6) produces a *trusted, gated* report; this layer adds the human
**control** an official MoSPI workflow needs on top of it:

    draft → generated → reviewed → edited → locked → published → archived

The report's lifecycle state lives on ``metadata.publishStatus`` (+ ``publishedAt`` /
``publishedBy``); a transition log is appended to ``auditAST.humanReview.lifecycle[]``,
alongside the existing edit trail (``auditAST.humanReview.edits[]`` from ``edit.py``).
Individual content blocks carry a ``locked`` flag so an officer can freeze a reviewed
paragraph while still editing the rest.

Guard-rails (do not weaken):
  * ``published`` is reachable **only** through :func:`mark_published`, which enforces
    the verifier publish gate (``auditAST.publishable``) — the generic
    :func:`set_publish_status` refuses a direct hop to ``published``.
  * a locked block, or a report in a non-editable state (``locked`` / ``published`` /
    ``archived``), rejects edits via :func:`assert_editable`.
  * ``archived`` is terminal except through :func:`restore_version`, which re-opens an
    earlier version as a new, editable version (forward-only versioning).

Everything is deterministic and offline; these are pure state mutations on the report
dict, never value computations.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

# Lifecycle states, in nominal order.
LIFECYCLE_STATUSES = (
    "draft", "generated", "reviewed", "edited", "locked", "published", "archived",
)
DEFAULT_STATUS = "generated"

# States in which no block may be edited.
_NON_EDITABLE = {"locked", "published", "archived"}

# Allowed transitions for the generic setter. ``published`` is intentionally NOT a
# target here — it is reachable only via mark_published (which enforces the gate).
_TRANSITIONS: dict[str, set[str]] = {
    "draft":     {"generated", "archived"},
    "generated": {"reviewed", "edited", "archived"},
    "reviewed":  {"edited", "locked", "archived"},
    "edited":    {"reviewed", "locked", "archived"},
    "locked":    {"reviewed", "edited", "archived"},   # unlock ⇒ back to reviewed/edited
    "published": {"archived"},
    "archived":  set(),                                 # only re-opened via restore_version
}

# Statuses from which an officer may publish (policy: must be reviewed-or-locked).
_PUBLISHABLE_FROM = {"reviewed", "edited", "locked"}


class LifecycleError(ValueError):
    """Raised on an invalid lifecycle transition, a locked-edit, or a failed publish."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────────────────────────────────────


def ensure_lifecycle(report: dict[str, Any]) -> dict[str, Any]:
    """Ensure the report carries lifecycle defaults (in place); return it.

    A freshly generated report starts at ``publishStatus="generated"`` with
    ``version=1`` and an empty lifecycle log. Idempotent — existing values are kept.
    """
    meta = report.setdefault("metadata", {})
    meta.setdefault("publishStatus", DEFAULT_STATUS)
    meta.setdefault("version", 1)
    human = report.setdefault("auditAST", {}).setdefault("humanReview", {})
    human.setdefault("lifecycle", [])
    human.setdefault("edits", [])
    return report


def get_status(report: dict[str, Any]) -> str:
    return str((report.get("metadata") or {}).get("publishStatus") or DEFAULT_STATUS)


def _log(report: dict[str, Any], entry: dict[str, Any]) -> None:
    report.setdefault("auditAST", {}).setdefault("humanReview", {}) \
        .setdefault("lifecycle", []).append(entry)


# ─────────────────────────────────────────────────────────────────────────────
# Status transitions
# ─────────────────────────────────────────────────────────────────────────────


def _transition(report: dict[str, Any], to: str, *, user: str, note: str,
                action: str = "status") -> dict[str, Any]:
    """Apply a validated transition (internal — allows ``published`` for mark_published)."""
    ensure_lifecycle(report)
    cur = get_status(report)
    if to not in LIFECYCLE_STATUSES:
        raise LifecycleError(f"unknown publishStatus {to!r}")
    if to == cur:
        return report  # idempotent no-op
    allowed = _TRANSITIONS.get(cur, set()) | ({"published"} if to == "published"
                                              and cur in _PUBLISHABLE_FROM else set())
    if to not in allowed:
        raise LifecycleError(
            f"invalid transition {cur!r} → {to!r} "
            f"(allowed: {sorted(_TRANSITIONS.get(cur, set())) or 'none'})"
        )
    report["metadata"]["publishStatus"] = to
    _log(report, {"action": action, "from": cur, "to": to, "by": user, "at": _now(),
                  "note": note})
    return report


def set_publish_status(report: dict[str, Any], status: str, *, user: str = "",
                       note: str = "") -> dict[str, Any]:
    """Transition the report to ``status`` (in place); return it.

    Validates the transition against the lifecycle graph. Refuses a direct hop to
    ``published`` — use :func:`mark_published`, which enforces the verifier gate.
    """
    status = (status or "").strip().lower()
    if status == "published":
        raise LifecycleError("use mark_published() to publish — it enforces the verifier gate")
    return _transition(report, status, user=user, note=note)


def mark_reviewed(report: dict[str, Any], *, user: str = "", note: str = "") -> dict[str, Any]:
    """Convenience: mark the report reviewed."""
    return set_publish_status(report, "reviewed", user=user, note=note)


def mark_published(report: dict[str, Any], *, user: str = "",
                   require_publishable: bool = True) -> dict[str, Any]:
    """Publish the report (in place) — gated by the verifier verdict.

    Requires a publishable report (``auditAST.publishable is True``) unless
    ``require_publishable=False`` is passed for an explicit, audited override. Sets
    ``publishStatus=published`` + ``publishedAt`` (+ ``publishedBy`` when ``user`` set).
    """
    ensure_lifecycle(report)
    cur = get_status(report)
    if cur not in _PUBLISHABLE_FROM:
        raise LifecycleError(
            f"cannot publish from {cur!r} — review/lock the report first "
            f"(publishable from {sorted(_PUBLISHABLE_FROM)})"
        )
    publishable = bool((report.get("auditAST") or {}).get("publishable", True))
    if require_publishable and not publishable:
        gate = (report.get("auditAST") or {}).get("gate") or {}
        failed = gate.get("failedChecks") or []
        raise LifecycleError(
            "report is not publishable (verifier gate) — "
            f"failed checks: {', '.join(failed) or 'see auditAST.verification'}"
        )
    _transition(report, "published", user=user, note="", action="publish")
    meta = report["metadata"]
    meta["publishedAt"] = _now()
    if user:
        meta["publishedBy"] = user
    if not require_publishable and not publishable:
        # Record that this was an explicit override of a non-publishable report.
        _log(report, {"action": "publish_override", "by": user, "at": _now(),
                      "note": "published despite non-publishable verifier gate"})
    return report


def archive(report: dict[str, Any], *, user: str = "", note: str = "") -> dict[str, Any]:
    """Archive the report (in place). Terminal except via :func:`restore_version`."""
    return _transition(report, "archived", user=user, note=note, action="archive")


# ─────────────────────────────────────────────────────────────────────────────
# Block locks
# ─────────────────────────────────────────────────────────────────────────────


def _find_block(report: dict[str, Any], block_id: str) -> dict[str, Any] | None:
    for b in (report.get("contentAST") or {}).get("blocks", []):
        if b.get("blockId") == block_id:
            return b
    return None


def lock_block(report: dict[str, Any], block_id: str, *, user: str = "",
               note: str = "") -> dict[str, Any]:
    """Lock one content block so it rejects edits (in place); return the report."""
    ensure_lifecycle(report)
    block = _find_block(report, block_id)
    if block is None:
        raise LifecycleError(f"block not found: {block_id!r}")
    block["locked"] = True
    _log(report, {"action": "lock_block", "blockId": block_id, "by": user,
                  "at": _now(), "note": note})
    return report


def unlock_block(report: dict[str, Any], block_id: str, *, user: str = "",
                 note: str = "") -> dict[str, Any]:
    """Unlock one content block so it may be edited again (in place); return the report."""
    ensure_lifecycle(report)
    block = _find_block(report, block_id)
    if block is None:
        raise LifecycleError(f"block not found: {block_id!r}")
    block["locked"] = False
    _log(report, {"action": "unlock_block", "blockId": block_id, "by": user,
                  "at": _now(), "note": note})
    return report


def is_block_locked(report: dict[str, Any], block_id: str) -> bool:
    block = _find_block(report, block_id)
    return bool(block and block.get("locked"))


def assert_editable(report: dict[str, Any], block_id: str | None = None) -> None:
    """Raise :class:`LifecycleError` if the report (or the given block) is not editable.

    A report in ``locked`` / ``published`` / ``archived`` state rejects all edits; a
    block with ``locked=True`` rejects edits even when the report is otherwise open.
    """
    status = get_status(report)
    if status in _NON_EDITABLE:
        raise LifecycleError(f"report is {status!r} — not editable (unlock/restore first)")
    if block_id is not None and is_block_locked(report, block_id):
        raise LifecycleError(f"block {block_id!r} is locked — unlock it before editing")


# ─────────────────────────────────────────────────────────────────────────────
# Version restore
# ─────────────────────────────────────────────────────────────────────────────


def _version_of(report: dict[str, Any]) -> int:
    return int((report.get("metadata") or {}).get("version") or 1)


def restore_version(
    current_report: dict[str, Any],
    history: list[dict[str, Any]],
    version: str | int,
    *,
    user: str = "",
) -> dict[str, Any]:
    """Re-open a previous version as a new, editable version (forward-only).

    Finds the report in ``history`` whose ``metadata.version`` matches ``version``,
    returns a deep copy of it stamped with a *new* version (current max + 1) and
    ``publishStatus="edited"``, preserving the running edit/lifecycle audit trail and
    appending a ``restore`` entry. Never mutates ``current_report`` or ``history``.
    """
    try:
        want = int(version)
    except (TypeError, ValueError) as exc:
        raise LifecycleError(f"invalid version {version!r}") from exc

    source = next((h for h in history if _version_of(h) == want), None)
    if source is None:
        raise LifecycleError(f"version {want} not found in history")

    restored = copy.deepcopy(source)
    new_version = max([_version_of(current_report), *[_version_of(h) for h in history]]) + 1
    ensure_lifecycle(restored)
    restored["metadata"]["version"] = new_version
    restored["metadata"]["publishStatus"] = "edited"
    # Carry the running audit trail forward so history stays continuous.
    cur_human = (current_report.get("auditAST") or {}).get("humanReview") or {}
    human = restored["auditAST"]["humanReview"]
    human["edits"] = list(cur_human.get("edits") or human.get("edits") or [])
    human["lifecycle"] = list(cur_human.get("lifecycle") or [])
    _log(restored, {"action": "restore", "fromVersion": want, "toVersion": new_version,
                    "by": user, "at": _now(),
                    "note": f"restored content of v{want} as v{new_version}"})
    return restored
