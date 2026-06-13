"""Unit tests for generation run modes + data content hashing (`run_modes`).

These cover the reproducibility primitives in isolation (the API integration of
fresh/frozen/test lives in `test_generate_phase_bundle.py`):
- the content hash is deterministic, value-sensitive, and order-sensitive;
- mode resolution honors request > env > default;
- drift verification raises only on a real mismatch against a *pinned* hash;
- the freeze addressing key is unchanged (contentHash lives in dataframeRef, not the key).
"""
from __future__ import annotations

import pandas as pd
import pytest

from report_builder.binding.execution_contracts import ExecutionBundle
from report_builder.generation.run_modes import (
    DEFAULT_MODE,
    DataDriftError,
    attach_data_hash,
    bundle_data_hash,
    compute_data_content_hash,
    resolve_mode,
    verify_data_hash,
)


# ─────────────────────────────────────────────────────────────────────────────
# compute_data_content_hash
# ─────────────────────────────────────────────────────────────────────────────

class TestContentHash:
    def test_deterministic_same_frame(self):
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        assert compute_data_content_hash(df) == compute_data_content_hash(df.copy())

    def test_prefix_and_shape(self):
        h = compute_data_content_hash(pd.DataFrame({"a": [1]}))
        assert h.startswith("sha256:")
        assert len(h.split(":", 1)[1]) == 32

    def test_value_change_changes_hash(self):
        a = pd.DataFrame({"v": [1, 2, 3]})
        b = pd.DataFrame({"v": [1, 2, 4]})        # one value differs
        assert compute_data_content_hash(a) != compute_data_content_hash(b)

    def test_row_order_changes_hash(self):
        a = pd.DataFrame({"v": [1, 2, 3]})
        b = pd.DataFrame({"v": [3, 2, 1]})        # same values, different order
        assert compute_data_content_hash(a) != compute_data_content_hash(b)

    def test_same_shape_different_data_differs(self):
        # The signature-blind case: identical columns/dtypes, different values.
        a = pd.DataFrame({"state": ["A", "B"], "n": [10, 20]})
        b = pd.DataFrame({"state": ["A", "B"], "n": [11, 21]})
        assert compute_data_content_hash(a) != compute_data_content_hash(b)

    def test_empty_frame_is_stable(self):
        assert compute_data_content_hash(pd.DataFrame()) == compute_data_content_hash(None)


# ─────────────────────────────────────────────────────────────────────────────
# resolve_mode
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveMode:
    def test_default_is_fresh(self, monkeypatch):
        monkeypatch.delenv("GENERATION_MODE", raising=False)
        assert resolve_mode(None) == "fresh" == DEFAULT_MODE

    def test_request_wins(self, monkeypatch):
        monkeypatch.setenv("GENERATION_MODE", "frozen")
        assert resolve_mode("test") == "test"        # request overrides env

    def test_env_used_when_no_request(self, monkeypatch):
        monkeypatch.setenv("GENERATION_MODE", "frozen")
        assert resolve_mode(None) == "frozen"

    def test_unknown_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("GENERATION_MODE", raising=False)
        assert resolve_mode("banana") == "fresh"

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.delenv("GENERATION_MODE", raising=False)
        assert resolve_mode("FROZEN") == "frozen"


# ─────────────────────────────────────────────────────────────────────────────
# pin + read + drift
# ─────────────────────────────────────────────────────────────────────────────

class TestDrift:
    def _bundle(self, data_hash: str = "") -> ExecutionBundle:
        b = ExecutionBundle(templateId="t", datasetId="d", status="READY")
        if data_hash:
            attach_data_hash(b, data_hash)
        return b

    def test_attach_and_read_back(self):
        b = self._bundle()
        attach_data_hash(b, "sha256:abc")
        assert bundle_data_hash(b) == "sha256:abc"
        assert b.dataframeRef["contentHash"] == "sha256:abc"

    def test_unpinned_bundle_has_empty_hash(self):
        assert bundle_data_hash(self._bundle()) == ""

    def test_verify_matches(self):
        df = pd.DataFrame({"v": [1, 2]})
        b = self._bundle(compute_data_content_hash(df))
        # same data → no raise, returns the current hash
        assert verify_data_hash(b, df) == compute_data_content_hash(df)

    def test_verify_drift_raises(self):
        df = pd.DataFrame({"v": [1, 2]})
        b = self._bundle(compute_data_content_hash(df))
        drifted = pd.DataFrame({"v": [9, 9]})
        with pytest.raises(DataDriftError) as exc:
            verify_data_hash(b, drifted)
        assert exc.value.expected == bundle_data_hash(b)
        assert exc.value.actual == compute_data_content_hash(drifted)

    def test_verify_unpinned_is_accepted(self):
        # A bundle with no pinned hash has nothing to drift against; returns current.
        df = pd.DataFrame({"v": [1, 2]})
        b = self._bundle()                      # unpinned
        assert verify_data_hash(b, df) == compute_data_content_hash(df)


# ─────────────────────────────────────────────────────────────────────────────
# freeze addressing key is unchanged (contentHash is a value, not the key)
# ─────────────────────────────────────────────────────────────────────────────

def test_freeze_key_unaffected_by_content_hash(tmp_path, monkeypatch):
    """Pinning a data hash must not change the (templateId, datasetSignature) address."""
    from report_builder.binding import freeze_store
    from report_builder.binding.schema import BindingAST

    monkeypatch.setattr(freeze_store, "FREEZE_DIR", tmp_path / "frozen")
    sig = "sig_shape_0001"
    bundle = ExecutionBundle(
        templateId="tpl_x", datasetId="ds_x", status="READY",
        bindingAst=BindingAST(datasetSignature=sig),
    )
    attach_data_hash(bundle, compute_data_content_hash(pd.DataFrame({"v": [1]})))
    freeze_store.freeze_bundle(bundle)
    # Loadable by the SHAPE signature (the address), regardless of the content hash.
    loaded = freeze_store.load_frozen_bundle("tpl_x", sig)
    assert loaded is not None
    assert bundle_data_hash(loaded) == bundle_data_hash(bundle)
