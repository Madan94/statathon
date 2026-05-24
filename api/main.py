import sys
from pathlib import Path

# Repo root — needed for imports like object_storage/, pipelines/ when cwd is api/
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from database.database import Base, engine, SessionLocal
import database.models  # noqa: F401 — register metadata for semantic tables

from pipelines.model_path import ensure_huggingface_hub_cache

ensure_huggingface_hub_cache(_REPO_ROOT)

from auth.routes import router as auth_router
from auth.oauth_routes import router as oauth_router
from datasets.routes import router as datasets_router
from analysis.routes import router as analysis_router
from reports.routes import router as reports_router

app = FastAPI(title="Statathon")

_cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)
app.include_router(auth_router)
app.include_router(oauth_router)
app.include_router(datasets_router)
app.include_router(analysis_router)
app.include_router(reports_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    """Verify SQLAlchemy can reach the database (use after pointing DATABASE_URL at Neon, etc.)."""
    db: Session = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "reachable"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()