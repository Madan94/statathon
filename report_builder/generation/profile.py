"""R4 — report customization: template profile (author defaults) + report
overrides (viewer), merged into one *effective profile* that re-shapes the
report AST and drives the render chrome.

Two layers, same shape:

* **TemplateProfile** — the author's defaults for a template (theme, page setup,
  number system, locale, section order, included questions, per-question chart
  type / table format / tone, front & back matter).
* **ReportOverrides** — a *sparse* viewer override for one report instance; only
  the keys present win.

``effective_profile(template, overrides)`` deep-merges the two (override wins;
``perQuestion`` merges per question id so a viewer can tweak one question without
clobbering the rest). ``apply_profile(report, eff)`` returns a **new** report
dict reshaped by the effective profile:

* reorder ``semanticAST.sections`` to ``sectionOrder`` (unlisted keep their order);
* drop elements/sections for questions not in ``includedQuestions`` (empty ⇒ all);
* swap ``chartType`` and apply table ``format`` per question;
* stamp locale / number system / theme onto ``metadata`` (and a customization trace).

Pure data transforms over ``report.output.ast.json`` dicts — no web / IO deps, so
the generation core stays canonical and this layer is opt-in post-processing.
``render_flags(eff)`` maps the effective profile to ``render_html`` kwargs.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Front / back matter defaults
# ---------------------------------------------------------------------------


def _default_front_matter() -> dict[str, bool]:
    return {"cover": True, "foreword": False, "toc": True}


def _default_back_matter() -> dict[str, bool]:
    return {"glossary": False, "notes": True}


# ---------------------------------------------------------------------------
# Profile dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TemplateProfile:
    """Author-side defaults for a template (fully populated)."""

    theme: Optional[str] = None
    pageSetup: dict[str, Any] = field(
        default_factory=lambda: {"size": "A4", "orientation": "portrait"}
    )
    numberSystem: str = "indian"            # "indian" | "international"
    locale: str = "en-IN"                   # "en-IN" | "hi-IN"
    sectionOrder: list[str] = field(default_factory=list)       # [] ⇒ keep AST order
    includedQuestions: list[str] = field(default_factory=list)  # [] ⇒ all questions
    perQuestion: dict[str, dict[str, Any]] = field(default_factory=dict)
    frontMatter: dict[str, bool] = field(default_factory=_default_front_matter)
    backMatter: dict[str, bool] = field(default_factory=_default_back_matter)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def default(cls) -> "TemplateProfile":
        return cls()

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "TemplateProfile":
        data = data or {}
        base = cls().to_dict()
        merged = deep_merge(base, {k: v for k, v in data.items() if k in base})
        return cls(**merged)


@dataclass
class ReportOverrides:
    """Sparse per-report overrides — only set keys take effect."""

    theme: Optional[str] = None
    pageSetup: Optional[dict[str, Any]] = None
    numberSystem: Optional[str] = None
    locale: Optional[str] = None
    sectionOrder: Optional[list[str]] = None
    includedQuestions: Optional[list[str]] = None
    perQuestion: Optional[dict[str, dict[str, Any]]] = None
    frontMatter: Optional[dict[str, bool]] = None
    backMatter: Optional[dict[str, bool]] = None

    def to_dict(self) -> dict[str, Any]:
        """Only the keys that are actually set (drops ``None``)."""
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "ReportOverrides":
        data = data or {}
        fields = {f for f in cls.__dataclass_fields__}  # noqa: C416
        return cls(**{k: v for k, v in data.items() if k in fields})


# ---------------------------------------------------------------------------
# Deep merge + effective profile
# ---------------------------------------------------------------------------


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``over`` onto ``base`` (override wins).

    Nested dicts merge key-by-key (so ``perQuestion`` tweaks one question without
    dropping the others); lists and scalars *replace*; ``None`` values are skipped.
    """
    out = copy.deepcopy(base)
    for key, value in (over or {}).items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def effective_profile(
    template_profile: Optional[dict[str, Any]],
    overrides: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Merge author defaults + viewer overrides into one effective profile dict."""
    base = TemplateProfile.from_dict(template_profile).to_dict()
    sparse = ReportOverrides.from_dict(overrides).to_dict()
    return deep_merge(base, sparse)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _element_question_map(report: dict[str, Any]) -> dict[str, str]:
    """Map every renderable element id → the question id it belongs to."""
    out: dict[str, str] = {}

    for block in (report.get("contentAST") or {}).get("blocks", []) or []:
        qid = (block.get("provenance") or {}).get("questionId") or block.get("biQuery")
        if block.get("blockId") and qid:
            out[block["blockId"]] = qid

    charts_q: dict[str, str] = {}
    for chart in (report.get("chartAST") or {}).get("charts", []) or []:
        qid = (chart.get("provenance") or {}).get("questionId") or chart.get("biQuery")
        if chart.get("chartId") and qid:
            charts_q[chart["chartId"]] = qid

    for fig in (report.get("figureAST") or {}).get("figures", []) or []:
        qid = charts_q.get(fig.get("chartRef"))
        if fig.get("figureId") and qid:
            out[fig["figureId"]] = qid

    for table in (report.get("tableAST") or {}).get("tables", []) or []:
        qid = (table.get("provenance") or {}).get("questionId") or table.get("biQuery")
        if table.get("tableId") and qid:
            out[table["tableId"]] = qid

    return out


def _filter_questions(
    report: dict[str, Any], sections: list[dict[str, Any]], included: list[str]
) -> list[dict[str, Any]]:
    """Drop children for questions not in ``included``; drop emptied sections."""
    keep = set(included)
    elem_q = _element_question_map(report)
    out: list[dict[str, Any]] = []
    for sec in sections:
        children = sec.get("children") or []
        new_children = [c for c in children if elem_q.get(c) is None or elem_q.get(c) in keep]
        # A section that had question-bearing children but kept none is removed.
        had_qs = any(elem_q.get(c) is not None for c in children)
        if had_qs and not any(elem_q.get(c) in keep for c in new_children):
            continue
        sec = dict(sec)
        sec["children"] = new_children
        out.append(sec)
    return out


def _reorder_sections(
    sections: list[dict[str, Any]], order: list[str]
) -> list[dict[str, Any]]:
    """Reorder by ``sectionId`` per ``order``; unlisted keep their relative order."""
    rank = {sid: i for i, sid in enumerate(order)}
    big = len(order)
    indexed = list(enumerate(sections))
    indexed.sort(key=lambda pair: (rank.get(pair[1].get("sectionId"), big), pair[0]))
    out = []
    for i, (_, sec) in enumerate(indexed):
        sec = dict(sec)
        sec["order"] = i + 1
        out.append(sec)
    return out


def _apply_per_question(report: dict[str, Any], per_question: dict[str, dict[str, Any]]) -> None:
    """Swap chart types and apply table column formats per question, in place."""
    if not per_question:
        return

    charts = (report.get("chartAST") or {}).get("charts", []) or []
    tables = (report.get("tableAST") or {}).get("tables", []) or []

    def chart_q(c: dict[str, Any]) -> Optional[str]:
        return (c.get("provenance") or {}).get("questionId") or c.get("biQuery")

    def table_q(t: dict[str, Any]) -> Optional[str]:
        return (t.get("provenance") or {}).get("questionId") or t.get("biQuery")

    for qid, spec in per_question.items():
        if not isinstance(spec, dict):
            continue
        chart_type = spec.get("chartType")
        if chart_type:
            for chart in charts:
                if chart_q(chart) == qid:
                    chart["chartType"] = chart_type

        table_format = spec.get("tableFormat")
        if table_format:
            for table in tables:
                if table_q(table) != qid:
                    continue
                for col in table.get("columns", []) or []:
                    if isinstance(table_format, dict):
                        if col.get("columnId") in table_format:
                            col["format"] = table_format[col["columnId"]]
                    elif col.get("role") == "measure":
                        col["format"] = table_format


# ---------------------------------------------------------------------------
# apply_profile
# ---------------------------------------------------------------------------


def apply_profile(report: dict[str, Any], eff: dict[str, Any]) -> dict[str, Any]:
    """Return a new report dict reshaped by the effective profile ``eff``."""
    report = copy.deepcopy(report)
    eff = eff or {}

    semantic = report.setdefault("semanticAST", {})
    sections = list(semantic.get("sections") or [])

    included = eff.get("includedQuestions") or []
    if included:
        sections = _filter_questions(report, sections, included)

    order = eff.get("sectionOrder") or []
    if order:
        sections = _reorder_sections(sections, order)

    semantic["sections"] = sections

    _apply_per_question(report, eff.get("perQuestion") or {})

    metadata = report.setdefault("metadata", {})
    metadata["locale"] = eff.get("locale", metadata.get("locale", "en-IN"))
    metadata["numberSystem"] = eff.get("numberSystem", "indian")
    if eff.get("theme") is not None:
        metadata["theme"] = eff.get("theme")
    metadata["customization"] = {
        "sectionOrder": order,
        "includedQuestions": included,
        "perQuestion": eff.get("perQuestion") or {},
        "frontMatter": eff.get("frontMatter") or _default_front_matter(),
        "backMatter": eff.get("backMatter") or _default_back_matter(),
    }
    return report


def render_flags(eff: dict[str, Any]) -> dict[str, Any]:
    """Map an effective profile to keyword args for ``render_html`` / ``render_pdf``."""
    eff = eff or {}
    front = eff.get("frontMatter") or _default_front_matter()
    back = eff.get("backMatter") or _default_back_matter()
    include_cover = bool(front.get("cover"))
    include_toc = bool(front.get("toc"))
    include_appendix = bool(back.get("notes") or back.get("glossary"))
    return {
        "theme": eff.get("theme"),
        "locale": eff.get("locale", "en-IN"),
        "number_system": eff.get("numberSystem", "indian"),
        "include_cover": include_cover,
        "include_toc": include_toc,
        "include_appendix": include_appendix,
        "number_elements": include_cover or include_toc or include_appendix,
    }
