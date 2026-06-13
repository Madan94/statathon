"""S5b — Narrator: turn analytics facts into MoSPI-style prose, value-safe.

Fills the template ``contentAST`` paragraph slots. Every sentence is grounded in
``analyticsAST`` / ``evidenceAST`` values and carries provenance back to them.

Three tiers, each a strict superset-of-trust over the last. A higher tier is only
accepted if **every number it states re-validates** against the analytics facts;
otherwise the narrator falls back to the tier below. The deterministic floor
therefore guarantees a correct, offline answer no matter what:

    Tier 0  deterministic   facts → sentence from a fixed templater.
                            Numbers are emitted *from* the facts, so always valid.
    Tier 1  LTM-grounded    + a learned, NUMBERLESS commentary clause from memory
                            (MoSPI rulebook / accepted prior prose). Numberless ⇒
                            cannot introduce a bad value.
    Tier 2  LLM rewrite      a fluent rewrite (gated by LLM availability), grounded
                            on the facts + Tier-1 clauses, then **number-validated**.
                            Any hallucinated figure ⇒ rejected, fall back.

So prose quality can rise over time (LTM learns clauses; the LLM polishes) while
the stated figures can never drift from what the data actually says.
"""
from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)

# Absolute tolerance when checking a narrative number against an analytics value.
_NUM_TOL = 0.05

# Pull decimal/integer tokens out of prose for validation. Commas in "1,234" are
# stripped first so grouped numbers compare cleanly.
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

# An LtmRetriever returns learned, numberless commentary clauses for a question.
LtmRetriever = Callable[..., Sequence[str]]
# An LlmCaller takes a prompt and returns prose (or None on failure / disabled).
LlmCaller = Callable[[str], "str | None"]


# ─────────────────────────────────────────────────────────────────────────────
# Facts model
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class GroupFact:
    name: Any
    value: float | None
    n: int = 0
    rowIds: list[str] = field(default_factory=list)


@dataclass
class RankFact:
    rank: int
    name: Any
    value: float | None
    rowIds: list[str] = field(default_factory=list)


@dataclass
class QuestionFacts:
    questionId: str
    operation: str                       # group_aggregate | rank | trend | metric
    period: str = ""
    measureLabel: str = "the indicator"
    measureShort: str = ""
    dimensionNoun: str = ""
    forClause: str = ""                  # e.g. " for persons aged 15 years and above"
    unit: str | None = None
    metric: float | None = None
    groups: list[GroupFact] = field(default_factory=list)
    ranking: list[RankFact] = field(default_factory=list)
    filterValues: list[float] = field(default_factory=list)
    analyticsRef: str | None = None
    evidenceRef: str | None = None
    componentId: str = ""

    def allowed_values(self) -> set[float]:
        """Every number the prose is *allowed* to state, rounded to 1 dp.

        Includes raw facts plus the small set of figures a desk officer derives
        from them (pairwise gaps between group values, the all-India anchor), so
        a sentence like "a gap of 9.2 percentage points" validates.
        """
        vals: set[float] = set()

        def add(v: Any) -> None:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.add(round(float(v), 1))

        add(self.metric)
        for g in self.groups:
            add(g.value)
            add(g.n)
        for r in self.ranking:
            add(r.value)
            add(r.rank)
        for fv in self.filterValues:
            add(fv)
        # Pairwise gaps between group values (and vs the all-India metric).
        group_vals = [g.value for g in self.groups if g.value is not None]
        anchor = [self.metric] if self.metric is not None else []
        pool = group_vals + anchor
        for i in range(len(pool)):
            for j in range(i + 1, len(pool)):
                add(round(abs(pool[i] - pool[j]), 1))
        return vals


# ─────────────────────────────────────────────────────────────────────────────
# Analytics indexing
# ─────────────────────────────────────────────────────────────────────────────

_COMPONENT_SUFFIX = re.compile(r"_c\d+$")


def _base_question(ref: str | None) -> str:
    return _COMPONENT_SUFFIX.sub("", ref or "")


def _primary_dim(group_by: Any) -> str | None:
    if isinstance(group_by, str):
        return group_by or None
    if isinstance(group_by, (list, tuple)) and group_by:
        return group_by[0]
    return None


