"""Add OWL/domain columns to schema_graph_edges for existing databases."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from database.database import engine

logger = logging.getLogger(__name__)


def migrate_schema_graph_edges_schema() -> None:
    insp = inspect(engine)
    if not insp.has_table("schema_graph_edges"):
        logger.info("schema_graph_edges table missing — will be created by create_all")
        return

    cols = {c["name"] for c in insp.get_columns("schema_graph_edges")}
    dialect_name = engine.dialect.name

    needed: list[tuple[str, str]] = []
    if "owl_type" not in cols:
        needed.append(("owl_type", "VARCHAR(128)"))
    if "source_domain" not in cols:
        needed.append(("source_domain", "VARCHAR(128)"))
    if "target_domain" not in cols:
        needed.append(("target_domain", "VARCHAR(128)"))

    if not needed:
        return

    with engine.begin() as conn:
        for col_name, col_type in needed:
            if dialect_name == "postgresql":
                sql = f"ALTER TABLE schema_graph_edges ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
            else:
                sql = f"ALTER TABLE schema_graph_edges ADD COLUMN {col_name} {col_type}"
            conn.execute(text(sql))
            logger.info("schema_graph_edges: added column %s", col_name)
