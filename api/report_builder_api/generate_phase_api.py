"""Generation-phase REST API (signature-keyed, filesystem-backed).

Thin HTTP wrapper over :mod:`report_builder.generation`. The generation core
stays free of any web dependency; this router only translates HTTP ⇄ the S4–S6
pipeline, reusing the binding-phase stash (datasetAST + blueprint + CSV) so a
report can be generated straight after ``/binding-phase/.../finalize`` without
re-uploading anything.

Endpoints (prefix ``/report-builder/generate-phase``):
  POST /{template_id}/{signature}/generate   run S4→S6, persist + return summary
  GET  /{template_id}/{signature}/report      the assembled report.output.ast.json
  GET  /{template_id}/{signature}/report.html the rendered standalone HTML

The binding must be finalized first (its confirmations live in the review record).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from report_builder.binding import review as R
from report_builder.binding.report import build_coverage
from report_builder.binding.question_binder import bind_questions
from report_builder.binding.schema import BindingAST, DatasetAST, EntityBinding
from report_builder.generation import (
    assemble_report,
    apply_edit,
    apply_profile,
    build_plans,
    bump_version,
    current_version,
    deep_merge,
    effective_profile,
    fill_visuals,
    narrate,
    pdf_available,
    render_flags,
    render_html,
    render_pdf,
    run_analytics,
    run_execution,
    attach_insights,
    enrich_report_provenance,
    ensure_lifecycle,
    evaluate_gate,
    validate_report,
    verify_report,
    EditRejected,
    ReportOverrides,
    TemplateProfile,
)
from report_builder.binding.execution_bundle_factory import build_execution_bundle
from report_builder.binding.freeze_store import get_freeze_info, load_frozen_bundle
from report_builder.generation.bundle_adapter import adapt_bundle
from report_builder.generation.run_modes import (
    DataDriftError,
    bundle_data_hash,
    compute_data_content_hash,
    resolve_mode,
    resolve_publish_mode,
    verify_data_hash,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-builder/generate-phase", tags=["generate-phase"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GOLD_DIR  = _REPO_ROOT / "report_builder" / "gold_standard"
_GOLD_TEMPLATE_AST = _GOLD_DIR / "template.ast.json"   # default/fallback


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class GenerateIn(BaseModel):
    period: Optional[str] = None            # reference period label, e.g. "2023-24"
    report_id: Optional[str] = None
    use_llm: Optional[bool] = None          # None ⇒ auto (on iff LLM enabled)
    plan_source: Optional[str] = None       # "bundle" (gold, default) | "legacy" (override; else env GENERATION_PLAN_SOURCE)
    mode: Optional[str] = None              # "fresh" (default) | "frozen" | "test" (else env GENERATION_MODE)
    bundle_version: Optional[int] = None    # frozen mode: which frozen version to load (None ⇒ latest)
    publish_mode: Optional[str] = None      # "strict" (default, FAIL→409) | "draft" (FAIL allowed, non-publishable)


class GenerateOut(BaseModel):
    template_id: str
    signature: str
    report_id: str
    valid: bool
    errors: list[str]
    warnings: list[str]
    stats: dict[str, Any]
    coverage: dict[str, Any]
    narrative_trace: list[dict[str, Any]]
    fill_trace: list[dict[str, Any]]
    plan_source: str = "execution_bundle"   # which planner produced analyticsAST.plans
    mode: str = "fresh"                      # fresh | frozen | test
    data_content_hash: str = ""             # value-level hash of the executed dataset
    bundle_version: Optional[int] = None    # frozen bundle version used (when known)
    verdict: str = "PASS"                    # verifier gate: PASS | WARN | FAIL
    quality_score: float = 0.0              # report quality score 0..100
    publishable: bool = True                # False when verifier FAILed (draft mode)
    publish_mode: str = "strict"            # strict | draft


# ---------------------------------------------------------------------------
# Stash access (shared with the binding-phase router)
# ---------------------------------------------------------------------------


def _stash_path(template_id: str, signature: str, suffix: str) -> Path:
    safe = template_id or "template"
    return R._DEFAULT_STORE / f"{safe}__{signature}.{suffix}"


def _read_stash(template_id: str, signature: str) -> tuple[DatasetAST, dict[str, Any], "Any"]:
    import pandas as pd

    ds_path = _stash_path(template_id, signature, "dataset.json")
    bp_path = _stash_path(template_id, signature, "blueprint.json")
    csv_path = _stash_path(template_id, signature, "data.csv")
    if not (ds_path.exists() and bp_path.exists() and csv_path.exists()):
        raise HTTPException(
            status_code=409,
            detail="binding session data expired — please re-run binding 'start' for this dataset",
        )
    dataset = DatasetAST.from_dict(json.loads(ds_path.read_text(encoding="utf-8")))
    blueprint = json.loads(bp_path.read_text(encoding="utf-8"))
    df = pd.read_csv(csv_path)
    return dataset, blueprint, df


def _report_path(template_id: str, signature: str) -> Path:
    return _stash_path(template_id, signature, "report.output.ast.json")


def _html_path(template_id: str, signature: str) -> Path:
    return _stash_path(template_id, signature, "report.html")


def _profile_path(template_id: str, signature: str) -> Path:
    return _stash_path(template_id, signature, "profile.json")


def _overrides_path(template_id: str, signature: str) -> Path:
    return _stash_path(template_id, signature, "overrides.json")


def _version_path(template_id: str, signature: str, n: int) -> Path:
    return _stash_path(template_id, signature, f"report.v{n}.output.ast.json")


def _list_versions(template_id: str, signature: str) -> list[int]:
    prefix = f"{template_id or 'template'}__{signature}.report.v"
    out: list[int] = []
    for path in R._DEFAULT_STORE.glob(f"{template_id or 'template'}__{signature}.report.v*.output.ast.json"):
        name = path.name[len(prefix):]
        num = name.split(".", 1)[0]
        if num.isdigit():
            out.append(int(num))
    return sorted(out)


def _load_profile(template_id: str, signature: str) -> dict[str, Any]:
    path = _profile_path(template_id, signature)
    if path.exists():
        return TemplateProfile.from_dict(json.loads(path.read_text(encoding="utf-8"))).to_dict()
    return TemplateProfile.default().to_dict()


def _load_overrides(template_id: str, signature: str) -> dict[str, Any]:
    path = _overrides_path(template_id, signature)
    if path.exists():
        return ReportOverrides.from_dict(json.loads(path.read_text(encoding="utf-8"))).to_dict()
    return {}


def _load_template_ast(template_id: str = "") -> dict[str, Any]:
    """Load a template AST, preferring the template-specific one if it exists.

    Search order:
      1. gold_standard/<template_id>/<template_id>.template.ast.json
      2. gold_standard/<template_id>.template.ast.json
      3. gold_standard/template.ast.json (generic fallback)
    """
    if template_id:
        # 1. Subdirectory: gold_standard/energy_enterprise_v2/energy_enterprise_v2.template.ast.json
        # Strip 'tpl_' prefix for directory names
        tid = template_id.replace("tpl_", "")
        sub = _GOLD_DIR / tid / f"{tid}.template.ast.json"
        if sub.exists():
            logger.info("[template_ast] loaded %s", sub.name)
            return json.loads(sub.read_text(encoding="utf-8-sig"))
        # 2. Flat: gold_standard/energy_enterprise_v2.template.ast.json
        flat = _GOLD_DIR / f"{tid}.template.ast.json"
        if flat.exists():
            logger.info("[template_ast] loaded %s", flat.name)
            return json.loads(flat.read_text(encoding="utf-8-sig"))
        # 3. With tpl_ prefix
        sub2 = _GOLD_DIR / template_id / f"{template_id}.template.ast.json"
        if sub2.exists():
            logger.info("[template_ast] loaded %s", sub2.name)
            return json.loads(sub2.read_text(encoding="utf-8-sig"))
    # Fallback: generic template
    logger.warning("[template_ast] no template-specific AST for '%s', using generic fallback", template_id)
    return json.loads(_GOLD_TEMPLATE_AST.read_text(encoding="utf-8-sig"))


def _load_slot_graph(template_id: str, signature: str) -> dict[str, Any] | None:
    """Load the semantic slot graph (declares per-slot chart types, etc.).

    Prefers the binding stash (authoritative for this session), then the gold
    template directory. Returns ``None`` when no slot graph exists.
    """
    stash = _stash_path(template_id, signature, "semantic_slot_graph.json")
    if stash.exists():
        try:
            return json.loads(stash.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            pass
    if template_id:
        tid = template_id.replace("tpl_", "")
        for cand in (_GOLD_DIR / tid / f"{tid}.semantic_slot_graph.json",
                     _GOLD_DIR / f"{tid}.semantic_slot_graph.json"):
            if cand.exists():
                try:
                    return json.loads(cand.read_text(encoding="utf-8-sig"))
                except Exception:  # noqa: BLE001
                    pass
    return None


def _iter_questions(blueprint: dict[str, Any]):
    """Walk the full topic→chapter→section→question hierarchy, yielding
    ``(question_dict, section_path_list)`` for every question found.

    The energy-enterprise blueprint stores questions at the *section* level
    (topics[].chapters[].sections[].questions[]), not at the topic level.
    Earlier helpers only walked ``topic.questions`` and found nothing.
    """
    for topic in blueprint.get("topics") or []:
        t_title = topic.get("title") or topic.get("topicId") or "Topic"
        # questions directly on topic (flat blueprints)
        for q in topic.get("questions") or []:
            yield q, [t_title]
        for chapter in topic.get("chapters") or []:
            c_title = chapter.get("title") or chapter.get("chapterId") or "Chapter"
            for q in chapter.get("questions") or []:
                yield q, [t_title, c_title]
            for section in chapter.get("sections") or []:
                s_title = section.get("title") or section.get("sectionId") or "Section"
                for q in section.get("questions") or []:
                    yield q, [t_title, c_title, s_title]


def _question_meta(blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for q, _path in _iter_questions(blueprint):
        qid = q.get("questionId")
        if qid:
            meta[qid] = {"label": q.get("intent") or q.get("sourceHeading") or q.get("questionText") or qid}
    return meta


def _prose_config(blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ent = {e.get("entityId"): e for e in (blueprint.get("entities") or [])}

    def name(ref: Any) -> str:
        e = ent.get(ref) or {}
        return e.get("canonicalName") or e.get("entityName") or e.get("name") or ""

    cfg: dict[str, dict[str, Any]] = {}
    for q, _path in _iter_questions(blueprint):
        qid = q.get("questionId")
        spec = q.get("analyticsSpec") or {}
        if not qid:
            continue
        # Handle both structured measure spec and flat entity-ref formats
        measure_spec = spec.get("measure") or {}
        if isinstance(measure_spec, dict):
            measure_ref = measure_spec.get("entityRef") or measure_spec.get("entity")
            agg = measure_spec.get("agg") or measure_spec.get("aggregation") or ""
            unit = measure_spec.get("unit")
        else:
            measure_ref = str(measure_spec) if measure_spec else None
            agg = spec.get("aggregation") or ""
            unit = None
        # Fallback: sortBy as the measure entity (for rank operations)
        if not measure_ref:
            measure_ref = spec.get("sortBy") or spec.get("grain")
        raw_groups = spec.get("groupBy") or []
        group_refs = []
        for g in raw_groups:
            if isinstance(g, dict):
                group_refs.append(g.get("entityRef") or g.get("entity"))
            elif isinstance(g, str):
                group_refs.append(g)
        # Also add grain as a group if not already listed
        grain = spec.get("grain")
        if grain and grain not in group_refs:
            group_refs.insert(0, grain)
        mlabel = name(measure_ref) if measure_ref else ""
        dim_label = name(group_refs[0]) if group_refs else ""
        cfg[qid] = {
            "measureLabel": mlabel or (q.get("questionText") or qid)[:40],
            "measureShort": mlabel.split("(")[0].strip() if mlabel else "",
            "dimensionNoun": dim_label.lower() if dim_label else "",
            "unit": unit or ("percent" if ("ratio" in agg or "share" in agg) else None),
            "operation": spec.get("operation") or "",
        }
    return cfg


def _question_registry(blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a lookup: questionId → {title, questionText, sectionPath, componentTypes}.

    Used by the generation-queue and generate-component endpoints to provide
    rich metadata (proper titles, section breadcrumbs, component types) for
    the frontend's document canvas and trace sidebar.
    """
    registry: dict[str, dict[str, Any]] = {}
    for q, section_path in _iter_questions(blueprint):
        qid = q.get("questionId")
        if not qid:
            continue
        # Gather component types from answerStructure.components (kind) or
        # outputContract.components (componentType/type) — support both shapes.
        components: list[str] = []
        ans = q.get("answerStructure") or {}
        for comp in ans.get("components") or []:
            ck = comp.get("kind") or comp.get("componentKind") or comp.get("componentType") or comp.get("type")
            if ck:
                components.append(ck)
        if not components:
            oc = q.get("outputContract") or {}
            for comp in oc.get("components") or []:
                ct = comp.get("componentType") or comp.get("type")
                if ct:
                    components.append(ct)
        # Fallback: infer from analyticsSpec
        if not components:
            spec = q.get("analyticsSpec") or {}
            op = (spec.get("operation") or "").lower()
            if "rank" in op or "group" in op:
                components = ["table", "narrative"]
            elif "trend" in op or "growth" in op:
                components = ["chart", "narrative"]
            elif "share" in op or "ratio" in op:
                components = ["chart", "narrative"]
            else:
                components = ["narrative"]

        registry[qid] = {
            "title": q.get("questionText") or q.get("intent") or q.get("sourceHeading") or qid,
            "questionText": q.get("questionText") or "",
            "sectionPath": section_path,
            "componentTypes": components,
            "intent": q.get("intent") or "",
        }
    return registry


