"""
S3-compatible object storage with presigned PUT/GET URLs (AWS S3, Cloudflare R2, MinIO).
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any


class StorageConfigError(RuntimeError):
    """Raised when required env vars for object storage are missing."""


class ObjectStore(ABC):
    @abstractmethod
    def generate_presigned_upload_url(
        self, object_key: str, content_type: str, expires: int
    ) -> str: ...

    @abstractmethod
    def generate_presigned_download_url(self, object_key: str, expires: int) -> str: ...

    @abstractmethod
    def get_object_metadata(self, object_key: str) -> dict[str, Any]: ...

    @abstractmethod
    def delete_object(self, object_key: str) -> None: ...

    @abstractmethod
    def download_object_body(self, object_key: str) -> bytes:
        """Return full object body (MVP — stream large files to disk in a future iteration)."""
        ...


def _truthy_raw(val: str | None) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


class S3CompatibleStore(ObjectStore):
    """boto3 S3 client — works with AWS S3, R2, MinIO via endpoint_url."""

    def __init__(self):
        try:
            import boto3  # noqa: WPS433
        except ImportError as e:
            raise StorageConfigError("Install boto3 to use object storage: pip install boto3") from e

        bucket = os.getenv("S3_BUCKET") or os.getenv("AWS_BUCKET")
        if not bucket:
            raise StorageConfigError(
                "S3_BUCKET (or AWS_BUCKET) is required for presigned uploads"
            )

        ak = os.getenv("AWS_ACCESS_KEY_ID")
        sk = os.getenv("AWS_SECRET_ACCESS_KEY")
        if not ak or not sk:
            raise StorageConfigError(
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required for object storage"
            )

        endpoint = os.getenv("S3_ENDPOINT_URL") or None  # unset or empty -> AWS global
        region = os.getenv("AWS_REGION") or (
            os.getenv("AWS_DEFAULT_REGION") or "auto"
        )

        kwargs: dict[str, Any] = {
            "service_name": "s3",
            "aws_access_key_id": ak,
            "aws_secret_access_key": sk,
            "region_name": region,
        }
        if endpoint:
            kwargs["endpoint_url"] = endpoint

        self._bucket = bucket
        self._client = boto3.client(**kwargs)

    @property
    def bucket_name(self) -> str:
        return self._bucket

    def generate_presigned_upload_url(
        self, object_key: str, content_type: str, expires: int = 3600
    ) -> str:
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": object_key,
            "ContentType": content_type,
        }
        return self._client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=expires,
            HttpMethod="PUT",
        )

    def generate_presigned_download_url(self, object_key: str, expires: int = 3600) -> str:
        params = {"Bucket": self._bucket, "Key": object_key}
        return self._client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expires, HttpMethod="GET"
        )

    def get_object_metadata(self, object_key: str) -> dict[str, Any]:
        return self._client.head_object(Bucket=self._bucket, Key=object_key)

    def delete_object(self, object_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=object_key)

    def download_object_body(self, object_key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=object_key)
        return resp["Body"].read()


def build_default_store() -> ObjectStore:
    """Build store from env. Raises StorageConfigError if misconfigured."""

    disabled = os.getenv("OBJECT_STORAGE_DISABLED", "").lower()
    if _truthy_raw(disabled) or os.getenv("STORAGE_PROVIDER", "").strip().lower() == "disabled":
        raise StorageConfigError("Object storage disabled via OBJECT_STORAGE_DISABLED")

    provider = (os.getenv("STORAGE_PROVIDER") or "s3").strip().lower()
    # R2/minio/digitalocean spaces all use the same S3 API
    if provider in {"s3", "r2", "minio", "spaces"}:
        return S3CompatibleStore()
    raise StorageConfigError(f"Unsupported STORAGE_PROVIDER: {provider!r}")


def try_build_default_store() -> ObjectStore | None:
    try:
        return build_default_store()
    except StorageConfigError:
        return None
