"""S4 — Generation analytics CLI: blueprint + bindingAST + CSV → analytics/evidence.

Runs the deterministic analytics core of the generation phase:

    build_plans (S4a)  ▶  run_analytics (S4b)

and writes two artifacts to the output directory:

    analyticsAST.json   — plans + executions + aggregations/rankings/trends/metrics
    evidenceAST.json    — row-level provenance for every value

Fully offline and deterministic. This is the inspectable core that the later
fill/narrate/assemble stages (S5/S6) build on.

Usage:
    python scripts/run_generation.py --blueprint <bp.json> --binding <bindingAST.json> \\
        --csv <data.csv> [--dataset <datasetAST.json>] [--out <dir>]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from report_builder.binding.schema import BindingAST, DatasetAST  # noqa: E402
from report_builder.generation.planner_adapter import build_plans  # noqa: E402
from report_builder.generation.executor import run_analytics  # noqa: E402
from report_builder.generation.filler import fill_visuals  # noqa: E402
from report_builder.generation.narrator import narrate  # noqa: E402
from report_builder.generation.assembler import assemble_report, validate_report  # noqa: E402
from report_builder.generation.renderer import render_html, render_pdf  # noqa: E402

logger = logging.getLogger("run_generation")


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _question_meta(blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-question metric label + component list, used for evidence/metric naming."""
    meta: dict[str, dict[str, Any]] = {}
    for topic in blueprint.get("topics") or []:
        for q in topic.get("questions") or []:
            qid = q.get("questionId")
            if not qid:
                continue
            comps = (q.get("answerStructure") or {}).get("components") or []
            meta[qid] = {
                "label": q.get("intent") or q.get("sourceHeading") or qid,
                "components": [c.get("componentId") for c in comps if c.get("componentId")],
            }
    return meta


def run_generation_analytics(
    blueprint: dict[str, Any],
    binding: BindingAST,
    df: pd.DataFrame,
    dataset: DatasetAST | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[int]]]:
    """Importable S4 core: returns (analyticsAST dict, evidenceAST dict, row_index)."""
    plans = build_plans(blueprint, binding, dataset)
    analytics, evidence, row_index = run_analytics(plans, df, question_meta=_question_meta(blueprint))
    return analytics.to_dict(), evidence.to_dict(), row_index

