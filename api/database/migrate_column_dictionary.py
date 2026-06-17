"""Idempotent migration for global column dictionary table."""
from __future__ import annotations

import logging

from database.database import engine
from database.models import Base, ColumnDictionaryGlobal

logger = logging.getLogger(__name__)

SINGLETON_ID = 1


def migrate_column_dictionary_schema() -> dict:
    Base.metadata.create_all(bind=engine, tables=[ColumnDictionaryGlobal.__table__])
    from sqlalchemy.orm import Session

    from database.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(ColumnDictionaryGlobal).filter(ColumnDictionaryGlobal.id == SINGLETON_ID).first()
        if not row:
            db.add(ColumnDictionaryGlobal(id=SINGLETON_ID, mappings={}, version=0))
            db.commit()
            logger.info("Column dictionary singleton row created")
            return {"migration": "column_dictionary", "state": "seeded"}
        return {"migration": "column_dictionary", "state": "exists"}
    finally:
        db.close()
