"""
Minimal GPU worker stub contract for INFERENCE_MODE=remote testing.
Replace with real model execution service on EC2 GPU instance.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="BharatStat GPU Worker Stub")


class AnalyzeRequest(BaseModel):
    dataset_id: int
    analysis_id: int
    filename: str
    storage_path: str | None = None
    object_key: str | None = None
    storage_provider: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/analyze")
def analyze(req: AnalyzeRequest):
    # TODO: run heavy inference + pipeline on GPU node and return structured result.
    # Must include content_hash if available, to preserve report metadata linkage.
    return {
        "analysis_id": req.analysis_id,
        "dataset_id": req.dataset_id,
        "content_hash": None,
        "mode": "stub",
    }
