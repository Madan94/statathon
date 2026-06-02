"""Report delivery hub — email and webhook channels."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import httpx

from database.models import ReportJob
from auth.email_client import send_report_email

from .schemas import DeliverRequest

logger = logging.getLogger(__name__)


def _pdf_path(job: ReportJob) -> Path | None:
    if not job.final_pdf_path:
        return None
    path = Path(job.final_pdf_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path if path.is_file() else None


def deliver_report(*, job: ReportJob, request: DeliverRequest) -> dict:
    channel = (request.channel or "").strip().lower()
    ts = datetime.utcnow().isoformat() + "Z"

    if channel == "email":
        to = (request.to or "").strip()
        if not to:
            return {"channel": "email", "ok": False, "error": "Missing to address", "at": ts}
        path = _pdf_path(job)
        if not path:
            return {"channel": "email", "ok": False, "error": "PDF not ready", "at": ts}
        meta = send_report_email(to, path, job_id=job.id, content_hash=job.content_hash)
        return {"channel": "email", "to": to, "ok": meta.get("ok", False), "detail": meta, "at": ts}

    if channel == "webhook":
        url = (request.url or "").strip()
        if not url:
            return {"channel": "webhook", "ok": False, "error": "Missing url", "at": ts}
        payload = {
            "job_id": job.id,
            "analysis_id": job.analysis_id,
            "status": job.status,
            "content_hash": job.content_hash,
            "template_id": job.template_id,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        secret = os.getenv("WEBHOOK_SIGNING_SECRET", "")
        if secret:
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Statathon-Signature"] = sig
        try:
            resp = httpx.post(url, content=body, headers=headers, timeout=30.0)
            ok = 200 <= resp.status_code < 300
            return {
                "channel": "webhook",
                "url": url,
                "ok": ok,
                "status_code": resp.status_code,
                "at": ts,
            }
        except Exception as exc:
            logger.warning("Webhook delivery failed: %s", exc)
            return {"channel": "webhook", "url": url, "ok": False, "error": str(exc), "at": ts}

    return {"channel": channel, "ok": False, "error": "Unknown channel", "at": ts}
