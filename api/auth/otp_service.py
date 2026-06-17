"""OTP challenge creation and verification."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from auth.dev_user import get_dev_fixed_otp, is_dev_test_email, log_test_user_otp, resolve_dev_user
from auth.utils import hash_password
from database.models import OtpChallenge, User
from dev_console import log_dev_otp

OTP_LENGTH = int(os.getenv("OTP_LENGTH", "6"))
OTP_TTL_MINUTES = int(os.getenv("OTP_TTL_MINUTES", "10"))
MAX_OTP_ATTEMPTS = int(os.getenv("MAX_OTP_ATTEMPTS", "5"))
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password(password: str) -> str | None:
    if len(password) < 12:
        return "Password must be at least 12 characters"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must include letters and numbers"
    return None


def _hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode("utf-8")).hexdigest()


def _generate_otp() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))


def _get_challenge(db: Session, challenge_id: str) -> OtpChallenge | None:
    return db.query(OtpChallenge).filter(OtpChallenge.id == challenge_id).first()


def _challenge_valid(ch: OtpChallenge) -> bool:
    if ch.consumed_at:
        return False
    if ch.expires_at < datetime.utcnow():
        return False
    if ch.attempts >= MAX_OTP_ATTEMPTS:
        return False
    return True


def start_signup(
    db: Session,
    full_name: str,
    officer_role: str,
    email: str,
    password: str,
) -> tuple[str, int, dict]:
    full_name = full_name.strip()
    officer_role = officer_role.strip()
    email = normalize_email(email)

    if len(full_name) < 2 or len(full_name) > 256:
        raise ValueError("Name must be between 2 and 256 characters")
    if len(officer_role) < 2 or len(officer_role) > 256:
        raise ValueError("Role must be between 2 and 256 characters")
    if not EMAIL_RE.match(email):
        raise ValueError("Invalid email address")
    pwd_err = validate_password(password)
    if pwd_err:
        raise ValueError(pwd_err)

    existing = db.query(User).filter(User.email == email).first()
    if existing and existing.is_active:
        raise ValueError("If this email is registered, check your inbox or try signing in")

    otp = _generate_otp()
    challenge_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)

    db.query(OtpChallenge).filter(
        OtpChallenge.email == email,
        OtpChallenge.purpose == "signup_verify",
        OtpChallenge.consumed_at.is_(None),
    ).delete(synchronize_session=False)

    ch = OtpChallenge(
        id=challenge_id,
        purpose="signup_verify",
        email=email,
        code_hash=_hash_otp(otp),
        payload_json={
            "full_name": full_name,
            "officer_role": officer_role,
            "password_hash": hash_password(password),
        },
        expires_at=expires_at,
    )
    db.add(ch)
    db.commit()

    return challenge_id, OTP_TTL_MINUTES * 60, otp


def verify_signup_otp(db: Session, challenge_id: str, otp: str) -> User:
    ch = _get_challenge(db, challenge_id)
    if not ch or ch.purpose != "signup_verify":
        raise ValueError("Invalid or expired verification session")
    if not _challenge_valid(ch):
        raise ValueError("Invalid or expired verification session")

    ch.attempts += 1
    if ch.code_hash != _hash_otp(otp.strip()):
        db.commit()
        if ch.attempts >= MAX_OTP_ATTEMPTS:
            raise ValueError("Too many attempts. Request a new code.")
        raise ValueError("Incorrect verification code")

    payload = ch.payload_json or {}
    email = ch.email
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        existing.full_name = payload.get("full_name") or existing.full_name
        existing.officer_role = payload.get("officer_role") or existing.officer_role
        existing.password = payload.get("password_hash") or existing.password
        existing.is_active = True
        existing.email_verified_at = datetime.utcnow()
        user = existing
    else:
        user = User(
            email=email,
            password=payload["password_hash"],
            full_name=payload.get("full_name"),
            officer_role=payload.get("officer_role"),
            is_active=True,
            email_verified_at=datetime.utcnow(),
        )
        db.add(user)

    ch.consumed_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def start_login(db: Session, email: str, password: str) -> tuple[str | None, int | None, str | None]:
    """Returns (challenge_id, expires_in, otp) or (None, None, None) on auth failure."""
    from auth.services import authenticate_user

    email = normalize_email(email)
    user = authenticate_user(db, email, password)
    if not user and is_dev_test_email(email):
        user = resolve_dev_user(db, email, password)
    if not user:
        return None, None, None
    if not user.is_active:
        return None, None, None

    if user.locked_until and user.locked_until > datetime.utcnow():
        return None, None, None

    otp = get_dev_fixed_otp() if is_dev_test_email(email) else _generate_otp()
    challenge_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)

    db.query(OtpChallenge).filter(
        OtpChallenge.email == email,
        OtpChallenge.purpose == "login_verify",
        OtpChallenge.consumed_at.is_(None),
    ).delete(synchronize_session=False)

    ch = OtpChallenge(
        id=challenge_id,
        purpose="login_verify",
        email=email,
        code_hash=_hash_otp(otp),
        payload_json={"user_id": user.id},
        expires_at=expires_at,
    )
    db.add(ch)
    user.failed_login_count = 0
    db.commit()

    log_dev_otp(email=email, otp=otp, purpose="login_verify", via="otp_service")
    if is_dev_test_email(email):
        log_test_user_otp(purpose="login_verify")
    return challenge_id, OTP_TTL_MINUTES * 60, otp


def verify_login_otp(db: Session, challenge_id: str, otp: str) -> User:
    ch = _get_challenge(db, challenge_id)
    if not ch or ch.purpose != "login_verify":
        raise ValueError("Invalid or expired verification session")
    if not _challenge_valid(ch):
        raise ValueError("Invalid or expired verification session")

    ch.attempts += 1
    if ch.code_hash != _hash_otp(otp.strip()):
        db.commit()
        if ch.attempts >= MAX_OTP_ATTEMPTS:
            raise ValueError("Too many attempts. Request a new code.")
        raise ValueError("Incorrect verification code")

    user_id = (ch.payload_json or {}).get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise ValueError("Invalid or expired verification session")

    ch.consumed_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def resend_otp(db: Session, challenge_id: str) -> tuple[int, str, str]:
    ch = _get_challenge(db, challenge_id)
    if not ch:
        raise ValueError("Invalid or expired verification session")
    if ch.consumed_at:
        raise ValueError("This code was already used. Sign in again to get a new code.")

    otp = get_dev_fixed_otp() if is_dev_test_email(ch.email) else _generate_otp()
    ch.code_hash = _hash_otp(otp)
    ch.attempts = 0
    ch.expires_at = datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)
    db.commit()

    log_dev_otp(email=ch.email, otp=otp, purpose=ch.purpose, via="resend")
    if is_dev_test_email(ch.email):
        log_test_user_otp(purpose=ch.purpose)
    return OTP_TTL_MINUTES * 60, otp, ch.purpose