# Component kind → frontend block component_type.
_KIND_TO_COMPONENT_TYPE = {
    "narrative": "narrative",
    "table": "table",
    "chart": "chart",
    "metric": "formula_metric",
    "methodology": "narrative",
    "source_note": "source_note",
    "glossary": "narrative",
    "caveat": "narrative",
}


def _build_component_queue(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    """One queue item per *component* (narrative/table/chart/metric) in document order.

    This is the single source of truth shared by ``get_generation_queue`` and
    ``generate_single_component`` so the index↔component mapping is identical on
    both sides. Expanding by component (not by fanned-out measure) means the canvas
    builds the SAME rich block set as the full ``generate`` report — narrative +
    table + chart per question — instead of duplicate measure fan-outs.
    """
    items: list[dict[str, Any]] = []
    for q, section_path in _iter_questions(blueprint):
        qid = q.get("questionId")
        if not qid:
            continue
        q_title = q.get("questionText") or q.get("intent") or qid
        ans = q.get("answerStructure") or {}
        comps = ans.get("components") or []
        # Order components by their declared 'order' (narrative usually first).
        comps = sorted(comps, key=lambda c: c.get("order", 99))
        if not comps:
            comps = [{"kind": "narrative"}]
        for comp in comps:
            kind = (comp.get("kind") or comp.get("componentKind")
                    or comp.get("componentType") or comp.get("type") or "narrative")
            ctype = _KIND_TO_COMPONENT_TYPE.get(kind, "narrative")
            label = {"table": "Table", "chart": "Chart", "metric": "Metric"}.get(kind, "")
            title = f"{q_title} — {label}" if label and kind != "narrative" else q_title
            items.append({
                "index": len(items),
                "question_id": qid,
                "component_id": comp.get("componentId") or f"{qid}_{kind}",
                "component_kind": kind,
                "component_type": ctype,
                "title": title,
                "section_path": section_path,
            })
    return items


def _pretty(col: str) -> str:
    """Human label for a column (drop trailing measure noise)."""
    return str(col or "").strip()


def _measure_unit(bp_q: dict[str, Any], dataset: "Any") -> str:
    """Best-effort unit for a question's primary measure from requiredEntities/dataset."""
    for r in bp_q.get("requiredEntities") or []:
        if (r.get("role") or "").lower() == "measure" and r.get("unit"):
            return str(r["unit"])
    return ""


def _fmt_value(value: Any, unit: str | None = None) -> str:
    """Compact human number with optional unit (Indian grouping for big ints)."""
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    s = f"{n:,.0f}" if float(n).is_integer() else f"{n:,.2f}"
    return f"{s}{('%' if unit == 'percent' else (' ' + unit if unit else ''))}"


def _NUMBER_DRIFT(original: str, improved: str) -> bool:
    """True if the LLM-polished prose introduced/changed numbers vs the grounded draft.

    Guards against hallucinated figures: the rewrite must reuse exactly the same set
    of numeric tokens as the deterministic draft (order-independent).
    """
    import re as _re
    num = _re.compile(r"\d[\d,]*\.?\d*")
    return sorted(num.findall(original)) != sorted(num.findall(improved))




def _build_component_template(
    base_template: dict[str, Any],
    question_id: str,
    qinfo: dict[str, Any],
    plan: "Any",
) -> dict[str, Any]:
    """Build a per-component template AST for narration.

    The static template AST has contentAST.blocks pre-defined for specific
    question IDs. When doing per-component generation, we need to ensure the
    narrator can find a block matching this question. If no block exists, we
    dynamically inject one.

    Returns a shallow copy of the base template with an ensured content block.
    """
    import copy
    tpl = copy.deepcopy(base_template)

    # Check if the template already has a block for this question
    content_ast = tpl.get("contentAST") or {}
    blocks = content_ast.get("blocks", [])
    has_match = any(
        _block_matches_question(b, question_id)
        for b in blocks
    )

    if has_match:
        # Template has a matching block — use it as-is
        return tpl

    # No matching block — inject a dynamic one for this question
    title = qinfo.get("title") or question_id
    measure_col = plan.measureColumn if hasattr(plan, "measureColumn") else ""
    op = plan.planRec.operation if hasattr(plan, "planRec") else ""

    dynamic_block = {
        "blockId": f"p_{question_id}_{measure_col}".replace(" ", "_").lower(),
        "kind": "paragraph",
        "styleRef": "bodyText",
        "content": "",
        "biQuery": question_id,
        "templateQuestion": title,
        "slot": {
            "fillFrom": question_id,
            "operation": op,
            "measure": measure_col,
        },
        "provenance": {"questionId": question_id},
    }

    content_ast.setdefault("blocks", []).append(dynamic_block)
    tpl["contentAST"] = content_ast
    return tpl


def _block_matches_question(block: dict[str, Any], question_id: str) -> bool:
    """Check if a template content block targets this question ID."""
    slot_ref = (block.get("slot") or {}).get("fillFrom") or block.get("biQuery") or ""
    if slot_ref == question_id:
        return True
    # Also match base question from compound refs like "q_coal_state_rank__chart"
    if slot_ref and question_id and slot_ref.startswith(question_id):
        return True
    return False


def _surface_degraded_caveats(report: dict[str, Any], adapted: "list | None") -> None:
    """Make DEGRADED-plan diagnostics visible in the report (transparency).

    The S4 bundle adapter flags honest analytic caveats (e.g. summing a rate
    column) on DEGRADED plans. We record them — deduplicated, each tagged with its
    questionId so the audit can trace them — into ``auditAST.caveats``,
    ``metadata.warnings`` and a reader-facing ``Caveats & Limitations`` content
    block. No values are changed; the report simply stops hiding its limitations.
    """
    if not adapted:
        return
    seen: set[str] = set()
    caveats: list[dict[str, Any]] = []
    lines: list[str] = []
    for plan in adapted:
        status = (getattr(plan, "status", "") or "").upper()
        diagnostics = getattr(plan, "diagnostics", None) or []
        if status != "DEGRADED" and not diagnostics:
            continue
        qid = getattr(plan, "questionId", "") or getattr(getattr(plan, "planRec", None), "questionId", "")
        for diag in diagnostics:
            text = str(diag).strip()
            if not text:
                continue
            key = f"{qid}::{text}"
            if key in seen:
                continue
            seen.add(key)
            # Tag the caveat with its question id so CAVEAT_VISIBILITY can trace it.
            caveats.append({"questionId": qid, "severity": "warn", "message": text})
            lines.append(f"{qid}: {text}" if qid else text)
    if not caveats:
        return

    audit = report.setdefault("auditAST", {})
    existing_caveats = audit.get("caveats")
    audit["caveats"] = (existing_caveats or []) + caveats
    # Plain-text warnings (questionId embedded) — these are what the verifier scans.
    audit_warnings = audit.get("warnings") or []
    audit["warnings"] = audit_warnings + lines

    metadata = report.setdefault("metadata", {})
    meta_warnings = metadata.get("warnings") or []
    metadata["warnings"] = meta_warnings + lines

    # Reader-facing block so the caveats are visible in the rendered report too.
    content = report.setdefault("contentAST", {})
    blocks = content.setdefault("blocks", [])
    blocks.append({
        "blockId": "caveats_limitations",
        "kind": "key_findings",
        "title": "Caveats & Limitations",
        "items": [c["message"] for c in caveats],
        "provenance": {"derivedFrom": "auditAST.caveats"},
        "slot": {"status": "filled"},
    })


def _rebuild_binding(template_id: str, signature: str, dataset: DatasetAST,
                     blueprint: dict[str, Any], df: "Any") -> BindingAST:
    """Rebuild the finalized binding from the persisted review record + stash."""
    record = R.load_record(template_id, signature)
    if record is None:
        raise HTTPException(status_code=404, detail="no binding record — finalize binding first")
    entity_bindings = [EntityBinding.from_dict(p) for p in record.proposals]
    binding = BindingAST(
        templateId=record.templateId,
        datasetId=record.datasetId,
        datasetSignature=signature,
        entityBindings=entity_bindings,
    )
    R.apply_confirmations(binding, record)
    binding.questionBindings = bind_questions(blueprint, binding.entityBindings, dataset, df=df)
    build_coverage(binding)
    return binding


def _plan_source(body: GenerateIn) -> str:
    """Resolve the plan source: request override > env > default 'bundle'.

    'bundle' (gold) sources analyticsAST.plans from the team's ExecutionBundle.
    'legacy' uses the older blueprint+BindingAST planner (fallback only).
    """
    choice = (body.plan_source or os.getenv("GENERATION_PLAN_SOURCE") or "bundle").strip().lower()
    return "legacy" if choice == "legacy" else "bundle"


def _build_bundle(template_id: str, signature: str, dataset: DatasetAST,
                  blueprint: dict[str, Any], df: "Any", data_content_hash: str = ""):
    """Build the canonical ExecutionBundle for this dataset (the S4 input contract).

    Always builds from the *current* stash + review record via the single canonical
    factory, which also freezes the result for reproducibility/audit. We intentionally
    do NOT prefer a previously-frozen bundle here: a stale frozen artifact from an
    earlier blueprint/binding must never silently drive generation.

    ``data_content_hash`` (when provided) is pinned into the frozen bundle's
    ``dataframeRef`` so a later ``frozen`` run can detect data drift.
    """
    record = R.load_record(template_id, signature)
    if record is None:
        raise HTTPException(status_code=404, detail="no binding record — finalize binding first")
    df_path = str(_stash_path(template_id, signature, "data.csv"))
    return build_execution_bundle(
        template_id=template_id,
        signature=signature,
        record=record,
        dataset=dataset,
        blueprint=blueprint,
        dataframe_path=df_path,
        df=df,
        data_content_hash=data_content_hash,
    )


def _load_fixture_bundle(template_id: str, signature: str):
    """Load a fixture ExecutionBundle for ``test`` mode (deterministic regression).

    Reads ``<stash>/<template>__<signature>.bundle.json`` — a pre-built bundle laid
    down alongside the fixture dataset. ``test`` mode runs straight from this fixture
    without rebuilding (no factory/binder) or freezing (no real-storage writes), so a
    regression always executes the exact same plans over the exact same data.
    """
    from report_builder.binding.execution_contracts import ExecutionBundle

    path = _stash_path(template_id, signature, "bundle.json")
    if not path.exists():
        return None
    try:
        return ExecutionBundle.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("[generate-phase] failed to load fixture bundle %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{template_id}/{signature}/generate", response_model=GenerateOut)
def generate_report(template_id: str, signature: str, body: GenerateIn) -> GenerateOut:
    """Run the full generation pipeline (S4→S6) and persist the report.

    Reuses the binding-phase stash (datasetAST + blueprint + CSV) and the
    finalized binding (review record). Produces analyticsAST + evidenceAST →
    filled visuals + narrative → assembled ``report.output.ast.json`` (validated)
    → standalone HTML. Idempotent: overwrites the prior report for this dataset.
    """
    dataset, blueprint, df = _read_stash(template_id, signature)
    binding = _rebuild_binding(template_id, signature, dataset, blueprint, df)
    if any(i.get("severity") == "error" for i in binding.coverage.get("issues", [])):
        raise HTTPException(status_code=409, detail="binding coverage gate has errors — resolve before generating")

    template = _load_template_ast(template_id)
    context = {
        "dataset": {"title": (blueprint.get("metadata") or {}).get("title") or dataset.datasetId},
        "period": {"current": body.period or ""},
    }

    # S4 — analytics.
    # GOLD PATH (default): plans come from the team's validated ExecutionBundle, not a
    # re-derived planner. Readiness is honored here: NOT_READY blocks generation, and
    # the adapter never emits BLOCKED plans. LEGACY planner stays behind a flag.
    #
    # Reproducibility (generation modes): the dataset is pinned by a value-level
    # contentHash. `fresh` builds + freezes the bundle with that hash; `frozen` loads a
    # frozen bundle and refuses to run if the live data has drifted from the pinned hash.
    mode = resolve_mode(body.mode)
    data_content_hash = compute_data_content_hash(df)
    plan_source = _plan_source(body)
    bundle_version: Optional[int] = None
    bundle = None
    adapted = None
    if plan_source == "legacy":
        plans = build_plans(blueprint, binding, dataset)
        analytics_obj, evidence_obj, row_index = run_analytics(
            plans, df, question_meta=_question_meta(blueprint))
    else:
        if mode == "frozen":
            bundle = load_frozen_bundle(template_id, signature, body.bundle_version)
            if bundle is None:
                raise HTTPException(
                    status_code=404,
                    detail="no frozen bundle for this dataset — run a fresh generation first",
                )
            # Reproducibility gate: the live data must match the pinned snapshot.
            try:
                verify_data_hash(bundle, df)
            except DataDriftError as drift:
                raise HTTPException(status_code=409, detail=str(drift)) from drift
            info = get_freeze_info(template_id, signature) or {}
            bundle_version = body.bundle_version or info.get("version")
            data_content_hash = bundle_data_hash(bundle) or data_content_hash
        elif mode == "test":
            bundle = _load_fixture_bundle(template_id, signature)
            if bundle is None:
                raise HTTPException(
                    status_code=404,
                    detail="no fixture bundle for this dataset — test mode needs a .bundle.json fixture",
                )
            data_content_hash = bundle_data_hash(bundle) or data_content_hash
        else:  # fresh
            bundle = _build_bundle(template_id, signature, dataset, blueprint, df,
                                   data_content_hash=data_content_hash)
            if bundle.status == "NOT_READY":
                raise HTTPException(
                    status_code=409,
                    detail="execution bundle is NOT_READY — binding has blocking errors; resolve before generating",
                )
            info = get_freeze_info(template_id, signature) or {}
            bundle_version = info.get("version")
        # Adapt the full bundle (carries formulaSpec / normalizationPlan / lineage /
        # multi-measure fan-out) and route each plan through the S4 coordinator, which
        # applies normalization, computes formulas, and runs simple aggregations.
        adapted = adapt_bundle(bundle)
        if not adapted:
            raise HTTPException(
                status_code=409,
                detail="execution bundle has no runnable plans (all BLOCKED) — nothing to generate",
            )
        analytics_obj, evidence_obj, row_index = run_execution(
            adapted, df, question_meta=_question_meta(blueprint))
    analytics, evidence = analytics_obj.to_dict(), evidence_obj.to_dict()

    # S5a — fill visuals; S5b — narrate
    visuals = fill_visuals(template, analytics, evidence, context=context)
    narrated = narrate(template, analytics, evidence, context=context,
                       questions=_prose_config(blueprint), use_llm=body.use_llm)

    # S5a-bridge — documentMap archetype. Templates that ship a ``documentMap``
    # tree (topic→chapter→section→question→slots) instead of the
    # ``semanticAST.sections`` + ``tableAST``/``chartAST`` slot archetype yield
    # nothing from fill_visuals. Synthesize render-ready sections + filled visuals
    # from the computed analytics (linked by questionId) so the standalone report
    # renders fully. Gated: only when documentMap is a node list and the template
    # has no semantic sections — never affects the existing slot archetype.
    _doc_map = template.get("documentMap")
    _has_sections = bool((template.get("semanticAST") or {}).get("sections"))
    if isinstance(_doc_map, list) and _doc_map and not _has_sections:
        from report_builder.generation.document_map_bridge import bridge_document_map_report
        _slot_graph = _load_slot_graph(template_id, signature)
        _bridged = bridge_document_map_report(_doc_map, analytics, evidence, slot_graph=_slot_graph)
        if _bridged["semanticAST"]["sections"]:
            template = {**template, "semanticAST": _bridged["semanticAST"]}
            visuals["tableAST"] = _bridged["tableAST"]
            visuals["chartAST"] = _bridged["chartAST"]
            visuals["figureAST"] = _bridged["figureAST"]
            visuals.setdefault("fillTrace", [])
            _content = narrated.setdefault("contentAST", {"blocks": []})
            _content["blocks"] = (_content.get("blocks") or []) + _bridged["blocks"]

    # S5c — assemble + validate
    report_id = body.report_id or f"rpt_{template_id or 'generated'}_{signature[:8]}"
    report = assemble_report(
        template,
        datasetAST=dataset,
        bindingAST=binding,
        analyticsAST=analytics,
        evidenceAST=evidence,
        visuals=visuals,
        contentAST=narrated["contentAST"],
        report_id=report_id,
        period={"current": body.period} if body.period else None,
    )
    result = validate_report(report, row_index=row_index)
    report["auditAST"]["warnings"] = result["warnings"]

    # S5e — provenance + statistical-context enrichment. Closes the audit chain:
    # per-plan lineage into each artifact's provenance, coverage + dataset identity
    # under auditAST.provenance, and the bundle's StatisticalContext surfaced under
    # auditAST.statisticalContext. Additive — the gold report shape is unchanged.
    enrich_report_provenance(
        report, adapted=adapted, evidence=evidence, bundle=bundle,
        content_hash=data_content_hash,
    )

    # S5e-caveats — surface DEGRADED-plan diagnostics as visible caveats. The S4
    # adapter records honest warnings (e.g. "X is a rate but aggregation is sum") on
    # DEGRADED plans; make them transparent in the report (auditAST.caveats +
    # metadata.warnings + a reader-facing "Caveats & Limitations" block) instead of
    # hiding them. This keeps the report trustworthy and satisfies CAVEAT_VISIBILITY.
    _surface_degraded_caveats(report, adapted)

    # S5d — verify: judge trust without mutating the report's values. The verdict is
    # recorded into auditAST and then enforced by the publish gate below.
    verification = verify_report(
        report, analytics, evidence,
        bundle=bundle, adapted=adapted, dataframe=df,
        row_index=row_index, content_hash=data_content_hash,
    )
    report["auditAST"]["verification"] = verification.to_dict()

    # S5f — BI insights: evidence-backed findings derived from the trusted analytics
    # only (never the raw data). Records machine-readable objects under
    # auditAST.insights + a human "Key Findings" block. Deterministic / offline.
    attach_insights(
        report,
        quality=verification.quality,
        verifier_checks=[c.to_dict() for c in verification.checks],
    )

    # S5g — publish gate. A verifier FAIL is never publishable; in `strict` (official,
    # default) mode it blocks output with 409 and nothing is persisted, in `draft` mode
    # the report is returned but clearly marked non-publishable. WARN never blocks.
    publish_mode = resolve_publish_mode(body.publish_mode)
    gate = evaluate_gate(verification, publish_mode=publish_mode)
    report["auditAST"]["gate"] = gate.to_dict()
    report["auditAST"]["publishable"] = gate.publishable
    if gate.blocked:
        logger.warning("[generate-phase] %s__%s — BLOCKED by verifier gate: %s",
                       template_id, signature, gate.reason)
        raise HTTPException(status_code=409, detail=gate.reason)

    # S5h — lifecycle defaults: a freshly generated, publishable report starts at
    # publishStatus=generated with an empty officer-review/lifecycle audit log.
    ensure_lifecycle(report)

    # S6 — render + persist
    _tmeta = template.get("metadata") or {}
    _bmeta = blueprint.get("templateMeta") or blueprint.get("metadata") or {}
    _doc_title = (
        _tmeta.get("name") or _tmeta.get("title")
        or _bmeta.get("title") or _bmeta.get("name")
        or blueprint.get("name")
    )
    html_str = render_html(report, title=_doc_title) if _doc_title else render_html(report)
    _report_path(template_id, signature).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _html_path(template_id, signature).write_text(html_str, encoding="utf-8")

    logger.info("[generate-phase] %s__%s — report=%s valid=%s errors=%d plans=%s mode=%s hash=%s",
                template_id, signature, report_id, result["ok"], len(result["errors"]),
                plan_source, mode, data_content_hash)

    return GenerateOut(
        template_id=template_id,
        signature=signature,
        report_id=report_id,
        valid=result["ok"],
        errors=result["errors"],
        warnings=result["warnings"],
        stats=result["stats"],
        coverage=report["metadata"]["coverage"],
        narrative_trace=narrated["narrativeTrace"],
        fill_trace=visuals["fillTrace"],
        plan_source="execution_bundle" if plan_source == "bundle" else "legacy_planner",
        mode=mode,
        data_content_hash=data_content_hash,
        bundle_version=bundle_version,
        verdict=verification.verdict,
        quality_score=verification.quality.get("finalScore", 0.0),
        publishable=gate.publishable,
        publish_mode=publish_mode,
    )


# ---------------------------------------------------------------------------
# Per-component generation (step-by-step officer-controlled)
# ---------------------------------------------------------------------------


class ComponentQueueItem(BaseModel):
    index: int
    plan_id: str
    question_id: str = ""
    component_type: str = ""
    title: str = ""
    section_path: list[str] = []
    status: str = "pending"  # pending | generating | done | skipped


class GenerateComponentIn(BaseModel):
    index: int
    use_llm: Optional[bool] = None
    redo: bool = False


class GenerateComponentOut(BaseModel):
    index: int
    plan_id: str
    component_type: str
    title: str
    content: dict[str, Any] = {}
    narrative: str = ""
    status: str = "done"
    next_index: Optional[int] = None
    next_preview: Optional[dict[str, Any]] = None
    total: int = 0
    progress_pct: float = 0.0


@router.get("/{template_id}/{signature}/generation-queue")
def get_generation_queue(template_id: str, signature: str) -> list[dict[str, Any]]:
    """Return the ordered queue of components to generate, with metadata for preview.

    One item per *component* (narrative/table/chart/metric) in document order — the
    same expansion the full report uses — so the canvas builds the complete rich
    report (narrative + table + chart per question) rather than duplicate measure
    fan-outs. Blocked questions are skipped.
    """
    dataset, blueprint, df = _read_stash(template_id, signature)

    # Honor blocked questions: drop their components from the queue.
    binding = _rebuild_binding(template_id, signature, dataset, blueprint, df)
    data_content_hash = compute_data_content_hash(df)
    bundle = _build_bundle(template_id, signature, dataset, blueprint, df,
                           data_content_hash=data_content_hash)
    blocked_qids = {b.get("questionId") for b in (bundle.blockedQuestions or [])}

    queue_items = _build_component_queue(blueprint)
    queue: list[dict[str, Any]] = []
    for it in queue_items:
        if it["question_id"] in blocked_qids:
            continue
        queue.append(ComponentQueueItem(
            index=len(queue),
            plan_id=it["component_id"],
            question_id=it["question_id"],
            component_type=it["component_type"],
            title=it["title"],
            section_path=it["section_path"],
            status="pending",
        ).dict())

    logger.info("[generation-queue] %d components → %d queue items (%d blocked qids)",
                len(queue_items), len(queue), len(blocked_qids))
    return queue



@router.post("/{template_id}/{signature}/generate-component")
def generate_single_component(
    template_id: str, signature: str, body: GenerateComponentIn
) -> GenerateComponentOut:
    """Generate ONE component (narrative/table/chart/metric) by queue index.

    The queue expands each question into its declared components (the same shape the
    full report renders), so this fills a single block with rich content matching
    the final report: ranking/aggregation items for table+chart, a computed metric
    for formula slots, and grounded prose for narrative.
    """
    dataset, blueprint, df = _read_stash(template_id, signature)
    binding = _rebuild_binding(template_id, signature, dataset, blueprint, df)
    context = blueprint.get("statisticalContext") or {}

    # Build & adapt bundle (for the question's plans).
    data_content_hash = compute_data_content_hash(df)
    bundle = _build_bundle(template_id, signature, dataset, blueprint, df,
                           data_content_hash=data_content_hash)
    adapted = adapt_bundle(bundle)
    if not adapted:
        raise HTTPException(status_code=409, detail="No runnable plans")

    # The component queue is the single source of truth shared with the queue endpoint.
    blocked_qids = {b.get("questionId") for b in (bundle.blockedQuestions or [])}
    queue = [it for it in _build_component_queue(blueprint) if it["question_id"] not in blocked_qids]
    # Re-index after filtering so indices line up with the queue endpoint.
    for i, it in enumerate(queue):
        it["index"] = i

    idx = body.index
    if idx < 0 or idx >= len(queue):
        raise HTTPException(status_code=400, detail=f"Index {idx} out of range (0..{len(queue)-1})")

    item = queue[idx]
    question_id = item["question_id"]
    component_kind = item["component_kind"]
    component_type = item["component_type"]
    title = item["title"]

    # Look up the blueprint question (for composition parts + intent).
    bp_q: dict[str, Any] = {}
    for q, _sp in _iter_questions(blueprint):
        if q.get("questionId") == question_id:
            bp_q = q
            break
    q_title = bp_q.get("questionText") or bp_q.get("intent") or question_id

    # Run ALL of this question's plans → analytics (rankings/aggregations/metrics).
    q_plans = [a for a in adapted if (a.questionId or a.planRec.questionId) == question_id]
    analytics: dict[str, Any] = {"rankings": [], "aggregations": [], "metrics": [], "trends": []}
    if q_plans:
        analytics_obj, evidence_obj, _row_index = run_execution(
            q_plans, df, question_meta=_question_meta(blueprint))
        analytics = analytics_obj.to_dict()

    rankings = analytics.get("rankings") or []
    aggs = analytics.get("aggregations") or []
    metrics = [m for m in (analytics.get("metrics") or []) if m.get("value") is not None]

    # ── Build chart/table items (key/value rows the frontend renders both ways) ──
    def _items_and_measure() -> tuple[list[dict[str, Any]], str]:
        if rankings:
            rk = rankings[0]
            return list(rk.get("items") or [])[:12], rk.get("measure") or title
        if aggs:
            ag = aggs[0]
            rows = ag.get("rows") or []
            return ([{"key": r.get("key"), "value": r.get("value"), "rowIds": r.get("rowIds")}
                     for r in rows][:15], ag.get("measure") or title)
        # Composition / share with no ranking: build slices from the part columns.
        spec = bp_q.get("analyticsSpec") or {}
        parts = spec.get("parts") or []
        ent_col = {(r.get("entityId") or r.get("entityRef")): r.get("columnExpr")
                   for r in (bp_q.get("requiredEntities") or [])}
        pts: list[dict[str, Any]] = []
        for p in parts:
            col = ent_col.get(p)
            if col and col in df.columns:
                pts.append({"key": {"component": _pretty(col)}, "value": float(df[col].sum())})
        return pts, "Establishments"

    component_content: dict[str, Any] = {"questionId": question_id}
    narrative_text = ""

    if component_kind in ("table", "chart"):
        items, measure = _items_and_measure()
        component_content = {
            "type": "ranking" if rankings else ("aggregation" if aggs else "composition"),
            "questionId": question_id,
            "items": items,
            "rankingData": items,
            "measure": measure,
            "unit": _measure_unit(bp_q, dataset),
            "source": (context.get("sourceDocument") or ""),
        }
        narrative_text = f"{measure} across {len(items)} categories."
    elif component_kind == "metric":
        if metrics:
            mt = metrics[0]
            component_content = {
                "type": "metric", "questionId": question_id,
                "value": mt.get("value"), "unit": mt.get("unit", ""),
                "label": mt.get("label") or title,
            }
            narrative_text = f"{component_content['label']}: {_fmt_value(mt.get('value'), mt.get('unit'))}".strip()
        else:
            component_content = {"type": "metric", "questionId": question_id,
                                 "value": None, "label": title}
            narrative_text = f"{title}: (not available)"
    else:
        # Narrative (and appendix kinds): grounded prose from the analytics roll-up.
        from report_builder.generation.document_map_bridge import _narrative_for
        roll_kind = "ranking" if rankings else ("aggregation" if aggs else "")
        rollup = (rankings[0] if rankings else (aggs[0] if aggs else None))
        narrative_text = _narrative_for(q_title, roll_kind, rollup, metrics)
        component_content = {"type": "narrative", "questionId": question_id,
                             "text": narrative_text}
        # Optional LLM polish (Azure) when enabled.
        if body.use_llm:
            try:
                from report_builder.generation.narrator import _default_llm_caller
                caller = _default_llm_caller()
                if caller:
                    prompt = (
                        "You are a MoSPI desk officer writing one concise, factual paragraph for "
                        "an official statistical report. Use ONLY the figures in the draft; do not "
                        "invent or re-round numbers. Be precise and neutral.\n\n"
                        f"DRAFT:\n{narrative_text}\n\nReturn only the improved paragraph."
                    )
                    improved = caller(prompt)
                    if improved and len(improved.strip()) > 20 and not _NUMBER_DRIFT(narrative_text, improved):
                        narrative_text = improved.strip()
                        component_content["text"] = narrative_text
            except Exception as _llm_exc:  # noqa: BLE001
                logger.info("[generate-component] narrative LLM polish skipped: %s", _llm_exc)

    # ── Next preview ──
    next_idx = idx + 1 if idx + 1 < len(queue) else None
    next_preview = None
    if next_idx is not None:
        nxt = queue[next_idx]
        next_preview = {
            "index": next_idx, "plan_id": nxt["component_id"],
            "component_type": nxt["component_type"], "title": nxt["title"],
            "section_path": nxt["section_path"],
        }

    total = len(queue)
    progress = round(((idx + 1) / total) * 100, 1)

    logger.info("[generate-component] %d/%d (%s) q=%s — narrative=%d chars, items=%d",
                idx + 1, total, component_kind, question_id, len(narrative_text),
                len(component_content.get("items") or []))

    return GenerateComponentOut(
        index=idx,
        plan_id=item["component_id"],
        component_type=component_type,
        title=title,
        content=component_content,
        narrative=narrative_text,
        status="done",
        next_index=next_idx,
        next_preview=next_preview,
        total=total,
        progress_pct=progress,
    )



@router.get("/{template_id}/{signature}/report")
def get_report(
    template_id: str, signature: str, version: Optional[int] = None
) -> dict[str, Any]:
    """Return the assembled ``report.output.ast.json`` (latest, or a saved version)."""
    if version is not None:
        vpath = _version_path(template_id, signature, version)
        if not vpath.exists():
            raise HTTPException(status_code=404, detail=f"version {version} not found")
        return json.loads(vpath.read_text(encoding="utf-8"))
    path = _report_path(template_id, signature)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no report generated yet — call /generate first")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/{template_id}/{signature}/report.html", response_class=HTMLResponse)
