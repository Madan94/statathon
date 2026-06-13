"""S5d — Verifier gate + report quality score.

The verifier turns "we generated a report" into "we can trust this report". It is a
**judge, not a fixer**: it never mutates the report, it only inspects the assembled
artifact + its analytics/evidence + (optionally) the bundle, adapted plans, executed
dataframe and pinned content hash, and returns a verdict (PASS / WARN / FAIL) with a
quality score.

Checks (each emits one :class:`VerificationCheck`):
  * STRUCTURE        — the gold report shape + provenance chain (`validate_report`).
  * PROVENANCE       — every filled table/chart/metric value traces to evidence/rowIds.
  * NO_BLOCKED_LEAK  — no BLOCKED/skipped plan produced a value in the analytics.
  * CAVEAT_VISIBILITY— every DEGRADED plan's diagnostic is visible in the audit/warnings.
  * NARRATIVE_NUMBERS— every number in the prose matches an analytics value (`validate_numbers`).
  * CONTENT_HASH     — the pinned bundle hash matches the executed dataset hash.
  * FORMULA_RECOMPUTE— SHARE/RATE/RATIO are independently recomputable from the data;
                       unsupported verifier types WARN (never FAIL, never crash).

Verdict policy: any FAIL ⇒ FAIL (blocks official publish later); else any WARN ⇒ WARN
(draft allowed, caveats visible); else PASS. Policy knobs (tolerance, score weights)
come from a :class:`VerifierPolicy` derived from the generation profile — MoSPI rules
are not hardcoded here. Fully offline and deterministic.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pandas as pd

from report_builder.generation._agg import _apply_filters
from report_builder.generation.assembler import validate_report
from report_builder.generation.config import GenerationConfig, load_profile
from report_builder.generation.lineage import iter_measured_values
from report_builder.generation.narrator import validate_numbers

if TYPE_CHECKING:
    from report_builder.binding.execution_contracts import ExecutionBundle
    from report_builder.generation.bundle_adapter import AdaptedPlan

logger = logging.getLogger(__name__)

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_SEVERITY_RANK = {"pass": 0, "warn": 1, "fail": 2}

# Formula families the verifier can independently recompute today. Others WARN.
_RECOMPUTABLE = {"SHARE", "RATE", "RATIO"}

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


# ─────────────────────────────────────────────────────────────────────────────
# Policy (profile-derived; not hardcoded MoSPI)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VerifierPolicy:
    """Tunable verifier thresholds + score weights, derived from a generation profile."""

    tolerance: float = 0.05          # relative tolerance for recompute equality
    abs_tolerance: float = 0.1       # absolute floor (rounded values)
    # Quality score weights (coverage portion, summing to 1.0).
    w_provenance: float = 0.35
    w_formula: float = 0.25
    w_numbers: float = 0.25
    w_caveat: float = 0.15
    # Penalties subtracted from the coverage score (0..100).
    penalty_blocked: float = 25.0
    penalty_fail: float = 15.0
    penalty_warn: float = 4.0

    @classmethod
    def from_profile(cls, profile: GenerationConfig) -> "VerifierPolicy":
        return cls(tolerance=profile.verifier_tolerance)


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class VerificationCheck:
    code: str
    severity: str                    # pass | warn | fail
    message: str
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity,
                "message": self.message, "refs": dict(self.refs)}


@dataclass
class VerificationReport:
    verdict: str                     # PASS | WARN | FAIL
    checks: list[VerificationCheck] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "checks": [c.to_dict() for c in self.checks],
            "quality": dict(self.quality),
        }

    @property
    def failures(self) -> list[VerificationCheck]:
        return [c for c in self.checks if c.severity == "fail"]


# ─────────────────────────────────────────────────────────────────────────────
# Small numeric helpers
# ─────────────────────────────────────────────────────────────────────────────


def _num(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _close(a: float, b: float, policy: VerifierPolicy) -> bool:
    return abs(a - b) <= max(policy.abs_tolerance, policy.tolerance * max(abs(a), abs(b), 1.0))


def _analytics_values(analytics: dict[str, Any]) -> set[float]:
    """Every number the prose is allowed to state (rounded to 1dp).

    Mirrors the narrator's ``QuestionFacts.allowed_values``: the raw analytics values
    **plus** the within-question pairwise gaps a desk officer derives from them (e.g.
    "a gap of 18.0 points" between two group values). Without the gaps the verifier
    would falsely FAIL legitimate prose the narrator itself emits and validated.
    """
    vals: set[float] = set()
    # questionId → pool of values that can be differenced against each other.
    pools: dict[str, list[float]] = {}

    def add(v: Any, qid: str | None = None) -> None:
        n = _num(v)
        if n is None:
            return
        r = round(n, 1)
        vals.add(r)
        if qid is not None:
            pools.setdefault(qid, []).append(r)

    for a in analytics.get("aggregations", []):
        qid = a.get("questionId") or ""
        for row in a.get("rows", []):
            add(row.get("value"), qid)
    for m in analytics.get("metrics", []):
        add(m.get("value"), m.get("questionId") or "")
    for r in analytics.get("rankings", []):
        qid = r.get("questionId") or ""
        for it in r.get("items", []):
            add(it.get("value"), qid)
    for t in analytics.get("trends", []):
        qid = t.get("questionId") or ""
        for p in t.get("points", []):
            add(p.get("value"), qid)

    # Pairwise within-question gaps (the figures the narrator derives + validates).
    for pool in pools.values():
        for i in range(len(pool)):
            for j in range(i + 1, len(pool)):
                vals.add(round(abs(pool[i] - pool[j]), 1))
    return vals


# ─────────────────────────────────────────────────────────────────────────────
# Individual checks
# ─────────────────────────────────────────────────────────────────────────────


def _check_structure(report: dict[str, Any], row_index: dict[str, list[int]] | None,
                     checks: list[VerificationCheck]) -> None:
    res = validate_report(report, row_index=row_index)
    if res["errors"]:
        checks.append(VerificationCheck(
            "STRUCTURE", "fail",
            f"report failed structural/provenance validation ({len(res['errors'])} error(s))",
            {"errors": res["errors"][:10]},
        ))
    elif res["warnings"]:
        checks.append(VerificationCheck(
            "STRUCTURE", "warn",
            f"report has {len(res['warnings'])} structural warning(s)",
            {"warnings": res["warnings"][:10]},
        ))
    else:
        checks.append(VerificationCheck("STRUCTURE", "pass", "report structure + provenance chain valid"))


def _filled_artifacts(report: dict[str, Any]) -> list[tuple[str, str, list[str]]]:
    """Every filled value slot → (kind, id, refs). Uses the shared measured-value
    enumeration (the same one the audit coverage uses) so the two never disagree."""
    return [(m.kind, m.elementId, m.refs) for m in iter_measured_values(report)]


def _check_provenance(report: dict[str, Any], checks: list[VerificationCheck]) -> float:
    artifacts = _filled_artifacts(report)
    if not artifacts:
        checks.append(VerificationCheck("PROVENANCE", "pass", "no filled value slots to trace"))
        return 1.0
    traced = sum(1 for _kind, _id, refs in artifacts if refs)
    missing = [(k, i) for k, i, refs in artifacts if not refs]
    coverage = traced / len(artifacts)
    if missing:
        checks.append(VerificationCheck(
            "PROVENANCE", "fail",
            f"{len(missing)} filled value(s) have no provenance/evidence link",
            {"missing": missing[:10], "coverage": round(coverage, 3)},
        ))
    else:
        checks.append(VerificationCheck(
            "PROVENANCE", "pass", "every filled value links to evidence/provenance",
            {"coverage": 1.0},
        ))
    return coverage


def _blocked_qids(analytics: dict[str, Any], adapted: "list[AdaptedPlan] | None") -> set[str]:
    blocked: set[str] = set()
    for e in analytics.get("executions", []):
        if e.get("status") == "skipped":
            ref = str(e.get("questionId") or e.get("executionId") or e.get("planRef") or "")
            qid = ref.split("_", 1)[1] if ref.startswith("exec_") else ref
            if qid:
                blocked.add(qid)
    for plan in adapted or []:
        if (getattr(plan, "status", "") or "").upper() == "BLOCKED":
            blocked.add(plan.questionId or plan.planRec.questionId)
    return blocked


def _check_no_blocked_leak(analytics: dict[str, Any], adapted: "list[AdaptedPlan] | None",
                           checks: list[VerificationCheck]) -> int:
    blocked = _blocked_qids(analytics, adapted)
    if not blocked:
        checks.append(VerificationCheck("NO_BLOCKED_LEAK", "pass", "no BLOCKED plans present"))
        return 0
    leaked: list[str] = []
    for bucket, id_key in (("aggregations", "aggId"), ("rankings", "rankId"),
                           ("trends", "trendId"), ("metrics", "metricId")):
        for obj in analytics.get(bucket, []):
            qid = obj.get("questionId")
            if qid in blocked and _has_value(bucket, obj):
                leaked.append(obj.get(id_key, qid))
    if leaked:
        checks.append(VerificationCheck(
            "NO_BLOCKED_LEAK", "fail",
            f"{len(leaked)} analytics result(s) came from BLOCKED plan(s)",
            {"leaked": leaked[:10], "blockedQuestions": sorted(blocked)},
        ))
    else:
        checks.append(VerificationCheck(
            "NO_BLOCKED_LEAK", "pass", "BLOCKED plans produced no values",
            {"blockedQuestions": sorted(blocked)},
        ))
    return len(leaked)


def _has_value(bucket: str, obj: dict[str, Any]) -> bool:
    if bucket == "aggregations":
        return any(_num(r.get("value")) is not None for r in obj.get("rows", []))
    if bucket == "rankings":
        return any(_num(it.get("value")) is not None for it in obj.get("items", []))
    if bucket == "trends":
        return any(_num(p.get("value")) is not None for p in obj.get("points", []))
    return _num(obj.get("value")) is not None


def _caveat_haystack(report: dict[str, Any]) -> str:
    audit = report.get("auditAST") or {}
    parts: list[str] = []
    parts.extend(str(w) for w in (audit.get("warnings") or []))
    parts.extend(str(w) for w in ((report.get("metadata") or {}).get("warnings") or []))
    parts.extend(str(c) for c in (audit.get("caveats") or []))
    return "\n".join(parts).lower()


def _check_caveats(report: dict[str, Any], adapted: "list[AdaptedPlan] | None",
                   checks: list[VerificationCheck]) -> float:
    degraded = [p for p in (adapted or [])
                if (getattr(p, "status", "") or "").upper() == "DEGRADED" or p.diagnostics]
    if not degraded:
        checks.append(VerificationCheck("CAVEAT_VISIBILITY", "pass", "no DEGRADED plans to caveat"))
        return 1.0
    haystack = _caveat_haystack(report)
    uncovered: list[str] = []
    for plan in degraded:
        qid = plan.questionId or plan.planRec.questionId
        # Covered if the question id or any of its diagnostics surfaces in the audit/caveats.
        token = qid.lower() if qid else ""
        diag_hit = any(str(d).lower()[:24] in haystack for d in (plan.diagnostics or []) if d)
        if not ((token and token in haystack) or diag_hit):
            uncovered.append(qid)
    covered = len(degraded) - len(uncovered)
    coverage = covered / len(degraded)
    if uncovered:
        checks.append(VerificationCheck(
            "CAVEAT_VISIBILITY", "warn",
            f"{len(uncovered)} DEGRADED plan(s) have no visible caveat",
            {"uncovered": uncovered[:10], "coverage": round(coverage, 3)},
        ))
    else:
        checks.append(VerificationCheck(
            "CAVEAT_VISIBILITY", "pass", "every DEGRADED plan has a visible caveat",
            {"coverage": 1.0},
        ))
    return coverage


def _check_narrative(report: dict[str, Any], analytics: dict[str, Any],
                     checks: list[VerificationCheck]) -> float:
    allowed = _analytics_values(analytics)
    period = ((report.get("metadata") or {}).get("period") or {}).get("current") or ""
    ignore = [str(period)] if period else []
    total = 0
    bad_total: list[str] = []
    for b in (report.get("contentAST") or {}).get("blocks", []):
        if (b.get("slot") or {}).get("status") != "filled":
            continue
        text = b.get("content") or ""
        if not text:
            continue
        scrubbed = text
        for ig in ignore:
            scrubbed = scrubbed.replace(ig, " ")
        total += len(_NUMBER_RE.findall(scrubbed.replace(",", "")))
        ok, bad = validate_numbers(text, allowed, ignore=ignore)
        if not ok:
            bad_total.extend(bad)
    if total == 0:
        checks.append(VerificationCheck("NARRATIVE_NUMBERS", "pass", "no narrative numbers to verify"))
        return 1.0
    ratio = max(0.0, (total - len(bad_total)) / total)
    if bad_total:
        checks.append(VerificationCheck(
            "NARRATIVE_NUMBERS", "fail",
            f"{len(bad_total)} narrative number(s) do not match any analytics value",
            {"unverified": bad_total[:10], "verifiedRatio": round(ratio, 3)},
        ))
    else:
        checks.append(VerificationCheck(
            "NARRATIVE_NUMBERS", "pass", "every narrative number matches analytics",
            {"verifiedRatio": 1.0},
        ))
    return ratio


def _check_content_hash(bundle: "ExecutionBundle | None", content_hash: str | None,
                        checks: list[VerificationCheck]) -> None:
    pinned = ""
    if bundle is not None:
        pinned = str((bundle.dataframeRef or {}).get("contentHash") or "")
    if not pinned or not content_hash:
        checks.append(VerificationCheck(
            "CONTENT_HASH", "pass", "no pinned/current hash pair to compare",
            {"pinned": pinned, "current": content_hash or ""},
        ))
        return
    if pinned != content_hash:
        checks.append(VerificationCheck(
            "CONTENT_HASH", "fail",
            "executed dataset hash does not match the bundle's pinned contentHash (data drift)",
            {"pinned": pinned, "current": content_hash},
        ))
    else:
        checks.append(VerificationCheck("CONTENT_HASH", "pass", "dataset content hash matches the pinned snapshot"))


def _recompute_quotient(plan: "AdaptedPlan", df: pd.DataFrame,
                        profile: GenerationConfig) -> dict[tuple, float | None] | None:
    """Independently recompute a SHARE/RATE/RATIO plan from the data (aggregate-then-divide)."""
    spec = plan.formulaSpec
    num = spec.numeratorColumn or plan.measureColumn or plan.planRec.measure.columnExpr
    den = spec.denominatorColumn
    if not num or not den or num not in df.columns or den not in df.columns:
        return None
    frame, _ = _apply_filters(df.reset_index(drop=True), plan.planRec.filters)
    dims = [d for d in (plan.planRec.groupBy or []) if d and d in frame.columns]
    mult = profile.multiplier_for(spec.type, spec.multiplier)
    out: dict[tuple, float | None] = {}

    def q(sub: pd.DataFrame) -> float | None:
        n = pd.to_numeric(sub[num], errors="coerce").sum()
        d = pd.to_numeric(sub[den], errors="coerce").sum()
        return round(n / d * mult, profile.rounding) if d else None

    if dims:
        gkey = dims[0] if len(dims) == 1 else dims
        for member, sub in frame.groupby(gkey, sort=False):
            key = (member,) if not isinstance(member, tuple) else member
            out[key] = q(sub)
    else:
        out[("__overall__",)] = q(frame)
    return out


def _agg_rows_for(analytics: dict[str, Any], qid: str) -> dict[tuple, float | None]:
    for a in analytics.get("aggregations", []):
        if a.get("questionId") == qid:
            return {tuple(r.get("key", {}).values()) or ("__overall__",): _num(r.get("value"))
                    for r in a.get("rows", [])}
    for m in analytics.get("metrics", []):
        if m.get("questionId") == qid:
            return {("__overall__",): _num(m.get("value"))}
    return {}


def _check_formula_recompute(analytics: dict[str, Any], adapted: "list[AdaptedPlan] | None",
                             df: pd.DataFrame | None, profile: GenerationConfig,
                             policy: VerifierPolicy, checks: list[VerificationCheck]) -> float:
    formula_plans = [p for p in (adapted or [])
                     if (p.formulaSpec.type or "DIRECT").upper() != "DIRECT"]
    if not formula_plans or df is None:
        checks.append(VerificationCheck("FORMULA_RECOMPUTE", "pass",
                                        "no formula plans / no dataframe to recompute"))
        return 1.0

    total = 0
    ok_count = 0
    mismatches: list[str] = []
    unsupported: list[str] = []
    for plan in formula_plans:
        ftype = (plan.formulaSpec.type or "").upper()
        qid = plan.questionId or plan.planRec.questionId
        if ftype not in _RECOMPUTABLE or (plan.normalizationPlan.type or "NONE").upper() != "NONE":
            unsupported.append(f"{qid}:{ftype}")
            continue
        recomputed = _recompute_quotient(plan, df, profile)
        if recomputed is None:
            unsupported.append(f"{qid}:{ftype}")
            continue
        expected = _agg_rows_for(analytics, qid)
        total += 1
        agree = True
        for key, rv in recomputed.items():
            ev = expected.get(key)
            if rv is None or ev is None:
                continue
            if not _close(rv, ev, policy):
                agree = False
                mismatches.append(f"{qid}{list(key)}: recomputed {rv} vs report {ev}")
        if agree:
            ok_count += 1

    if mismatches:
        checks.append(VerificationCheck(
            "FORMULA_RECOMPUTE", "fail",
            f"{len(mismatches)} formula value(s) are not recomputable from the data",
            {"mismatches": mismatches[:10], "unsupported": unsupported[:10]},
        ))
    elif unsupported and total == 0:
        checks.append(VerificationCheck(
            "FORMULA_RECOMPUTE", "warn",
            f"{len(unsupported)} formula plan(s) are not verifier-recomputable yet",
            {"unsupported": unsupported[:10]},
        ))
    elif unsupported:
        checks.append(VerificationCheck(
            "FORMULA_RECOMPUTE", "warn",
            f"recomputed {ok_count}/{total} formula(s); {len(unsupported)} unsupported type(s)",
            {"unsupported": unsupported[:10]},
        ))
    else:
        checks.append(VerificationCheck(
            "FORMULA_RECOMPUTE", "pass",
            f"recomputed {ok_count}/{total} formula(s) from the data",
        ))
    return (ok_count / total) if total else 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Quality score + verdict
# ─────────────────────────────────────────────────────────────────────────────


def _score(provenance: float, formula: float, numbers: float, caveat: float,
           blocked_leak: int, fail_count: int, warn_count: int,
           policy: VerifierPolicy) -> dict[str, Any]:
    coverage = 100.0 * (
        policy.w_provenance * provenance
        + policy.w_formula * formula
        + policy.w_numbers * numbers
        + policy.w_caveat * caveat
    )
    penalty = (policy.penalty_blocked * blocked_leak
               + policy.penalty_fail * fail_count
               + policy.penalty_warn * warn_count)
    final = max(0.0, min(100.0, coverage - penalty))
    return {
        "provenanceCoverage": round(provenance, 3),
        "formulaCoverage": round(formula, 3),
        "verifiedNumberRatio": round(numbers, 3),
        "caveatCoverage": round(caveat, 3),
        "blockedLeakCount": blocked_leak,
        "failCount": fail_count,
        "warnCount": warn_count,
        "finalScore": round(final, 1),
    }


def _verdict(checks: list[VerificationCheck]) -> str:
    worst = max((_SEVERITY_RANK[c.severity] for c in checks), default=0)
    return {0: PASS, 1: WARN, 2: FAIL}[worst]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def verify_report(
    report: dict[str, Any],
    analytics: dict[str, Any],
    evidence: dict[str, Any],
    *,
    bundle: "ExecutionBundle | None" = None,
    adapted: "list[AdaptedPlan] | None" = None,
    dataframe: pd.DataFrame | None = None,
    row_index: dict[str, list[int]] | None = None,
    content_hash: str | None = None,
    profile: GenerationConfig | None = None,
) -> VerificationReport:
    """Judge a report's trustworthiness — never mutate it. Returns a verdict + quality.

    Only ``report`` / ``analytics`` / ``evidence`` are required; the optional bundle /
    adapted plans / dataframe / hash unlock the deeper checks (formula recompute, drift,
    blocked-leak via plan status). Missing context degrades a check to PASS-with-note,
    never to a crash.
    """
    profile = profile or load_profile()
    policy = VerifierPolicy.from_profile(profile)
    checks: list[VerificationCheck] = []

    _check_structure(report, row_index, checks)
    provenance = _check_provenance(report, checks)
    blocked_leak = _check_no_blocked_leak(analytics, adapted, checks)
    caveat = _check_caveats(report, adapted, checks)
    numbers = _check_narrative(report, analytics, checks)
    _check_content_hash(bundle, content_hash, checks)
    formula = _check_formula_recompute(analytics, adapted, dataframe, profile, policy, checks)

    fail_count = sum(1 for c in checks if c.severity == "fail")
    warn_count = sum(1 for c in checks if c.severity == "warn")
    quality = _score(provenance, formula, numbers, caveat,
                     blocked_leak, fail_count, warn_count, policy)
    verdict = _verdict(checks)

    logger.info("[verifier] verdict=%s score=%s fails=%d warns=%d",
                verdict, quality["finalScore"], fail_count, warn_count)
    return VerificationReport(verdict=verdict, checks=checks, quality=quality)


# ─────────────────────────────────────────────────────────────────────────────
# Publish gate — turn a verdict into a publish decision (a judge, still not a fixer)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class GateDecision:
    """Whether a verified report may be published, and whether output is blocked.

    ``publishable`` is the trust decision (a FAIL is never publishable). ``blocked``
    is the *action*: in ``strict`` mode a non-publishable report blocks output (the
    caller should refuse, e.g. HTTP 409); in ``draft`` mode it is allowed through but
    stays marked non-publishable so a reviewer can inspect it.
    """

    verdict: str
    publishMode: str                 # strict | draft
    publishable: bool
    blocked: bool
    reason: str = ""
    failedChecks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "publishMode": self.publishMode,
            "publishable": self.publishable,
            "blocked": self.blocked,
            "reason": self.reason,
            "failedChecks": list(self.failedChecks),
        }


def is_publishable(verdict: str) -> bool:
    """A report is publishable unless the verifier returned FAIL."""
    return verdict != FAIL


def evaluate_gate(verification: VerificationReport, *, publish_mode: str = "strict") -> GateDecision:
    """Decide whether ``verification`` permits publishing under ``publish_mode``.

    Pure + deterministic. PASS/WARN are always publishable (WARN never blocks). A FAIL
    is non-publishable; it **blocks** only in ``strict`` mode — ``draft`` lets it
    through, still flagged ``publishable=False`` so nothing FAILed is silently shipped.
    """
    mode = publish_mode if publish_mode in ("strict", "draft") else "strict"
    publishable = is_publishable(verification.verdict)
    failed = [c.code for c in verification.failures]
    if publishable:
        return GateDecision(verification.verdict, mode, True, False, "", failed)
    blocked = (mode == "strict")
    reason = (
        f"report failed verification (FAIL): {', '.join(failed) or 'see checks'}"
        + (" — blocked in strict publish mode; retry with publish_mode='draft' to inspect."
           if blocked else " — allowed in draft mode but marked non-publishable.")
    )
    return GateDecision(verification.verdict, mode, False, blocked, reason, failed)

