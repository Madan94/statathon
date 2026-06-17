# Bootstrap Statathon schema against DATABASE_URL (use after RDS tunnel is up).
# Usage (from repo root):
#   .\scripts\aws\bootstrap_rds_schema.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $RepoRoot

Write-Host "Bootstrapping schema using DATABASE_URL from .env ..."
python scripts/migrate_db.py --bootstrap
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python scripts/migrate_db.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Push-Location api
python -c @"
from database.database import engine, Base
import database.models
from database.migrate_drop_weight_application import migrate_drop_weight_application_schema
from database.migrate_schema_graph_edges import migrate_schema_graph_edges_schema
from database.migrate_column_dictionary import migrate_column_dictionary_schema
from database.migrate_perf_indexes import migrate_perf_indexes
Base.metadata.create_all(bind=engine)
migrate_drop_weight_application_schema()
migrate_schema_graph_edges_schema()
migrate_column_dictionary_schema()
migrate_perf_indexes()
print('startup migrations OK')
"@
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { exit $code }

python scripts/verify_db_connection.py
exit $LASTEXITCODE
