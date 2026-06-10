"""Generation run modes + data content hashing — reproducibility for official reports.

The bundle is addressed by ``(templateId, datasetSignature)`` where the signature is
the dataset **shape** (column names + dtypes). Shape is not enough to guarantee a
frozen report is reproducible: two datasets with the same columns but different
*values* share a signature. This module adds the missing piece — a **data content
hash** that pins the actual values — and the three generation modes that use it:

  * ``fresh``  — build the current bundle from the live stash/review, compute the data
                 content hash, freeze it into the bundle, and execute. (default)
  * ``frozen`` — load a previously frozen bundle (by version), verify the *current*
                 dataset's content hash matches the one pinned in the frozen bundle,
                 and execute reproducibly. A mismatch is **data drift** → caller 409s.
  * ``test``   — load a fixture bundle + fixture dataset offline, never touching real
                 storage, for deterministic regression.

Invariants (do not weaken):
  * The freeze **addressing key stays ``(templateId, datasetSignature)``** — the content
    hash is a *value* pinned inside ``dataframeRef``, never part of the freeze key.
  * Frozen mode never silently rebuilds a stale bundle; it loads and verifies.
  * Hashing is deterministic and offline (no model calls), so ``LLM_DISABLED=1`` runs
    are unaffected.
"""
from __future__ import annotations

import hashlib
import logging
import os

import pandas as pd

from report_builder.binding.execution_contracts import ExecutionBundle

logger = logging.getLogger(__name__)

GENERATION_MODES = ("fresh", "frozen", "test")
DEFAULT_MODE = "fresh"


# ─────────────────────────────────────────────────────────────────────────────
# Mode resolution
# ─────────────────────────────────────────────────────────────────────────────


def resolve_mode(value: str | None) -> str:
    """Resolve the generation mode: request override > env ``GENERATION_MODE`` > fresh."""
    mode = (value or os.getenv("GENERATION_MODE") or DEFAULT_MODE).strip().lower()
    return mode if mode in GENERATION_MODES else DEFAULT_MODE


# ─────────────────────────────────────────────────────────────────────────────
# Data content hash
# ─────────────────────────────────────────────────────────────────────────────


def compute_data_content_hash(df: pd.DataFrame | None) -> str:
    """A deterministic, value-level hash of the dataframe actually executed.

    Canonicalised as headered CSV (column order + every row value, in order), so it
    captures the data *content* — not just its shape. Returned as ``sha256:<32hex>``.
    Two frames with identical columns+values+order hash equal; any value/row change
    (the signature-blind case) changes the hash, which is exactly what frozen mode
    needs to detect drift.
    """
    if df is None:
        df = pd.DataFrame()
    # `to_csv` is stable for a given frame (same dtypes ⇒ same text); both the
    # fresh-freeze and the frozen-verify read their CSV the same way, so the
    # round-trip is consistent on both sides of the comparison.
    canonical = df.to_csv(index=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:32]}"


def bundle_data_hash(bundle: ExecutionBundle) -> str:
    """The data content hash pinned in a bundle's ``dataframeRef`` (or "" if none)."""
    return str((bundle.dataframeRef or {}).get("contentHash") or "")


def attach_data_hash(bundle: ExecutionBundle, data_hash: str) -> ExecutionBundle:
    """Pin ``data_hash`` into the bundle's ``dataframeRef`` (in-memory; additive)."""
    ref = dict(bundle.dataframeRef or {})
    if data_hash:
        ref["contentHash"] = data_hash
    bundle.dataframeRef = ref
    return bundle


# ─────────────────────────────────────────────────────────────────────────────
# Drift detection
# ─────────────────────────────────────────────────────────────────────────────


class DataDriftError(Exception):
    """Raised when a frozen bundle's pinned data hash disagrees with the live data."""

    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"DATA_DRIFT: frozen bundle pinned data {expected!r} but current dataset "
            f"hashes to {actual!r} — the data changed since freezing"
        )


def verify_data_hash(bundle: ExecutionBundle, df: pd.DataFrame | None) -> str:
    """Verify the live data matches the frozen bundle's pinned hash.

    Returns the freshly computed content hash. Raises :class:`DataDriftError` when the
    bundle carries a pinned hash that differs from the current data. A bundle with no
    pinned hash (legacy/unpinned) is accepted — there is nothing to drift against — but
    the computed hash is still returned so the caller can surface/repin it.
    """
    current = compute_data_content_hash(df)
    pinned = bundle_data_hash(bundle)
    if pinned and pinned != current:
        raise DataDriftError(pinned, current)
    return current
