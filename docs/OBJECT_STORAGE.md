# Object storage (presigned uploads)

## Flow

1. **POST `/datasets/upload-url`** — JSON `{ "filename": "...", "content_type": "..." }`  
   Response: `{ "upload_url", "object_key", "expires_in" }`.

2. **PUT `upload_url`** — Send raw file bytes. **Important:** Use the **same** `Content-Type` you gave in step 1 (signature binds it).

3. **POST `/datasets/register`** — JSON `{ "object_key", "filename", "file_size", "checksum" }` (`checksum` optional).  
   The API `HEAD`s the object and checks `Content-Length` matches `file_size`.  
   It creates `Dataset`, starts `Analysis` in **`BackgroundTasks`**, and streams the object from storage through the semantic pipeline.

4. **GET `/datasets/{dataset_id}`** — Metadata incl. `upload_status`.

5. **`GET /analysis/{analysis_id}/results`** once `analysis.status` is `complete` (same as multipart path).

## Upload status (object-backed datasets only)

| Value        | Meaning                          |
|-------------|-----------------------------------|
| `null`      | Legacy / local `/datasets/upload` |
| `UPLOADED`  | Registered after PUT            |
| `PROCESSING`| Analysis running               |
| `ANALYZED`  | Pipeline finished OK           |
| `FAILED`    | Pipeline error                 |

---

## Accuracy / verification by step (engineering checks)

These are **not ML accuracy** — they describe how confidently each step validates the flow.

| Step | What we enforce | Confidence |
|------|-----------------|------------|
| Presigned URL generation | boto3 SigV4; Content-Type baked into PUT URL | **High** — client must exact-match header |
| Direct PUT upload | Storage provider authoritative size | **High** |
| `/datasets/register` | `HeadObject`; `ContentLength` vs `file_size` (± `REGISTER_SIZE_TOLERANCE_BYTES`) | **High** |
| Duplicate key | Unique `object_key` in DB | **High** (409 Conflict) |
| Checksum match | Accepted from client only; optional server recomputation (`checksum` verification) — **not** implemented yet | **Low / N/A** |
| Semantic pipeline quality | Separate benchmark scripts / labeled eval | Separate process |

---

## Neon / Postgres migrations

Existing deployments need new columns on `datasets`. Example (adjust names/constraints):

```sql
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS object_key VARCHAR(1024) UNIQUE;
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS storage_provider VARCHAR(32) NOT NULL DEFAULT 'local';
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS storage_url VARCHAR(2048);
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS file_size BIGINT;
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS checksum VARCHAR(128);
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS upload_status VARCHAR(32);
-- Allow object-only datasets:
ALTER TABLE datasets ALTER COLUMN storage_path DROP NOT NULL;
```

SQLite dev DB: safest is deleting the file and letting `create_all` recreate, **or** run equivalent `ALTER` manually.
