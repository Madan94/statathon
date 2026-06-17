# Object storage (AWS S3 + SSE-KMS)

Raw datasets are stored in **AWS S3 only** with **SSE-KMS** (customer-managed key). No local copy is written under `storage/uploads/`.

See [docs/deploy/aws/07-s3-datasets-kms.md](deploy/aws/07-s3-datasets-kms.md) for bucket, KMS, IAM, and migration setup.

## Required environment

```env
STORAGE_PROVIDER=s3
S3_BUCKET=your-bucket-name
AWS_REGION=ap-south-1
S3_ENDPOINT_URL=
S3_UPLOAD_PREFIX=datasets
S3_KMS_KEY_ID=arn:aws:kms:ap-south-1:ACCOUNT:key/KEY-ID
OBJECT_STORAGE_DISABLED=
```

Optional: `S3_VAULT_KMS_KEY_ID` for report-template vault objects under `S3_VAULT_PREFIX`.

On ECS, use the task IAM role (omit `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`). For local dev, use `aws configure` or scoped IAM user keys.

---

## Primary flow: server-relay multipart upload

1. **POST `/datasets/upload`** — multipart file upload from browser/dashboard.
2. API reads bytes in memory, profiles the file, uploads to S3 with SSE-KMS.
3. DB row: `object_key` set, `storage_path` null, `storage_provider=s3`.

This is the default path used by the upload page (`datasetsApi.upload()`).

---

## Alternate flow: presigned direct upload

For large files or clients that cannot POST multipart to the API:

1. **POST `/datasets/upload-url`** — JSON `{ "filename": "...", "content_type": "..." }`  
   Response: `{ "upload_url", "object_key", "expires_in" }` (presigned PUT includes SSE-KMS headers).

2. **PUT `upload_url`** — Send raw file bytes. **Important:** Use the **same** `Content-Type` you gave in step 1 (signature binds it).

3. **POST `/datasets/register`** — JSON `{ "object_key", "filename", "file_size", "checksum" }` (`checksum` optional).  
   The API `HEAD`s the object and checks `Content-Length` matches `file_size`.

---

## Import from presigned GET URL

**POST `/datasets/import-from-url`** — JSON `{ "url", "filename"? }`  
Server fetches the file from a presigned S3 GET URL and stores it in S3 (SSE-KMS). Avoids browser CORS issues.

---

## Upload status

| Value        | Meaning                          |
|-------------|-----------------------------------|
| `UPLOADED`  | Registered in S3                  |
| `PROCESSING`| Analysis running                  |
| `ANALYZED`  | Pipeline finished OK              |
| `FAILED`    | Pipeline error                    |

Legacy rows may still have `storage_path` (local). Run `scripts/migrate_local_datasets_to_s3.py` to move them to S3.

---

## Verification by step

| Step | What we enforce | Confidence |
|------|-----------------|------------|
| Server-relay upload | `PutObject` with `ServerSideEncryption=aws:kms` | **High** |
| Presigned URL generation | SigV4; Content-Type + SSE-KMS baked into PUT URL | **High** |
| `/datasets/register` | `HeadObject`; size tolerance | **High** |
| Duplicate key | Unique `object_key` in DB | **High** (409 Conflict) |

---

## Migrate legacy local datasets

```bash
cd api
python ../scripts/migrate_local_datasets_to_s3.py --dry-run
python ../scripts/migrate_local_datasets_to_s3.py
```

---

## Database columns

Object-backed datasets use:

- `object_key` — S3 key (e.g. `datasets/2026/06/12/{uuid}-file.csv`)
- `storage_provider` — `s3`
- `storage_path` — null for new uploads
