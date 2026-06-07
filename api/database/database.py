import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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


def _make_engine(url: str):
    is_sqlite = url.startswith("sqlite")
    return create_engine(
        url,
        connect_args={"check_same_thread": False} if is_sqlite else {"connect_timeout": 15},
        pool_pre_ping=not is_sqlite,
        pool_recycle=280 if not is_sqlite else -1,
        pool_size=15 if not is_sqlite else 5,
        max_overflow=15 if not is_sqlite else 0,
        pool_timeout=30 if not is_sqlite else 30,
    )


engine = _make_engine(DATABASE_URL)

# If the configured DATABASE_URL is a remote DB, verify connectivity and
# fall back to a local sqlite database if the host is unreachable. This
# avoids startup crashes when developers keep placeholder env values.
if not _is_sqlite:
    try:
        # perform a light-weight check
        with engine.connect() as conn:
            pass
    except Exception as exc:  # pragma: no cover - environment dependent
        # On failure, fall back to a file-based sqlite DB in api/ directory
        import logging
        logging.getLogger("bharatstat.api").warning(
            "Could not connect to DATABASE_URL '%s' — falling back to local sqlite. Error: %s",
            DATABASE_URL,
            exc,
        )
        DATABASE_URL = f"sqlite:///{_api_root / 'statathon.db'}"
        engine = _make_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
from sqlalchemy.orm import declarative_base
Base = declarative_base()