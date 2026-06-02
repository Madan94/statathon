"""Development test officer — fixed credentials, optional OTP skip."""
from __future__ import annotations

import logging
import os
from datetime import datetime

from sqlalchemy.orm import Session

from auth.utils import hash_password, verify_password
from database.models import User

logger = logging.getLogger("bharatstat.dev_user")

DEV_TEST_EMAIL = os.getenv("DEV_TEST_EMAIL", "officer@example.com").strip().lower()
DEV_TEST_EMAIL_LEGACY = "officer@test.local"
DEV_TEST_PASSWORD = os.getenv("DEV_TEST_PASSWORD", "TestOfficer123!")
DEV_TEST_OTP = os.getenv("DEV_TEST_OTP", "123456")
DEV_TEST_FULL_NAME = os.getenv("DEV_TEST_FULL_NAME", "Dev Test Officer")
DEV_TEST_ROLE = os.getenv("DEV_TEST_OFFICER_ROLE", "Statistical Officer")


def dev_auth_enabled() -> bool:
    """True in development unless explicitly disabled."""
    if os.getenv("DEV_AUTH_ENABLED", "").lower() in ("0", "false", "no"):
        return False
    return os.getenv("APP_ENV", "development").lower() in ("development", "dev", "local")


def is_dev_test_email(email: str) -> bool:
    normalized = email.strip().lower()
    return normalized in (DEV_TEST_EMAIL, DEV_TEST_EMAIL_LEGACY)


def get_dev_fixed_otp() -> str:
    return DEV_TEST_OTP


def resolve_dev_user(db: Session, email: str, password: str) -> User | None:
    """Authenticate dev test officer; accepts legacy @test.local login email."""
    from auth.services import authenticate_user

    if not is_dev_test_email(email):
        return None
    user = authenticate_user(db, DEV_TEST_EMAIL, password)
    if user:
        return user
    user = authenticate_user(db, DEV_TEST_EMAIL_LEGACY, password)
    if user and user.email == DEV_TEST_EMAIL_LEGACY:
        user.email = DEV_TEST_EMAIL
        db.commit()
        db.refresh(user)
    return user


def log_test_user_otp(purpose: str = "login_verify") -> None:
    if not dev_auth_enabled():
        return
    msg = (
        f"\n[DEV TEST USER] OTP for {DEV_TEST_EMAIL} ({purpose}): {DEV_TEST_OTP}\n"
        f"  Or use POST /auth/dev/quick-login to skip OTP entirely.\n"
    )
    print(msg, flush=True)
    logger.info("Dev test OTP (%s): %s", purpose, DEV_TEST_OTP)


def ensure_dev_test_user(db: Session) -> User | None:
    """Create or refresh the dev test officer on API startup."""
    if not dev_auth_enabled():
        return None

    user = db.query(User).filter(User.email == DEV_TEST_EMAIL).first()
    legacy = db.query(User).filter(User.email == DEV_TEST_EMAIL_LEGACY).first()
    if user is None and legacy is not None:
        legacy.email = DEV_TEST_EMAIL
        db.commit()
        db.refresh(legacy)
        user = legacy
        logger.info("Migrated dev test user email to %s", DEV_TEST_EMAIL)
    elif user is not None and legacy is not None and legacy.id != user.id:
        db.delete(legacy)
        db.commit()

    hashed = hash_password(DEV_TEST_PASSWORD)

    if user is None:
        user = User(
            email=DEV_TEST_EMAIL,
            password=hashed,
            full_name=DEV_TEST_FULL_NAME,
            officer_role=DEV_TEST_ROLE,
            is_active=True,
            email_verified_at=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(
            "Created dev test user: %s (password in DEV_TEST_PASSWORD env or default)",
            DEV_TEST_EMAIL,
        )
        print(
            f"\n[DEV TEST USER] Created {DEV_TEST_EMAIL}\n"
            f"  Password: {DEV_TEST_PASSWORD}\n"
            f"  OTP:      {DEV_TEST_OTP}\n"
            f"  Quick login: POST /auth/dev/quick-login\n",
            flush=True,
        )
        return user

    changed = False
    if not user.is_active:
        user.is_active = True
        changed = True
    if not user.email_verified_at:
        user.email_verified_at = datetime.utcnow()
        changed = True
    if not user.password or not verify_password(DEV_TEST_PASSWORD, user.password):
        user.password = hashed
        changed = True
    if not user.full_name:
        user.full_name = DEV_TEST_FULL_NAME
        changed = True
    if not user.officer_role:
        user.officer_role = DEV_TEST_ROLE
        changed = True

    if changed:
        db.commit()
        db.refresh(user)
        logger.info("Updated dev test user: %s", DEV_TEST_EMAIL)

    print(
        f"\n[DEV TEST USER] Ready: {DEV_TEST_EMAIL} / {DEV_TEST_PASSWORD} "
        f"(OTP {DEV_TEST_OTP} or quick-login)\n",
        flush=True,
    )
    return user
