"""Auth OTP and password validation tests."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

os.environ.setdefault("DATABASE_URL", f"sqlite:///{ROOT / 'test_auth_otp.db'}")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-jwt-minimum-32-chars")
os.environ.setdefault("AUTH_REQUIRED", "true")
os.environ.setdefault("MAIL_INTERNAL_SECRET", "")

from auth.otp_service import validate_password, _hash_otp, _generate_otp
from auth.rate_limit import check_rate_limit


def test_validate_password_rules():
    assert validate_password("short") is not None
    assert validate_password("nodigitshere!!") is not None
    assert validate_password("ValidPass12345") is None


def test_otp_hash_stable():
    assert _hash_otp("123456") == _hash_otp("123456")
    assert _hash_otp("123456") != _hash_otp("654321")


def test_generate_otp_length():
    os.environ["OTP_LENGTH"] = "6"
    otp = _generate_otp()
    assert len(otp) == 6
    assert otp.isdigit()


def test_rate_limit_allows_then_blocks():
    key = "test-rate-key-unique"
    allowed = 0
    for _ in range(25):
        if check_rate_limit(key):
            allowed += 1
    assert allowed <= 20
