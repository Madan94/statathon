#!/usr/bin/env python3
"""Create statathon database on RDS if missing."""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

import os

db_url = os.getenv("DATABASE_URL", "")
if not db_url:
    print("DATABASE_URL not set in .env", file=sys.stderr)
    raise SystemExit(1)

parsed = urlparse(db_url)
admin_url = urlunparse(parsed._replace(path="/postgres"))

engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
with engine.connect() as conn:
    exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = 'statathon'")).scalar()
    if exists:
        print("Database statathon already exists")
    else:
        conn.execute(text("CREATE DATABASE statathon"))
        print("Created database statathon")
