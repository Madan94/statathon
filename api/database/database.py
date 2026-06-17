import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("bharatstat.database")

# `database.py` lives in api/database/ — repo API root is one level up
_api_root = Path(__file__).resolve().parents[1]
_root_env = _api_root.parent / ".env"
if _root_env.is_file():
    load_dotenv(_root_env)
else:
    load_dotenv()
_default_sqlite = (_api_root / "statathon.db").resolve().as_posix()
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_default_sqlite}")
_is_sqlite = DATABASE_URL.startswith("sqlite")
_is_xata = ".sql.xata.sh" in DATABASE_URL.lower() or ".xata.tech" in DATABASE_URL.lower()

# For Postgres (Supabase, Xata, Neon, RDS):
#  - pool_pre_ping → SELECT 1 before handing out a connection
#  - pool_recycle  → drop idle connections before server-side timeout
#  - pool_size/max_overflow → keep small for hobby tier, allow burst
#  - pool_timeout → wait at most 30s to get a connection from the pool
#  - connect_args.connect_timeout → fail-fast on DNS/network hangs
#  - options statement_timeout / lock_timeout → avoid runaway queries
# Xata: use ?sslmode=require; optional -pooler host suffix for serverless workloads
_default_statement_timeout_ms = os.getenv("DB_STATEMENT_TIMEOUT_MS", "60000" if _is_xata else "15000")
_default_lock_timeout_ms = os.getenv("DB_LOCK_TIMEOUT_MS", "30000" if _is_xata else "5000")
_pg_connect_args = {
    "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
    "options": (
        f"-c statement_timeout={_default_statement_timeout_ms} "
        f"-c lock_timeout={_default_lock_timeout_ms}"
    ),
}
if "sslmode" not in DATABASE_URL.lower() and not _is_sqlite:
    logger.warning(
        "DATABASE_URL has no sslmode= — Postgres providers (Xata, Supabase) usually require sslmode=require"
    )

# Use NullPool if env says so (useful for serverless / extraction workers that
# open one connection, do one query, close — avoids pool accumulation)
_use_null_pool = os.getenv("DB_NULL_POOL", "").strip().lower() in ("1", "true", "yes")

if _use_null_pool and not _is_sqlite:
    from sqlalchemy.pool import NullPool
    engine = create_engine(
        DATABASE_URL,
        connect_args=_pg_connect_args,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False} if _is_sqlite else _pg_connect_args,
        pool_pre_ping=not _is_sqlite,
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "280")) if not _is_sqlite else -1,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")) if not _is_sqlite else 5,
        max_overflow=int(os.getenv("DB_POOL_MAX_OVERFLOW", "10")) if not _is_sqlite else 10,
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
        echo_pool=os.getenv("DB_ECHO_POOL", "false").lower() in ("1", "true", "yes"),
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
from sqlalchemy.orm import declarative_base  # noqa: E402
Base = declarative_base()


def _is_transient_db_error(exc: BaseException) -> bool:
    """Classify DB exceptions: True if DNS/network/connection issue (retriable)."""
    msg = str(exc).lower()
    indicators = (
        "could not translate host name",
        "name or service not known",
        "connection refused",
        "connection reset",
        "connection timed out",
        "server closed the connection",
        "no route to host",
        "temporary failure in name resolution",
        "ssl syscall error",
        "eof detected",
    )
    return any(ind in msg for ind in indicators)


@event.listens_for(engine, "handle_error")
def _on_db_error(ctx) -> None:
    """Auto-recover the pool when DNS/network failures invalidate connections.

    Without this, once DNS hiccups, the pool caches dead psycopg2 connections
    and every subsequent request returns 500 even after the network recovers.
    """
    exc = ctx.original_exception
    if isinstance(exc, (OperationalError, DBAPIError)) and _is_transient_db_error(exc):
        logger.warning("[db] transient error detected (%s) — disposing pool for fresh DNS lookup",
                       type(exc).__name__)
        try:
            engine.dispose()
        except Exception as dispose_exc:
            logger.error("[db] pool dispose failed: %s", dispose_exc)


def pool_stats() -> dict:
    """Pool diagnostics for /health/db."""
    if _is_sqlite:
        return {"backend": "sqlite", "url": DATABASE_URL}
    p = engine.pool
    stats = {
        "backend": "xata" if _is_xata else "postgresql",
        "host_redacted": DATABASE_URL.split("@")[-1].split("/")[0] if "@" in DATABASE_URL else "",
        "pool_class": type(p).__name__,
    }
    # NullPool (DB_NULL_POOL=true / serverless) holds no connections and does
    # not implement size()/checkedin()/checkedout()/overflow(). Only report
    # these for pools that expose them (QueuePool etc.).
    for attr in ("size", "checkedin", "checkedout", "overflow"):
        meth = getattr(p, attr, None)
        if callable(meth):
            try:
                stats[attr] = meth()
            except Exception:
                pass
    return stats


def is_transient_db_error(exc: BaseException) -> bool:
    """Public helper: True if exception is a retriable DNS/network issue."""
    return _is_transient_db_error(exc)
