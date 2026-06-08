"""B7 — Binding-phase CLI / orchestrator.

Runs the full binder over a (blueprint, CSV) pair:

    S0 profile ▶ S1 resolve ▶ S2 review ▶ S3 question-bind ▶ B6 coverage

and writes four artifacts to the output directory:

    datasetAST.json   — the S0 dataset profile
    bindingAST.json   — entity + question bindings (the core artifact)
    coverage.json     — structured gate report
    coverage.md       — human-readable digest

Exit code is the **gate**: non-zero when coverage has errors (a question is
blocked), unless ``--no-gate`` is passed. Fully offline with ``--accept-proposed``
(or ``LLM_DISABLED=1``).

Usage:
    python scripts/run_binding.py --blueprint <bp.json> --csv <data.csv> \\
        [--out <dir>] [--accept-proposed] [--template-id <id>] [--no-gate]
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

from report_builder.binding.profiler import profile_dataframe  # noqa: E402
from report_builder.binding.resolver import resolve_entities  # noqa: E402
from report_builder.binding.question_binder import bind_questions  # noqa: E402
from report_builder.binding.review import dataset_signature, finalize_review, open_review  # noqa: E402
from report_builder.binding.report import build_coverage, to_markdown  # noqa: E402
from report_builder.binding.schema import BindingAST  # noqa: E402

logger = logging.getLogger("run_binding")


# ─────────────────────────────────────────────────────────────────────────────
# Core orchestration (importable)
# ─────────────────────────────────────────────────────────────────────────────


def run_binding(
    blueprint: dict[str, Any],
    df: pd.DataFrame,
    *,
    dataset_id: str = "",
    source_file: str = "",
    template_id: str = "",
    accept_proposed: bool = False,
    storage_dir: str | Path | None = None,
) -> tuple[BindingAST, dict[str, Any]]:
    """Run S0→S1→S2→S3→coverage and return ``(binding_ast, dataset_ast_dict)``."""
    tpl = template_id or str((blueprint.get("templateMeta") or {}).get("templateId") or "template")

    # S0 — profile
    dataset = profile_dataframe(df, dataset_id=dataset_id, source_file=source_file)

    # S1 — propose entity bindings
    entity_bindings = resolve_entities(blueprint.get("entities") or [], dataset)

    # S2 — review (headless accept, or resume cached confirmations)
    binding = BindingAST(
        templateId=tpl,
        datasetId=dataset.datasetId,
        datasetSignature=dataset_signature(dataset),
        entityBindings=entity_bindings,
    )
    binding, record, _deltas = open_review(binding, dataset, storage_dir=storage_dir)
    binding, _path = finalize_review(
        binding, record, accept_proposed=accept_proposed, storage_dir=storage_dir
    )

    # S3 — bind questions on the (now reviewed) entity bindings
    binding.questionBindings = bind_questions(blueprint, binding.entityBindings, dataset, df=df)

    # B6 — coverage (also stamps binding.coverage)
    build_coverage(binding)

    return binding, dataset.to_dict()


def write_artifacts(
    binding: BindingAST, dataset_ast: dict[str, Any], out_dir: Path
) -> dict[str, Path]:
    """Write the four binding artifacts; return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "datasetAST": out_dir / "datasetAST.json",
        "bindingAST": out_dir / "bindingAST.json",
        "coverage": out_dir / "coverage.json",
        "coverageMd": out_dir / "coverage.md",
    }
    paths["datasetAST"].write_text(json.dumps(dataset_ast, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["bindingAST"].write_text(json.dumps(binding.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    paths["coverage"].write_text(json.dumps(binding.coverage, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["coverageMd"].write_text(to_markdown(binding), encoding="utf-8")
    return paths


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the binding phase over a blueprint + CSV.")
    parser.add_argument("--blueprint", required=True, help="path to template.blueprint.json")
    parser.add_argument("--csv", required=True, help="path to the dataset CSV")
    parser.add_argument("--out", default=None, help="output directory (default outputs/binding/<tpl>__<sig>)")
    parser.add_argument("--template-id", default="", help="override templateId")
    parser.add_argument("--accept-proposed", action="store_true", help="headless: auto-accept all proposals")
    parser.add_argument("--no-gate", action="store_true", help="always exit 0 even with coverage errors")
    parser.add_argument("--storage-dir", default=None, help="override review cache directory")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

    bp_path = Path(args.blueprint).resolve()
    csv_path = Path(args.csv).resolve()
    if not bp_path.exists():
        logger.error("blueprint not found: %s", bp_path)
        return 2
    if not csv_path.exists():
        logger.error("csv not found: %s", csv_path)
        return 2

    blueprint = json.loads(bp_path.read_text(encoding="utf-8"))
    df = pd.read_csv(csv_path)

    binding, dataset_ast = run_binding(
        blueprint, df,
        dataset_id=csv_path.stem,
        source_file=csv_path.name,
        template_id=args.template_id,
        accept_proposed=args.accept_proposed,
        storage_dir=args.storage_dir,
    )

    out_dir = (
        Path(args.out).resolve() if args.out
        else REPO_ROOT / "outputs" / "binding" / f"{binding.templateId}__{binding.datasetSignature}"
    )
    paths = write_artifacts(binding, dataset_ast, out_dir)

    cov = binding.coverage
    has_errors = any(i.get("severity") == "error" for i in cov.get("issues", []))
    logger.info("=" * 70)
    logger.info("BINDING COMPLETE → %s", out_dir)
    logger.info("  entities: %s", cov.get("entities"))
    logger.info("  questions: %s", cov.get("questions"))
    logger.info("  gate: %s", "ERRORS" if has_errors else "PASS")
    for name, p in paths.items():
        logger.info("  %-12s %s", name, p.name)
    logger.info("=" * 70)

    return 1 if (has_errors and not args.no_gate) else 0


if __name__ == "__main__":
    raise SystemExit(main())
