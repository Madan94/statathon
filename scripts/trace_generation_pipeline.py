#!/usr/bin/env python
"""Complete end-to-end trace of the generation pipeline.

Runs every step that generate-component does, printing exactly what
goes in and what comes out at each stage. No HTTP — direct Python calls.
"""
from __future__ import annotations
import json, sys, pathlib, textwrap, traceback
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

TEMPLATE_ID = "tpl_energy_enterprise_v2"
SIGNATURE   = "b7acf2ae375faab7"
TEST_INDEX  = 0   # which adapted plan to trace
TEST_INDICES = [0, 2, 6, 8, 11]  # test multiple

DIVIDER = "=" * 70

def section(title: str):
    print(f"\n{DIVIDER}\n  {title}\n{DIVIDER}")

def show(label: str, obj, depth=120):
    s = repr(obj) if not isinstance(obj, str) else obj
    if len(s) > depth:
        s = s[:depth] + "..."
    print(f"  {label}: {s}")

# ──────────────────────────────────────────────────────────────────
section("STEP 0: Load stash (dataset + blueprint + CSV)")
# ──────────────────────────────────────────────────────────────────
from api.report_builder_api.generate_phase_api import (
    _read_stash, _rebuild_binding, _build_bundle, _load_template_ast,
    _question_meta, _prose_config, _question_registry,
    _build_component_template,
)
from report_builder.generation.bundle_adapter import adapt_bundle
from report_builder.generation.coordinator import run_execution
from report_builder.generation.filler import fill_visuals
from report_builder.generation.narrator import narrate
from report_builder.generation.run_modes import compute_data_content_hash

try:
    dataset, blueprint, df = _read_stash(TEMPLATE_ID, SIGNATURE)
    show("dataset.datasetId", dataset.datasetId)
    show("dataset.columns count", len(dataset.columns))
    show("dataset.rowCount", dataset.rowCount)
    show("df.shape", df.shape)
    show("df.columns", list(df.columns)[:8])
    show("blueprint topics", len(blueprint.get("topics", [])))
