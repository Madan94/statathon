# Local storage folders (paths from `.env`)

- **uploads** — multipart datasets (`UPLOAD_STORAGE_PATH`, default `./storage/uploads`).
- **reports** — generated PDFs / JSON helpers (`REPORT_STORAGE_PATH`, default `./storage/reports`; use **`reports`** plural so it matches code defaults).

If you change these in `.env`, create those folders or the API may fail when writing files.
