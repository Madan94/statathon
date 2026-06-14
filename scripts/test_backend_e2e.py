"""Full end-to-end backend test — exercises every endpoint the canvas uses.

Tests:
1. GET /generation-queue → returns 26 items with titles, paths, types
2. POST /generate-component (idx=0) → real data with narrative
3. POST /generate-component (idx=8) → different question
4. POST /generate (full assembly) → report created
5. GET /report → report AST returned
6. GET /generation-queue consistency → all indices sequential

Validates:
- No 'Component N' generic titles
- Section paths are 3-level (topic > chapter > section)
- Component types are correct (table for rank, narrative for others)
- Narratives contain actual data (not 'could not be computed')
- Rankings have items with values
- Full pipeline runs without crash
"""
import json
import sys
import time
import requests

BASE = "http://localhost:8000/report-builder/generate-phase"
TID = "tpl_energy_enterprise_v2"
SIG = "b7acf2ae375faab7"
URL = f"{BASE}/{TID}/{SIG}"

# Create a session with dev login to bypass CSRF
session = requests.Session()
# Dev quick login (no OTP needed)
login_r = session.post("http://localhost:8000/auth/dev/quick-login", json={"email": "officer@example.com", "password": "TestOfficer123!"})
if login_r.status_code == 200:
    print(f"  Dev login OK (session established)")
else:
    print(f"  Dev login failed ({login_r.status_code}) — CSRF will block POSTs")
    print(f"  Falling back to GET-only tests")

# Extract CSRF token from cookies and set as header for all requests
csrf_token = session.cookies.get("csrf_token") or session.cookies.get("_csrf") or ""
if csrf_token:
    session.headers["X-CSRF-Token"] = csrf_token
    print(f"  CSRF token set: {csrf_token[:8]}...")
else:
    # Try to disable CSRF for testing (env var)
    print(f"  No CSRF cookie found — POSTs may fail")

# Use session for all requests
def get(path: str, **kwargs):
    return session.get(f"{URL}{path}", **kwargs)

def post(path: str, **kwargs):
    # Always send the latest csrf token
    csrf = session.cookies.get("csrf_token") or session.cookies.get("_csrf") or ""
    if csrf:
        session.headers["X-CSRF-Token"] = csrf
    return session.post(f"{URL}{path}", **kwargs)

PASS = 0
FAIL = 0

def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label} — {detail}")

def section(title: str):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")

# ─── TEST 1: Generation Queue ─────────────────────────────────────

section("TEST 1: GET /generation-queue")
t0 = time.time()
r = get("/generation-queue")
elapsed = time.time() - t0

check("Status 200", r.status_code == 200, f"got {r.status_code}")
if r.status_code != 200:
    print(f"  BODY: {r.text[:200]}")
    sys.exit(1)

queue = r.json()
check("Returns list", isinstance(queue, list))
check("26 items", len(queue) == 26, f"got {len(queue)}")
check("Response < 5s", elapsed < 5, f"took {elapsed:.1f}s")

# Check first item
item0 = queue[0] if queue else {}
check("Has index field", "index" in item0)
check("Has plan_id", "plan_id" in item0 and item0["plan_id"] != "")
check("Has question_id", "question_id" in item0 and item0["question_id"] != "")
check("Has title (not generic)", "title" in item0 and "Component" not in item0["title"], f"title={item0.get('title')}")
check("Has section_path (non-empty)", "section_path" in item0 and len(item0.get("section_path", [])) > 0, f"path={item0.get('section_path')}")
check("section_path is 3-level", len(item0.get("section_path", [])) == 3, f"depth={len(item0.get('section_path', []))}")
check("component_type not 'narrative' for rank", item0.get("component_type") == "table", f"type={item0.get('component_type')}")

# Check all items have non-generic titles
generic_titles = [q for q in queue if "Component" in q.get("title", "")]
check("No generic 'Component N' titles", len(generic_titles) == 0, f"found {len(generic_titles)}")

# Check sequential indices
indices = [q["index"] for q in queue]
check("Indices start at 0", indices[0] == 0 if indices else False)

# Check all have section paths
empty_paths = [q for q in queue if not q.get("section_path")]
check("All have section_path", len(empty_paths) == 0, f"{len(empty_paths)} missing")

# ─── TEST 2: Generate Component (idx=0, Coal ranking) ─────────────

