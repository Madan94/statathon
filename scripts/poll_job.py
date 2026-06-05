import sys
import time

import requests

BASE = "http://127.0.0.1:8000"
job_id = int(sys.argv[1]) if len(sys.argv) > 1 else 13

s = requests.Session()
s.post(
    f"{BASE}/auth/dev/quick-login",
    json={"email": "officer@example.com", "password": "TestOfficer123!"},
)
h = {"X-CSRF-Token": s.cookies.get("bharatstat_csrf", "")}

for i in range(60):
    try:
        rj = s.get(f"{BASE}/report-builder/jobs/{job_id}", headers=h, timeout=60).json()
        print(f"job {i+1}: {rj.get('status')} stage={rj.get('stage')} err={rj.get('error_message')}")
        if rj.get("status") in ("completed", "failed", "error"):
            break
    except Exception as exc:
        print(f"job {i+1}: err {exc}")
    time.sleep(10)

pr = s.get(f"{BASE}/report-builder/jobs/{job_id}/progress", headers=h, timeout=30)
print("PROGRESS", pr.status_code, pr.text[:400])