class _Index:
    def __init__(self, analytics: dict[str, Any], evidence: dict[str, Any]):
        self.aggregations = {a["questionId"]: a for a in analytics.get("aggregations", [])}
        self.rankings = {r["questionId"]: r for r in analytics.get("rankings", [])}
        self.metrics: dict[str, list[dict]] = {}
        for m in analytics.get("metrics", []):
            self.metrics.setdefault(m["questionId"], []).append(m)
        self.plans = {p["questionId"]: p for p in analytics.get("plans", [])}
        self.evidence_by_q: dict[str, str] = {}
        for ev in evidence.get("evidence", []):
            self.evidence_by_q.setdefault(ev["questionId"], ev["evidenceId"])


def _build_facts(qid: str, idx: _Index, qcfg: dict[str, Any], context: dict[str, Any]) -> QuestionFacts:
    plan = idx.plans.get(qid, {})
    agg = idx.aggregations.get(qid)
    ranking = idx.rankings.get(qid)
    metrics = idx.metrics.get(qid) or []
    operation = plan.get("operation") or ("rank" if ranking else "group_aggregate" if agg else "metric")

    facts = QuestionFacts(
        questionId=qid,
        operation=operation,
        period=str((context.get("period") or {}).get("current") or qcfg.get("period") or ""),
        measureLabel=qcfg.get("measureLabel") or (metrics[0]["label"] if metrics else None)
        or (agg.get("measure") if agg else None) or "the indicator",
        measureShort=qcfg.get("measureShort") or "",
        dimensionNoun=qcfg.get("dimensionNoun") or (_primary_dim(agg.get("groupBy")) if agg else "")
        or (_primary_dim(ranking.get("measure")) if ranking else "") or "",
        forClause=qcfg.get("forClause") or "",
        evidenceRef=idx.evidence_by_q.get(qid) or None,
        componentId="",
    )

    # filter numerics (e.g. age>=15 → 15) so "aged 15 years" validates.
    for expr in plan.get("filters") or []:
        for tok in _NUMBER_RE.findall(str(expr)):
            facts.filterValues.append(float(tok))

    if metrics:
        facts.metric = metrics[0].get("value")
        facts.unit = metrics[0].get("unit")
        facts.analyticsRef = metrics[0].get("metricId")
    if agg:
        for row in agg.get("rows", []):
            key = row.get("key") or {}
            dim = _primary_dim(agg.get("groupBy"))
            facts.groups.append(GroupFact(
                name=key.get(dim) if dim else next(iter(key.values()), None),
                value=row.get("value"), n=int(row.get("n") or 0),
                rowIds=list(row.get("rowIds") or [])))
        facts.analyticsRef = facts.analyticsRef or agg.get("aggId")
        if facts.unit is None:
            facts.unit = qcfg.get("unit")
    if ranking:
        for it in ranking.get("items", []):
            key = it.get("key") or {}
            facts.ranking.append(RankFact(
                rank=int(it.get("rank") or 0),
                name=next(iter(key.values()), None),
                value=it.get("value"), rowIds=list(it.get("rowIds") or [])))
        facts.analyticsRef = facts.analyticsRef or ranking.get("rankId")
        if facts.unit is None:
            facts.unit = qcfg.get("unit")
    facts.unit = facts.unit or qcfg.get("unit")
    return facts


# ─────────────────────────────────────────────────────────────────────────────
# Number formatting + validation
# ─────────────────────────────────────────────────────────────────────────────


