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
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=not _is_sqlite,
    pool_recycle=280 if not _is_sqlite else -1,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
from sqlalchemy.orm import declarative_base
Base = declarative_base()