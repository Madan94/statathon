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


def send_report_email(to_email: str, pdf_path, job_id: int, content_hash: str | None) -> dict:
    """Deliver generated PDF via dashboard Nodemailer."""
    import base64
    from pathlib import Path

    app_env = os.getenv("APP_ENV", "development").lower()
    internal_url = os.getenv("NEXT_INTERNAL_URL", "http://localhost:3000").rstrip("/")
    secret = os.getenv("MAIL_INTERNAL_SECRET", "").strip()
    path = Path(pdf_path)

    if not path.is_file():
        return {"ok": False, "error": "PDF file missing"}

    if not secret:
        if app_env == "development":
            logger.warning("MAIL_INTERNAL_SECRET unset — report for job %s would email %s", job_id, to_email)
            return {"ok": False, "dev_logged": True}
        return {"ok": False, "error": "MAIL_INTERNAL_SECRET not configured"}

    pdf_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    url = f"{internal_url}/api/internal/send-report"
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                url,
                json={
                    "to": to_email,
                    "job_id": job_id,
                    "content_hash": content_hash,
                    "filename": f"statathon-report-{job_id}.pdf",
                    "pdf_base64": pdf_b64,
                },
                headers={"X-Mail-Internal-Secret": secret},
            )
            data = resp.json() if resp.content else {}
        if resp.status_code == 200 and data.get("sent"):
            return {"ok": True}
        detail = data.get("detail") or data.get("error") or resp.text[:200]
        return {"ok": False, "error": str(detail)}
    except Exception as e:
        logger.error("Report email request failed: %s", e)
        return {"ok": False, "error": str(e)}
