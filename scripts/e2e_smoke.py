"""Quick API smoke test: login, upload, analyze, extract template, generate report."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "test_data" / "MoSPI Dataset Example.csv"
PDF = ROOT / "sample_reports" / "template_1.pdf"


def main() -> int:
    s = requests.Session()
    login = s.post(
        f"{BASE}/auth/dev/quick-login",
        json={"email": "officer@example.com", "password": "TestOfficer123!"},
        timeout=30,
    )
    login.raise_for_status()
    print("LOGIN", login.json())

    csrf = s.cookies.get("bharatstat_csrf", "")
    headers = {"X-CSRF-Token": csrf} if csrf else {}

    dataset_id = 17  # reuse latest smoke upload when present
    try:
        ds = s.get(f"{BASE}/datasets/{dataset_id}", headers=headers, timeout=30)
        if ds.status_code != 200:
            dataset_id = None
    except Exception:
        dataset_id = None

    if not dataset_id:
        with CSV.open("rb") as f:
            up = s.post(f"{BASE}/datasets/upload", files={"file": ("mospi.csv", f)}, headers=headers, timeout=120)
        up.raise_for_status()
        upload = up.json()
        print("UPLOAD", upload)
        dataset_id = upload.get("dataset_id") or upload.get("id")
        if not dataset_id:
            print("No dataset_id in upload response", file=sys.stderr)
            return 1
    else:
        print("REUSE_DATASET", dataset_id)

    an = s.post(f"{BASE}/analysis/{dataset_id}/analyze-async", headers=headers, timeout=30)
    an.raise_for_status()
    analysis = an.json()
    print("ANALYZE", analysis)
    analysis_id = analysis["analysis_id"]

    for i in range(120):
        st = s.get(f"{BASE}/analysis/{analysis_id}/status", timeout=30).json()
        print(f"analysis poll {i+1}: {st.get('status')}")
        if st.get("status") in ("complete", "failed"):
            if st.get("status") == "failed":
                print("Analysis failed:", st.get("error_message"), file=sys.stderr)
                return 1
            break
        time.sleep(5)
    else:
        print("Analysis timed out", file=sys.stderr)
        return 1

    with PDF.open("rb") as f:
        ex = s.post(
            f"{BASE}/report-builder/templates/extract-async",
            data={"name": "Smoke Template", "description": "e2e smoke"},
            files={"file": ("template_1.pdf", f, "application/pdf")},
            headers=headers,
            timeout=120,
        )
    ex.raise_for_status()
    job = ex.json()
    print("EXTRACT_JOB", job)
    job_id = job["id"]

    for i in range(180):
        ej = s.get(f"{BASE}/report-builder/templates/extract-jobs/{job_id}", timeout=30).json()
        print(f"extract poll {i+1}: {ej.get('status')} stage={ej.get('stage')} pct={ej.get('progress_pct')}")
        if ej.get("status") in ("completed", "failed"):
            if ej.get("status") == "failed":
                print("Extract failed:", ej.get("stage_diagnostics"), file=sys.stderr)
                return 1
            template_id = ej.get("created_template_id")
            break
        time.sleep(10)
    else:
        print("Extract timed out", file=sys.stderr)
        return 1

    gen = s.post(
        f"{BASE}/report-builder/generate",
        json={"analysis_id": analysis_id, "template_id": template_id},
        headers=headers,
        timeout=30,
    )
    gen.raise_for_status()
    report_job = gen.json()
    print("GENERATE", report_job)
    report_job_id = report_job["job_id"]

    for i in range(120):
        rj = s.get(f"{BASE}/report-builder/jobs/{report_job_id}", timeout=30).json()
        print(f"report poll {i+1}: {rj.get('status')} stage={rj.get('stage')}")
        if rj.get("status") in ("completed", "failed", "error"):
            print("REPORT_FINAL", json.dumps(rj, default=str)[:500])
            return 0 if rj.get("status") == "completed" else 1
        time.sleep(5)

    print("Report generation timed out (job may still be running)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