except Exception as e:
    print(f"  FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────
section("STEP 1: Question metadata from blueprint")
# ──────────────────────────────────────────────────────────────────
qmeta = _question_meta(blueprint)
prose = _prose_config(blueprint)
registry = _question_registry(blueprint)
show("question_meta entries", len(qmeta))
show("prose_config entries", len(prose))
show("registry entries", len(registry))
for qid, info in registry.items():
    print(f"    {qid}: title={info['title'][:50]}")
    print(f"      path={' > '.join(info['sectionPath'])}")
    print(f"      types={info['componentTypes']}")

# ──────────────────────────────────────────────────────────────────
section("STEP 2: Rebuild binding")
# ──────────────────────────────────────────────────────────────────
try:
    binding = _rebuild_binding(TEMPLATE_ID, SIGNATURE, dataset, blueprint, df)
    show("binding.templateId", binding.templateId)
    show("entityBindings count", len(binding.entityBindings))
    show("questionBindings count", len(binding.questionBindings))
    cov = binding.coverage or {}
    show("coverage entities", cov.get("entities"))
    show("coverage questions", cov.get("questions"))
except Exception as e:
    print(f"  FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────
section("STEP 3: Build ExecutionBundle")
# ──────────────────────────────────────────────────────────────────
try:
    data_hash = compute_data_content_hash(df)
    bundle = _build_bundle(TEMPLATE_ID, SIGNATURE, dataset, blueprint, df,
                           data_content_hash=data_hash)
    show("bundle.status", bundle.status)
    show("bundle.plans count", len(bundle.plans))
    for i, p in enumerate(bundle.plans):
        show(f"  plan[{i}].planId", p.planId)
        show(f"  plan[{i}].questionId", p.questionId)
        show(f"  plan[{i}].questionText", p.questionText[:60] if p.questionText else "EMPTY")
        show(f"  plan[{i}].status", p.status)
        spec = p.analyticsSpec or {}
        show(f"  plan[{i}].operation", spec.get("operation", "?"))
        roles = p.resolvedRoles
        show(f"  plan[{i}].measures", roles.measures[:3] if roles.measures else "NONE")
        dims_raw = roles.dimensions if hasattr(roles, 'dimensions') else []
        dim_list = []
        for d in (dims_raw or []):
            if isinstance(d, str):
                dim_list.append(d)
            elif hasattr(d, 'column'):
                dim_list.append(d.column)
        show(f"  plan[{i}].dimensions", dim_list[:3] or "NONE")
except Exception as e:
    print(f"  FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────
section("STEP 4: Adapt bundle → AdaptedPlans")
# ──────────────────────────────────────────────────────────────────
try:
    adapted = adapt_bundle(bundle)
    show("adapted plans count", len(adapted))
    for i, ap in enumerate(adapted[:5]):
        print(f"    [{i}] planId={ap.planRec.planId}")
        print(f"        qid={ap.questionId} measure={ap.measureColumn}")
        print(f"        op={ap.planRec.operation} groupBy={ap.planRec.groupBy}")
        print(f"        formula={ap.formulaSpec.type if ap.formulaSpec else 'NONE'}")
        print(f"        status={ap.status}")
    if len(adapted) > 5:
        print(f"    ... ({len(adapted) - 5} more)")
except Exception as e:
    print(f"  FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────
section(f"STEP 5: Execute single plan [index={TEST_INDEX}]")
# ──────────────────────────────────────────────────────────────────
try:
    single = [adapted[TEST_INDEX]]
    show("executing plan", single[0].planRec.planId)
    show("  questionId", single[0].questionId)
    show("  measureColumn", single[0].measureColumn)
    show("  operation", single[0].planRec.operation)
    show("  groupBy", single[0].planRec.groupBy)
    show("  measure.columnExpr", single[0].planRec.measure.columnExpr)
    show("  measure.agg", single[0].planRec.measure.agg)
    show("  filters", single[0].planRec.filters)
    show("  sort", single[0].planRec.sort)
    show("  topN", single[0].planRec.topN)

    analytics_obj, evidence_obj, row_index = run_execution(
        single, df, question_meta=qmeta
    )
    analytics = analytics_obj.to_dict()
    evidence = evidence_obj.to_dict()

    show("analytics.plans", len(analytics.get("plans", [])))
    show("analytics.executions", len(analytics.get("executions", [])))
    show("analytics.aggregations", len(analytics.get("aggregations", [])))
    show("analytics.rankings", len(analytics.get("rankings", [])))
    show("analytics.trends", len(analytics.get("trends", [])))
    show("analytics.metrics", len(analytics.get("metrics", [])))

    # Show actual data
    for ex in analytics.get("executions", []):
        print(f"    execution: id={ex.get('executionId')} engine={ex.get('engine')} "
              f"rows={ex.get('rowsScanned')} status={ex.get('status')} ms={ex.get('ms')}")

    for agg in analytics.get("aggregations", [])[:2]:
        rows = agg.get("rows", [])
        print(f"    aggregation: measure={agg.get('measure')} groupBy={agg.get('groupBy')} "
              f"rows={len(rows)}")
        for r in rows[:3]:
            print(f"      {r}")

    for rk in analytics.get("rankings", [])[:2]:
        rows = rk.get("rows", [])
        print(f"    ranking: measure={rk.get('measure')} groupBy={rk.get('groupBy')} "
              f"rows={len(rows)}")
        for r in rows[:3]:
            print(f"      {r}")

    for mt in analytics.get("metrics", [])[:2]:
        print(f"    metric: label={mt.get('label')} value={mt.get('value')}")

    show("evidence.items", len(evidence.get("evidence", [])))
    show("row_index keys", list(row_index.keys())[:5])

except Exception as e:
    print(f"  FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────
section("STEP 6: Load template AST (template-aware)")
# ──────────────────────────────────────────────────────────────────
try:
    template = _load_template_ast(TEMPLATE_ID)
    show("template type", type(template).__name__)
    if isinstance(template, dict):
        show("template keys", list(template.keys())[:10])
        # Check if contentAST has blocks matching our question
        blocks = (template.get("contentAST") or {}).get("blocks", [])
        show("contentAST.blocks count", len(blocks))
        qid = adapted[TEST_INDEX].questionId
        matching = [b for b in blocks if (b.get("biQuery") or (b.get("slot") or {}).get("fillFrom", "")).startswith(qid)]
        show(f"blocks matching {qid}", len(matching))
        if matching:
            for b in matching[:3]:
                print(f"    block: {b.get('blockId')} biQuery={b.get('biQuery')}")
        else:
            print(f"    NO BLOCKS MATCH {qid} — will inject dynamic block")
except Exception as e:
    print(f"  FAILED: {e}")
    traceback.print_exc()

# ──────────────────────────────────────────────────────────────────
section("STEP 6b: Build component template")
# ──────────────────────────────────────────────────────────────────
try:
    qid = adapted[TEST_INDEX].questionId
    qinfo_for_tpl = registry.get(qid, {})
    component_template = _build_component_template(template, qid, qinfo_for_tpl, adapted[TEST_INDEX])
    comp_blocks = (component_template.get("contentAST") or {}).get("blocks", [])
    show("component template blocks", len(comp_blocks))
    matching2 = [b for b in comp_blocks if (b.get("biQuery") or (b.get("slot") or {}).get("fillFrom", "")).startswith(qid)]
    show(f"blocks matching {qid} (after inject)", len(matching2))
    for b in matching2:
        print(f"    block: {b.get('blockId')} biQuery={b.get('biQuery')} slot={b.get('slot')}")
except Exception as e:
    print(f"  FAILED: {e}")
    traceback.print_exc()

# ──────────────────────────────────────────────────────────────────
section("STEP 7: Fill visuals")
# ──────────────────────────────────────────────────────────────────
context = blueprint.get("statisticalContext") or {}
try:
    visuals = fill_visuals(component_template, analytics, evidence, context=context)
    show("visuals type", type(visuals).__name__)
    if isinstance(visuals, dict):
        show("visuals keys", list(visuals.keys()))
        ft = visuals.get("fillTrace", {})
        show("fillTrace", ft)
    else:
        show("visuals", str(visuals)[:200])
except Exception as e:
    print(f"  FAILED: {e}")
    traceback.print_exc()

# ──────────────────────────────────────────────────────────────────
section("STEP 8: Narrate (use_llm=False first)")
# ──────────────────────────────────────────────────────────────────
try:
    narrated = narrate(component_template, analytics, evidence, context=context,
                       questions=prose, use_llm=False)
    show("narrated type", type(narrated).__name__)
    if isinstance(narrated, dict):
        show("narrated keys", list(narrated.keys()))
        content_ast = narrated.get("contentAST", {})
        blocks = content_ast.get("blocks", [])
        show("contentAST.blocks count", len(blocks))
        for i, block in enumerate(blocks[:5]):
            btype = block.get("type", block.get("blockType", "?"))
            content = str(block.get("content") or block.get("text") or block.get("value") or "")
            print(f"    block[{i}]: type={btype}")
            print(f"      content={content[:120]}")
            print(f"      all_keys={list(block.keys())}")
        trace = narrated.get("narrativeTrace", {})
        show("narrativeTrace", trace)
    else:
        show("narrated", str(narrated)[:300])
except Exception as e:
    print(f"  FAILED: {e}")
    traceback.print_exc()

# ──────────────────────────────────────────────────────────────────
section("STEP 9: Narrate (use_llm=True)")
# ──────────────────────────────────────────────────────────────────
try:
    narrated_llm = narrate(component_template, analytics, evidence, context=context,
                           questions=prose, use_llm=True)
    if isinstance(narrated_llm, dict):
        blocks_llm = narrated_llm.get("contentAST", {}).get("blocks", [])
        show("contentAST.blocks count (LLM)", len(blocks_llm))
        for i, block in enumerate(blocks_llm[:5]):
            content = str(block.get("content") or block.get("text") or block.get("value") or "")
            print(f"    block[{i}]: {content[:150]}")
        show("narrativeTrace (LLM)", narrated_llm.get("narrativeTrace", {}))
except Exception as e:
    print(f"  FAILED (LLM narration): {e}")
    traceback.print_exc()

# ──────────────────────────────────────────────────────────────────
section("SUMMARY")
# ──────────────────────────────────────────────────────────────────
print(f"""
  Blueprint questions found: {len(qmeta)}
  Prose config entries:      {len(prose)}
  Bundle plans:              {len(bundle.plans)}
  Adapted plans:             {len(adapted)}
  
  For index={TEST_INDEX} ({adapted[TEST_INDEX].planRec.planId}):
    Aggregations: {len(analytics.get('aggregations', []))}
    Rankings:     {len(analytics.get('rankings', []))}
    Metrics:      {len(analytics.get('metrics', []))}
    Trends:       {len(analytics.get('trends', []))}
    Content blocks: {len(narrated.get('contentAST', {}).get('blocks', []))}
""")
