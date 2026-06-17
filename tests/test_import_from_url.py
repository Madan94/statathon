"""Tests for server-side presigned URL import."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from dataset_api.import_url import (
    fetch_url_bytes,
    resolve_import_filename,
    validate_import_url,
)


def test_validate_import_url_requires_https_for_remote():
    with pytest.raises(HTTPException) as exc:
        validate_import_url("http://example.com/file.csv")
    assert exc.value.status_code == 400


def test_validate_import_url_allows_localhost_http():
    assert validate_import_url("http://127.0.0.1:8080/stream?token=abc").startswith("http://")


def test_resolve_import_filename_from_url():
    name = resolve_import_filename(
        "https://bucket.r2.cloudflarestorage.com/uploads/report.csv?X-Amz-Signature=abc",
        requested=None,
        content_type="binary/octet-stream",
        content_disposition=None,
    )
    assert name == "report.csv"


def test_resolve_import_filename_from_override():
    name = resolve_import_filename(
        "https://bucket.example.com/object?sig=1",
        requested="survey.xlsx",
        content_type=None,
        content_disposition=None,
    )
    assert name == "survey.xlsx"


def test_fetch_url_bytes_success(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/csv"}

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield b"col\n1\n"

    class FakeStream:
        def __enter__(self):
            return FakeResponse()

        def __exit__(self, *args):
            return False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url):
            assert method == "GET"
            return FakeStream()

    monkeypatch.setattr("dataset_api.import_url.httpx.Client", FakeClient)
    body, content_type, disposition = fetch_url_bytes("https://example.com/data.csv?sig=1")
    assert body == b"col\n1\n"
    assert content_type == "text/csv"
    assert disposition is None
