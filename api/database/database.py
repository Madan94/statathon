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
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {"connect_timeout": 15},
    pool_pre_ping=not _is_sqlite,
    pool_recycle=280 if not _is_sqlite else -1,
    pool_size=15 if not _is_sqlite else 5,
    max_overflow=15 if not _is_sqlite else 0,
    pool_timeout=30 if not _is_sqlite else 30,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
from sqlalchemy.orm import declarative_base
Base = declarative_base()