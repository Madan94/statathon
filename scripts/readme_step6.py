"""README Step 6: login → dataset+analysis → templates/upload → generate."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "test_data" / "MoSPI Dataset Example.csv"
PDF = ROOT / "sample_reports" / "template_1.pdf"


def _login(session: requests.Session) -> dict:
    r = session.post(
        f"{BASE}/auth/dev/quick-login",
        json={"email": "officer@example.com", "password": "TestOfficer123!"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _headers(session: requests.Session) -> dict:
    csrf = session.cookies.get("bharatstat_csrf", "")
    return {"X-CSRF-Token": csrf} if csrf else {}


def _ensure_colpali() -> bool:
    """Restart ColPali per README before template upload (needs VLM)."""
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "docker-compose.gpu.yml"),
            "--profile",
            "gpu",
            "up",
            "-d",
            "colpali",
        ],
        cwd=ROOT,
        check=False,
    )
    for i in range(36):
        try:
            h = requests.get("http://localhost:8100/health", timeout=8)
            if h.ok and h.json().get("status") == "ok":
                print("COLPALI_READY", h.json())
                return True
        except Exception as exc:
            print(f"colpali wait {i+1}: {exc}")
        time.sleep(10)
    print("COLPALI_NOT_READY — template upload may use pdfplumber fallback", file=sys.stderr)
    return False


def main() -> int:
    s = requests.Session()
    print("LOGIN", _login(s))
    h = _headers(s)

    with CSV.open("rb") as f:
        up = s.post(f"{BASE}/datasets/upload", files={"file": ("mospi.csv", f)}, headers=h, timeout=120)
    up.raise_for_status()
    upload = up.json()
    print("UPLOAD", {k: upload[k] for k in ("dataset_id", "id", "row_count") if k in upload})
    dataset_id = upload.get("dataset_id") or upload.get("id")

    an = s.post(f"{BASE}/analysis/{dataset_id}/analyze-async", headers=h, timeout=30)
    an.raise_for_status()
    analysis = an.json()
    print("ANALYZE", analysis)
    analysis_id = analysis["analysis_id"]

    for i in range(120):
        try:
            st = s.get(f"{BASE}/analysis/{analysis_id}/status", headers=h, timeout=60).json()
        except requests.RequestException as exc:
            print(f"analysis poll {i+1}: connection error {exc}; retrying")
            time.sleep(5)
            continue
        print(f"analysis poll {i+1}: {st.get('status')} err={st.get('error_message')}")
        if st.get("status") == "complete":
            break
        if st.get("status") == "failed":
            return 1
        time.sleep(5)
    else:
        print("Analysis timed out", file=sys.stderr)
        return 1

    _ensure_colpali()

    with PDF.open("rb") as f:
        tpl = s.post(
            f"{BASE}/report-builder/templates/upload",
            data={"name": "README-Smoke-Template", "description": "README Step 6"},
            files={"file": ("template_1.pdf", f, "application/pdf")},
            headers=h,
            timeout=600,
        )
    print("TEMPLATE_UPLOAD", tpl.status_code, tpl.text[:500] if not tpl.ok else tpl.json())
    if not tpl.ok:
        return 1
    template_id = tpl.json().get("id") or tpl.json().get("template_id")

    gen = s.post(
        f"{BASE}/report-builder/generate",
        json={"analysis_id": analysis_id, "template_id": template_id},
        headers=h,
        timeout=30,
    )
    print("GENERATE", gen.status_code, gen.json() if gen.ok else gen.text[:300])
    if not gen.ok:
        return 1
    job_id = gen.json().get("job_id") or gen.json().get("id")

    try:
        with s.get(
            f"{BASE}/report-builder/jobs/{job_id}/progress/stream",
            headers=h,
            stream=True,
            timeout=30,
        ) as stream:
            for line in stream.iter_lines(decode_unicode=True):
                if line:
                    print("SSE", line[:200])
                if line and "complete" in line.lower():
                    break
    except Exception as exc:
        print("SSE stream ended:", exc)

    rj = s.get(f"{BASE}/report-builder/jobs/{job_id}", headers=h, timeout=30).json()
    print("JOB_FINAL", json.dumps(rj, default=str)[:800])
    return 0 if rj.get("status") in ("completed", "running", "pending") else 1


if __name__ == "__main__":
    raise SystemExit(main())
