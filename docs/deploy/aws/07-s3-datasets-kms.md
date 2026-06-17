# S3 Raw Dataset Storage with SSE-KMS

Production raw uploads are stored in AWS S3 only (no local `storage/uploads/` copy). Every object is encrypted with a customer-managed KMS key.

## 1. KMS customer-managed key

1. AWS Console → KMS → Create key → Symmetric → Alias `statathon-datasets`.
2. Key policy: allow the ECS API task role and (optionally) your dev IAM user:

```json
{
  "Sid": "AllowApiTaskRole",
  "Effect": "Allow",
  "Principal": { "AWS": "arn:aws:iam::ACCOUNT:role/bharatstat-api-task" },
  "Action": [
    "kms:Encrypt",
    "kms:Decrypt",
    "kms:GenerateDataKey",
    "kms:DescribeKey"
  ],
  "Resource": "*"
}
```

3. Record the key ARN for `S3_KMS_KEY_ID` in ECS env / Secrets Manager.

## 2. S3 bucket

Create `statathon-datasets-prod` (or your chosen name):

| Setting | Value |
|---------|--------|
| Region | Same as ECS (e.g. `ap-south-1`) |
| Block public access | All ON |
| Default encryption | SSE-KMS with CMK above |
| Versioning | Enabled |
| Object ownership | Bucket owner enforced |

Optional lifecycle rule on prefix `datasets/` to expire noncurrent versions after 90 days.

## 3. Bucket policy (deny unencrypted puts)

Replace `BUCKET`, `ACCOUNT`, and `KEY-ID`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyUnencryptedObjectUploads",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::statathon-datasets-prod/datasets/*",
      "Condition": {
        "StringNotEquals": {
          "s3:x-amz-server-side-encryption": "aws:kms"
        }
      }
    }
  ]
}
```

## 4. IAM task role (ECS API)

Attach to `bharatstat-api` task role — no long-lived access keys in production:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:HeadObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::statathon-datasets-prod/datasets/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:GenerateDataKey",
        "kms:DescribeKey"
      ],
      "Resource": "arn:aws:kms:ap-south-1:ACCOUNT:key/KEY-ID"
    }
  ]
}
```

Also scope `report_templates/immutable/*` if using vault uploads (see `S3_VAULT_PREFIX`).

## 5. Application env

```env
STORAGE_PROVIDER=s3
S3_BUCKET=statathon-datasets-prod
AWS_REGION=ap-south-1
S3_ENDPOINT_URL=
S3_UPLOAD_PREFIX=datasets
S3_KMS_KEY_ID=arn:aws:kms:ap-south-1:ACCOUNT:key/KEY-ID
OBJECT_STORAGE_DISABLED=
```

Do **not** set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` on ECS when the task role is attached. For local dev, use `aws configure` or scoped IAM user keys.

## 6. Migrate existing local datasets

```bash
cd api
$env:PYTHONPATH = (Resolve-Path "..").Path
python ../scripts/migrate_local_datasets_to_s3.py --dry-run
python ../scripts/migrate_local_datasets_to_s3.py
```

## 7. Audit

Enable CloudTrail data events for S3 object-level API activity and KMS `Decrypt`/`GenerateDataKey` usage.