def get_report_html(template_id: str, signature: str) -> HTMLResponse:
    """Return the rendered standalone HTML report."""
    path = _html_path(template_id, signature)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no report generated yet — call /generate first")
    return HTMLResponse(content=path.read_text(encoding="utf-8"))


@router.get("/{template_id}/{signature}/report.pdf")
def get_report_pdf(
    template_id: str,
    signature: str,
    engine: str = "weasyprint",
    locale: str = "en-IN",
    theme: Optional[str] = None,
) -> Response:
    """Stream the report as PDF (regenerated on demand from the stored AST).

    Document chrome (cover, TOC, provenance appendix, figure/table numbering) is
    on for the PDF deliverable. Returns ``503`` when the selected PDF engine is
    unavailable on the host (e.g. WeasyPrint native libs missing) so the caller
    can fall back to the HTML report.
    """
    path = _report_path(template_id, signature)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no report generated yet — call /generate first")

    if not pdf_available(engine):
        raise HTTPException(
            status_code=503,
            detail=f"PDF engine '{engine}' is not available on this server; use report.html instead",
        )

    report = json.loads(path.read_text(encoding="utf-8"))
    try:
        pdf_bytes = render_pdf(report, engine=engine, locale=locale, theme=theme)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not pdf_bytes:
        raise HTTPException(
            status_code=503,
            detail=f"PDF engine '{engine}' failed to produce output; use report.html instead",
        )

    report_id = (report.get("metadata") or {}).get("reportId") or "report"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{report_id}.pdf"'},
    )


