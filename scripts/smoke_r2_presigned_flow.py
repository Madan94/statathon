#!/usr/bin/env python3
"""
End-to-end smoke: POST /datasets/upload-url → PUT CSV to R2 → POST /datasets/register → poll results.

Loads `.env` via database.database (repo root). Requires boto3 + ML deps for background analysis.

Usage (repo root):
  python scripts/smoke_r2_presigned_flow.py

Optional env:
  SMOKE_POLL_SECONDS=900   max wait for analysis completion
"""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_API = _REPO / "api"
for p in (str(_REPO), str(_API)):
    if p not in sys.path:
        sys.path.insert(0, p)


def seed_user_id_one() -> None:
    from auth.utils import hash_password
    from database.database import SessionLocal
    from database.models import User

    db = SessionLocal()
    try:
        db.merge(
            User(
                id=1,
                email="smoke-r2-presign@local.test",
                password=hash_password("smoke-unused-secret"),
            )
        )
        db.commit()
    finally:
        db.close()


def put_presigned(upload_url: str, body: bytes, content_type: str) -> tuple[int, str]:
    req = urllib.request.Request(upload_url, data=body, method="PUT")
    req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.reason
    except urllib.error.HTTPError as e:
        return e.code, e.reason


def _semantic_mapping_len(body: dict) -> int:
    sem = body.get("semantic_mapping") or []
    if isinstance(sem, list):
        return len(sem)
    if isinstance(sem, dict):
        return len(sem)
    return 0


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(_REPO / ".env")
    os.chdir(_API)

    missing = []
    if not os.getenv("S3_BUCKET"):
        missing.append("S3_BUCKET")
    if not os.getenv("AWS_ACCESS_KEY_ID"):
        missing.append("AWS_ACCESS_KEY_ID")
    if not os.getenv("AWS_SECRET_ACCESS_KEY"):
        missing.append("AWS_SECRET_ACCESS_KEY")
    if not os.getenv("S3_ENDPOINT_URL"):
        missing.append("S3_ENDPOINT_URL")
    if missing:
        print("ERROR: Missing env vars:", ", ".join(missing))
        print("Fill them in repo-root `.env` then retry.")
        return 2

    print("Ensuring DB columns…")
    import subprocess

    rc = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "ensure_dataset_storage_columns.py")],
        cwd=str(_REPO),
        check=False,
    )
    if rc.returncode != 0:
        print("Migration helper exited non-zero — fix DB before smoke.")
        return rc.returncode

    seed_user_id_one()

    print("Importing FastAPI app…")
    from fastapi.testclient import TestClient

    import database.models  # noqa: F401
    from main import app

    client = TestClient(app)

    csv_body = b"a,b,c\n1,2,3\n4,5,6\n"
    fname = "smoke_presigned.csv"
    ct = "text/csv"

    print("POST /datasets/upload-url …")
    r = client.post("/datasets/upload-url", json={"filename": fname, "content_type": ct})
    if r.status_code != 200:
        print("FAILED upload-url:", r.status_code, r.text)
        return 1
    data = r.json()
    upload_url = data["upload_url"]
    object_key = data["object_key"]
    print("object_key:", object_key)

    print("PUT object to R2 (presigned) …")
    status, reason = put_presigned(upload_url, csv_body, ct)
    if status not in (200, 204):
        print("FAILED PUT:", status, reason)
        return 1
    print("PUT OK:", status)

    payload = {
        "object_key": object_key,
        "filename": fname,
        "file_size": len(csv_body),
        "checksum": None,
    }
    print("POST /datasets/register …")
    rr = client.post("/datasets/register", json=payload)
    if rr.status_code != 200:
        print("FAILED register:", rr.status_code, rr.text)
        return 1
    reg = rr.json()
    ds_id = reg["dataset_id"]
    an_id = reg["analysis_id"]
    print("dataset_id:", ds_id, "analysis_id:", an_id)

    md = client.get(f"/datasets/{ds_id}")
    print("GET /datasets:", md.status_code, md.json() if md.status_code == 200 else md.text)

    max_wait = int(os.getenv("SMOKE_POLL_SECONDS", "900"))
    deadline = time.monotonic() + max_wait
    print(f"Polling /analysis/{an_id}/results (max {max_wait}s) …")

    last_txt = ""
    while time.monotonic() < deadline:
        ar = client.get(f"/analysis/{an_id}/results")
        if ar.status_code == 200:
            body = ar.json()
            clusters = len(body.get("clusters") or [])
            mapping_n = _semantic_mapping_len(body)
            print("SUCCESS semantic payload:", "clusters=", clusters, "semantic_mapping_items=", mapping_n)
            return 0
        last_txt = ar.text
        if ar.status_code not in (409,):
            print("Unexpected:", ar.status_code, ar.text[:500])
            return 1
        time.sleep(3)

    print("TIMEOUT waiting for analysis. Last response:", last_txt[:800])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
