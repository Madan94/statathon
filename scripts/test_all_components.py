"""Test: generate multiple components to verify all work correctly."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from api.report_builder_api.generate_phase_api import (
    _read_stash, _rebuild_binding, _build_bundle, _load_template_ast,
    _question_meta, _prose_config, _question_registry, _build_component_template,
)
from report_builder.generation.bundle_adapter import adapt_bundle
from report_builder.generation.coordinator import run_execution
from report_builder.generation.filler import fill_visuals
from report_builder.generation.narrator import narrate
from report_builder.generation.run_modes import compute_data_content_hash

TID = "tpl_energy_enterprise_v2"
SIG = "b7acf2ae375faab7"

dataset, blueprint, df = _read_stash(TID, SIG)
binding = _rebuild_binding(TID, SIG, dataset, blueprint, df)
bundle = _build_bundle(TID, SIG, dataset, blueprint, df, data_content_hash=compute_data_content_hash(df))
adapted = adapt_bundle(bundle)
template = _load_template_ast(TID)
qmeta = _question_meta(blueprint)
prose = _prose_config(blueprint)
registry = _question_registry(blueprint)
context = blueprint.get("statisticalContext") or {}

print(f"Testing {len(adapted)} adapted plans with template: {TID}\n")

for idx in range(len(adapted)):
    plan = adapted[idx]
    qid = plan.questionId
    qinfo = registry.get(qid, {})

    # Execute
    a_obj, e_obj, ri = run_execution([plan], df, question_meta=qmeta)
    analytics = a_obj.to_dict()
    evidence = e_obj.to_dict()

    # Build component template + narrate
    comp_tpl = _build_component_template(template, qid, qinfo, plan)
    narrated = narrate(comp_tpl, analytics, evidence, context=context, questions=prose, use_llm=False)

    blocks = narrated.get("contentAST", {}).get("blocks", [])
    text = blocks[0].get("content", "") if blocks else ""

    # Check analytics
    aggs = len(analytics.get("aggregations", []))
    ranks = len(analytics.get("rankings", []))
    metrics_c = len(analytics.get("metrics", []))

    # Determine quality
    good = text and "could not be computed" not in text.lower() and len(text) > 20
    status = "OK" if good else "FALLBACK"

    path = " > ".join(qinfo.get("sectionPath", []))
    measure = plan.measureColumn or "—"

    print(f"  [{idx:2d}] {status:8s} | {measure:20s} | q={qid:30s} | a={aggs} r={ranks} m={metrics_c}")
    if good:
        print(f"           {text[:100]}")
    else:
        print(f"           NARRATION: {text[:80] if text else '(empty)'}")
    if idx < len(adapted) - 1 and adapted[idx + 1].questionId != qid:
        print()  # Visual separator between questions

print(f"\nDone: {sum(1 for i in range(len(adapted)) if True)} components traced")
