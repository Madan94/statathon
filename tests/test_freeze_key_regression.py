"""Trunk-side regression test for the freeze-store key bug (gold integration).

Contract: `freeze_bundle` MUST key the frozen artifact by **`BindingAST.datasetSignature`**
so that a downstream consumer can reload it with `load_frozen_bundle(template_id,
datasetSignature)`. Reproducibility of the S4→S6 pipeline depends on this round-trip.

The bug (pre-fix): `freeze_bundle` keyed by `bundle.datasetAst.signature`, but `DatasetAST`
has no `signature` field, so it silently fell back to `bundle.datasetId`. Loaders, however,
look up by the dataset *signature* (which lives on `BindingAST.datasetSignature`). When the
signature differs from the datasetId — the normal production case — freeze writes under one
key and load reads under another, so `load_frozen_bundle` returns `None` and the frozen
bundle is unreachable.

This test fails before the fix and passes after it. Adding it (not weakening any guardian)
documents the contract per the integration change-note.
"""
from __future__ import annotations

import pytest

from report_builder.binding import freeze_store
from report_builder.binding.execution_contracts import (
    ExecutionBundle,
    FormulaSpec,
    LineageRef,
    QuestionExecutionPlan,
)
from report_builder.binding.schema import (
    BindingAST,
    ColumnProfile,
    DatasetAST,
    ResolvedRoles,
)


def _make_bundle(template_id: str, dataset_id: str, dataset_signature: str) -> ExecutionBundle:
    dataset = DatasetAST(columns=[
        ColumnProfile(name="State", role="dimension", dtype="string", cardinality=28),
        ColumnProfile(name="Coal_Reserve_MT", role="measure", dtype="float", unit="MT", cardinality=28),
    ])
    binding = BindingAST(
        templateId=template_id,
        datasetId=dataset_id,
        datasetSignature=dataset_signature,
    )
    plan = QuestionExecutionPlan(
        planId="p1", questionId="q1", status="EXECUTABLE",
        resolvedRoles=ResolvedRoles(measures=["Coal_Reserve_MT"], dimensions=["State"]),
        formulaSpec=FormulaSpec(type="DIRECT"),
        lineage=LineageRef(sourceQuestionId="q1", sourceColumnIds=["Coal_Reserve_MT"]),
    )
    return ExecutionBundle(
        templateId=template_id,
        datasetId=dataset_id,
        bindingAstId="bind_energy_001",
        status="READY",
        datasetAst=dataset,
        bindingAst=binding,
        plans=[plan],
    )


def test_freeze_then_load_by_dataset_signature_roundtrips(tmp_path, monkeypatch):
    """Freeze, then load by `BindingAST.datasetSignature` — must round-trip.

    Uses a signature that is DISTINCT from datasetId, which is the only case that
    exposes the key mismatch (when they coincide the bug is masked).
    """
    monkeypatch.setattr(freeze_store, "FREEZE_DIR", tmp_path)

    dataset_id = "ds_energy_001"
    dataset_signature = "sig_abc123def4567890"  # deliberately != datasetId
    assert dataset_id != dataset_signature, "test is only meaningful when the keys differ"

    bundle = _make_bundle("tpl_energy", dataset_id, dataset_signature)

    info = freeze_store.freeze_bundle(bundle)
    assert info["isNew"] is True

    # Load by the contract key: BindingAST.datasetSignature.
    loaded = freeze_store.load_frozen_bundle("tpl_energy", bundle.bindingAst.datasetSignature)

    assert loaded is not None, (
        "Freeze/load key mismatch: the bundle was frozen under a key other than "
        "BindingAST.datasetSignature, so load_frozen_bundle(template_id, datasetSignature) "
        "could not find it. freeze_bundle must key by BindingAST.datasetSignature."
    )
    assert loaded.templateId == "tpl_energy"
    assert loaded.bindingAst.datasetSignature == dataset_signature
    assert len(loaded.plans) == 1


def test_freeze_falls_back_to_dataset_id_when_signature_absent(tmp_path, monkeypatch):
    """Backward-compat: when `datasetSignature` is empty, freeze/load still works via datasetId.

    Guards against the fix over-correcting and breaking older bundles that carry no signature.
    """
    monkeypatch.setattr(freeze_store, "FREEZE_DIR", tmp_path)

    bundle = _make_bundle("tpl_legacy", "ds_legacy_001", "")  # no signature

    info = freeze_store.freeze_bundle(bundle)
    assert info["isNew"] is True

    loaded = freeze_store.load_frozen_bundle("tpl_legacy", "ds_legacy_001")
    assert loaded is not None, "legacy datasetId fallback must still round-trip"
    assert loaded.templateId == "tpl_legacy"
