"""Send OTP via dashboard Nodemailer (SMTP only — no SendGrid/SES SDK)."""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


def send_otp_email(to_email: str, otp: str, purpose: str) -> dict:
    """Returns {sent: bool, dev_otp_logged?: bool, error?: str}."""
    app_env = os.getenv("APP_ENV", "development").lower()
    internal_url = os.getenv("NEXT_INTERNAL_URL", "http://localhost:3000").rstrip("/")
    secret = os.getenv("MAIL_INTERNAL_SECRET", "").strip()

    if not secret:
        if app_env == "development":
            logger.warning("MAIL_INTERNAL_SECRET unset — OTP for %s: %s", to_email, otp)
            return {"sent": False, "dev_otp_logged": True}
        return {"sent": False, "error": "MAIL_INTERNAL_SECRET not configured"}

    url = f"{internal_url}/api/internal/send-otp"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                url,
                json={"to": to_email, "otp": otp, "purpose": purpose},
                headers={"X-Mail-Internal-Secret": secret},
            )
            data = resp.json() if resp.content else {}
        if resp.status_code == 200 and data.get("sent"):
            return {"sent": True}
        if resp.status_code == 200 and data.get("dev"):
            logger.warning("SMTP dev log mode — OTP for %s: %s", to_email, otp)
            return {"sent": False, "dev_otp_logged": True}
        detail = data.get("detail") or data.get("error") or resp.text[:200]
        logger.error("Nodemailer send-otp failed: %s %s", resp.status_code, detail)
        if app_env == "development":
            logger.warning("Dev fallback OTP for %s: %s", to_email, otp)
            return {"sent": False, "dev_otp_logged": True, "error": str(detail)}
        return {"sent": False, "error": str(detail)}
    except Exception as e:
        logger.error("Nodemailer request failed: %s", e)
        if app_env == "development":
            logger.warning("Dev fallback OTP for %s: %s", to_email, otp)
            return {"sent": False, "dev_otp_logged": True}
        return {"sent": False, "error": str(e)}
