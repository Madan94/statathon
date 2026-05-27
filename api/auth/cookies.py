"""HttpOnly session cookies for BharatStat."""

from __future__ import annotations

import os

from fastapi import Response

ACCESS_COOKIE = "bharatstat_access"
REFRESH_COOKIE = "bharatstat_refresh"
CSRF_COOKIE = "bharatstat_csrf"


def _cookie_secure() -> bool:
    return os.getenv("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")


def _cookie_domain() -> str | None:
    domain = os.getenv("COOKIE_DOMAIN", "").strip()
    return domain or None


def set_session_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
    access_max_age: int,
    refresh_max_age: int,
    csrf_token: str | None = None,
) -> None:
    common = {
        "httponly": True,
        "secure": _cookie_secure(),
        "samesite": "lax",
        "path": "/",
        "domain": _cookie_domain(),
    }
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=access_token,
        max_age=access_max_age,
        **common,
    )
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        max_age=refresh_max_age,
        **common,
    )
    if csrf_token:
        response.set_cookie(
            key=CSRF_COOKIE,
            value=csrf_token,
            max_age=refresh_max_age,
            httponly=False,
            secure=_cookie_secure(),
            samesite="strict",
            path="/",
            domain=_cookie_domain(),
        )


def clear_session_cookies(response: Response) -> None:
    domain = _cookie_domain()
    for key in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(key=key, path="/", domain=domain)