# ---------------------------------------------------------------------------
# R4 — customization (template profile + report overrides + re-render)
# ---------------------------------------------------------------------------


@router.get("/{template_id}/{signature}/profile")
def get_profile(template_id: str, signature: str) -> dict[str, Any]:
    """Return the author's template profile (defaults if none saved yet)."""
    return _load_profile(template_id, signature)


@router.put("/{template_id}/{signature}/profile")
def put_profile(
    template_id: str, signature: str, payload: dict[str, Any] = Body(default_factory=dict)
) -> dict[str, Any]:
    """Persist the author's template profile (full document of defaults)."""
    profile = TemplateProfile.from_dict(payload).to_dict()
    _profile_path(template_id, signature).write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


@router.patch("/{template_id}/{signature}/overrides")
def patch_overrides(
    template_id: str, signature: str, payload: dict[str, Any] = Body(default_factory=dict)
) -> dict[str, Any]:
    """Merge sparse viewer overrides into the stored overrides for this report."""
    current = _load_overrides(template_id, signature)
    incoming = ReportOverrides.from_dict(payload).to_dict()
    sparse = ReportOverrides.from_dict(deep_merge(current, incoming)).to_dict()
    _overrides_path(template_id, signature).write_text(
        json.dumps(sparse, ensure_ascii=False, indent=2), encoding="utf-8")
    return sparse


