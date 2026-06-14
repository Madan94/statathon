"""Real officer flow test — simulates what the frontend actually does.

Tests the EXACT API calls the canvas page makes, in order:
1. Login (get session)
2. GET /generation-queue
3. POST /generate-component for multiple indices
4. POST /generate (full assembly)
5. GET /report

Also tests:
- Binding endpoints still work
- Template packages list
- Error handling for bad inputs
"""
import json
import sys
import time
import requests

BASE = "http://localhost:8000"
TID = "tpl_energy_enterprise_v2"
SIG = "b7acf2ae375faab7"

session = requests.Session()
PASS = 0
FAIL = 0

def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label} — {detail}")

def section(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")

# ─── PHASE 1: Auth ────────────────────────────────────────────────

section("PHASE 1: Authentication")
r = session.post(f"{BASE}/auth/dev/quick-login", json={"email": "officer@example.com", "password": "TestOfficer123!"})
check("Dev login returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:100]}")

# ─── PHASE 2: Binding API (what the binder page calls) ────────────

section("PHASE 2: Binding API")

# List template packages
r = session.get(f"{BASE}/report-builder/binding-phase/template-packages")
check("GET /packages → 200", r.status_code == 200, f"got {r.status_code}")
if r.status_code == 200:
    pkgs = r.json()
    check("Packages is list", isinstance(pkgs, list))
    check("Has templates", len(pkgs) > 0, f"got {len(pkgs)}")
    valid = [p for p in pkgs if p.get("status") == "VALID"]
    check("Has valid templates", len(valid) > 0)
    energy = [p for p in pkgs if "energy" in p.get("template_id", "").lower()]
    check("Has energy template", len(energy) > 0)

# Check workspace (existing binding)
r = session.get(f"{BASE}/report-builder/binding-phase/{TID}/{SIG}/workspace")
check("GET /workspace → 200", r.status_code == 200, f"got {r.status_code}")
if r.status_code == 200:
    ws = r.json()
    check("Workspace has phase_statuses", "phase_statuses" in ws)
    check("Workspace has issues", "issues" in ws)

# ─── PHASE 3: Generation Queue (what the canvas page calls) ───────

section("PHASE 3: Generation Queue")
t0 = time.time()
r = session.get(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/generation-queue")
elapsed = time.time() - t0
check("GET /generation-queue → 200", r.status_code == 200, f"got {r.status_code}")

queue = []
if r.status_code == 200:
    queue = r.json()
    check("Returns 26 items", len(queue) == 26, f"got {len(queue)}")
    
    # Validate structure
    for i, item in enumerate(queue[:3]):
        check(f"  item[{i}] has title (not generic)", "Component" not in item.get("title", "Component"), f"title={item.get('title')}")
        check(f"  item[{i}] has section_path", len(item.get("section_path", [])) > 0)
        check(f"  item[{i}] has component_type", item.get("component_type", "") != "")

# ─── PHASE 4: Generate Components (what auto-generate does) ───────

section("PHASE 4: Generate Components")

# Generate idx=0 (Coal ranking)
t0 = time.time()
r = session.post(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/generate-component", 
                 json={"index": 0, "use_llm": False, "redo": False})
elapsed = time.time() - t0
check("POST /generate-component idx=0 → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:100]}")

if r.status_code == 200:
    comp = r.json()
    check("Has plan_id", comp.get("plan_id", "") != "")
    check("Has title='Coal'", "Coal" in comp.get("title", ""), f"title={comp.get('title')}")
    check("component_type=table", comp.get("component_type") == "table", f"type={comp.get('component_type')}")
    check("Has narrative (non-empty)", len(comp.get("narrative", "")) > 20, f"len={len(comp.get('narrative', ''))}")
    check("Narrative is not generic fallback", "could not be computed" not in comp.get("narrative", "").lower())
    check("Has content with data", isinstance(comp.get("content"), dict) and len(comp.get("content", {})) > 0)
    
    # Check ranking data
    content = comp.get("content", {})
    items = content.get("items") or content.get("rankingData") or []
    check("Content has ranking items", len(items) > 0, f"items={len(items)}, keys={list(content.keys())[:5]}")
    if items:
        check("Ranking item has value", items[0].get("value") is not None)
        check("Ranking item has key.State/UT", "State/UT" in (items[0].get("key") or {}))
    
    check("progress_pct > 0", comp.get("progress_pct", 0) > 0)
    check("total = 26", comp.get("total") == 26)
    check(f"Response time: {elapsed:.1f}s", elapsed < 15)

# Generate idx=6 (Crude Oil)
r = session.post(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/generate-component",
                 json={"index": 6, "use_llm": False, "redo": False})
check("POST /generate-component idx=6 → 200", r.status_code == 200, f"got {r.status_code}")
if r.status_code == 200:
    comp6 = r.json()
    check("idx=6 different question from idx=0", comp6.get("plan_id") != comp.get("plan_id"))
    check("idx=6 has narrative", len(comp6.get("narrative", "")) > 10)

# Generate idx=25 (last - methodology)
r = session.post(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/generate-component",
                 json={"index": 25, "use_llm": False, "redo": False})
check("POST /generate-component idx=25 → 200", r.status_code == 200, f"got {r.status_code}")
if r.status_code == 200:
    comp25 = r.json()
    check("idx=25 progress_pct = 100", comp25.get("progress_pct") == 100.0)
    check("idx=25 next_index = null", comp25.get("next_index") is None)

# Bounds checking
r = session.post(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/generate-component",
                 json={"index": -1, "use_llm": False})
check("Index -1 → 400", r.status_code == 400, f"got {r.status_code}")

r = session.post(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/generate-component",
                 json={"index": 99, "use_llm": False})
check("Index 99 → 400", r.status_code == 400, f"got {r.status_code}")

# ─── PHASE 5: Full Generation (what 'finish' does) ────────────────

section("PHASE 5: Full Report Generation")
t0 = time.time()
r = session.post(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/generate",
                 json={"use_llm": False, "publish_mode": "draft"})
elapsed = time.time() - t0
check("POST /generate → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:150]}")
if r.status_code == 200:
    gen = r.json()
    check("Has template_id", gen.get("template_id") == TID)
    check("Has signature", gen.get("signature") == SIG)
    check("Has stats dict", isinstance(gen.get("stats"), dict))
    stats = gen.get("stats", {})
    check("Stats has analytics IDs", stats.get("analyticIds", 0) > 0, f"stats={stats}")
    check(f"Full generation: {elapsed:.1f}s", elapsed < 60)

# ─── PHASE 6: Report Retrieval ────────────────────────────────────

section("PHASE 6: Report Retrieval")
r = session.get(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/report")
check("GET /report → 200", r.status_code == 200, f"got {r.status_code}")
if r.status_code == 200:
    report = r.json()
    check("Report has metadata", "metadata" in report)
    check("Report has contentAST or semanticAST", "contentAST" in report or "semanticAST" in report)

# HTML report
r = session.get(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/report.html")
check("GET /report.html → 200", r.status_code == 200, f"got {r.status_code}")
if r.status_code == 200:
    check("HTML has <html>", "<html" in r.text[:500].lower())

# ─── PHASE 7: Versions ────────────────────────────────────────────

section("PHASE 7: Versions")
r = session.get(f"{BASE}/report-builder/generate-phase/{TID}/{SIG}/versions")
check("GET /versions → 200", r.status_code == 200, f"got {r.status_code}")
if r.status_code == 200:
    versions = r.json()
    check("Has versions list", isinstance(versions.get("versions"), list))

# ─── PHASE 8: Invalid template/sig ───────────────────────────────

section("PHASE 8: Error Handling")
r = session.get(f"{BASE}/report-builder/generate-phase/nonexistent_template/bad_sig/generation-queue")
check("Bad template \u2192 4xx", r.status_code in (404, 409), f"got {r.status_code}")

r = session.post(f"{BASE}/report-builder/generate-phase/nonexistent/bad/generate-component",
                 json={"index": 0, "use_llm": False})
check("Bad template generate \u2192 4xx", r.status_code in (404, 409), f"got {r.status_code}")

# ─── SUMMARY ──────────────────────────────────────────────────────

section("SUMMARY")
total = PASS + FAIL
print(f"\n  {PASS}/{total} passed, {FAIL} failed\n")
if FAIL == 0:
    print("  ✓ ALL TESTS PASSED — backend is fully operational")
elif FAIL <= 3:
    print(f"  ⚠ Minor issues ({FAIL} failures)")
else:
    print(f"  ✗ SIGNIFICANT FAILURES ({FAIL}) — needs fixing")
sys.exit(0 if FAIL == 0 else 1)
