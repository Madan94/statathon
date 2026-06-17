"""Tests for S3 server-relay dataset uploads with SSE-KMS."""
from __future__ import annotations

import io
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from dataset_api.services import save_upload
from object_storage.object_store import S3CompatibleStore, StorageConfigError, resolve_kms_key_id, validate_object_storage_config


@pytest.fixture
def csv_bytes():
    return b"col\n1\n2\n"


@pytest.fixture
def mock_upload_file(csv_bytes):
    file = MagicMock()
    file.filename = "survey.csv"
    file.file = io.BytesIO(csv_bytes)
    return file


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.upload_object_body = MagicMock()
    return store


def test_save_upload_stores_object_key_not_local_path(mock_upload_file, mock_store, csv_bytes):
    db = MagicMock()
    ds_mock = MagicMock()
    ds_mock.id = 42

    with patch("dataset_api.services.generate_object_key", return_value="datasets/2026/01/01/abc-survey.csv"):
        with patch("dataset_api.services.DatasetRepository") as repo_cls:
            repo = repo_cls.return_value
            repo.create_from_object_registration.return_value = ds_mock
            with patch("dataset_api.services.profile_registered_dataset", return_value=ds_mock) as profile_fn:
                result = save_upload(mock_upload_file, user_id=1, db=db, store=mock_store)

    mock_store.upload_object_body.assert_called_once()
    args = mock_store.upload_object_body.call_args
    assert args[0][0] == "datasets/2026/01/01/abc-survey.csv"
    assert args[0][1] == csv_bytes
    assert args[0][2] == "text/csv"

    repo.create_from_object_registration.assert_called_once()
    reg_kwargs = repo.create_from_object_registration.call_args.kwargs
    assert reg_kwargs["object_key"] == "datasets/2026/01/01/abc-survey.csv"
    assert reg_kwargs["storage_provider"] == "s3"
    assert reg_kwargs["file_size"] == len(csv_bytes)
    profile_fn.assert_called_once()
    assert result is ds_mock


def test_save_upload_rejects_empty_file(mock_store):
    file = MagicMock()
    file.filename = "empty.csv"
    file.file = io.BytesIO(b"")
    with pytest.raises(HTTPException) as exc:
        save_upload(file, user_id=1, db=MagicMock(), store=mock_store)
    assert exc.value.status_code == 400
    mock_store.upload_object_body.assert_not_called()


def test_save_upload_maps_s3_client_error_to_502(mock_upload_file, mock_store):
    from botocore.exceptions import ClientError

    mock_store.upload_object_body.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}},
        "PutObject",
    )
    with patch("dataset_api.services.generate_object_key", return_value="datasets/x.csv"):
        with pytest.raises(HTTPException) as exc:
            save_upload(mock_upload_file, user_id=1, db=MagicMock(), store=mock_store)
    assert exc.value.status_code == 502


def test_put_object_includes_sse_kms(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    monkeypatch.setenv("S3_KMS_KEY_ID", "arn:aws:kms:ap-south-1:123:key/abc")
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    mock_client = MagicMock()
    with patch("boto3.client", return_value=mock_client):
        store = S3CompatibleStore()
        store.upload_object_body("datasets/x.csv", b"data", "text/csv")

    mock_client.put_object.assert_called_once()
    kwargs = mock_client.put_object.call_args.kwargs
    assert kwargs["ServerSideEncryption"] == "aws:kms"
    assert kwargs["SSEKMSKeyId"] == "arn:aws:kms:ap-south-1:123:key/abc"


def test_validate_object_storage_config_requires_kms(monkeypatch):
    monkeypatch.setenv("STORAGE_PROVIDER", "s3")
    monkeypatch.setenv("S3_BUCKET", "b")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    monkeypatch.delenv("OBJECT_STORAGE_DISABLED", raising=False)
    monkeypatch.delenv("S3_KMS_KEY_ID", raising=False)

    with pytest.raises(StorageConfigError, match="S3_KMS_KEY_ID"):
        validate_object_storage_config()


def test_resolve_kms_key_id_rejects_iam_arn(monkeypatch):
    monkeypatch.setenv("S3_KMS_KEY_ID", "arn:aws:iam::123456789012:user/MyUser")
    with pytest.raises(StorageConfigError, match="not an IAM"):
        resolve_kms_key_id()


def test_build_default_store_rejects_non_s3_provider(monkeypatch):
    monkeypatch.setenv("STORAGE_PROVIDER", "r2")
    monkeypatch.setenv("S3_BUCKET", "b")
    monkeypatch.setenv("AWS_REGION", "auto")
    monkeypatch.setenv("S3_KMS_KEY_ID", "arn:aws:kms:us-east-1:1:key/x")
    monkeypatch.delenv("OBJECT_STORAGE_DISABLED", raising=False)

    from object_storage.object_store import build_default_store

    with pytest.raises(StorageConfigError, match="only s3"):
        build_default_store()
