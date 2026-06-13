"""Tests for Phase 9 officer report lifecycle (`lifecycle`).

Covers the control layer on top of a generated/verified report: lifecycle defaults,
status transitions (valid + rejected), per-block locks gating edits, the publish gate
integration (publishable required), version restore, and the archived terminal state.
"""
from __future__ import annotations

import copy

import pytest

from report_builder.generation.edit import apply_edit, bump_version, current_version
from report_builder.generation.lifecycle import (
    LifecycleError,
    archive,
    assert_editable,
    ensure_lifecycle,
    get_status,
    is_block_locked,
    lock_block,
    mark_published,
    mark_reviewed,
    restore_version,
    set_publish_status,
    unlock_block,
)


# ─────────────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────────────

def _report(*, publishable: bool = True, version: int = 1) -> dict:
    return {
        "$schema": "bharatstat/report-output-ast/v1",
        "metadata": {"reportId": "rpt_x", "version": version},
        "analyticsAST": {
            "aggregations": [{"aggId": "agg_q1", "questionId": "q1", "measure": "sal",
                              "rows": [{"key": {"sector": "Urban"}, "value": 69000.0,
                                        "n": 2, "rowIds": ["r:sector=Urban"]}]}],
            "rankings": [], "trends": [], "metrics": [],
        },
        "contentAST": {"blocks": [
            {"blockId": "p_q1", "kind": "paragraph", "content": "Urban salary was 69000.0.",
             "slot": {"status": "filled"},
             "provenance": {"questionId": "q1", "analyticsRef": "agg_q1"}},
            {"blockId": "p_q2", "kind": "paragraph", "content": "Some prose.",
             "slot": {"status": "filled"}, "provenance": {"questionId": "q1"}}]},
        "auditAST": {"publishable": publishable,
                     "gate": {"publishable": publishable, "blocked": not publishable,
                              "failedChecks": [] if publishable else ["CONTENT_HASH"]}},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────────────────────────────────────

def test_generated_report_gets_lifecycle_defaults():
    rep = _report()
    rep["metadata"].pop("version", None)
    ensure_lifecycle(rep)
    assert rep["metadata"]["publishStatus"] == "generated"
    assert rep["metadata"]["version"] == 1
    assert rep["auditAST"]["humanReview"]["lifecycle"] == []
    assert rep["auditAST"]["humanReview"]["edits"] == []


def test_ensure_lifecycle_idempotent():
    rep = _report()
    ensure_lifecycle(rep)
    rep["metadata"]["publishStatus"] = "reviewed"
    ensure_lifecycle(rep)
    assert rep["metadata"]["publishStatus"] == "reviewed"   # not reset


# ─────────────────────────────────────────────────────────────────────────────
# Block locks gate edits
# ─────────────────────────────────────────────────────────────────────────────

def test_lock_block_prevents_edit():
    rep = ensure_lifecycle(_report())
    lock_block(rep, "p_q1", user="officer1", note="reviewed wording")
    assert is_block_locked(rep, "p_q1")
    with pytest.raises(LifecycleError):
        assert_editable(rep, "p_q1")
    # a different, unlocked block is still editable
    assert_editable(rep, "p_q2")


def test_unlock_block_allows_edit():
    rep = ensure_lifecycle(_report())
    lock_block(rep, "p_q1")
    unlock_block(rep, "p_q1", user="officer1")
    assert not is_block_locked(rep, "p_q1")
    assert_editable(rep, "p_q1")   # no raise


def test_lock_unknown_block_raises():
    rep = ensure_lifecycle(_report())
    with pytest.raises(LifecycleError):
        lock_block(rep, "nope")


def test_lock_records_lifecycle_audit():
    rep = ensure_lifecycle(_report())
    lock_block(rep, "p_q1", user="officer1", note="freeze")
    log = rep["auditAST"]["humanReview"]["lifecycle"]
    assert log and log[-1]["action"] == "lock_block"
    assert log[-1]["blockId"] == "p_q1" and log[-1]["by"] == "officer1"


# ─────────────────────────────────────────────────────────────────────────────
# Edit bumps version, audit trail intact, respects locks
# ─────────────────────────────────────────────────────────────────────────────

def test_edit_unlocked_block_bumps_version_and_audits():
    rep = ensure_lifecycle(_report())
    assert_editable(rep, "p_q1")
    edited, entry = apply_edit(rep, {"target": {"kind": "block", "id": "p_q1"},
                                     "value": "Urban salary was 69000.0 this period.",
                                     "by": "officer1"})
    edited = bump_version(edited, current_version(edited) + 1)
    assert edited["metadata"]["version"] == 2
    assert edited["auditAST"]["humanReview"]["edits"][-1] == entry


def test_locked_block_blocks_edit_flow():
    rep = ensure_lifecycle(_report())
    lock_block(rep, "p_q1")
    with pytest.raises(LifecycleError):
        assert_editable(rep, "p_q1")   # the officer flow checks this before apply_edit


# ─────────────────────────────────────────────────────────────────────────────
# Status transitions
# ─────────────────────────────────────────────────────────────────────────────

def test_status_transition_generated_reviewed_locked_published():
    rep = ensure_lifecycle(_report(publishable=True))
    assert get_status(rep) == "generated"
    set_publish_status(rep, "reviewed", user="o1")
    assert get_status(rep) == "reviewed"
    set_publish_status(rep, "locked", user="o1")
    assert get_status(rep) == "locked"
    mark_published(rep, user="o1")
    assert get_status(rep) == "published"
    assert rep["metadata"]["publishedBy"] == "o1"
    assert rep["metadata"]["publishedAt"]


def test_invalid_transition_rejected():
    rep = ensure_lifecycle(_report())
    # generated → locked is not allowed (must be reviewed/edited first)
    with pytest.raises(LifecycleError):
        set_publish_status(rep, "locked", user="o1")


def test_set_publish_status_refuses_direct_published():
    rep = ensure_lifecycle(_report())
    set_publish_status(rep, "reviewed")
    with pytest.raises(LifecycleError):
        set_publish_status(rep, "published")   # must use mark_published


def test_transition_log_records_from_to():
    rep = ensure_lifecycle(_report())
    set_publish_status(rep, "reviewed", user="o1", note="looks good")
    entry = rep["auditAST"]["humanReview"]["lifecycle"][-1]
    assert entry["from"] == "generated" and entry["to"] == "reviewed"
    assert entry["by"] == "o1" and entry["note"] == "looks good"


# ─────────────────────────────────────────────────────────────────────────────
# Publish gate integration
# ─────────────────────────────────────────────────────────────────────────────

def test_publish_blocked_when_not_publishable():
    rep = ensure_lifecycle(_report(publishable=False))
    mark_reviewed(rep, user="o1")
    with pytest.raises(LifecycleError) as exc:
        mark_published(rep, user="o1")
    assert "publishable" in str(exc.value).lower() or "CONTENT_HASH" in str(exc.value)
    assert get_status(rep) == "reviewed"   # unchanged


def test_publish_allowed_when_publishable():
    rep = ensure_lifecycle(_report(publishable=True))
    mark_reviewed(rep, user="o1")
    mark_published(rep, user="o1")
    assert get_status(rep) == "published"


def test_publish_override_allows_non_publishable_with_flag():
    rep = ensure_lifecycle(_report(publishable=False))
    mark_reviewed(rep, user="admin")
    mark_published(rep, user="admin", require_publishable=False)
    assert get_status(rep) == "published"
    actions = [e.get("action") for e in rep["auditAST"]["humanReview"]["lifecycle"]]
    assert "publish_override" in actions


def test_cannot_publish_directly_from_generated():
    rep = ensure_lifecycle(_report(publishable=True))
    with pytest.raises(LifecycleError):
        mark_published(rep, user="o1")        # must review/lock first


# ─────────────────────────────────────────────────────────────────────────────
# Restore
# ─────────────────────────────────────────────────────────────────────────────

def test_restore_previous_version_works_and_audits():
    v1 = ensure_lifecycle(_report(version=1))
    v1["contentAST"]["blocks"][0]["content"] = "ORIGINAL v1 text."
    # current is v3 with different content
    current = copy.deepcopy(v1)
    current["metadata"]["version"] = 3
    current["contentAST"]["blocks"][0]["content"] = "v3 text."

    restored = restore_version(current, [v1], 1, user="o1")
    assert restored["metadata"]["version"] == 4          # forward-only (max+1)
    assert restored["contentAST"]["blocks"][0]["content"] == "ORIGINAL v1 text."
    assert restored["metadata"]["publishStatus"] == "edited"
    log = restored["auditAST"]["humanReview"]["lifecycle"]
    assert any(e.get("action") == "restore" and e.get("fromVersion") == 1 for e in log)
    # inputs not mutated
    assert current["metadata"]["version"] == 3


def test_restore_missing_version_raises():
    current = ensure_lifecycle(_report(version=2))
    with pytest.raises(LifecycleError):
        restore_version(current, [], 1, user="o1")


# ─────────────────────────────────────────────────────────────────────────────
# Archived terminal state
# ─────────────────────────────────────────────────────────────────────────────

def test_archived_report_rejects_edits():
    rep = ensure_lifecycle(_report())
    mark_reviewed(rep, user="o1")
    archive(rep, user="o1")
    assert get_status(rep) == "archived"
    with pytest.raises(LifecycleError):
        assert_editable(rep, "p_q1")
    # and no normal transition leaves archived
    with pytest.raises(LifecycleError):
        set_publish_status(rep, "reviewed")


def test_archived_reopened_via_restore():
    archived = ensure_lifecycle(_report(version=2))
    archived["metadata"]["publishStatus"] = "archived"
    restored = restore_version(archived, [archived], 2, user="o1")
    assert restored["metadata"]["publishStatus"] == "edited"
    assert_editable(restored, "p_q1")   # editable again
