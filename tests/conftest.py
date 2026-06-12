"""tests/conftest.py — shared fixtures for all test modules.

Markers and filterwarnings are declared in pyproject.toml [tool.pytest.ini_options].
.env loading is done by the root conftest.py.
This file only contains session-scoped fixtures used across test classes.
"""
from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest


# ── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def env():
    """Return current environment as a dict (read-only)."""
    return dict(os.environ)


@pytest.fixture(scope="session")
def gemini_api_key():
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        pytest.skip("GEMINI_API_KEY not set — skipping live LLM test")
    return key


def _tcp_service_reachable(endpoint: str, *, timeout: float = 2.0) -> bool:
    parsed = urlparse(endpoint)
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def database_url():
    url = os.getenv("DATABASE_URL", "")
    if not url or "your-host" in url:
        pytest.skip("DATABASE_URL not configured — skipping live DB test")
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 5432
    if host in {"localhost", "127.0.0.1", "::1"}:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                pass
        except OSError:
            pytest.skip(f"DATABASE_URL points to {host}:{port}, but Postgres is not reachable — skipping live DB test")
    return url


@pytest.fixture(scope="session")
def s3_config():
    bucket = os.getenv("S3_BUCKET", "")
    endpoint = os.getenv("S3_ENDPOINT_URL", "")
    key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
    if not (bucket and endpoint and key_id):
        pytest.skip("S3/R2 credentials not configured — skipping live storage test")
    return {
        "bucket": bucket,
        "endpoint": endpoint,
        "key_id": key_id,
        "region": os.getenv("AWS_REGION", "auto"),
    }


@pytest.fixture(scope="session")
def colpali_endpoint():
    endpoint = os.getenv("COLPALI_ENDPOINT", "")
    if not endpoint:
        pytest.skip("COLPALI_ENDPOINT not set — skipping live VLM test")
    if not _tcp_service_reachable(endpoint):
        pytest.skip(f"COLPALI_ENDPOINT not reachable at {endpoint} — skipping live VLM test")
    return endpoint


@pytest.fixture(scope="session")
def sglang_endpoint():
    endpoint = os.getenv("SGLANG_ENDPOINT", "")
    if not endpoint:
        pytest.skip("SGLANG_ENDPOINT not set — skipping live SGLang test")
    if not _tcp_service_reachable(endpoint):
        pytest.skip(f"SGLANG_ENDPOINT not reachable at {endpoint} — skipping live SGLang test")
    return endpoint


@pytest.fixture
def minimal_pdf(tmp_path: Path) -> Path:
    """Reusable minimal PDF for tests that just need a file to hash."""
    pdf = tmp_path / "test_report.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    return pdf


@pytest.fixture
def mospi_like_pdf(tmp_path: Path) -> Path:
    """A minimal PDF that mock VLM treats as a synthetic MoSPI report."""
    pdf = tmp_path / "mospi_sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\nMoSPI Annual Survey Report\n%%EOF\n")
    return pdf
