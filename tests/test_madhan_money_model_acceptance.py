from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from report_builder.binding.execution_bundle_factory import build_execution_bundle
from report_builder.binding.profiler import profile_dataframe
from report_builder.binding.resolver import resolve_entities
from report_builder.binding.review import ReviewRecord, accept_all_proposed, dataset_signature
from report_builder.binding.reviewed_plan import build_reviewed_plan
from report_builder.binding.schema import BindingAST
from report_builder.template_compiler import compile_template_artifacts


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "outputs" / "test_madhan_money_model"
PLFS_CSV = ROOT / "test_data" / "synthetic_plfs_dataset.csv"


def _load_compiled():
    if not OUTPUT_DIR.exists():
        pytest.skip("outputs/test_madhan_money_model not available")
    ast = json.loads((OUTPUT_DIR / "template.ast.json").read_text(encoding="utf-8"))
    blueprint = json.loads((OUTPUT_DIR / "template.blueprint.json").read_text(encoding="utf-8"))
    pass0 = json.loads((OUTPUT_DIR / "_pass_outputs" / "pass0_text_extraction.json").read_text(encoding="utf-8"))
    page_texts = [str(page) for page in pass0.get("pages", [])]
    return compile_template_artifacts(raw_ast=ast, blueprint=blueprint, page_texts=page_texts)


def test_madhan_template_extraction_is_binder_native():
    result = _load_compiled()
    ast = result["template_ast"]
    blueprint = result["template_blueprint"]
    diagnostics = result["diagnostics"]

    charts = ast.get("chartAST", {}).get("charts", [])
    tables = ast.get("tableAST", {}).get("tables", [])
    questions = [q for topic in blueprint.get("topics", []) for q in topic.get("questions", [])]

    assert diagnostics.status == "VALID"
    assert diagnostics.binderReadinessScore >= 0.80
    assert len(charts) == 11
    assert len(tables) == 0
    assert blueprint.get("externalTableReferences"), "External annual-report table reference must be explicit"
    assert blueprint.get("chartPanelGroups"), "Physical chart panels must be grouped for binder preview"
    assert 6 <= len(questions) <= 9
    assert all(q.get("requiredEntities") for q in questions)
    assert all(q.get("measureEntityId") for q in questions)
    assert any(topic.get("questions") for topic in blueprint.get("topics", [])[1:]), "Questions must not all sit in topic_01"

    for chart in charts:
        chart_id = chart.get("chartId", "")
        assert not chart_id.startswith("chart_ft_"), f"stale figureTemplate slot leaked: {chart_id}"
        assert chart.get("title") or chart.get("biQuery"), f"chart slot lacks title and question link: {chart_id}"


def test_madhan_template_binds_to_reviewed_plan_and_execution_bundle(tmp_path: Path, monkeypatch):
    result = _load_compiled()
    blueprint = result["template_blueprint"]
    df = pd.read_csv(PLFS_CSV)
    dataset = profile_dataframe(df, dataset_id="madhan_plfs", source_file=str(PLFS_CSV.name))
    bindings = resolve_entities(blueprint.get("entities", []), dataset)
    signature = dataset_signature(dataset)
    binding = BindingAST(
        templateId="tpl_madhan_money_model",
        datasetId=dataset.datasetId,
        datasetSignature=signature,
        entityBindings=bindings,
    )
    record = ReviewRecord(
        templateId=binding.templateId,
        datasetSignature=signature,
        datasetId=dataset.datasetId,
        proposals=[entity.to_dict() for entity in bindings],
    )
    accept_all_proposed(binding, record)
    import report_builder.binding.freeze_store as freeze_store

    monkeypatch.setattr(freeze_store, "FREEZE_DIR", tmp_path / "frozen_bundles")

    reviewed_plan = build_reviewed_plan(
        template_id=binding.templateId,
        signature=signature,
        dataset=dataset,
        blueprint=blueprint,
        binding=binding,
        semantic_slot_graph=result.get("semantic_slot_graph"),
        template_ast=result.get("template_ast"),
    )
    assert reviewed_plan.planTree
    assert reviewed_plan.templatePackageRef.blueprintHash

    bundle = build_execution_bundle(
        template_id=binding.templateId,
        signature=signature,
        record=record,
        dataset=dataset,
        blueprint=blueprint,
        dataframe_path=str(tmp_path / "data.csv"),
        df=df,
    )
    assert bundle.status in {"READY", "DEGRADED", "NOT_READY"}
    assert bundle.plans, "S3.5 handoff must contain execution plans"
    assert bundle.bindingAst.entityBindings
    assert bundle.readinessReport is not None
