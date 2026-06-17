#!/usr/bin/env python3
"""Migrate datasets with local storage_path to AWS S3 (SSE-KMS).

Usage:
  cd api
  $env:PYTHONPATH = (Resolve-Path "..").Path   # Windows
  python ../scripts/migrate_local_datasets_to_s3.py --dry-run
  python ../scripts/migrate_local_datasets_to_s3.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_API_DIR = _REPO_ROOT / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(1, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")

from botocore.exceptions import ClientError, NoCredentialsError
from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import Dataset
from dataset_api.storage_keys import generate_object_key
from object_storage.object_store import ObjectStore, build_default_store, StorageConfigError
from pipelines.storage_paths import resolve_dataset_storage_path


def _content_type_for_filename(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".csv":
        return "text/csv"
    if ext == ".xls":
        return "application/vnd.ms-excel"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _kms_region_from_id(kms_key_id: str) -> str | None:
    """Extract region from arn:aws:kms:REGION:... or return None for alias-only ids."""
    if kms_key_id.lower().startswith("arn:aws:kms:"):
        parts = kms_key_id.split(":")
        if len(parts) > 3:
            return parts[3] or None
    return None


def _bucket_region(s3_client, bucket: str) -> str:
    loc = s3_client.get_bucket_location(Bucket=bucket).get("LocationConstraint")
    return loc or "us-east-1"


def ensure_bucket_kms_region_match(store: ObjectStore) -> None:
    """S3 SSE-KMS requires the CMK to live in the same region as the bucket."""
    kms_region = _kms_region_from_id(store._kms_key_id)  # noqa: SLF001
    if not kms_region:
        return
    try:
        bucket_region = _bucket_region(store._client, store.bucket_name)  # noqa: SLF001
    except ClientError as exc:
        print(f"Warning: could not read bucket region: {exc}", file=sys.stderr)
        return
    if kms_region != bucket_region:
        print(
            f"KMS/S3 region mismatch: bucket {store.bucket_name!r} is in {bucket_region!r} "
            f"but S3_KMS_KEY_ID is in {kms_region!r}.\n"
            f"Create a KMS key in {bucket_region} and set S3_KMS_KEY_ID to that ARN, "
            f"and set AWS_REGION={bucket_region}.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _ensure_aws_credentials() -> None:
    """Fail fast with a helpful message when neither env keys nor aws configure exist."""
    ak = (os.getenv("AWS_ACCESS_KEY_ID") or "").strip()
    sk = (os.getenv("AWS_SECRET_ACCESS_KEY") or "").strip()
    if ak and sk:
        return
    try:
        import boto3

        creds = boto3.Session().get_credentials()
        if creds and creds.access_key:
            return
    except Exception:
        pass
    print(
        "No AWS credentials found.\n"
        "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env (uncomment if needed),\n"
        "or run: aws configure",
        file=sys.stderr,
    )
    raise SystemExit(1)


def migrate_one(ds: Dataset, db: Session, store: ObjectStore | None, *, dry_run: bool) -> str:
    if ds.object_key:
        return "skip (already has object_key)"
    if not ds.storage_path:
        return "skip (no storage_path)"

    path = resolve_dataset_storage_path(ds.storage_path) or ds.storage_path
    if not path or not os.path.isfile(path):
        return f"skip (missing file: {path})"

    file_bytes = Path(path).read_bytes()
    if not file_bytes:
        return "skip (empty file)"

    object_key = generate_object_key(ds.filename or Path(path).name)
    content_type = _content_type_for_filename(ds.filename or path)

    if dry_run:
        return f"would upload {len(file_bytes)} bytes -> s3://.../{object_key}"

    try:
        assert store is not None
        store.upload_object_body(object_key, file_bytes, content_type)
        store.get_object_metadata(object_key)
    except NoCredentialsError:
        return "error (auth): no AWS credentials — set keys in .env or run aws configure"
    except ClientError as exc:
        return f"error (s3): {exc}"

    ds.object_key = object_key
    ds.storage_provider = "s3"
    ds.storage_path = None
    if ds.file_size is None:
        ds.file_size = len(file_bytes)
    db.commit()
    return f"ok -> {object_key}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate local dataset files to S3")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without uploading")
    parser.add_argument("--limit", type=int, default=0, help="Max rows to process (0 = all)")
    args = parser.parse_args()

    if not args.dry_run:
        _ensure_aws_credentials()
        try:
            store = build_default_store()
            ensure_bucket_kms_region_match(store)
        except StorageConfigError as exc:
            print(f"Object storage not configured: {exc}", file=sys.stderr)
            return 1
    else:
        store = None

    db = SessionLocal()
    try:
        q = (
            db.query(Dataset)
            .filter(Dataset.storage_path.isnot(None), Dataset.object_key.is_(None))
            .order_by(Dataset.id)
        )
        if args.limit > 0:
            q = q.limit(args.limit)
        rows = q.all()
        if not rows:
            print("No datasets to migrate.")
            return 0

        ok = 0
        for ds in rows:
            result = migrate_one(ds, db, store, dry_run=args.dry_run)
            print(f"dataset_id={ds.id} filename={ds.filename!r}: {result}")
            if result.startswith("ok") or result.startswith("would upload"):
                ok += 1
            if result.startswith("error (auth)"):
                print("Aborting — fix credentials and re-run.", file=sys.stderr)
                return 1
        print(f"Done. {ok}/{len(rows)} processed.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
