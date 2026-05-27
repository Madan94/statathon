# Hugging Face cache root (`HUGGINGFACE_HUB_CACHE`)

This directory is created automatically when the pipeline runs (`pipelines/model_path.ensure_paths()` sets `HF_HOME` here).

- Default in `.env.example`: `./model/cache` (relative to **repo root**).
- Model weights for SentenceTransformers / `transformers` download under `HF_HOME` (e.g. `hub/`).

**Tip:** Add `model/cache/` to your local `.gitignore` if the cache grows large; do not commit downloaded weights.
