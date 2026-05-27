"""JWT access tokens and refresh token rotation."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta

from jose import jwt
from sqlalchemy.orm import Session

from auth.utils import ALGORITHM, SECRET_KEY, create_token
from database.models import RefreshToken

ACCESS_MINUTES = int(os.getenv("JWT_ACCESS_MINUTES", "30"))
REFRESH_DAYS = int(os.getenv("JWT_REFRESH_DAYS", "14"))


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_access_token(user_id: int) -> str:
    return create_token({"user_id": user_id, "type": "access"})


def issue_refresh_token(db: Session, user_id: int, user_agent: str | None = None) -> str:
    raw = secrets.token_urlsafe(48)
    row = RefreshToken(
        user_id=user_id,
        token_hash=_hash_token(raw),
        expires_at=datetime.utcnow() + timedelta(days=REFRESH_DAYS),
        user_agent=(user_agent or "")[:512] or None,
    )
    db.add(row)
    db.commit()
    return raw


def decode_access_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        uid = payload.get("user_id")
        return int(uid) if uid is not None else None
    except Exception:
        return None


def rotate_refresh_token(db: Session, raw_refresh: str, user_agent: str | None = None) -> tuple[str, str] | None:
    """Returns (new_access, new_refresh) or None if invalid."""
    token_hash = _hash_token(raw_refresh)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if not row or row.revoked_at or row.expires_at < datetime.utcnow():
        return None

    row.revoked_at = datetime.utcnow()
    db.commit()

    access = create_access_token(row.user_id)
    new_refresh = issue_refresh_token(db, row.user_id, user_agent=user_agent)
    return access, new_refresh


def revoke_refresh_token(db: Session, raw_refresh: str) -> None:
    token_hash = _hash_token(raw_refresh)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if row:
        row.revoked_at = datetime.utcnow()
        db.commit()


def revoke_all_user_refresh_tokens(db: Session, user_id: int) -> None:
    now = datetime.utcnow()
    rows = db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
    )
    for row in rows:
        row.revoked_at = now
    db.commit()


def access_max_age_seconds() -> int:
    return ACCESS_MINUTES * 60


def refresh_max_age_seconds() -> int:
    return REFRESH_DAYS * 24 * 3600
