#!/usr/bin/env bash
# Stop Neo4j + Redis started by scripts/start-infra.sh
# Run from repo root: bash scripts/stop-infra.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found."
  exit 1
fi

DOCKER=(docker)
if ! docker info >/dev/null 2>&1; then
  if sudo -n docker info >/dev/null 2>&1; then
    DOCKER=(sudo docker)
  else
    echo "Docker daemon not accessible. Run in your terminal:"
    echo "  sudo bash scripts/stop-infra.sh"
    exit 1
  fi
fi

stop_if_exists() {
  local name="$1"
  if "${DOCKER[@]}" ps -a --format '{{.Names}}' | grep -qx "$name"; then
    "${DOCKER[@]}" stop "$name" >/dev/null
    echo "Stopped: $name"
  else
    echo "Not found (skipped): $name"
  fi
}

stop_if_exists statathon-neo4j
stop_if_exists statathon-redis

echo ""
echo "Infrastructure stopped. API will show Neo4j connection warnings until you start again or set NEO4J_ENABLED=false."
