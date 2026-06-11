"""S5f — BI insights: evidence-backed findings derived from trusted analytics only.

The insight layer reads what the pipeline already *proved* — ``analyticsAST`` /
``evidenceAST`` / ``auditAST.provenance`` / ``statisticalContext`` / the verifier
quality + diagnostics — and turns it into human-readable findings. It is deliberately
the weakest-privilege stage:

  * it does **not** decide what to compute (the binder did);
  * it does **not** query or re-bind the raw dataset (it only reads analytics rollups);
  * it does **not** invent numbers — every numeric insight quotes a value that already
    exists in ``analyticsAST`` and references its ``analyticsRef`` / ``evidenceRef`` /
    ``rowIds`` so it stays auditable;
  * it is fully deterministic and offline (``LLM_DISABLED=1`` safe). An optional LLM
    pass may *rephrase* an insight's text later, but never changes its value or refs.

Output is two-sided: machine-readable :class:`Insight` objects (persisted under
``auditAST.insights``) and a short ordered list of human findings the assembler can
surface as a "Key Findings" content block. Insight order is stable (a fixed kind
priority, then questionId, then value) so the same report always yields the same list.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Stable kind ordering for deterministic output (lower = earlier).
_KIND_ORDER = {
    "top_value": 0,
    "bottom_value": 1,
    "concentration": 2,
    "share_contribution": 3,
    "trend_direction": 4,
    "growth": 5,
    "outlier_high": 6,
    "outlier_low": 7,
    "data_caveat": 8,
    "coverage_caveat": 9,
}

# Severity vocabulary.
INFO, WARNING, CAVEAT = "info", "warning", "caveat"

# An outlier is flagged when a group value's robust (median/MAD) modified z-score
# exceeds this threshold. The MAD-based score (Iglewicz–Hoaglin) resists masking —
# a single large spike does not inflate the scale enough to hide itself, unlike mean/std.
_OUTLIER_MODZ = 3.5

# Coverage below this fraction raises a provenance caveat.
_COVERAGE_FLOOR = 0.99


@dataclass
class Insight:
    """One evidence-backed finding. Numeric insights always carry an analytics ref."""

    insightId: str
    kind: str
    text: str
    questionId: str | None = None
    planId: str | None = None
    analyticsRef: str | None = None
    evidenceRef: str | None = None
    value: Any = None
    confidence: float = 0.9
    severity: str = INFO              # info | warning | caveat
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "insightId": self.insightId,
            "kind": self.kind,
            "text": self.text,
            "value": self.value,
            "confidence": round(self.confidence, 3),
            "severity": self.severity,
            "refs": dict(self.refs),
        }
        for k in ("questionId", "planId", "analyticsRef", "evidenceRef"):
            v = getattr(self, k)
            if v:
                out[k] = v
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _num(v: Any) -> float | None:
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v: Any) -> str:
    n = _num(v)
    if n is None:
        return str(v)
    return str(int(n)) if float(n).is_integer() else f"{n:.1f}"


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _member(key: dict[str, Any]) -> str:
    """Human label for an aggregation/ranking key (first member value)."""
    if not key:
        return ""
    return str(next(iter(key.values())))


def _evidence_ref_for(evidence: dict[str, Any], qid: str) -> str:
    for ev in (evidence or {}).get("evidence", []):
        if ev.get("questionId") == qid:
            return str(ev.get("evidenceId") or "")
    return ""


def _plan_for(report: dict[str, Any] | None, qid: str) -> str:
    if not report:
        return ""
    entries = ((report.get("auditAST") or {}).get("provenance") or {}).get("entries") or []
    for e in entries:
        if e.get("questionId") == qid:
            return str(e.get("planId") or "")
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Per-rollup detectors
# ─────────────────────────────────────────────────────────────────────────────


def _aggregation_insights(agg: dict[str, Any], evidence: dict[str, Any],
                          report: dict[str, Any] | None) -> list[Insight]:
    qid = agg.get("questionId") or ""
    ref = agg.get("aggId") or ""
    measure = agg.get("measure") or "value"
    ev_ref = _evidence_ref_for(evidence, qid)
    plan = _plan_for(report, qid)
    rows = [r for r in (agg.get("rows") or []) if _num(r.get("value")) is not None]
    out: list[Insight] = []
    if not rows:
        return out

    def _mk(kind: str, text: str, row: dict[str, Any], *, severity: str = INFO,
            conf: float = 0.9) -> Insight:
        return Insight(
            insightId=f"ins_{qid}_{kind}", kind=kind, text=text,
            questionId=qid, planId=plan or None, analyticsRef=ref,
            evidenceRef=ev_ref or None, value=row.get("value"),
            confidence=conf, severity=severity,
            refs={"member": _member(row.get("key") or {}), "measure": measure,
                  "rowIds": list(row.get("rowIds") or [])},
        )

    ordered = sorted(rows, key=lambda r: _num(r.get("value")), reverse=True)
    hi, lo = ordered[0], ordered[-1]

    out.append(_mk("top_value",
                   f"{_member(hi.get('key') or {})} recorded the highest {measure} "
                   f"at {_fmt(hi.get('value'))}.", hi))
    if len(ordered) >= 2:
        out.append(_mk("bottom_value",
                       f"{_member(lo.get('key') or {})} recorded the lowest {measure} "
                       f"at {_fmt(lo.get('value'))}.", lo))

    # Concentration: top entry's share of the total (only meaningful for additive measures).
    values = [_num(r.get("value")) for r in rows]
    total = sum(v for v in values if v is not None)
    if total > 0 and len(rows) >= 3:
        share = 100.0 * (_num(hi.get("value")) or 0.0) / total
        out.append(Insight(
            insightId=f"ins_{qid}_concentration", kind="concentration",
            text=(f"{_member(hi.get('key') or {})} alone accounts for "
                  f"{share:.1f}% of the total {measure} across {len(rows)} groups."),
            questionId=qid, planId=plan or None, analyticsRef=ref,
            evidenceRef=ev_ref or None, value=round(share, 1), confidence=0.85,
            severity=INFO,
            refs={"member": _member(hi.get("key") or {}), "ofTotal": round(total, 1),
                  "measure": measure, "rowIds": list(hi.get("rowIds") or [])}))

    # Outliers: robust modified z-score (median + MAD), resistant to masking.
    vals = [v for v in values if v is not None]
    if len(vals) >= 3:
        med = _median(vals)
        deviations = [abs(v - med) for v in vals]
        mad = _median(deviations)
        # Scale + factor: MAD (×0.6745) when non-zero, else mean-abs-dev (×0.7979).
        if mad > 0:
            scale, factor = mad, 0.6745
        else:
            mean_ad = sum(deviations) / len(deviations)
            scale, factor = mean_ad, 0.7979
        if scale > 0:
            for r in rows:
                v = _num(r.get("value"))
                if v is None:
                    continue
                mz = factor * (v - med) / scale
                if mz >= _OUTLIER_MODZ:
                    out.append(_mk("outlier_high",
                                   f"{_member(r.get('key') or {})} is an outlier on the high "
                                   f"side for {measure} ({_fmt(v)}, well above the typical range).",
                                   r, severity=WARNING, conf=0.8))
                elif mz <= -_OUTLIER_MODZ:
                    out.append(_mk("outlier_low",
                                   f"{_member(r.get('key') or {})} is an outlier on the low "
                                   f"side for {measure} ({_fmt(v)}, well below the typical range).",
                                   r, severity=WARNING, conf=0.8))
    return out


def _ranking_insights(rank: dict[str, Any], evidence: dict[str, Any],
                      report: dict[str, Any] | None) -> list[Insight]:
    qid = rank.get("questionId") or ""
    ref = rank.get("rankId") or ""
    measure = rank.get("measure") or "value"
    ev_ref = _evidence_ref_for(evidence, qid)
    plan = _plan_for(report, qid)
    items = [it for it in (rank.get("items") or []) if _num(it.get("value")) is not None]
    if not items:
        return []
    top = items[0]
    names = ", ".join(_member(it.get("key") or {}) for it in items[: min(3, len(items))])
    out = [Insight(
        insightId=f"ins_{qid}_top_value", kind="top_value",
        text=(f"{_member(top.get('key') or {})} leads on {measure} "
              f"at {_fmt(top.get('value'))}" + (f"; top entries: {names}." if len(items) > 1 else ".")),
        questionId=qid, planId=plan or None, analyticsRef=ref, evidenceRef=ev_ref or None,
        value=top.get("value"), confidence=0.9, severity=INFO,
        refs={"member": _member(top.get("key") or {}), "measure": measure,
              "topN": len(items), "rowIds": list(top.get("rowIds") or [])})]
    if len(items) >= 2:
        bottom = items[-1]
        out.append(Insight(
            insightId=f"ins_{qid}_bottom_value", kind="bottom_value",
            text=(f"{_member(bottom.get('key') or {})} ranks lowest on {measure} "
                  f"at {_fmt(bottom.get('value'))}."),
            questionId=qid, planId=plan or None, analyticsRef=ref, evidenceRef=ev_ref or None,
            value=bottom.get("value"), confidence=0.9, severity=INFO,
            refs={"member": _member(bottom.get("key") or {}), "measure": measure,
                  "rowIds": list(bottom.get("rowIds") or [])}))
    return out


def _trend_insights(trend: dict[str, Any], evidence: dict[str, Any],
                    report: dict[str, Any] | None) -> list[Insight]:
    qid = trend.get("questionId") or ""
    ref = trend.get("trendId") or ""
    measure = trend.get("measure") or "value"
    ev_ref = _evidence_ref_for(evidence, qid)
    plan = _plan_for(report, qid)
    pts = [p for p in (trend.get("points") or []) if _num(p.get("value")) is not None]
    if len(pts) < 2:
        return []
    first, last = pts[0], pts[-1]
    fv, lv = _num(first.get("value")), _num(last.get("value"))
    direction = "rose" if lv > fv else ("fell" if lv < fv else "held steady")
    out = [Insight(
        insightId=f"ins_{qid}_trend_direction", kind="trend_direction",
        text=(f"{measure} {direction} from {_fmt(fv)} in {first.get('period')} "
              f"to {_fmt(lv)} in {last.get('period')}."),
        questionId=qid, planId=plan or None, analyticsRef=ref, evidenceRef=ev_ref or None,
        value=lv, confidence=0.88, severity=INFO,
        refs={"measure": measure, "from": first.get("period"), "to": last.get("period"),
              "rowIds": list(first.get("rowIds") or []) + list(last.get("rowIds") or [])})]
    if fv not in (None, 0):
        growth = 100.0 * (lv - fv) / fv
        word = "growth" if growth >= 0 else "decline"
        out.append(Insight(
            insightId=f"ins_{qid}_growth", kind="growth",
            text=(f"That is a {abs(growth):.1f}% {word} in {measure} over the period."),
            questionId=qid, planId=plan or None, analyticsRef=ref, evidenceRef=ev_ref or None,
            value=round(growth, 1), confidence=0.85, severity=INFO,
            refs={"measure": measure, "fromValue": fv, "toValue": lv}))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Caveat detectors (pure caveats — no analytics ref required)
# ─────────────────────────────────────────────────────────────────────────────


def _caveat_insights(report: dict[str, Any] | None, quality: dict[str, Any] | None,
                     verifier_checks: list[dict[str, Any]] | None) -> list[Insight]:
    out: list[Insight] = []
    audit = (report or {}).get("auditAST") or {}

    # Verifier warn/fail checks → data caveats.
    checks = verifier_checks
    if checks is None:
        checks = (audit.get("verification") or {}).get("checks") or []
    for c in checks:
        sev = (c.get("severity") or "").lower()
        if sev in ("warn", "fail"):
            out.append(Insight(
                insightId=f"ins_caveat_{c.get('code', 'check')}".lower(),
                kind="data_caveat",
                text=f"Data caveat ({c.get('code')}): {c.get('message')}",
                value=None, confidence=0.9,
                severity=CAVEAT if sev == "warn" else WARNING,
                refs={"check": c.get("code"), "verifierSeverity": sev}))

    # Provenance coverage caveat.
    q = quality
    if q is None:
        q = (audit.get("verification") or {}).get("quality") or {}
    cov = q.get("provenanceCoverage")
    if isinstance(cov, (int, float)) and cov < _COVERAGE_FLOOR:
        out.append(Insight(
            insightId="ins_coverage_caveat", kind="coverage_caveat",
            text=(f"Provenance coverage is {100.0 * cov:.0f}% — some values could not be "
                  f"traced to source evidence; interpret those with care."),
            value=round(float(cov), 3), confidence=0.95, severity=CAVEAT,
            refs={"provenanceCoverage": round(float(cov), 3)}))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def _sort_key(ins: Insight) -> tuple:
    return (_KIND_ORDER.get(ins.kind, 99), ins.questionId or "", -(_num(ins.value) or 0.0))


def derive_insights(
    analytics: dict[str, Any],
    evidence: dict[str, Any],
    report: dict[str, Any] | None = None,
    *,
    statistical_context: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    verifier_checks: list[dict[str, Any]] | None = None,
) -> list[Insight]:
    """Derive deterministic, evidence-backed insights from trusted analytics.

    Reads only rollups + audit context; never the raw dataset. Returns a stably
    ordered list (kind priority → questionId → value). Pure caveats (verifier /
    coverage) are allowed to carry no analytics ref; every other insight references
    the rollup it came from.
    """
    analytics = analytics or {}
    evidence = evidence or {}
    insights: list[Insight] = []

    for agg in analytics.get("aggregations", []):
        insights.extend(_aggregation_insights(agg, evidence, report))
    for rank in analytics.get("rankings", []):
        insights.extend(_ranking_insights(rank, evidence, report))
    for trend in analytics.get("trends", []):
        insights.extend(_trend_insights(trend, evidence, report))

    insights.extend(_caveat_insights(report, quality, verifier_checks))

    insights.sort(key=_sort_key)
    logger.info("[S5f] derived %d insight(s) across %d agg / %d rank / %d trend",
                len(insights), len(analytics.get("aggregations", [])),
                len(analytics.get("rankings", [])), len(analytics.get("trends", [])))
    return insights


# ─────────────────────────────────────────────────────────────────────────────
# Report wiring (machine + human findings)
# ─────────────────────────────────────────────────────────────────────────────


def key_findings(insights: list[Insight], *, limit: int = 6) -> list[str]:
    """The top human-readable findings (info/warning first, caveats last)."""
    non_caveat = [i for i in insights if i.severity != CAVEAT]
    caveats = [i for i in insights if i.severity == CAVEAT]
    chosen = (non_caveat + caveats)[:limit]
    return [i.text for i in chosen]


def attach_insights(
    report: dict[str, Any],
    *,
    quality: dict[str, Any] | None = None,
    verifier_checks: list[dict[str, Any]] | None = None,
    add_key_findings_block: bool = True,
) -> list[Insight]:
    """Derive insights from the assembled report and record them (in place).

    Stores machine-readable objects under ``auditAST.insights`` and, when
    ``add_key_findings_block`` is set and a Key-Findings slot is absent, prepends a
    human "Key Findings" block to ``contentAST.blocks``. Backward-compatible: no new
    top-level key; existing blocks/order are preserved.
    """
    analytics = report.get("analyticsAST") or {}
    evidence = report.get("evidenceAST") or {}
    stat_ctx = (report.get("auditAST") or {}).get("statisticalContext")
    insights = derive_insights(
        analytics, evidence, report,
        statistical_context=stat_ctx, quality=quality, verifier_checks=verifier_checks,
    )

    audit = report.setdefault("auditAST", {})
    audit["insights"] = [i.to_dict() for i in insights]

    if add_key_findings_block:
        findings = key_findings(insights)
        if findings:
            blocks = (report.setdefault("contentAST", {})).setdefault("blocks", [])
            already = any(b.get("blockId") == "key_findings" for b in blocks)
            if not already:
                # Appended (not prepended) so existing narrated block order is preserved.
                blocks.append({
                    "blockId": "key_findings",
                    "kind": "key_findings",
                    "title": "Key Findings",
                    "items": findings,
                    "slot": {"status": "filled"},
                    "provenance": {"derivedFrom": "auditAST.insights"},
                })
    return insights
