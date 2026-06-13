"""Offline end-to-end pipeline simulation (no API key, no LLM, no LayoutLM).

Runs the full extraction pipeline with ``LLM_DISABLED=1`` so every model call is
skipped and the deterministic pdfplumber + programmatic-fallback paths are taken.
Verifies the 3-file value-free output model is produced and well-formed.

Usage:
    python scripts/simulate_offline.py [path/to/input.pdf]

Exit code 0 = all checks passed, non-zero = a check failed.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# ── Force fully-offline, deterministic behaviour BEFORE importing the pipeline ──
os.environ["LLM_DISABLED"] = "1"
os.environ.setdefault("VLM_PROVIDER", "qwen")
os.environ.setdefault("REASONING_PROVIDER", "qwen")
os.environ.setdefault("EXTRACTION_PIPELINE", "v2")
os.environ.setdefault("CHECKPOINT_ENABLED", "false")
os.environ.setdefault("NEO4J_ENABLED", "false")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("simulate_offline")


def _default_pdf() -> Path:
    candidates = [
        REPO_ROOT / "test_data" / "Stat reports.pdf",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Fall back to any PDF under test_data / sample_reports / data
    for folder in ("test_data", "sample_reports", "data"):
        d = REPO_ROOT / folder
        if d.exists():
            pdfs = sorted(d.rglob("*.pdf"))
            if pdfs:
                return pdfs[0]
    raise SystemExit("No PDF found to simulate with. Pass a path explicitly.")


def main() -> int:
    pdf_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else _default_pdf()
    if not pdf_path.exists():
        raise SystemExit(f"Input PDF not found: {pdf_path}")

    log.info("=" * 70)
    log.info("OFFLINE SIMULATION  (LLM_DISABLED=%s)", os.environ["LLM_DISABLED"])
    log.info("Input: %s", pdf_path)
    log.info("=" * 70)

    # Sanity: confirm the router really is in offline mode.
    from report_builder.llm_router import (
        is_provider_available,
        llm_disabled,
        llm_text_call,
        llm_vision_call,
    )

    assert llm_disabled() is True, "LLM_DISABLED not honoured"
    assert is_provider_available("qwen", vision=True) is False, "qwen should be unavailable offline"
    assert is_provider_available("gemini") is False, "gemini should be unavailable offline"
    assert llm_text_call("ping", task="reasoning") is None, "text call must be skipped offline"
    assert llm_vision_call("ping", task="entity_extraction") is None, "vision call must be skipped offline"
    log.info("[check] router offline guards OK (all calls skipped)")

    from report_builder.extraction_pipeline import run_extraction_pipeline

    def _progress(stage: str, pct: int, data=None):
        log.info("[progress] %3d%%  %s", pct, stage)

    doc_title = pdf_path.stem
    ast = run_extraction_pipeline(
        pdf_path=pdf_path,
        doc_title=doc_title,
        source_hash="offline-sim",
        progress_callback=_progress,
    )

    # ── Verify the 3-file value-free output model ──
    import re

    safe_name = re.sub(r"[^\w\-]", "_", doc_title).strip("_") or "document"
    out_dir = REPO_ROOT / "outputs" / safe_name
    ast_file = out_dir / "template.ast.json"
    bp_file = out_dir / "template.blueprint.json"

    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        status = "PASS" if cond else "FAIL"
        log.info("[verify] %-4s %s", status, msg)
        if not cond:
            failures.append(msg)

    check(ast_file.exists(), f"① template.ast.json emitted at {ast_file}")
    check(bp_file.exists(), f"② template.blueprint.json emitted at {bp_file}")

    import json

    if ast_file.exists():
        skeleton = json.loads(ast_file.read_text(encoding="utf-8"))
        check(isinstance(skeleton, dict), "① skeleton parses as JSON object")

    if bp_file.exists():
        blueprint = json.loads(bp_file.read_text(encoding="utf-8"))
        topics = blueprint.get("topics") or []
        entities = blueprint.get("entities") or []
        check(len(topics) >= 1, f"② blueprint has ≥1 topic (got {len(topics)})")
        check(len(entities) >= 1, f"② blueprint has ≥1 entity (got {len(entities)})")
        # Every question must have a single valid questionType + an analyticsSpec (P4/D8).
        from report_builder.question_quality import QUESTION_TYPES

        n_q = 0
        bad_type = 0
        no_spec = 0
        for t in topics:
            for q in t.get("questions") or []:
                n_q += 1
                if q.get("questionType") not in QUESTION_TYPES:
                    bad_type += 1
                if not q.get("analyticsSpec"):
                    no_spec += 1
        check(n_q >= 1, f"② blueprint has ≥1 question (got {n_q})")
        check(bad_type == 0, f"② all questions have a valid questionType ({bad_type} bad)")
        check(no_spec == 0, f"② all questions carry analyticsSpec ({no_spec} missing)")
        # value-free invariant on the emitted templates
        from report_builder.template_emit import assert_value_free

        v1 = assert_value_free(skeleton, label="①") if ast_file.exists() else []
        v2 = assert_value_free(blueprint, label="②")
        check(not v1, f"① value-free invariant holds ({len(v1)} violations)")
        check(not v2, f"② value-free invariant holds ({len(v2)} violations)")

    # ── Verify the pipeline trace recorded the offline path ──
    trace = ast.get("pipeline_trace", {})
    p1 = trace.get("passes", {}).get("pass1_layout", {})
    check(p1.get("layoutlm_used") is False, "pass1 used pdfplumber fallback (LayoutLM skipped)")
    p2 = trace.get("passes", {}).get("pass2_entities", {})
    check(p2.get("vlm_success", 0) == 0, "pass2 made no successful VLM calls (offline)")

    log.info("=" * 70)
    if failures:
        log.error("SIMULATION FAILED — %d check(s) failed:", len(failures))
        for f in failures:
            log.error("   ✗ %s", f)
        return 1
    log.info("SIMULATION PASSED — offline 3-file model produced and verified.")
    log.info("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