@router.get("/{template_id}/{signature}/overrides")
def get_overrides(template_id: str, signature: str) -> dict[str, Any]:
    """Return the sparse viewer overrides saved for this report."""
    return _load_overrides(template_id, signature)


@router.post("/{template_id}/{signature}/render")
def render_customized(
    template_id: str,
    signature: str,
    fmt: str = Query("html", alias="format"),
    engine: str = "weasyprint",
) -> Response:
    """Re-render the stored report through the effective profile (author+overrides).

    ``format=html`` (default) returns the customized standalone HTML; ``format=pdf``
    streams the customized PDF (``503`` when the engine is unavailable).
    """
    path = _report_path(template_id, signature)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no report generated yet — call /generate first")

    report = json.loads(path.read_text(encoding="utf-8"))
    eff = effective_profile(
        _load_profile(template_id, signature),
        _load_overrides(template_id, signature),
    )
    shaped = apply_profile(report, eff)
    flags = render_flags(eff)

    if fmt == "pdf":
        if not pdf_available(engine):
            raise HTTPException(
                status_code=503,
                detail=f"PDF engine '{engine}' is not available on this server; use format=html instead",
            )
        try:
            pdf_bytes = render_pdf(shaped, engine=engine, **flags)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not pdf_bytes:
            raise HTTPException(
                status_code=503,
                detail=f"PDF engine '{engine}' failed to produce output; use format=html instead",
            )
        report_id = (shaped.get("metadata") or {}).get("reportId") or "report"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{report_id}.pdf"'},
        )

    html_str = render_html(shaped, **flags)
    return HTMLResponse(content=html_str)


