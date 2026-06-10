"""Validate Template Compiler on saved extraction output.

Runs the E1-E12 compiler modules on existing template.ast.json + template.blueprint.json
and reports before/after quality improvement.

Usage:
    python scripts/validate_template_compiler.py --input-dir outputs/syl_payaluga
    python scripts/validate_template_compiler.py --input-dir outputs/syl_payaluga --write-out outputs/syl_payaluga/compiled
    python scripts/validate_template_compiler.py --input-dir outputs/syl_payaluga --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser(description="Validate Template Compiler on saved output")
    parser.add_argument("--input-dir", required=True, help="Directory with template.ast.json + template.blueprint.json")
    parser.add_argument("--write-out", help="Output directory for compiled files")
    parser.add_argument("--strict", action="store_true", help="Use strict contract validation")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    ast_path = input_dir / "template.ast.json"
    bp_path = input_dir / "template.blueprint.json"

    if not ast_path.exists() or not bp_path.exists():
        print(f"ERROR: Missing files in {input_dir}")
        print(f"  template.ast.json: {'exists' if ast_path.exists() else 'MISSING'}")
        print(f"  template.blueprint.json: {'exists' if bp_path.exists() else 'MISSING'}")
        sys.exit(1)

    # Load inputs
    ast = json.loads(ast_path.read_text(encoding="utf-8"))
    bp = json.loads(bp_path.read_text(encoding="utf-8"))

    # ── BEFORE: Baseline ──
    from report_builder.extraction_contracts import validate_extraction_contract, ExtractionMode
    from report_builder.value_free_validator import validate_value_free
    from report_builder.extraction_diagnostics import build_extraction_diagnostics

    mode = ExtractionMode.STRICT if args.strict else ExtractionMode.WARN
    before_contract = validate_extraction_contract(bp, mode=mode)
    before_vf = validate_value_free(ast, bp)
    before_diag = build_extraction_diagnostics(blueprint=bp, skeleton=ast, contract_result=before_contract, value_free_result=before_vf)

    before_entities = bp.get("entities", [])
    before_seq_ids = sum(1 for e in before_entities if re.match(r'^ent_\d{2,}$', e.get("entityId", "")))
    before_with_aliases = sum(1 for e in before_entities if e.get("aliases"))
    before_with_domain = sum(1 for e in before_entities if (e.get("valueDomain") or {}).get("kind") and e.get("valueDomain", {}).get("kind") != "open")

    # ── COMPILE ──
    from report_builder.template_compiler import compile_template_artifacts
    result = compile_template_artifacts(raw_ast=ast, blueprint=bp)

    compiled_ast = result["template_ast"]
    compiled_bp = result["template_blueprint"]
    diag = result["diagnostics"]

    # ── AFTER: Compiled ──
    after_entities = compiled_bp.get("entities", [])
    after_seq_ids = sum(1 for e in after_entities if re.match(r'^ent_\d{2,}$', e.get("entityId", "")))
    after_with_aliases = sum(1 for e in after_entities if e.get("aliases"))
    after_with_domain = sum(1 for e in after_entities if (e.get("valueDomain") or {}).get("kind") and e.get("valueDomain", {}).get("kind") != "open")

    report = {
        "input_dir": str(input_dir),
        "before": {
            "score": round(before_diag.binderReadinessScore, 3),
            "status": before_diag.status,
            "entities": len(before_entities),
            "sequential_ids": before_seq_ids,
            "with_aliases": before_with_aliases,
            "with_valueDomain": before_with_domain,
            "contract": before_contract.status,
            "value_free": before_vf.status,
        },
        "after": {
            "score": round(diag.binderReadinessScore, 3),
            "status": diag.status,
            "entities": len(after_entities),
            "sequential_ids": after_seq_ids,
            "with_aliases": after_with_aliases,
            "with_valueDomain": after_with_domain,
            "contract": diag.status,
            "value_free": diag.categoryScores.get("valueFreeCompliance", 0),
            "recommendation": diag.binderCompatibility.recommendation,
        },
        "improvement": {
            "score_delta": round(diag.binderReadinessScore - before_diag.binderReadinessScore, 3),
            "entities_removed": len(before_entities) - len(after_entities),
            "sequential_ids_fixed": before_seq_ids - after_seq_ids,
            "aliases_added": after_with_aliases - before_with_aliases,
            "domains_added": after_with_domain - before_with_domain,
        },
        "categories": {k: round(v, 3) for k, v in diag.categoryScores.items()},
    }

    # Output
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("=" * 60)
        print("TEMPLATE COMPILER VALIDATION")
        print("=" * 60)
        print(f"Input: {input_dir}")
        print()
        print("── BEFORE (baseline) ──")
        print(f"  Score:          {report['before']['score']}")
        print(f"  Status:         {report['before']['status']}")
        print(f"  Entities:       {report['before']['entities']}")
        print(f"  Sequential IDs: {report['before']['sequential_ids']}")
        print(f"  With aliases:   {report['before']['with_aliases']}")
        print(f"  With domains:   {report['before']['with_valueDomain']}")
        print(f"  Contract:       {report['before']['contract']}")
        print(f"  Value-free:     {report['before']['value_free']}")
        print()
        print("── AFTER (compiled) ──")
        print(f"  Score:          {report['after']['score']}")
        print(f"  Status:         {report['after']['status']}")
        print(f"  Entities:       {report['after']['entities']}")
        print(f"  Sequential IDs: {report['after']['sequential_ids']}")
        print(f"  With aliases:   {report['after']['with_aliases']}")
        print(f"  With domains:   {report['after']['with_valueDomain']}")
        print(f"  Recommendation: {report['after']['recommendation']}")
        print()
        print("── IMPROVEMENT ──")
        print(f"  Score delta:    +{report['improvement']['score_delta']}")
        print(f"  Entities removed: {report['improvement']['entities_removed']}")
        print(f"  Seq IDs fixed:  {report['improvement']['sequential_ids_fixed']}")
        print(f"  Aliases added:  {report['improvement']['aliases_added']}")
        print(f"  Domains added:  {report['improvement']['domains_added']}")
        print()
        print("── CATEGORY SCORES ──")
        for k, v in report["categories"].items():
            print(f"  {k:30s} {v}")
        print("=" * 60)

    # Write compiled output if requested
    if args.write_out:
        out_dir = Path(args.write_out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "template.ast.json").write_text(json.dumps(compiled_ast, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        (out_dir / "template.blueprint.json").write_text(json.dumps(compiled_bp, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        (out_dir / "template.diagnostics.json").write_text(json.dumps(diag.to_dict(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        if not args.json:
            print(f"\nCompiled output written to: {out_dir}")

    # Exit code based on improvement
    if diag.binderReadinessScore >= before_diag.binderReadinessScore:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