def _prose_config(blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Derive clean per-question narrator labels from blueprint entities.

    Gives the deterministic narrator a tidy ``measureLabel`` (the measure entity's
    canonical name) and ``dimensionNoun`` (first groupBy entity), so offline prose
    reads well without any LLM. Optional — the narrator degrades gracefully without it.
    """
    ent = {e.get("entityId"): e for e in (blueprint.get("entities") or [])}

    def name(ref: Any) -> str:
        e = ent.get(ref) or {}
        return e.get("canonicalName") or e.get("name") or ""

    cfg: dict[str, dict[str, Any]] = {}
    for topic in blueprint.get("topics") or []:
        for q in topic.get("questions") or []:
            qid = q.get("questionId")
            spec = q.get("analyticsSpec") or {}
            if not qid:
                continue
            measure_ref = (spec.get("measure") or {}).get("entityRef")
            group_refs = [g.get("entityRef") for g in (spec.get("groupBy") or [])]
            unit = (spec.get("measure") or {}).get("unit")
            agg = (spec.get("measure") or {}).get("agg") or ""
            mlabel = name(measure_ref)
            cfg[qid] = {
                "measureLabel": mlabel or qid,
                "measureShort": mlabel.split("(")[0].strip() if mlabel else "",
                "dimensionNoun": name(group_refs[0]).lower() if group_refs else "",
                "unit": unit or ("percent" if ("ratio" in agg or "share" in agg) else None),
            }
    return cfg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S4 generation analytics (offline).")
    parser.add_argument("--blueprint", required=True)
    parser.add_argument("--binding", required=True)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--dataset", default="")
    parser.add_argument("--template", default="",
                        help="template.ast.json — if given, also runs S5a visual fill")
    parser.add_argument("--period", default="", help="current period label for caption/footnotes")
    parser.add_argument("--report-id", default="", help="reportId for the assembled output")
    parser.add_argument("--out", default="outputs/generation")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    blueprint = _load_json(args.blueprint)
    binding = BindingAST.from_dict(_load_json(args.binding))
    df = pd.read_csv(args.csv)
    dataset = DatasetAST.from_dict(_load_json(args.dataset)) if args.dataset else None

    analytics, evidence, row_index = run_generation_analytics(blueprint, binding, df, dataset)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analyticsAST.json").write_text(
        json.dumps(analytics, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "evidenceAST.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    n_exec = sum(1 for e in analytics["executions"] if e["status"] == "ok")
    logger.info("[S4] plans=%d executions_ok=%d aggregations=%d rankings=%d metrics=%d evidence=%d",
                len(analytics["plans"]), n_exec, len(analytics["aggregations"]),
                len(analytics["rankings"]), len(analytics["metrics"]), len(evidence["evidence"]))
    logger.info("[S4] wrote %s/{analyticsAST,evidenceAST}.json", out_dir)

    # ── S5a: fill template visual slots (optional) ──
    if args.template:
        template = _load_json(args.template)
        context = {
            "dataset": {"title": (blueprint.get("metadata") or {}).get("title")
                        or (template.get("metadata") or {}).get("title") or "dataset"},
            "period": {"current": args.period},
        }
        filled = fill_visuals(template, analytics, evidence, context=context)
        (out_dir / "visualsAST.json").write_text(
            json.dumps({k: filled[k] for k in ("tableAST", "chartAST", "figureAST")},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        n_filled = sum(1 for x in filled["fillTrace"] if x.get("status") == "filled")
        logger.info("[S5a] filled %d/%d slots; wrote %s/visualsAST.json",
                    n_filled, len(filled["fillTrace"]), out_dir)

        # ── S5b: narrate paragraph slots (offline-first; LLM only if enabled) ──
        narrated = narrate(template, analytics, evidence, context=context,
                           questions=_prose_config(blueprint))
        (out_dir / "contentAST.json").write_text(
            json.dumps(narrated["contentAST"], ensure_ascii=False, indent=2), encoding="utf-8")
        tiers = {}
        for t in narrated["narrativeTrace"]:
            tiers[t["tier"]] = tiers.get(t["tier"], 0) + 1
        logger.info("[S5b] narrated %d blocks %s; wrote %s/contentAST.json",
                    len(narrated["narrativeTrace"]), tiers, out_dir)

        # ── S5c: assemble the full report.output.ast.json + validate provenance ──
        report = assemble_report(
            template,
            datasetAST=dataset.to_dict() if dataset else {"datasetId": binding.datasetId},
            bindingAST=binding,
            analyticsAST=analytics,
            evidenceAST=evidence,
            visuals=filled,
            contentAST=narrated["contentAST"],
            report_id=args.report_id or f"rpt_{binding.templateId or 'generated'}",
            period={"current": args.period} if args.period else None,
        )
        result = validate_report(report, row_index=row_index)
        report["auditAST"]["warnings"] = result["warnings"]
        (out_dir / "report.output.ast.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[S5c] assembled report.output.ast.json (valid=%s errors=%d warnings=%d) %s",
                    result["ok"], len(result["errors"]), len(result["warnings"]), result["stats"])
        for err in result["errors"]:
            logger.warning("[S5c] PROVENANCE ERROR: %s", err)

        # ── S6: render standalone HTML (+ PDF when WeasyPrint is available) ──
        html_str = render_html(report)
        (out_dir / "report.html").write_text(html_str, encoding="utf-8")
        logger.info("[S6] wrote %s/report.html (%d chars)", out_dir, len(html_str))
        pdf = render_pdf(report)
        if pdf:
            (out_dir / "report.pdf").write_bytes(pdf)
            logger.info("[S6] wrote %s/report.pdf (%d bytes)", out_dir, len(pdf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
