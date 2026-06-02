# Report Builder Architecture

Maps the Report Engine diagram to code in this repository.

## User flow (wizard)

1. **Officer context** — `GET /auth/me` ([`dashboard/app/report-builder/new`](dashboard/app/report-builder/new/page.tsx))
2. **Data source** — `GET /report-builder/ready-analyses` (completed analyses only)
3. **Template** — PDF upload, clone MoSPI default, or pick saved template
4. **Block mapping** — edit AST blocks and `hints.source` before generation
5. **Data filters** — [`report_builder/filter_engine.py`](../report_builder/filter_engine.py)
6. **Generate** — `POST /report-builder/generate` → background [`report_builder/pipeline.py`](../report_builder/pipeline.py)
7. **Canvas & delivery** — [`dashboard/app/report-builder/[jobId]`](dashboard/app/report-builder/[jobId]/page.tsx)

## Pipeline phases

| Phase | Code | Description |
|-------|------|-------------|
| 0 | `report_builder/blueprint.py`, `template_engine/` | PDF → Template AST |
| 1 | `report_builder/knowledge_graph.py` | KG export (Turtle, optional Neo4j) |
| 2 | `report_builder/memory.py` | STM + reflection ledger |
| 3 | `report_builder/kernel.py`, `filter_engine` | Arrow/DuckDB + filters |
| 4–5 | `report_builder/firewall.py`, `agents/` | Scribe + Verifier + consensus |
| 6 | `report_builder/exporter.py` | MoSPI-style PDF |

## Analytics layer

| Engine | Env | Module |
|--------|-----|--------|
| DuckDB (default) | — | `analytics_engine/duckdb_adapter.py` — **use this; no extra cost** |
| ClickHouse | `CLICKHOUSE_URL`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DATABASE` | `analytics_engine/clickhouse_adapter.py` |
| CubeJS (optional paid) | `CUBEJS_API_URL`, `CUBEJS_API_SECRET` | Only if you run Cube; leave unset otherwise |

Default report templates use DuckDB + in-memory pandas. Set block hint `engine` to `duckdb` or `clickhouse` only. Snapshots written under `REPORT_STORAGE_PATH/analytics/`.

## Delivery hub

| Channel | API | Notes |
|---------|-----|-------|
| PDF | `GET /report-builder/jobs/{id}/download` | Existing |
| Email | `POST /report-builder/jobs/{id}/deliver` | Via dashboard `api/internal/send-report` |
| Webhook | Same endpoint, `channel: webhook` | Optional `WEBHOOK_SIGNING_SECRET` HMAC |

## RBAC

Templates and jobs are scoped to the authenticated officer (`user_id` on templates; jobs via dataset ownership).

## Environment variables

See root [`.env.example`](../.env.example) for `CUBEJS_*`, `CLICKHOUSE_*`, `REPORT_DELIVERY_FROM_EMAIL`, `WEBHOOK_SIGNING_SECRET`, `REPORT_TEMPLATE_DIR`.
