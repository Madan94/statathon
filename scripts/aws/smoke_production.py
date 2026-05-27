"""
Basic post-deploy smoke checks for BharatStat production endpoints.

Usage:
  python scripts/aws/smoke_production.py --base-url https://app.example.com
"""

from __future__ import annotations

import argparse
import sys

import requests


def check(url: str, path: str, expected: int) -> bool:
    full = f"{url.rstrip('/')}{path}"
    try:
        resp = requests.get(full, timeout=10)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {path}: request error -> {exc}")
        return False
    ok = resp.status_code == expected
    marker = "PASS" if ok else "FAIL"
    print(f"[{marker}] {path}: {resp.status_code}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Public app URL, e.g. https://app.example.com")
    args = parser.parse_args()

    checks = [
        ("/", 200),
        ("/api/backend/health", 200),
        ("/api/backend/health/db", 200),
        # Protected route should redirect to login if unauthenticated:
        ("/upload", 200),
    ]

    passed = True
    for path, expected in checks:
        if path == "/upload":
            full = f"{args.base_url.rstrip('/')}{path}"
            resp = requests.get(full, timeout=10, allow_redirects=False)
            ok = resp.status_code in (302, 307, 308)
            print(f"[{'PASS' if ok else 'FAIL'}] {path}: {resp.status_code} (expected redirect)")
            passed = passed and ok
            continue
        passed = check(args.base_url, path, expected) and passed

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
