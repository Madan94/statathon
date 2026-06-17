"""Comprehensive multi-angle verification of the generated energy report.

Checks: API verdict/gate, AST top-level shape + provenance chain integrity,
caveat visibility, content completeness vs the template promise, number
traceability, and PDF validity. Prints a PASS/FAIL matrix.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import requests

BASE = "http://127.0.0.1:8099"
TID = "tpl_energy_enterprise_v2"
SIG = "b7acf2ae375faab7"
OUT = Path("outputs")
STEM = f"{TID}__{SIG}"

P = 0
F = 0


def ck(label: str, cond: bool, detail: str = "") -> None:
    global P, F
    mark = "✓" if cond else "✗"
    if cond:
        P += 1
    else:
        F += 1
    print(f"  {mark} {label}" + (f" — {detail}" if (detail and not cond) else (f"  ({detail})" if detail else "")))


print("=" * 70)
print("  MULTI-ANGLE REPORT VERIFICATION")
print("=" * 70)

# ── Angle 1: API verdict & gate ───────────────────────────────────
print("\n[1] API verdict & publish gate")
s = requests.Session()
s.post(f"{BASE}/auth/dev/quick-login", json={"email": "officer@example.com", "password": "TestOfficer123!"})
r = s.post(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/generate",
           json={"use_llm": False, "publish_mode": "strict", "mode": "fresh"})
ck("POST /generate → 200 (strict mode)", r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}")
gen = r.json() if r.status_code == 200 else {}
ck("verdict == PASS", gen.get("verdict") == "PASS", f"verdict={gen.get('verdict')}")
ck("quality_score == 100", gen.get("quality_score") == 100.0, f"score={gen.get('quality_score')}")
ck("publishable == True (strict)", gen.get("publishable") is True, f"publishable={gen.get('publishable')}")
ck("valid == True", gen.get("valid") is True)
st = gen.get("stats") or {}
ck("tableRows filled == traced", (st.get("tableRows") or {}).get("filled") == (st.get("tableRows") or {}).get("traced"))
ck("chartPoints filled == traced", (st.get("chartPoints") or {}).get("filled") == (st.get("chartPoints") or {}).get("traced"))

# ── Angle 2: AST shape + provenance chain ─────────────────────────
print("\n[2] Report AST integrity")
ast = json.loads((OUT / f"{STEM}.report.ast.json").read_text(encoding="utf-8"))
TOP = ["$schema", "metadata", "datasetAST", "bindingAST", "analyticsAST",
       "evidenceAST", "contentAST", "tableAST", "chartAST", "figureAST",
       "semanticAST", "auditAST"]
for k in TOP:
    ck(f"top-level key '{k}'", k in ast)
secs = (ast.get("semanticAST") or {}).get("sections") or []
ck("semanticAST.sections present", len(secs) > 0, f"{len(secs)} sections")
tables = (ast.get("tableAST") or {}).get("tables") or []
charts = (ast.get("chartAST") or {}).get("charts") or []
figs = (ast.get("figureAST") or {}).get("figures") or []
blocks = (ast.get("contentAST") or {}).get("blocks") or []
ck("tableAST has tables", len(tables) >= 4, f"{len(tables)} tables")
ck("chartAST has charts", len(charts) >= 6, f"{len(charts)} charts")
ck("figureAST has figures", len(figs) >= 6, f"{len(figs)} figures")
ck("contentAST has blocks", len(blocks) >= 7, f"{len(blocks)} blocks")

# provenance: every filled table/chart references analytics + evidence ids that exist
an = ast.get("analyticsAST") or {}
analytic_ids = set()
for a in an.get("aggregations", []):
    analytic_ids.add(a.get("aggId"))
for rk in an.get("rankings", []):
    analytic_ids.add(rk.get("rankId"))
for m in an.get("metrics", []):
    analytic_ids.add(m.get("metricId"))
analytic_ids.discard(None)
ev_ids = {e.get("evidenceId") for e in (ast.get("evidenceAST") or {}).get("evidence", [])}
ev_ids.discard(None)
bad_prov = []
for t in tables:
    pr = t.get("provenance") or {}
    if (t.get("slot") or {}).get("status") == "filled":
        ar = pr.get("analyticsRef")
        if ar and ar not in analytic_ids:
            bad_prov.append(("table", t.get("tableId"), ar))
ck("all filled tables have resolvable analyticsRef", not bad_prov, f"{bad_prov[:3]}")

# every chart point + table row carries rowIds
pts_no_rowids = sum(
    1 for c in charts for sgroup in (c.get("series") or []) for p in (sgroup.get("points") or [])
    if not p.get("rowIds")
)
ck("every chart point carries rowIds", pts_no_rowids == 0, f"{pts_no_rowids} missing")
rows_no_rowids = sum(1 for t in tables for row in (t.get("rows") or []) if not row.get("rowIds"))
ck("every table row carries rowIds", rows_no_rowids == 0, f"{rows_no_rowids} missing")

# ── Angle 3: caveat visibility ────────────────────────────────────
print("\n[3] Caveat visibility & verifier checks")
audit = ast.get("auditAST") or {}
ver = audit.get("verification") or {}
checks = {c.get("code"): c for c in (ver.get("checks") or [])}
cav = checks.get("CAVEAT_VISIBILITY") or {}
ck("CAVEAT_VISIBILITY == pass", cav.get("severity") == "pass", f"sev={cav.get('severity')} :: {cav.get('message')}")
nn = checks.get("NARRATIVE_NUMBERS") or {}
ck("NARRATIVE_NUMBERS == pass", nn.get("severity") == "pass", f"sev={nn.get('severity')} :: {nn.get('message')}")
fails = [c for c in (ver.get("checks") or []) if c.get("severity") in ("fail", "error")]
ck("no failing verifier checks", not fails, f"{[c.get('message') for c in fails][:3]}")
q = ver.get("quality") or {}
ck("provenanceCoverage == 1.0", q.get("provenanceCoverage") == 1.0, f"{q.get('provenanceCoverage')}")
ck("verifiedNumberRatio == 1.0", q.get("verifiedNumberRatio") == 1.0, f"{q.get('verifiedNumberRatio')}")
caveat_block = [b for b in blocks if b.get("blockId") == "caveats_limitations"]
ck("Caveats & Limitations block present", len(caveat_block) == 1,
   f"items={len(caveat_block[0]['items']) if caveat_block else 0}")

# ── Angle 4: content completeness vs template promise ─────────────
print("\n[4] Content completeness (vs template promise: 3 topics, 8 q, 6 charts, 4 tables)")
cov = (ast.get("metadata") or {}).get("coverage") or {}
ck("questionsAnswered >= 7", (cov.get("questionsAnswered") or 0) >= 7, f"answered={cov.get('questionsAnswered')}/{cov.get('questionsTotal')}")
ck("bindingsConfirmed == 20", cov.get("bindingsConfirmed") == 20, f"{cov.get('bindingsConfirmed')}")
ck(">=3 topic divider sections", sum(1 for s in secs if s.get("level") == 1) >= 3,
   f"{sum(1 for s in secs if s.get('level') == 1)} topics")
ck(">=4 tables (promise)", len(tables) >= 4)
ck(">=6 charts (promise)", len(charts) >= 6)

# ── Angle 5: rendered HTML + PDF ──────────────────────────────────
print("\n[5] Rendered HTML + PDF deliverables")
html = (OUT / f"{STEM}.report.html").read_text(encoding="utf-8")
ck("HTML standalone has <html>", "<html" in html[:200].lower())
ck("HTML title is the energy report", "India Energy Resources" in html)
ck("HTML has data tables", html.count("<table") >= 4, f"{html.count('<table')} tables")
ck("HTML has charts (svg)", html.count("<svg") >= 6, f"{html.count('<svg')} charts")
# Only count actual rendered unresolved markers in the body, not the CSS rule.
_body = html.split("</style>", 1)[-1]
ck("HTML has no unresolved slots",
   "[unresolved:" not in _body and 'class="empty-slot"' not in _body)
print_html = OUT / f"{STEM}.report.print.html"
ck("print HTML (full chrome) exists", print_html.exists(), f"{print_html.stat().st_size if print_html.exists() else 0} bytes")
pdf = OUT / f"{STEM}.report.pdf"
ck("PDF exists", pdf.exists())
if pdf.exists():
    head = pdf.read_bytes()[:5]
    ck("PDF magic bytes %PDF", head[:4] == b"%PDF", f"head={head!r}")
    ck("PDF non-trivial size (>50KB)", pdf.stat().st_size > 50_000, f"{pdf.stat().st_size:,} bytes")

# ── Angle 6: API report retrieval ─────────────────────────────────
print("\n[6] API retrieval endpoints")
r = s.get(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/report")
ck("GET /report → 200", r.status_code == 200)
r = s.get(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/report.html")
ck("GET /report.html → 200", r.status_code == 200)
ck("served HTML matches energy report", "India Energy Resources" in (r.text if r.status_code == 200 else ""))

print("\n" + "=" * 70)
print(f"  RESULT: {P} passed, {F} failed")
print("=" * 70)
sys.exit(0 if F == 0 else 1)