# ---------------------------------------------------------------------------
# R5 — editing with lock + audit + versioned report instances
# ---------------------------------------------------------------------------


class EditIn(BaseModel):
    target: dict[str, Any]                 # {kind, id, ...} — see edit._locate
    field: Optional[str] = None
    value: Any = None
    by: Optional[str] = None
    reason: Optional[str] = None


class EditOut(BaseModel):
    ok: bool
    version: int
    audit: dict[str, Any]


@router.post("/{template_id}/{signature}/edit", response_model=EditOut)
def edit_report(template_id: str, signature: str, body: EditIn) -> EditOut:
    """Apply one human edit, persist a new immutable version, return the audit entry.

    Prose edits are re-validated against the data (``400`` on a hallucinated
    number); number overrides require a ``reason`` and are flagged + audited. The
    pre-edit report is preserved as ``v1`` the first time it is edited.
    """
    path = _report_path(template_id, signature)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no report generated yet — call /generate first")
    report = json.loads(path.read_text(encoding="utf-8"))

    try:
        edited, audit = apply_edit(report, body.model_dump())
    except EditRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    versions = _list_versions(template_id, signature)
    if not versions:
        # Preserve the original as v1 before recording the first edit.
        v1 = bump_version(json.loads(json.dumps(report)), 1)
        _version_path(template_id, signature, 1).write_text(
            json.dumps(v1, ensure_ascii=False, indent=2), encoding="utf-8")
        versions = [1]

    n = max(versions) + 1
    bump_version(edited, n)
    _version_path(template_id, signature, n).write_text(
        json.dumps(edited, ensure_ascii=False, indent=2), encoding="utf-8")
    # Latest becomes the current report + re-rendered HTML.
    path.write_text(json.dumps(edited, ensure_ascii=False, indent=2), encoding="utf-8")
    _html_path(template_id, signature).write_text(render_html(edited), encoding="utf-8")

    return EditOut(ok=True, version=n, audit=audit)


