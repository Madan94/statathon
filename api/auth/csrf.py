"""CSRF double-submit validation for cookie-authenticated mutating requests."""

import os

from fastapi import HTTPException, Request

from auth.cookies import CSRF_COOKIE

_AUTH_PREFIXES = ("/auth/", "/health")
_EXEMPT_PREFIXES = ("/report-builder/generate-phase/", "/report-builder/binding-phase/")


def verify_csrf(request: Request) -> None:
    if os.getenv("CSRF_ENABLED", "true").lower() not in ("1", "true", "yes"):
        return
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    path = request.url.path
    if any(path.startswith(p) for p in _AUTH_PREFIXES):
        return
    # Generate-phase and binding-phase use template_id/signature in URL
    # which serves as a form of request authenticity (not guessable)
    if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        return

    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get("X-CSRF-Token")
    if not cookie or not header or cookie != header:
        raise HTTPException(status_code=403, detail="CSRF validation failed")
