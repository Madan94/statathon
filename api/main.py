import sys
from pathlib import Path

# Windows consoles often use cp1252; force UTF-8 so pipeline logs never crash analysis.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Repo root — needed for imports like object_storage/, pipelines/ when cwd is api/
_API_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _API_DIR.parent
# api/ must come before repo root so local `datasets` beats HuggingFace `datasets` package.
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(1, str(_REPO_ROOT))

import logging
import os
import time
import traceback
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from auth.csrf import verify_csrf
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session
from database.database import Base, engine, SessionLocal, is_transient_db_error, pool_stats
import database.models  # noqa: F401 — register metadata for semantic tables
from pipelines.model_path import ensure_huggingface_hub_cache
from pipelines.storage_paths import normalize_storage_env

ensure_huggingface_hub_cache(_REPO_ROOT)
normalize_storage_env()

# Configure rich logging BEFORE importing routers (so their module-level
# loggers inherit the new handler instead of basicConfig defaults).
from logging_setup import configure_rich_logging  # noqa: E402

configure_rich_logging(level=os.getenv("LOG_LEVEL", "INFO"))

from auth.routes import router as auth_router
from auth.oauth_routes import router as oauth_router
from dataset_api.routes import router as datasets_router
from analysis.routes import router as analysis_router
from reports.routes import router as reports_router
from report_builder_api.routes import router as report_builder_router
from report_builder_api.progress_sse import router as progress_sse_router
from report_builder_api.entity_binding_api import router as entity_binding_router
from report_builder_api.binding_phase_api import router as binding_phase_router
from report_builder_api.generate_phase_api import router as generate_phase_router
from report_builder_api.model_config_api import router as model_config_router
from dashboard.routes import router as dashboard_router

logger = logging.getLogger("bharatstat.api")

app = FastAPI(title="BharatStat")

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
    expose_headers=["*"],
)