@router.get("/{template_id}/{signature}/versions")
def get_versions(template_id: str, signature: str) -> dict[str, Any]:
    """List the saved version numbers (ascending); ``current`` is the latest."""
    versions = _list_versions(template_id, signature)
    path = _report_path(template_id, signature)
    current = None
    if path.exists():
        current = current_version(json.loads(path.read_text(encoding="utf-8")))
    return {"versions": versions, "current": current}


# ───────────────────────── Canvas Deep BI chat bridge ─────────────────────────


class CanvasChatIn(BaseModel):
    query: str
    selected_question_id: Optional[str] = None


def _payload_from_stash(
    dataset: DatasetAST,
    blueprint: dict[str, Any],
    binding: "BindingAST | None" = None,
) -> dict[str, Any]:
    """Build a DeepAgent ``analysis_payload`` from the generate-phase stash so the
    canvas chat can reuse the full Planner→Retrieval→Analytics→Scribe→Verifier
    pipeline without a persisted ``Analysis`` row.

    When a finalized ``binding`` is supplied (bound-first policy, decision B), the
    officer's **confirmed** entity→column decisions are injected two ways:

    * ``binding_glossary`` — {alias_or_entityName_lc: [columns]} so a query term
      like *"LFPR"* resolves to the confirmed column even when the physical name
      shares no words. The planner consumes this as its step-0 resolution.
    * ``semantic_mapping`` rows are tagged ``bound=True`` + carry the entityName so
      retrieval/scribe prefer confirmed columns. Unbound columns remain available
      for *exploratory* (clearly non-bound) discovery.
    """
    # Map column → confirmed entity (name + aliases) from the binding.
    col_entity: dict[str, dict[str, Any]] = {}
    binding_glossary: dict[str, list[str]] = {}
    if binding is not None:
        # Blueprint entities carry the rich detail (aliases/glossary) that the
        # binding's EntityBinding does not — index them by id + canonical name so
        # the glossary can expand every alias the template extraction captured.
        bp_aliases: dict[str, list[str]] = {}
        for ent in (blueprint.get("entities") or []):
            if not isinstance(ent, dict):
                continue
            aliases = [str(a) for a in (ent.get("aliases") or []) if a]
            for k in (ent.get("entityId"), ent.get("canonicalName"), ent.get("entityName")):
                key = str(k or "").strip().lower()
                if key:
                    bp_aliases[key] = aliases

        for eb in binding.entityBindings:
            if eb.status not in ("confirmed", "overridden"):
                continue
            cols = [bc.column for bc in eb.columns if bc.column]
            if not cols:
                continue
            # Glossary: entity name + every captured alias → the confirmed columns.
            extra = bp_aliases.get(str(eb.entityId).lower()) or \
                bp_aliases.get(str(eb.entityName).strip().lower()) or []
            terms = [eb.entityName, *extra]
            for term in terms:
                key = str(term or "").strip().lower()
                if key:
                    binding_glossary.setdefault(key, [])
                    for c in cols:
                        if c not in binding_glossary[key]:
                            binding_glossary[key].append(c)
            for c in cols:
                col_entity[c] = {"entityName": eb.entityName, "entityType": eb.entityType}

    semantic_mapping = []
    for c in dataset.columns:
        row: dict[str, Any] = {
            "column": c.name,
            "domain": c.role,            # measure/dimension/time/id → domain bucket
            "dtype": c.dtype,
            "unit": c.unit,
            "cardinality": c.cardinality,
        }
        ent = col_entity.get(c.name)
        if ent:
            row["bound"] = True
            row["entityName"] = ent["entityName"]
        semantic_mapping.append(row)

    return {
        "semantic_mapping": semantic_mapping,
        "binding_glossary": binding_glossary,
        "dataset_context": {
            "dataset_type": dataset.archetype or "generic",
            "source_file": dataset.sourceFile,
        },
        "health": {
            "row_count": dataset.rowCount,
            "column_count": len(dataset.columns),
        },
        "statistical_context": blueprint.get("statisticalContext") or {},
    }


