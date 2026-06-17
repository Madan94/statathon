"""
AWS S3 object storage with presigned PUT/GET URLs and SSE-KMS encryption.
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
    def generate_presigned_download_url(self, object_key: str, expires: int = 3600) -> str: ...

    @abstractmethod
    def get_object_metadata(self, object_key: str) -> dict[str, Any]: ...

    @abstractmethod
    def delete_object(self, object_key: str) -> None: ...

    @abstractmethod
    def download_object_body(self, object_key: str) -> bytes:
        """Return full object body (MVP — stream large files to disk in a future iteration)."""
        ...

    @abstractmethod
    def upload_object_body(
        self,
        object_key: str,
        body: bytes,
        content_type: str,
        *,
        kms_key_id: str | None = None,
    ) -> None:
        """Upload full object body for server-side ingestion pipelines."""
        ...


def _truthy_raw(val: str | None) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


def resolve_kms_key_id(env_var: str = "S3_KMS_KEY_ID") -> str:
    """Return KMS key id/ARN from env; raises StorageConfigError if missing."""
    key_id = (os.getenv(env_var) or "").strip()
    if not key_id:
        raise StorageConfigError(f"{env_var} is required for SSE-KMS object storage")
    lower = key_id.lower()
    if ":iam:" in lower or lower.startswith("arn:aws:iam:"):
        raise StorageConfigError(
            f"{env_var} must be a KMS key ARN or alias (e.g. arn:aws:kms:us-east-1:ACCOUNT:key/KEY-ID "
            f"or alias/statathon-datasets), not an IAM user/role ARN: {key_id!r}"
        )
    if not (lower.startswith("arn:aws:kms:") or lower.startswith("alias/")):
        raise StorageConfigError(
            f"{env_var} must be a KMS key ARN (arn:aws:kms:...) or alias (alias/...), got: {key_id!r}"
        )
    return key_id


def validate_object_storage_config() -> None:
    """Fail fast when S3 storage is enabled but misconfigured."""
    disabled = os.getenv("OBJECT_STORAGE_DISABLED", "").lower()
    if _truthy_raw(disabled) or os.getenv("STORAGE_PROVIDER", "").strip().lower() == "disabled":
        return

    provider = (os.getenv("STORAGE_PROVIDER") or "s3").strip().lower()
    if provider != "s3":
        raise StorageConfigError(f"Unsupported STORAGE_PROVIDER for production: {provider!r} (use s3)")

    bucket = os.getenv("S3_BUCKET") or os.getenv("AWS_BUCKET")
    if not bucket:
        raise StorageConfigError("S3_BUCKET is required when object storage is enabled")

    region = (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "").strip()
    endpoint = (os.getenv("S3_ENDPOINT_URL") or "").strip()
    if not endpoint and (not region or region.lower() == "auto"):
        raise StorageConfigError("AWS_REGION must be a real region (e.g. ap-south-1) for AWS S3")

    resolve_kms_key_id("S3_KMS_KEY_ID")


class S3CompatibleStore(ObjectStore):
    """boto3 S3 client for AWS S3 with SSE-KMS."""

    def __init__(self):
        try:
            import boto3  # noqa: WPS433
        except ImportError as e:
            raise StorageConfigError("Install boto3 to use object storage: pip install boto3") from e

        bucket = os.getenv("S3_BUCKET") or os.getenv("AWS_BUCKET")
        if not bucket:
            raise StorageConfigError("S3_BUCKET (or AWS_BUCKET) is required for object storage")

        endpoint = (os.getenv("S3_ENDPOINT_URL") or "").strip() or None
        region = (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "").strip()
        if not endpoint and (not region or region.lower() == "auto"):
            raise StorageConfigError("AWS_REGION must be set to a real region for AWS S3")

        self._kms_key_id = resolve_kms_key_id("S3_KMS_KEY_ID")
        self._vault_kms_key_id = (os.getenv("S3_VAULT_KMS_KEY_ID") or "").strip() or self._kms_key_id

        kwargs: dict[str, Any] = {
            "service_name": "s3",
            "region_name": region or "us-east-1",
        }
        if endpoint:
            kwargs["endpoint_url"] = endpoint

        ak = (os.getenv("AWS_ACCESS_KEY_ID") or "").strip()
        sk = (os.getenv("AWS_SECRET_ACCESS_KEY") or "").strip()
        if ak and sk:
            kwargs["aws_access_key_id"] = ak
            kwargs["aws_secret_access_key"] = sk

        self._bucket = bucket
        self._client = boto3.client(**kwargs)

    @property
    def bucket_name(self) -> str:
        return self._bucket

    def _sse_put_params(self, kms_key_id: str | None = None) -> dict[str, str]:
        key = kms_key_id or self._kms_key_id
        return {
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": key,
        }

    def _vault_kms_for_key(self, object_key: str) -> str | None:
        vault_prefix = (os.getenv("S3_VAULT_PREFIX") or "report_templates/immutable").strip().strip("/")
        if vault_prefix and object_key.startswith(f"{vault_prefix}/"):
            return self._vault_kms_key_id
        return None

    def generate_presigned_upload_url(
        self, object_key: str, content_type: str, expires: int = 3600
    ) -> str:
        kms = self._vault_kms_for_key(object_key) or self._kms_key_id
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": object_key,
            "ContentType": content_type,
            **self._sse_put_params(kms),
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

    def upload_object_body(
        self,
        object_key: str,
        body: bytes,
        content_type: str,
        *,
        kms_key_id: str | None = None,
    ) -> None:
        kms = kms_key_id or self._vault_kms_for_key(object_key) or self._kms_key_id
        self._client.put_object(
            Bucket=self._bucket,
            Key=object_key,
            Body=body,
            ContentType=content_type,
            **self._sse_put_params(kms),
        )


def build_default_store() -> ObjectStore:
    """Build store from env. Raises StorageConfigError if misconfigured."""
    disabled = os.getenv("OBJECT_STORAGE_DISABLED", "").lower()
    if _truthy_raw(disabled) or os.getenv("STORAGE_PROVIDER", "").strip().lower() == "disabled":
        raise StorageConfigError("Object storage disabled via OBJECT_STORAGE_DISABLED")

    provider = (os.getenv("STORAGE_PROVIDER") or "s3").strip().lower()
    if provider != "s3":
        raise StorageConfigError(f"Unsupported STORAGE_PROVIDER: {provider!r} (only s3 is supported)")
    return S3CompatibleStore()


def try_build_default_store() -> ObjectStore | None:
    try:
        return build_default_store()
    except StorageConfigError:
        return None