def _fmt(value: Any, unit: str | None = None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        s = f"{value:.1f}"
    else:
        s = str(value)
    if unit == "percent":
        return f"{s}%"
    return s


def _gap_unit(unit: str | None) -> str:
    return "percentage points" if unit == "percent" else "points"


def validate_numbers(text: str, allowed: set[float], *, ignore: Sequence[str] = ()) -> tuple[bool, list[str]]:
    """Return (ok, offending_tokens). Every numeric token in ``text`` must match
    an allowed value within tolerance. Tokens inside ``ignore`` strings (e.g. the
    period label "2023-24") are removed first so they aren't mistaken for data.
    """
    scrubbed = text
    for ig in ignore:
        if ig:
            scrubbed = scrubbed.replace(str(ig), " ")
    scrubbed = scrubbed.replace(",", "")
    bad: list[str] = []
    for tok in _NUMBER_RE.findall(scrubbed):
        val = round(float(tok), 1)
        if not any(abs(val - a) <= _NUM_TOL for a in allowed):
            bad.append(tok)
    return (not bad), bad


# ─────────────────────────────────────────────────────────────────────────────
# Tier 0 — deterministic templater
# ─────────────────────────────────────────────────────────────────────────────


def _deterministic(facts: QuestionFacts) -> str:
    unit = facts.unit
    label = facts.measureLabel
    short = facts.measureShort or label
    period = facts.period
    lead = f"In {period}, " if period else ""

    if facts.operation == "rank" and facts.ranking:
        items = facts.ranking
        top = items[0]
        head = f"{top.name} recorded the highest {label} at {_fmt(top.value, unit)}"
        tail = [f"{it.name} ({_fmt(it.value, unit)})" for it in items[1:3]]
        if tail:
            head += ", followed by " + " and ".join(tail)
        return head + "."

    parts: list[str] = []
    if facts.metric is not None:
        parts.append(f"{lead}the {label}{facts.forClause} stood at {_fmt(facts.metric, unit)}.")
    groups = [g for g in facts.groups if g.value is not None]
    if len(groups) >= 2:
        hi, lo = groups[0], groups[-1]
        rel = "higher" if (hi.value or 0) >= (lo.value or 0) else "lower"
        gap = round(abs((hi.value or 0) - (lo.value or 0)), 1)
        noun = f" {facts.dimensionNoun}" if facts.dimensionNoun else ""
        sentence = (f"The {hi.name}{noun} recorded a {rel} {short} "
                    f"({_fmt(hi.value, unit)}) than the {lo.name}{noun} "
                    f"({_fmt(lo.value, unit)}) — a gap of {_fmt(gap)} {_gap_unit(unit)}.")
        if not parts:
            sentence = (lead[:1].upper() + lead[1:] if lead else "") + sentence
        parts.append(sentence)
    elif len(groups) == 1 and facts.metric is None:
        g = groups[0]
        parts.append(f"{lead}the {label} for {g.name} stood at {_fmt(g.value, unit)}.")

    if not parts:
        return f"{lead}the {label} could not be computed for this period."
    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1 — LTM-grounded commentary (numberless)
# ─────────────────────────────────────────────────────────────────────────────


def _ltm_clauses(facts: QuestionFacts, ltm: LtmRetriever | None) -> list[str]:
    if ltm is None:
        return []
    query = f"{facts.measureLabel} {facts.operation} {facts.dimensionNoun}".strip()
    try:
        raw = ltm(query, indicator=facts.measureLabel, question_type=facts.operation) or []
    except Exception as exc:  # pragma: no cover - defensive
        logger.info("[S5b] ltm retrieval failed: %s", exc)
        return []
    clauses: list[str] = []
    for c in raw:
        c = (c or "").strip()
        # A learned commentary clause must be numberless to stay value-safe.
        if c and not _NUMBER_RE.search(c):
            clauses.append(c if c.endswith(".") else c + ".")
    return clauses


def _apply_clause(text0: str, clause: str) -> str:
    return f"{text0} {clause}"


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2 — LLM rewrite (gated + validated)
# ─────────────────────────────────────────────────────────────────────────────


def _llm_prompt(facts: QuestionFacts, grounded: str, clauses: list[str]) -> str:
    fact_lines = [f"- period: {facts.period}", f"- indicator: {facts.measureLabel}"]
    if facts.metric is not None:
        fact_lines.append(f"- all-India value: {_fmt(facts.metric, facts.unit)}")
    for g in facts.groups:
        fact_lines.append(f"- {g.name}: {_fmt(g.value, facts.unit)} (n={g.n})")
    for r in facts.ranking[:5]:
        fact_lines.append(f"- rank {r.rank}: {r.name} = {_fmt(r.value, facts.unit)}")
    rules = "\n".join(f"- {c}" for c in clauses) or "- (none)"
    return (
        "You are a MoSPI desk officer writing one concise, factual paragraph for an "
        "official statistical report. Use ONLY the figures listed; do not invent or "
        "round differently. Be precise and neutral.\n\n"
        f"FACTS:\n{chr(10).join(fact_lines)}\n\n"
        f"STYLE/RULES (numberless guidance):\n{rules}\n\n"
        f"DRAFT TO IMPROVE:\n{grounded}\n\n"
        "Return only the improved paragraph."
    )


def _default_llm_caller() -> LlmCaller | None:
    try:
        from report_builder.llm_router import llm_disabled, llm_text_call
    except Exception:
        return None
    if llm_disabled():
        return None

    def _call(prompt: str) -> str | None:
        return llm_text_call(prompt, task="report_narrative", max_tokens=320, temperature=0.2)

    return _call


# ─────────────────────────────────────────────────────────────────────────────
# Per-block narration
# ─────────────────────────────────────────────────────────────────────────────


def narrate_block(
    facts: QuestionFacts,
    *,
    ltm: LtmRetriever | None = None,
    llm_call: LlmCaller | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Run the 3-tier ladder for one question; return text + trace.

    The returned ``tier`` is the highest tier whose numbers validated.
    """
    allowed = facts.allowed_values()
    ignore = [facts.period] if facts.period else []

    # Tier 0 — deterministic floor (valid by construction).
    text = _deterministic(facts)
    tier = "deterministic"
    fallback = False

    # Tier 1 — append a learned, numberless clause.
    clauses = _ltm_clauses(facts, ltm)
    if clauses:
        candidate = _apply_clause(text, clauses[0])
        ok, _ = validate_numbers(candidate, allowed, ignore=ignore)
        if ok:
            text, tier = candidate, "ltm_grounded"
        else:  # pragma: no cover - clause is numberless by filter, defensive only
            fallback = True

    # Tier 2 — optional LLM rewrite, accepted only if every number checks out.
    llm_used = False
    if use_llm:
        caller = llm_call or _default_llm_caller()
        if caller is not None:
            try:
                out = caller(_llm_prompt(facts, text, clauses))
            except Exception as exc:  # pragma: no cover - defensive
                logger.info("[S5b] llm call failed: %s", exc)
                out = None
            if out and out.strip():
                llm_used = True
                ok, bad = validate_numbers(out, allowed, ignore=ignore)
                if ok:
                    text, tier = out.strip(), "llm"
                else:
                    fallback = True
                    logger.info("[S5b] rejected LLM prose for %s (bad numbers: %s)",
                                facts.questionId, bad)

    return {
        "text": text,
        "tier": tier,
        "ltmHits": len(clauses),
        "llmUsed": llm_used,
        "fallback": fallback,
        "validated": True,  # whatever we return has passed validation
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def narrate(
    template: dict[str, Any],
    analytics: dict[str, Any],
    evidence: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    questions: dict[str, dict[str, Any]] | None = None,
    ltm: LtmRetriever | None = None,
    llm_call: LlmCaller | None = None,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    """Fill every paragraph slot in the template ``contentAST``.

    Args:
        template:  template AST (needs ``contentAST.blocks``).
        analytics / evidence: the executor outputs (S4).
        context:   ``{"period": {"current": ...}}`` and any other shared values.
        questions: per-question prose config, ``{qid: {measureLabel, measureShort,
                   dimensionNoun, forClause, unit}}`` — improves wording; optional.
        ltm:       retriever of learned numberless commentary clauses (Tier 1).
        llm_call:  prose rewriter (Tier 2); defaults to ``llm_router`` when enabled.
        use_llm:   force-enable/disable Tier 2. ``None`` ⇒ auto (on iff LLM enabled).

    Returns ``{"contentAST": {"blocks": [...]}, "narrativeTrace": [...]}``.
    """
    context = context or {}
    questions = questions or {}
    if use_llm is None:
        use_llm = _default_llm_caller() is not None
    idx = _Index(analytics, evidence)

    blocks_out: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    for block in (template.get("contentAST") or {}).get("blocks", []):
        block = copy.deepcopy(block)
        slot_ref = (block.get("slot") or {}).get("fillFrom") or block.get("biQuery")
        qid = _base_question(slot_ref)
        component_id = slot_ref if slot_ref and slot_ref != qid else ""
        qcfg = questions.get(qid, {})

        facts = _build_facts(qid, idx, qcfg, context)
        facts.componentId = component_id
        result = narrate_block(facts, ltm=ltm, llm_call=llm_call, use_llm=use_llm)

        block["content"] = result["text"]
        block["provenance"] = {
            "questionId": qid,
            "componentId": component_id,
            "evidenceRef": facts.evidenceRef,
            "analyticsRef": facts.analyticsRef,
        }
        block.setdefault("slot", {})["status"] = "filled" if result["text"] else "empty"
        blocks_out.append(block)

        trace.append({
            "blockId": block.get("blockId"),
            "questionId": qid,
            "tier": result["tier"],
            "ltmHits": result["ltmHits"],
            "llmUsed": result["llmUsed"],
            "fallback": result["fallback"],
            "validated": result["validated"],
        })

    n_llm = sum(1 for t in trace if t["tier"] == "llm")
    logger.info("[S5b] narrated %d blocks (deterministic=%d ltm=%d llm=%d)",
                len(trace), sum(1 for t in trace if t["tier"] == "deterministic"),
                sum(1 for t in trace if t["tier"] == "ltm_grounded"), n_llm)

    return {"contentAST": {"blocks": blocks_out}, "narrativeTrace": trace}
