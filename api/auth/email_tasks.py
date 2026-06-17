"""Background OTP email delivery."""
from __future__ import annotations

import logging

from auth.email_client import send_otp_email

logger = logging.getLogger(__name__)


def deliver_otp_email_task(to_email: str, otp: str, purpose: str) -> None:
    try:
        send_otp_email(to_email, otp, purpose)
    except Exception as exc:
        logger.error("Background OTP email failed for %s: %s", to_email, exc)
