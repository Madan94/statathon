"""Offline end-to-end binding simulation (no LLM, no network).

Runs the binding phase fully offline (``LLM_DISABLED=1``, ``--accept-proposed``
semantics) over the gold PLFS blueprint + synthetic PLFS CSV, and over the energy
CSV as a second-archetype smoke test. Verifies the four artifacts are produced and
well-formed and that the PLFS golden run is gate-clean.

Usage:
    python scripts/simulate_binding_offline.py

Exit 0 = all checks passed; non-zero = a check failed.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

os.environ["LLM_DISABLED"] = "1"

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from report_builder.binding.schema import BindingAST, DatasetAST  # noqa: E402
from scripts.run_binding import run_binding, write_artifacts  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("simulate_binding_offline")

GOLD_BP = REPO_ROOT / "report_builder" / "gold_standard" / "template.blueprint.json"
PLFS_CSV = REPO_ROOT / "test_data" / "synthetic_plfs_dataset.csv"
ENERGY_CSV = REPO_ROOT / "test_data" / "unified_energy_reserves_dataset.csv"


def main() -> int:
    log.info("=" * 70)
    log.info("OFFLINE BINDING SIMULATION  (LLM_DISABLED=%s)", os.environ["LLM_DISABLED"])
    log.info("=" * 70)

    from report_builder.llm_router import llm_disabled
    assert llm_disabled() is True, "LLM_DISABLED not honoured"

    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        log.info("[verify] %-4s %s", "PASS" if cond else "FAIL", msg)
        if not cond:
            failures.append(msg)

    check(GOLD_BP.exists(), f"gold blueprint present at {GOLD_BP.name}")
    check(PLFS_CSV.exists(), f"synthetic PLFS CSV present at {PLFS_CSV.name}")
    check(ENERGY_CSV.exists(), f"energy CSV present at {ENERGY_CSV.name}")
    if failures:
        for f in failures:
            log.error("   ✗ %s", f)
        return 1

    blueprint = json.loads(GOLD_BP.read_text(encoding="utf-8"))
    store = Path(tempfile.mkdtemp(prefix="binding_sim_"))

    # ── Golden PLFS run (must be gate-clean) ──
    log.info("-" * 70)
    log.info("① GOLDEN PLFS  (blueprint × synthetic PLFS CSV)")
    df_plfs = pd.read_csv(PLFS_CSV)
    binding, dataset_ast = run_binding(
        blueprint, df_plfs,
        dataset_id="synthetic_plfs", source_file=PLFS_CSV.name,
        accept_proposed=True, storage_dir=store,
    )
    out1 = Path(tempfile.mkdtemp(prefix="binding_out_plfs_"))
    paths1 = write_artifacts(binding, dataset_ast, out1)

    # round-trip both ASTs
    check(DatasetAST.from_dict(dataset_ast).rowCount == len(df_plfs), "① datasetAST round-trips")
    rt = BindingAST.from_dict(binding.to_dict())
    check(rt.templateId == binding.templateId, "① bindingAST round-trips")
    for name, p in paths1.items():
        check(p.exists(), f"① artifact {name} written ({p.name})")

    cov = binding.coverage
    has_err = any(i.get("severity") == "error" for i in cov.get("issues", []))
    check(not has_err, "① PLFS golden run is gate-clean (no errors)")
    check(cov["entities"]["bound"] >= 5, f"① ≥5 entities bound (got {cov['entities']['bound']})")
    n_exec = cov["questions"]["executable"]
    check(n_exec >= 1, f"① ≥1 executable question (got {n_exec})")
    check(cov["questions"]["blocked"] == 0, "① no blocked questions")

    # spot-check a known binding: ent_wpr → Worker_Population_Ratio
    wpr = rt.binding_for("ent_wpr")
    check(wpr is not None and wpr.column_names == ["Worker_Population_Ratio"],
          "① ent_wpr bound to Worker_Population_Ratio")
    sector = rt.binding_for("ent_sector")
    check(sector is not None and sector.column_names == ["Sector"], "① ent_sector bound to Sector")
    period = rt.binding_for("ent_period")
    check(period is not None and period.column_names == ["Year"], "① ent_period bound to Year")

    # ── Energy second-archetype smoke test (domain-agnostic) ──
    log.info("-" * 70)
    log.info("② ENERGY SMOKE  (energy CSV, archetype proof)")
    energy_bp = {
        "templateMeta": {"templateId": "tpl_energy_smoke"},
        "entities": [
            {"entityId": "ent_state", "canonicalName": "State", "entityType": "dimension", "aliases": ["State"]},
            {"entityId": "ent_restype", "canonicalName": "Reserve Type", "entityType": "dimension",
             "aliases": ["reserve class"], "valueDomain": {"members": ["Proved", "Indicated", "Inferred"]}},
            {"entityId": "ent_reserves", "canonicalName": "Reserves", "entityType": "measure",
             "aliases": ["reserve quantity"]},
        ],
        "topics": [],
    }
    df_energy = pd.read_csv(ENERGY_CSV)
    binding2, dataset_ast2 = run_binding(
        energy_bp, df_energy,
        dataset_id="energy", source_file=ENERGY_CSV.name,
        accept_proposed=True, storage_dir=store,
    )
    check(DatasetAST.from_dict(dataset_ast2).archetype == "energy", "② energy archetype detected")
    rt2 = BindingAST.from_dict(binding2.to_dict())
    restype = rt2.binding_for("ent_restype")
    check(restype is not None and restype.cardinality == "memberSet",
          "② Reserve Type resolved as memberSet (wide members)")
    reserves = rt2.binding_for("ent_reserves")
    check(reserves is not None and reserves.cardinality == "composite",
          "② Reserves resolved as composite")
    groups = [g for g in dataset_ast2.get("columnGroups", [])]
    check(len(groups) == 1 and groups[0]["stem"] == "Reserve",
          "② single 'Reserve' measureGroup detected (no false collisions)")

    log.info("=" * 70)
    if failures:
        log.error("BINDING SIMULATION FAILED — %d check(s) failed:", len(failures))
        for f in failures:
            log.error("   ✗ %s", f)
        return 1
    log.info("BINDING SIMULATION PASSED — offline binder produced + verified.")
    log.info("PLFS golden gate-clean; energy archetype smoke OK.")
    log.info("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
