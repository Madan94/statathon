"""End-to-end binder ride for the Sixth Economic Census gold bundle.

Acts as the complete binder + generation module: takes the gold 3-JSON package +
its dense dataset and drives the full S0 -> S6 ride, writing every artifact into
the SAME bundle folder so the package is self-contained and report-canvas ready:

  S0 PROFILE     dataset.csv            -> datasetAST
  S1 RESOLVE     entities x columns     -> entityBindings (PROPOSED)
  S2 CONFIRM     headless auto-accept   -> entityBindings (CONFIRMED)
  S3 QUESTION    requiredEntities       -> questionBindings
  S3.5 GATE      readiness validation   -> ExecutionBundle (handoff artifact)
  S4 EXECUTE     plans over dataframe   -> analyticsAST + evidenceAST
  S5 FILL+BRIDGE documentMap            -> tableAST/chartAST/figureAST + contentAST
  S5c ASSEMBLE   everything             -> report.output.ast.json
  S6 RENDER      report.output.ast      -> report.canvas-draft.html

Outputs written next to the 3 JSONs:
  <slug>.binding.datasetAST.json
  <slug>.binding.bindingAST.json
  <slug>.binding.coverage.json
  <slug>.execution_bundle.json          (S3.5 handoff — ready for complete ride)
  <slug>.report.output.ast.json
  <slug>.report.canvas-draft.html
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from report_builder.binding import review as R
from report_builder.binding.profiler import profile_dataframe
from report_builder.binding.resolver import resolve_entities
from report_builder.binding.schema import BindingAST
from report_builder.binding.report import build_coverage
from report_builder.binding.execution_bundle_factory import build_execution_bundle
from report_builder.generation.bundle_adapter import adapt_bundle
from report_builder.generation import (
    run_execution, fill_visuals, narrate, assemble_report, render_html, validate_report,
)
from report_builder.generation.run_modes import compute_data_content_hash

SLUG = "economic_census_establishments_v1"
TEMPLATE_ID = "tpl_economic_census_establishments_v1"
ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "report_builder" / "gold_standard" / SLUG


def _load(name: str) -> dict:
    return json.loads((BUNDLE / f"{SLUG}.{name}").read_text(encoding="utf-8"))


def _question_meta(blueprint: dict) -> dict:
    """Map questionId -> {label, components} for metric labels + evidence wiring."""
    meta: dict = {}
    for t in blueprint.get("topics", []):
        for c in t.get("chapters", []):
            for s in c.get("sections", []):
                for q in s.get("questions", []):
                    comps = [comp.get("kind") for comp in
                             (q.get("answerStructure") or {}).get("components", [])]
                    meta[q["questionId"]] = {"label": q.get("intent", ""), "components": comps}
    return meta


def main() -> int:
    blueprint = _load("template.blueprint.json")
    template_ast = _load("template.ast.json")
    slot_graph = _load("semantic_slot_graph.json")
    df = pd.read_csv(BUNDLE / f"{SLUG}.dataset.csv")
    print(f"[load] blueprint entities={len(blueprint['entities'])} | dataset {df.shape}")

    # ── S0 PROFILE ──
    dataset = profile_dataframe(df, dataset_id=SLUG, source_file=f"{SLUG}.dataset.csv")
    signature = R.dataset_signature(dataset)
    print(f"[S0] datasetAST: {len(dataset.columns)} cols profiled | signature={signature[:12]}")

    # ── S1 RESOLVE ──
    entity_bindings = resolve_entities(blueprint.get("entities") or [], dataset)
    binding = BindingAST(templateId=TEMPLATE_ID, datasetId=dataset.datasetId,
                         datasetSignature=signature, entityBindings=entity_bindings)
    binding, record, _deltas = R.open_review(binding, dataset)
    n_proposed = sum(1 for e in binding.entityBindings if e.status == "proposed")
    n_unres = sum(1 for e in binding.entityBindings if e.status == "unresolved")
    print(f"[S1] resolved: {len(entity_bindings)} entities | proposed={n_proposed} unresolved={n_unres}")

    # ── S2 CONFIRM (headless auto-accept all proposed) ──
    R.accept_all_proposed(binding, record)
    R.save_record(record)
    n_conf = sum(1 for e in binding.entityBindings if e.status in ("confirmed", "overridden"))
    print(f"[S2] confirmed: {n_conf}/{len(binding.entityBindings)} entities")

    # ── S3 + S3.5 — build the ExecutionBundle (the handoff artifact) ──
    data_hash = compute_data_content_hash(df)
    bundle = build_execution_bundle(
        template_id=TEMPLATE_ID, signature=signature, record=record,
        dataset=dataset, blueprint=blueprint,
        dataframe_path=str(BUNDLE / f"{SLUG}.dataset.csv"), df=df,
        data_content_hash=data_hash,
    )
    plans_total = len(bundle.plans)
    plans_ready = sum(1 for p in bundle.plans if p.status != "BLOCKED")
    print(f"[S3.5] ExecutionBundle status={bundle.status} | plans {plans_ready}/{plans_total} runnable "
          f"| blocked={len(bundle.blockedQuestions)}")

    # ── S4 EXECUTE ──
    adapted = adapt_bundle(bundle)
    analytics_obj, evidence_obj, row_index = run_execution(
        adapted, df, question_meta=_question_meta(blueprint))
    analytics, evidence = analytics_obj.to_dict(), evidence_obj.to_dict()
    print(f"[S4] analytics: rankings={len(analytics.get('rankings', []))} "
          f"aggregations={len(analytics.get('aggregations', []))} "
          f"metrics={len(analytics.get('metrics', []))}")

    # ── S5 FILL + documentMap BRIDGE + NARRATE ──
    template = dict(template_ast)
    visuals = fill_visuals(template, analytics, evidence, context={})
    narrated = narrate(template, analytics, evidence, context={},
                       questions=None, use_llm=False)

    doc_map = template.get("documentMap")
    if isinstance(doc_map, list) and doc_map:
        from report_builder.generation.document_map_bridge import bridge_document_map_report
        bridged = bridge_document_map_report(doc_map, analytics, evidence, slot_graph=slot_graph)
        if bridged["semanticAST"]["sections"]:
            template = {**template, "semanticAST": bridged["semanticAST"]}
            visuals["tableAST"] = bridged["tableAST"]
            visuals["chartAST"] = bridged["chartAST"]
            visuals["figureAST"] = bridged["figureAST"]
            visuals.setdefault("fillTrace", [])
            content = narrated.setdefault("contentAST", {"blocks": []})
            content["blocks"] = (content.get("blocks") or []) + bridged["blocks"]
            print(f"[S5-bridge] sections={len(bridged['semanticAST']['sections'])} "
                  f"tables={len(bridged['tableAST']['tables'])} "
                  f"charts={len(bridged['chartAST']['charts'])} "
                  f"blocks={len(bridged['blocks'])}")

    # ── S5c ASSEMBLE ──
    report_id = f"rpt_{TEMPLATE_ID}_{signature[:8]}"
    report = assemble_report(
        template, datasetAST=dataset, bindingAST=binding,
        analyticsAST=analytics, evidenceAST=evidence, visuals=visuals,
        contentAST=narrated["contentAST"], report_id=report_id,
        period={"current": "2013"},
    )
    result = validate_report(report, row_index=row_index)
    report.setdefault("auditAST", {})["warnings"] = result.get("warnings", [])
    print(f"[S5c] report.output.ast assembled | valid={result.get('valid')} "
          f"warnings={len(result.get('warnings', []))}")

    # ── S6 RENDER (canvas draft) ──
    html = render_html(report, title=blueprint["templateMeta"]["name"])
    n_sections = html.count('class="report-section')
    n_charts = html.count("<svg")
    n_tables = html.count("<table")
    print(f"[S6] canvas draft HTML | sections={n_sections} charts={n_charts} tables={n_tables} "
          f"| {len(html):,} bytes")

    # ── Write all handoff + report artifacts into the bundle folder ──
    (BUNDLE / f"{SLUG}.binding.datasetAST.json").write_text(
        json.dumps(dataset.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (BUNDLE / f"{SLUG}.binding.bindingAST.json").write_text(
        json.dumps(binding.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    build_coverage(binding)
    (BUNDLE / f"{SLUG}.binding.coverage.json").write_text(
        json.dumps(binding.coverage, ensure_ascii=False, indent=2), encoding="utf-8")
    (BUNDLE / f"{SLUG}.execution_bundle.json").write_text(
        json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (BUNDLE / f"{SLUG}.report.output.ast.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (BUNDLE / f"{SLUG}.report.canvas-draft.html").write_text(html, encoding="utf-8")

    print(f"\nOK  Full ride complete -> {BUNDLE}")
    for p in sorted(BUNDLE.glob(f"{SLUG}.*")):
        print(f"  {p.stat().st_size/1024:6.1f} KB  {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
