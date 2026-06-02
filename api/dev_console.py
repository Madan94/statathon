"""Print OTP / dev auth messages to the API terminal (development only)."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("bharatstat.dev")


def log_dev_otp(
    *,
    email: str,
    otp: str,
    purpose: str,
    via: str = "unknown",
) -> None:
    if os.getenv("APP_ENV", "development").lower() != "development":
        return
    banner = (
        f"\n{'=' * 56}\n"
        f"  DEV OTP  purpose={purpose}  via={via}\n"
        f"  email: {email}\n"
        f"  code:  {otp}\n"
        f"{'=' * 56}\n"
    )
    print(banner, flush=True)
    logger.info("DEV OTP for %s (%s): %s", email, purpose, otp)
