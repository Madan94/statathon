# statathon

Statathon hackathon backend (FastAPI) with semantic profiling and optional **S3-compatible presigned uploads**.

## Quick start (API)

```bash
cd api
pip install -r ../requirements-windows.txt   # Windows-friendly
export PYTHONPATH="$(dirname "$PWD")"       # repo root — required for `object_storage/` + `pipelines/`
uvicorn main:app --reload
```

Copy `.env.example` → `.env` and set **`DATABASE_URL`**.  
For presigned uploads, also set **`S3_BUCKET`**, **`AWS_ACCESS_KEY_ID`**, **`AWS_SECRET_ACCESS_KEY`** and (for R2/MinIO) **`S3_ENDPOINT_URL`**.

See **[docs/R2_STEP_BY_STEP.md](docs/R2_STEP_BY_STEP.md)** for **Cloudflare R2** setup + PowerShell/API checks.  
See **[docs/OBJECT_STORAGE.md](docs/OBJECT_STORAGE.md)** for the generic flow, upload statuses, and Postgres migrations.