@app.middleware("http")
async def request_log_middleware(request: Request, call_next):
    """Per-request log line with unique req-id and end-to-end latency.

    Format (color-coded by rich based on status):
      ▶ [req_abc12345] GET  /path
      ✓ [req_abc12345] GET  /path  →  200   142.3 ms
      ✗ [req_abc12345] GET  /path  →  500   18.0 ms
    """
    req_id = uuid.uuid4().hex[:8]
    t0 = time.monotonic()
    method = request.method.ljust(4)
    path = request.url.path
    logger.info("▶ [req_%s] %s %s", req_id, method, path)
    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.error("✗ [req_%s] %s %s  →  CRASH %s   %.1f ms",
                     req_id, method, path, type(exc).__name__, elapsed_ms)
        raise
    elapsed_ms = (time.monotonic() - t0) * 1000
    sc = response.status_code
    icon = "✓" if sc < 400 else ("⚠" if sc < 500 else "✗")
    level = logger.warning if sc >= 500 else (logger.info if sc < 400 else logger.warning)
    level("%s [req_%s] %s %s  →  %d   %.1f ms",
          icon, req_id, method, path, sc, elapsed_ms)
    response.headers["X-Request-ID"] = req_id
    return response


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    from fastapi import HTTPException

    try:
        verify_csrf(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if os.getenv("APP_ENV", "development").lower() == "production":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains; preload",
        )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    from fastapi import HTTPException

    if isinstance(exc, HTTPException):
        raise exc

    # Classify DB connectivity errors → 503 (Service Unavailable, retriable)
    # rather than 500 (true server bug). Frontend can show "reconnecting…"
    # instead of a stack-trace error.
    if isinstance(exc, (OperationalError, DBAPIError)) and is_transient_db_error(exc):
        logger.warning(
            "[db] transient DB error on %s %s: %s",
            request.method, request.url.path, str(exc).split(chr(10))[0][:300],
        )
        return JSONResponse(
            status_code=503,
            content={
                "detail": "database temporarily unreachable (DNS/network) — retry shortly",
                "error_class": type(exc).__name__,
                "retry_after_seconds": 5,
            },
            headers={"Retry-After": "5"},
        )

    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    logger.error(traceback.format_exc())
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# ── Startup: DB schema + migrations ─────────────────────────────────────────
# IMPORTANT: do NOT call create_all / migrations at module level.
# If DATABASE_URL is temporarily unreachable (Supabase paused, DNS failure,
# network not ready) the entire uvicorn process would crash before serving
# a single request. Wrapping in a startup event lets the app start and
# respond to /health even while the DB is recovering.
@app.on_event("startup")
async def _startup_db() -> None:
    from database.migrate_auth import migrate_auth_schema
    from database.migrate_report_builder import migrate_report_builder_schema
    from database.migrate_dataset_columns import migrate_dataset_columns_schema
    from database.migrate_weight_application import migrate_weight_application_schema

    try:
        Base.metadata.create_all(bind=engine)
        migrate_auth_schema()
        migrate_report_builder_schema()
        migrate_dataset_columns_schema()
        migrate_weight_application_schema()
        logger.info("DB schema initialised (create_all + migrations OK)")
    except Exception as _db_exc:
        # Log clearly but do NOT re-raise — app still starts, DB-dependent
        # endpoints will fail with 500 until the DB becomes reachable.
        logger.error(
            "DB startup failed — app will start but DB endpoints will error: %s",
            _db_exc,
        )

    try:
        from services.analysis_runner import reset_orphaned_analyses
        _orphaned = reset_orphaned_analyses()
        if _orphaned:
            logger.info("Reset %s orphaned analysis job(s) after startup", _orphaned)
    except Exception as _orphan_exc:
        logger.warning("Orphaned analysis reset skipped: %s", _orphan_exc)

    # Seed dev test officer (development only)
    if os.getenv("APP_ENV", "development").lower() in ("development", "dev", "local"):
        try:
            from auth.dev_user import ensure_dev_test_user
            _seed_db = SessionLocal()
            try:
                ensure_dev_test_user(_seed_db)
            finally:
                _seed_db.close()
        except Exception as _seed_exc:
            logger.warning("Dev test user seed skipped: %s", _seed_exc)

    # One-time Neo4j schema bootstrap
    try:
        from graph.schema_bootstrap import ensure_schema as _kg_ensure_schema
        _kg_bootstrap_result = _kg_ensure_schema()
        if _kg_bootstrap_result.get("ok"):
            logger.info("Neo4j schema bootstrap: %s statements OK",
                        _kg_bootstrap_result.get("statements_run", 0))
        elif _kg_bootstrap_result.get("enabled"):
            logger.warning("Neo4j schema bootstrap: %s",
                           _kg_bootstrap_result.get("error") or _kg_bootstrap_result.get("errors"))
    except Exception as _exc:
        logger.info("Neo4j schema bootstrap skipped: %s", _exc)

_secret = os.getenv("SECRET_KEY", "")
if os.getenv("AUTH_REQUIRED", "true").lower() in ("1", "true", "yes"):
    if not _secret or _secret in ("supersecret", "change-me-use-long-random-string") or len(_secret) < 32:
        import warnings

        warnings.warn(
            "SECRET_KEY must be a long random string when AUTH_REQUIRED=true",
            stacklevel=1,
        )

app.include_router(auth_router)
app.include_router(oauth_router)
app.include_router(datasets_router)
app.include_router(analysis_router)
app.include_router(reports_router)
app.include_router(report_builder_router)
app.include_router(progress_sse_router)
app.include_router(entity_binding_router)
app.include_router(binding_phase_router)
app.include_router(generate_phase_router)
app.include_router(model_config_router)
app.include_router(dashboard_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    """Verify SQLAlchemy can reach the database + return pool stats.

    Returns 200 when reachable, 503 when DNS/network is down.
    """
    stats = pool_stats()
    db: Session = SessionLocal()
    try:
        t0 = time.monotonic()
        db.execute(text("SELECT 1"))
        elapsed_ms = (time.monotonic() - t0) * 1000
        return {
            "status": "ok",
            "database": "reachable",
            "ping_ms": round(elapsed_ms, 1),
            "pool": stats,
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "detail": str(e).split(chr(10))[0][:300],
                "error_class": type(e).__name__,
                "transient": is_transient_db_error(e),
                "pool": stats,
            },
        )
    finally:
        db.close()