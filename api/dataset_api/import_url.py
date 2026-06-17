"""Download datasets from presigned S3 GET URLs server-side (avoids browser CORS)."""
from __future__ import annotations

import ipaddress
import os
import re
import uuid
from urllib.parse import unquote, urlparse

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from dataset_api.storage_keys import generate_object_key
from object_storage.object_store import ObjectStore
from repositories.dataset_repository import DatasetRepository

SAFE_DOC_EXT = frozenset({".csv", ".xlsx", ".xls"})
_CONTENT_DISPOSITION_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";\n]+)"?', re.I)

DEFAULT_MAX_BYTES = 100 * 1024 * 1024


def _max_import_bytes() -> int:
    raw = os.getenv("IMPORT_URL_MAX_BYTES", str(DEFAULT_MAX_BYTES)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_BYTES


def _content_type_for_filename(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".csv":
        return "text/csv"
    if ext == ".xls":
        return "application/vnd.ms-excel"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _basename_from_url(url: str) -> str:
    try:
        path = urlparse(url).path
        name = unquote(path.split("/")[-1] or "")
        return os.path.basename(name)
    except Exception:
        return ""


def _filename_from_content_disposition(header: str | None) -> str:
    if not header:
        return ""
    match = _CONTENT_DISPOSITION_RE.search(header)
    if not match:
        return ""
    return os.path.basename(unquote(match.group(1).strip()))


def _filename_from_content_type(content_type: str | None) -> str:
    lower = (content_type or "").lower()
    if "text/csv" in lower or "application/csv" in lower:
        return f"dataset-{uuid.uuid4().hex[:8]}.csv"
    if "spreadsheetml.sheet" in lower:
        return f"dataset-{uuid.uuid4().hex[:8]}.xlsx"
    if "vnd.ms-excel" in lower:
        return f"dataset-{uuid.uuid4().hex[:8]}.xls"
    return ""


def resolve_import_filename(
    url: str,
    *,
    requested: str | None,
    content_type: str | None,
    content_disposition: str | None,
) -> str:
    for candidate in (
        (requested or "").strip(),
        _filename_from_content_disposition(content_disposition),
        _basename_from_url(url),
        _filename_from_content_type(content_type),
    ):
        if not candidate:
            continue
        name = os.path.basename(candidate)
        ext = os.path.splitext(name)[1].lower()
        if ext in SAFE_DOC_EXT:
            return name
    raise HTTPException(
        status_code=400,
        detail="Could not determine filename; provide a .csv, .xls, or .xlsx name",
    )


def validate_import_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="URL is required")
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("https", "http"):
        raise HTTPException(status_code=400, detail="Only http/https URLs are supported")
    host = (parsed.hostname or "").lower()
    if not host:
        raise HTTPException(status_code=400, detail="Invalid URL")

    allow_http_remote = os.getenv("ALLOW_IMPORT_URL_HTTP", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if parsed.scheme == "http":
        is_local = host in ("localhost", "127.0.0.1", "::1")
        if not is_local and not allow_http_remote:
            raise HTTPException(status_code=400, detail="HTTPS is required for remote import URLs")

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_link_local:
            if host not in ("127.0.0.1", "::1", "localhost"):
                raise HTTPException(status_code=400, detail="Private network URLs are not allowed")
    except ValueError:
        pass

    return cleaned


def fetch_url_bytes(url: str) -> tuple[bytes, str | None, str | None]:
    """GET file from presigned URL with size limit."""
    max_bytes = _max_import_bytes()
    timeout = float(os.getenv("IMPORT_URL_TIMEOUT_SECONDS", "120"))
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Remote URL returned {resp.status_code} {resp.reason_phrase}",
                    )
                content_type = resp.headers.get("content-type")
                disposition = resp.headers.get("content-disposition")
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Remote file exceeds limit of {max_bytes} bytes",
                        )
                    chunks.append(chunk)
                if total == 0:
                    raise HTTPException(status_code=400, detail="Remote URL returned an empty file")
                return b"".join(chunks), content_type, disposition
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {exc}") from exc


def _save_bytes_object_storage(
    db: Session,
    *,
    user_id: int,
    filename: str,
    file_bytes: bytes,
    store: ObjectStore,
    async_profile: bool = True,
    background_tasks=None,
):
    from dataset_api.profile_jobs import execute_dataset_profile_job
    from dataset_api.services import profile_registered_dataset

    key = generate_object_key(filename)
    content_type = _content_type_for_filename(filename)
    store.upload_object_body(key, file_bytes, content_type)
    ds = DatasetRepository(db).create_from_object_registration(
        user_id=user_id,
        filename=filename,
        object_key=key,
        file_size=len(file_bytes),
        checksum=None,
        storage_provider="s3",
        upload_status="PROCESSING" if async_profile else "UPLOADED",
        status="processing" if async_profile else "ingested",
        commit=True,
    )
    if async_profile and background_tasks is not None:
        background_tasks.add_task(
            execute_dataset_profile_job,
            ds.id,
            filename=filename,
            file_bytes=file_bytes,
            object_key=key,
            file_size=len(file_bytes),
        )
        return ds
    return profile_registered_dataset(
        db,
        ds.id,
        filename=filename,
        file_bytes=file_bytes,
        file_size=len(file_bytes),
    )


def import_from_presigned_url(
    db: Session,
    *,
    user_id: int,
    url: str,
    filename: str | None = None,
    store: ObjectStore,
    background_tasks=None,
    async_profile: bool = True,
):
    """Fetch CSV/Excel from a presigned GET URL and register as a dataset in S3."""
    safe_url = validate_import_url(url)
    file_bytes, content_type, disposition = fetch_url_bytes(safe_url)
    resolved_name = resolve_import_filename(
        safe_url,
        requested=filename,
        content_type=content_type,
        content_disposition=disposition,
    )
    return _save_bytes_object_storage(
        db,
        user_id=user_id,
        filename=resolved_name,
        file_bytes=file_bytes,
        store=store,
        async_profile=async_profile,
        background_tasks=background_tasks,
    )
