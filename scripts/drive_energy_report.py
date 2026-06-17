"""Drive a full energy-enterprise report end-to-end against the running backend.

Flow (exactly what the officer UI does, scripted):
  1. Auth (dev quick-login)
  2. POST /binding-phase/start   — upload the energy CSV, get a fresh signature
  3. POST /binding-phase/.../confirm  — confirm every proposed entity binding
  4. POST /binding-phase/.../finalize — resolve questions + coverage + reviewed plan
  5. GET  /generate-phase/.../generation-queue
  6. POST /generate-phase/.../generate-component  — for every queue item
  7. POST /generate-phase/.../generate            — full assembly + verify + publish
  8. GET  report (AST) + report.html + report.pdf  — save to outputs/

Usage:
  .venv\\Scripts\\python.exe scripts\\drive_energy_report.py [csv_path] [--llm]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

# Force UTF-8 stdout so check marks render on the Windows console (cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

BASE = os.getenv("REPORT_BASE", "http://127.0.0.1:8000")
TID = os.getenv("REPORT_TID", "tpl_energy_enterprise_v2")
DEFAULT_CSV = Path("report_builder/gold_standard/energy_enterprise_v2/energy_enterprise_v2.dataset.csv")
OUT_DIR = Path("outputs")

USE_LLM = "--llm" in sys.argv
_args = [a for a in sys.argv[1:] if not a.startswith("--")]
CSV_PATH = Path(_args[0]) if _args else DEFAULT_CSV

s = requests.Session()


def hr(title: str) -> None:
    print(f"\n{'=' * 68}\n  {title}\n{'=' * 68}")


def die(msg: str, resp: requests.Response | None = None) -> None:
    print(f"\nFATAL: {msg}")
    if resp is not None:
        print(f"  HTTP {resp.status_code}: {resp.text[:600]}")
    sys.exit(1)


def _find_browser() -> str | None:
    """Locate a Chromium-family browser for headless HTML→PDF (Edge or Chrome)."""
    import shutil
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    for name in ("chrome", "msedge", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _html_to_pdf_local(html_file: Path, pdf_file: Path) -> bool:
    """Render an HTML file to PDF with a local headless Chromium browser.

    Uses the new headless mode + a file:/// URL. Chromium may print harmless
    policy/GPU warnings to stderr and writes the file slightly after exit, so we
    ignore the return code and poll for the output file.
    """
    import subprocess
    import time as _t

    browser = _find_browser()
    if not browser:
        return False
    pdf_file.parent.mkdir(parents=True, exist_ok=True)
    if pdf_file.exists():
        pdf_file.unlink()
    url = "file:///" + str(html_file.resolve()).replace("\\", "/")
    out = str(pdf_file.resolve())
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--no-sandbox",
        f"--print-to-pdf={out}",
        url,
    ]
    try:
        subprocess.run(cmd, timeout=120, capture_output=True)
    except Exception as exc:  # noqa: BLE001
        print(f"    browser error: {exc}")
    # Poll briefly — the file can land just after the process exits.
    for _ in range(20):
        if pdf_file.exists() and pdf_file.stat().st_size > 0:
            return True
        _t.sleep(0.3)
    return pdf_file.exists() and pdf_file.stat().st_size > 0


# ── 1. Auth ───────────────────────────────────────────────────────
hr("1. AUTH")
r = s.post(f"{BASE}/auth/dev/quick-login",
           json={"email": "officer@example.com", "password": "TestOfficer123!"})
if r.status_code != 200:
    die("dev quick-login failed", r)
print(f"  logged in as {r.json().get('email')}")

# ── 2. Start binding ──────────────────────────────────────────────
hr("2. START BINDING")
if not CSV_PATH.exists():
    die(f"CSV not found: {CSV_PATH}")
print(f"  dataset: {CSV_PATH}  ({CSV_PATH.stat().st_size:,} bytes)")
with open(CSV_PATH, "rb") as f:
    r = s.post(f"{BASE}/report-builder/binding-phase/start",
               data={"template_id": TID},
               files={"dataset": (CSV_PATH.name, f, "text/csv")})
if r.status_code != 200:
    die("start binding failed", r)
start = r.json()
SIG = start["signature"]
proposals = start.get("proposals") or []
pending = start.get("pending") or []
print(f"  signature: {SIG}")
print(f"  dataset_id: {start.get('dataset_id')}")
print(f"  entities proposed: {len(proposals)}  |  pending: {len(pending)}")
bq = start.get("blueprint_qa") or {}
print(f"  blueprint_qa: {bq.get('status')}")

# ── 3. Confirm every proposed entity that has columns ─────────────
hr("3. CONFIRM BINDINGS")
confirmed = 0
skipped = 0
for p in proposals:
    eid = p.get("entityId") or p.get("entity_id")
    cols = p.get("columns") or p.get("proposedColumns") or []
    if not eid:
        continue
    if not cols:
        skipped += 1
        continue
    rc = s.post(f"{BASE}/report-builder/binding-phase/{TID}/{SIG}/confirm",
                json={"entity_id": eid, "action": "confirm"})
    if rc.status_code == 200:
        confirmed += 1
    else:
        # try without forcing — still continue
        skipped += 1
print(f"  confirmed: {confirmed}  |  skipped (no proposed cols): {skipped}")

# ── 4. Finalize ───────────────────────────────────────────────────
hr("4. FINALIZE (resolve questions + coverage)")
r = s.post(f"{BASE}/report-builder/binding-phase/{TID}/{SIG}/finalize", json={})
if r.status_code != 200:
    die("finalize failed", r)
fin = r.json()
cov = fin.get("coverage") or {}
qbs = fin.get("question_bindings") or []
print(f"  has_errors: {fin.get('has_errors')}")
print(f"  question_bindings: {len(qbs)}")
issues = cov.get("issues") or []
errs = [i for i in issues if i.get("severity") == "error"]
warns = [i for i in issues if i.get("severity") == "warn"]
print(f"  coverage issues: {len(errs)} error / {len(warns)} warn")
rp = fin.get("reviewed_plan")
print(f"  reviewed_plan: {'built' if rp else 'MISSING'}")

# ── 5. Generation queue ───────────────────────────────────────────
hr("5. GENERATION QUEUE")
r = s.get(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/generation-queue")
if r.status_code != 200:
    die("generation-queue failed", r)
queue = r.json()
print(f"  {len(queue)} components queued")
for it in queue:
    path = " / ".join(it.get("section_path") or [])
    print(f"   [{it.get('index'):>2}] {it.get('component_type'):<10} {it.get('title','')[:46]:<46} {path[:40]}")

# ── 6. Generate each component ────────────────────────────────────
hr(f"6. GENERATE COMPONENTS (use_llm={USE_LLM})")
ok = 0
fail = 0
t0 = time.time()
for it in queue:
    idx = it.get("index")
    rc = s.post(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/generate-component",
                json={"index": idx, "use_llm": USE_LLM, "redo": True})
    if rc.status_code == 200:
        c = rc.json()
        narr = (c.get("narrative") or "").replace("\n", " ")
        content = c.get("content") or {}
        nrows = len(content.get("items") or content.get("rows") or content.get("rankingData") or [])
        ok += 1
        print(f"   ✓ [{idx:>2}] {c.get('component_type'):<9} {c.get('title','')[:40]:<40} "
              f"rows={nrows:<3} narr={len(narr):>3}c")
    else:
        fail += 1
        print(f"   ✗ [{idx:>2}] HTTP {rc.status_code}: {rc.text[:120]}")
print(f"\n  components OK: {ok}  |  failed: {fail}  |  {time.time()-t0:.1f}s")

# ── 7. Full report generation ─────────────────────────────────────
hr("7. FULL REPORT GENERATION")
t0 = time.time()
r = s.post(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/generate",
           json={"use_llm": USE_LLM, "publish_mode": "draft", "mode": "fresh"})
if r.status_code != 200:
    die("full generate failed", r)
gen = r.json()
print(f"  valid: {gen.get('valid')}  |  publishable: {gen.get('publishable')}")
print(f"  verdict: {gen.get('verdict')}  |  quality_score: {gen.get('quality_score')}")
print(f"  report_id: {gen.get('report_id')}")
print(f"  stats: {gen.get('stats')}")
if gen.get("errors"):
    print(f"  errors: {gen.get('errors')[:5]}")
if gen.get("warnings"):
    print(f"  warnings ({len(gen.get('warnings'))}): {gen.get('warnings')[:3]}")
print(f"  took {time.time()-t0:.1f}s")

# ── 8. Retrieve + save outputs ────────────────────────────────────
hr("8. RETRIEVE + SAVE OUTPUTS")
OUT_DIR.mkdir(exist_ok=True)
stem = f"{TID}__{SIG}"

# AST JSON
r = s.get(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/report")
if r.status_code == 200:
    p = OUT_DIR / f"{stem}.report.ast.json"
    p.write_text(r.text, encoding="utf-8")
    print(f"  ✓ AST   → {p}  ({len(r.text):,} bytes)")
else:
    print(f"  ✗ AST   HTTP {r.status_code}")

# HTML
r = s.get(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/report.html")
if r.status_code == 200:
    p = OUT_DIR / f"{stem}.report.html"
    p.write_text(r.text, encoding="utf-8")
    print(f"  ✓ HTML  → {p}  ({len(r.text):,} bytes)")
else:
    print(f"  ✗ HTML  HTTP {r.status_code}: {r.text[:120]}")

# PDF (optional — engine may be unavailable)
r = s.get(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/report.pdf")
pdf_path = OUT_DIR / f"{stem}.report.pdf"
if r.status_code == 200 and r.content[:4] == b"%PDF":
    pdf_path.write_bytes(r.content)
    print(f"  ✓ PDF   → {pdf_path}  ({len(r.content):,} bytes)  [server engine]")
else:
    print(f"  - PDF   server engine unavailable (HTTP {r.status_code}); trying local browser…")
    html_file = OUT_DIR / f"{stem}.report.html"
    if _html_to_pdf_local(html_file, pdf_path):
        print(f"  ✓ PDF   → {pdf_path}  ({pdf_path.stat().st_size:,} bytes)  [headless browser]")
    else:
        print("  ✗ PDF   could not be produced (no server engine and no local browser)")

hr("DONE")
print(f"  template : {TID}")
print(f"  signature: {SIG}")
print(f"  canvas   : /report-builder/canvas/{TID}/{SIG}")
print(f"  outputs  : {OUT_DIR.resolve()}")