@router.post("/{template_id}/{signature}/chat")
def canvas_chat(template_id: str, signature: str, body: CanvasChatIn) -> dict[str, Any]:
    """Deep BI chat for the report canvas.

    Routes the officer's question through the full ``DeepAgent`` pipeline
    (Planner → Retrieval → Analytics → Scribe → Verifier) using the binding
    stash (dataset + blueprint + CSV) as the data source. Returns the
    ``deep_chat``-shaped payload: a primary narrative plus draggable, verified
    ``RenderedBlock``s with row-level evidence.

    Degrades gracefully: if the DeepAgent stack is unavailable the endpoint
    returns a structured notice instead of raising, so the canvas chat keeps
    working in offline/deterministic mode.
    """
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="Empty query")

    dataset, blueprint, df = _read_stash(template_id, signature)

    # Bound-first (decision B): reuse the officer's CONFIRMED entity bindings so
    # chat honors decisions made in the binder instead of re-resolving columns.
    # Best-effort — if the binding record is missing the chat still works in
    # explore-only mode (unbound columns are fair game, clearly non-bound).
    binding = None
    try:
        binding = _rebuild_binding(template_id, signature, dataset, blueprint, df)
    except HTTPException:
        binding = None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[canvas-chat] binding rebuild skipped: %s", exc)
        binding = None

    analysis_payload = _payload_from_stash(dataset, blueprint, binding=binding)
    bound_terms = len(analysis_payload.get("binding_glossary") or {})

    try:
        from agents.deep_agent import DeepAgent

        agent = DeepAgent(db=None)
        turn = agent.run(
            query=body.query.strip(),
            analysis_id=0,                      # no persisted Analysis row in canvas session
            analysis_payload=analysis_payload,
            df_loader=lambda: df,
            stm=None,
            ledger=None,
        )
    except Exception as exc:  # noqa: BLE001 — chat must never 500 the canvas
        logger.warning("[canvas-chat] DeepAgent unavailable: %s", exc)
        return {
            "role": "assistant",
            "text": (
                "The deep analysis engine is unavailable in this environment. "
                "Inline edit commands (inspect, outline, shorter, remove) still work."
            ),
            "blocks": [],
            "analytics": {},
            "verifier": None,
            "route": {"engine": "unavailable", "reason": str(exc)[:200]},
            "degraded": True,
        }

    primary_text = ""
    verifier_out = None
    for block in turn.blocks:
        if block.get("kind") == "narrative":
            primary_text = (block.get("payload") or {}).get("text", "")
            verifier_out = block.get("verifier")
            break
    if not primary_text:
        primary_text = turn.narrative_hints or f"Analysis complete ({turn.analytics.get('mode', '')})."

    logger.info("[canvas-chat] %s__%s — q=%r blocks=%d mode=%s bound_terms=%d",
                template_id, signature, body.query[:60], len(turn.blocks),
                turn.analytics.get("mode"), bound_terms)

    return {
        "role": "assistant",
        "text": primary_text,
        "blocks": turn.blocks,
        "plan": turn.plan,
        "analytics": turn.analytics,
        "context_used": turn.context_used,
        "verifier": verifier_out,
        "route": {"engine": "deep_agent", "bound": bound_terms > 0, "boundTerms": bound_terms},
        "turn_id": turn.turn_id,
    }


# ───────────────────────── Canvas layout persistence ──────────────────────────
# The report canvas lets an officer freely place / size blocks (Canva-style).
# That spatial intent (x/y/w/h + page assignment per block) is a *presentation*
# concern owned by the canvas, so it is stashed as its own JSON document keyed by
# (template_id, signature) — separate from the typed ReportOverrides (prose/number
# edits) and the value-free template. It is loaded on canvas mount and autosaved
# on change, so the officer's layout survives reloads and feeds the renderer.


def _canvas_layout_path(template_id: str, signature: str) -> Path:
    return _stash_path(template_id, signature, "canvas_layout.json")


class CanvasLayoutIn(BaseModel):
    # Opaque, frontend-owned shape: {"blocks": {id: {kind,title,content,x,y,w,h,
    # pageIndex,...}}, "pages": [...], "order": [id, ...], "updatedAt": "..."}.
    # Persisted verbatim. ``order`` is the canonical document sequence so a manual
    # reorder survives a reload.
    blocks: dict[str, Any] = {}
    pages: list[dict[str, Any]] = []
    order: list[str] = []
    updatedAt: Optional[str] = None


@router.get("/{template_id}/{signature}/canvas-layout")
def get_canvas_layout(template_id: str, signature: str) -> dict[str, Any]:
    """Return the saved canvas layout (empty doc if none saved yet)."""
    path = _canvas_layout_path(template_id, signature)
    if not path.exists():
        return {"blocks": {}, "pages": [], "order": [], "updatedAt": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[canvas-layout] read failed %s: %s", path, exc)
        return {"blocks": {}, "pages": [], "order": [], "updatedAt": None}


@router.put("/{template_id}/{signature}/canvas-layout")
def put_canvas_layout(template_id: str, signature: str, body: CanvasLayoutIn) -> dict[str, Any]:
    """Persist the canvas layout (full replace). Autosaved by the canvas."""
    from datetime import datetime, timezone

    doc = {
        "blocks": body.blocks or {},
        "pages": body.pages or [],
        "order": body.order or [],
        "updatedAt": body.updatedAt or datetime.now(timezone.utc).isoformat(),
    }
    path = _canvas_layout_path(template_id, signature)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[canvas-layout] saved %s__%s — %d blocks, %d pages",
                template_id, signature, len(doc["blocks"]), len(doc["pages"]))
    return {"ok": True, "updatedAt": doc["updatedAt"]}