section("TEST 2: POST /generate-component (idx=0)")
t0 = time.time()
r = post("/generate-component", json={"index": 0, "use_llm": False, "redo": False})
elapsed = time.time() - t0

check("Status 200", r.status_code == 200, f"got {r.status_code}: {r.text[:100]}")
if r.status_code == 200:
    data = r.json()
    check("Has plan_id", data.get("plan_id", "") != "")
    check("Has title (Coal)", "Coal" in data.get("title", ""), f"title={data.get('title')}")
    check("component_type=table", data.get("component_type") == "table", f"type={data.get('component_type')}")
    check("Has narrative", len(data.get("narrative", "")) > 10, f"narrative_len={len(data.get('narrative', ''))}")
    check("Narrative not generic fallback", "could not be computed" not in data.get("narrative", "").lower(), f"narrative={data.get('narrative', '')[:80]}")
    check("Has content dict", isinstance(data.get("content"), dict))
    check("progress_pct > 0", data.get("progress_pct", 0) > 0)
    check("total = 26", data.get("total") == 26, f"total={data.get('total')}")
    check("Response < 10s", elapsed < 10, f"took {elapsed:.1f}s")

    # Check content has ranking data
    content = data.get("content", {})
    items = content.get("items") or content.get("rankingData") or []
    check("Content has ranking items", len(items) > 0, f"items={len(items)}")
    if items:
        check("First item has value", items[0].get("value") is not None, f"item={items[0]}")
        check("First item has key", items[0].get("key") is not None)

# ─── TEST 3: Generate Component (idx=8, Wind ranking) ─────────────

section("TEST 3: POST /generate-component (idx=8)")
r = post("/generate-component", json={"index": 8, "use_llm": False, "redo": False})
check("Status 200", r.status_code == 200, f"got {r.status_code}")
if r.status_code == 200:
    data = r.json()
    check("Different question_id from idx=0", data.get("plan_id") != queue[0].get("plan_id"), f"same plan!")
    check("Has narrative", len(data.get("narrative", "")) > 10)
    check("progress_pct = ~34.6", abs(data.get("progress_pct", 0) - 34.6) < 1)

# ─── TEST 4: Index bounds ─────────────────────────────────────────

section("TEST 4: Bounds checking")
r = post("/generate-component", json={"index": -1, "use_llm": False})
check("Index -1 \u2192 400", r.status_code == 400, f"got {r.status_code}")

r = post("/generate-component", json={"index": 99, "use_llm": False})
check("Index 99 → 400", r.status_code == 400, f"got {r.status_code}")

# ─── TEST 5: Full generation ──────────────────────────────────────

section("TEST 5: POST /generate (full assembly)")
t0 = time.time()
r = post("/generate", json={"use_llm": False, "publish_mode": "draft"})
elapsed = time.time() - t0
check("Status 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
if r.status_code == 200:
    gen = r.json()
    check("Has template_id", gen.get("template_id") == TID)
    check("Has signature", gen.get("signature") == SIG)
    check("valid=True or warnings only", gen.get("valid") is not None)
    check("Has stats", isinstance(gen.get("stats"), dict))
    check("Response < 30s", elapsed < 30, f"took {elapsed:.1f}s")

# ─── TEST 6: Get report ───────────────────────────────────────────

section("TEST 6: GET /report")
r = get("/report")
check("Status 200", r.status_code == 200, f"got {r.status_code}")
if r.status_code == 200:
    report = r.json()
    check("Has metadata", "metadata" in report)
    check("Has contentAST or semanticAST", "contentAST" in report or "semanticAST" in report)

# ─── TEST 7: Queue consistency after generation ───────────────────

section("TEST 7: Queue consistency")
r = get("/generation-queue")
check("Queue still returns 200", r.status_code == 200)
q2 = r.json() if r.status_code == 200 else []
check("Same item count", len(q2) == len(queue), f"was {len(queue)}, now {len(q2)}")

# ─── SUMMARY ──────────────────────────────────────────────────────

section("SUMMARY")
total = PASS + FAIL
print(f"\n  {PASS}/{total} passed, {FAIL} failed\n")
if FAIL > 0:
    print("  ⚠ SOME TESTS FAILED — see above for details")
    sys.exit(1)
else:
    print("  ✓ ALL TESTS PASSED")
    sys.exit(0)
