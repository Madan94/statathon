"""Optional Google OAuth2 login (enabled when GOOGLE_OAUTH_CLIENT_ID is set)."""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from auth.services import create_user
from auth.cookies import set_session_cookies
from auth.token_service import (
    access_max_age_seconds,
    create_access_token,
    issue_refresh_token,
    refresh_max_age_seconds,
)
import secrets as sec
from database.database import SessionLocal
from database.models import User

router = APIRouter(prefix="/auth/oauth", tags=["auth-oauth"])

_pending_states: dict[str, str] = {}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _google_configured() -> bool:
    return bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"))


@router.get("/google/url")
def google_auth_url():
    if not _google_configured():
        raise HTTPException(status_code=503, detail="Google OAuth not configured")
    state = secrets.token_urlsafe(16)
    _pending_states[state] = "pending"
    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/oauth/google/callback")
    params = {
        "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return {"url": f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}", "state": state}


@router.get("/google/callback")
def google_callback(code: str, state: str, request: Request, db: Session = Depends(get_db)):
    if not _google_configured():
        raise HTTPException(status_code=503, detail="Google OAuth not configured")
    if state not in _pending_states:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    _pending_states.pop(state, None)

    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/oauth/google/callback")
    token_url = "https://oauth2.googleapis.com/token"
    with httpx.Client(timeout=15.0) as client:
        tok = client.post(
            token_url,
            data={
                "code": code,
                "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if tok.status_code != 200:
            raise HTTPException(status_code=400, detail="Token exchange failed")
        access = tok.json().get("access_token")
        if not access:
            raise HTTPException(status_code=400, detail="No access_token from Google")
        prof = client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access}"},
        )
        if prof.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch user profile")
        email = prof.json().get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Google account has no email")

    profile = prof.json()
    name = profile.get("name") or email.split("@")[0]
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = create_user(
            db,
            email,
            secrets.token_urlsafe(32),
            full_name=name,
            officer_role="OAuth sign-in",
            is_active=True,
        )
    elif not user.is_active:
        user.is_active = True
        user.full_name = user.full_name or name
        db.commit()

    access = create_access_token(user.id)
    refresh = issue_refresh_token(db, user.id, user_agent=request.headers.get("user-agent"))
    frontend = os.getenv("OAUTH_FRONTEND_REDIRECT", "http://localhost:3000/login")
    response = RedirectResponse(url=f"{frontend}?oauth=success")
    set_session_cookies(
        response,
        access,
        refresh,
        access_max_age_seconds(),
        refresh_max_age_seconds(),
        csrf_token=sec.token_urlsafe(32),
    )
    return response
