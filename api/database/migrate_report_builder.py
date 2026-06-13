"""Apply report builder schema changes to existing databases."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from database.database import engine

logger = logging.getLogger(__name__)


_TEMPLATE_PACKAGE_JSON_COLUMNS = (
    "blueprint_json",
    "semantic_slot_graph_json",
    "template_manifest_json",
    "extraction_diagnostics_json",
)

_EXTRACTION_PACKAGE_JSON_COLUMNS = (
    "template_ast_json",
    "blueprint_json",
    "semantic_slot_graph_json",
    "template_manifest_json",
    "extraction_diagnostics_json",
)


def _json_type(dialect_name: str) -> str:
    return "JSONB" if dialect_name == "postgresql" else "JSON"


def _guard_ddl(conn, dialect_name: str) -> None:
    """Bound how long DDL may wait for a lock / run, per transaction.

    The engine sets lock_timeout via connect_args ``options``, but that startup
    parameter is silently ignored by transaction-mode poolers (e.g. Supabase
    port 6543 / pgBouncer). Setting it again with ``SET LOCAL`` inside the DDL
    transaction guarantees an ``ALTER TABLE`` blocked on an ACCESS EXCLUSIVE lock
    (e.g. a leftover idle-in-transaction connection from a previously killed
    backend) fails fast instead of hanging the whole startup forever.
    """
    if dialect_name != "postgresql":
        return
    conn.execute(text("SET LOCAL lock_timeout = '5s'"))
    conn.execute(text("SET LOCAL statement_timeout = '30s'"))


def migrate_report_builder_schema() -> None:
    dialect_name = engine.dialect.name
    insp = inspect(engine)

    if insp.has_table("report_templates"):
        cols = {c["name"] for c in insp.get_columns("report_templates")}
        alters: list[str] = []
        if "filter_config" not in cols:
            if dialect_name == "postgresql":
                alters.append("ALTER TABLE report_templates ADD COLUMN filter_config JSONB")
            else:
                alters.append("ALTER TABLE report_templates ADD COLUMN filter_config JSON")
        for col in _TEMPLATE_PACKAGE_JSON_COLUMNS:
            if col not in cols:
                alters.append(f"ALTER TABLE report_templates ADD COLUMN {col} {_json_type(dialect_name)}")
        if "schema_version" not in cols:
            alters.append("ALTER TABLE report_templates ADD COLUMN schema_version VARCHAR(64)")
        with engine.begin() as conn:
            _guard_ddl(conn, dialect_name)
            for sql in alters:
                logger.info("Report builder migration: %s", sql)
                conn.execute(text(sql))

    if insp.has_table("report_jobs"):
        cols = {c["name"] for c in insp.get_columns("report_jobs")}
        alters = []
        if "filter_config" not in cols:
            if dialect_name == "postgresql":
                alters.append("ALTER TABLE report_jobs ADD COLUMN filter_config JSONB")
            else:
                alters.append("ALTER TABLE report_jobs ADD COLUMN filter_config JSON")
        if "delivery_log" not in cols:
            if dialect_name == "postgresql":
                alters.append("ALTER TABLE report_jobs ADD COLUMN delivery_log JSONB")
            else:
                alters.append("ALTER TABLE report_jobs ADD COLUMN delivery_log JSON")
        with engine.begin() as conn:
            _guard_ddl(conn, dialect_name)
            for sql in alters:
                logger.info("Report builder migration: %s", sql)
                conn.execute(text(sql))

    if not insp.has_table("report_template_extraction_jobs"):
        create_sql = """
        CREATE TABLE report_template_extraction_jobs (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            stage VARCHAR(64),
            progress_pct INTEGER NOT NULL DEFAULT 0,
            template_name VARCHAR(256) NOT NULL,
            source_filename VARCHAR(512),
            source_storage_path VARCHAR(1024),
            vault_object_key VARCHAR(1024),
            source_hash VARCHAR(128),
            extraction_method VARCHAR(64),
            stage_diagnostics JSON,
            template_ast_json JSON,
            blueprint_json JSON,
            semantic_slot_graph_json JSON,
            template_manifest_json JSON,
            extraction_diagnostics_json JSON,
            schema_version VARCHAR(64),
            error_message TEXT,
            created_template_id INTEGER,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
        if dialect_name == "postgresql":
            create_sql = """
            CREATE TABLE report_template_extraction_jobs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                stage VARCHAR(64),
                progress_pct INTEGER NOT NULL DEFAULT 0,
                template_name VARCHAR(256) NOT NULL,
                source_filename VARCHAR(512),
                source_storage_path VARCHAR(1024),
                vault_object_key VARCHAR(1024),
                source_hash VARCHAR(128),
                extraction_method VARCHAR(64),
                stage_diagnostics JSONB,
                template_ast_json JSONB,
                blueprint_json JSONB,
                semantic_slot_graph_json JSONB,
                template_manifest_json JSONB,
                extraction_diagnostics_json JSONB,
                schema_version VARCHAR(64),
                error_message TEXT,
                created_template_id INTEGER REFERENCES report_templates(id),
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
            )
            """
        with engine.begin() as conn:
            _guard_ddl(conn, dialect_name)
            logger.info("Report builder migration: create report_template_extraction_jobs")
            conn.execute(text(create_sql))

    if insp.has_table("report_template_extraction_jobs"):
        cols = {c["name"] for c in insp.get_columns("report_template_extraction_jobs")}
        alters: list[str] = []
        if "stage_diagnostics" not in cols:
            if dialect_name == "postgresql":
                alters.append(
                    "ALTER TABLE report_template_extraction_jobs ADD COLUMN stage_diagnostics JSONB"
                )
            else:
                alters.append(
                    "ALTER TABLE report_template_extraction_jobs ADD COLUMN stage_diagnostics JSON"
                )
        if "vault_object_key" not in cols:
            alters.append(
                "ALTER TABLE report_template_extraction_jobs ADD COLUMN vault_object_key VARCHAR(1024)"
            )
        if "source_hash" not in cols:
            alters.append(
                "ALTER TABLE report_template_extraction_jobs ADD COLUMN source_hash VARCHAR(128)"
            )
        if "extraction_method" not in cols:
            alters.append(
                "ALTER TABLE report_template_extraction_jobs ADD COLUMN extraction_method VARCHAR(64)"
            )
        for col in _EXTRACTION_PACKAGE_JSON_COLUMNS:
            if col not in cols:
                alters.append(
                    f"ALTER TABLE report_template_extraction_jobs ADD COLUMN {col} {_json_type(dialect_name)}"
                )
        if "schema_version" not in cols:
            alters.append(
                "ALTER TABLE report_template_extraction_jobs ADD COLUMN schema_version VARCHAR(64)"
            )
        with engine.begin() as conn:
            _guard_ddl(conn, dialect_name)
            for sql in alters:
                logger.info("Report builder migration: %s", sql)
                conn.execute(text(sql))
