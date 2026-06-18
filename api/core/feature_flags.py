"""Feature flags read from environment."""
from __future__ import annotations

import os


def validation_demo_noise_enabled() -> bool:
    return os.getenv("VALIDATION_DEMO_NOISE", "0").lower() in ("1", "true", "yes")
