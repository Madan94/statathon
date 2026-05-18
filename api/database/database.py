import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Repo root = parent of `api/` (works when cwd is `api/` during uvicorn)
_root_env = Path(__file__).resolve().parents[2] / ".env"
if _root_env.is_file():
    load_dotenv(_root_env)
else:
    load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./statathon.db")
_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=not _is_sqlite,
    pool_recycle=280 if not _is_sqlite else -1,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
from sqlalchemy.ext.declarative import declarative_base
Base = declarative_base()