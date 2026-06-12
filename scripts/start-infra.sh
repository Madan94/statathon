#!/usr/bin/env bash
# Start Neo4j + Redis for local dev (no Docker Compose plugin required).
# Run from repo root: bash scripts/start-infra.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found. Install Docker Engine first."
  exit 1
fi

DOCKER=(docker)
if ! docker info >/dev/null 2>&1; then
  if sudo -n docker info >/dev/null 2>&1; then
    DOCKER=(sudo docker)
    echo "Using sudo for Docker (passwordless sudo configured)."
  else
    echo "Docker daemon not accessible for user $(whoami)."
    echo "Run this script in your terminal (sudo will prompt for password):"
    echo "  sudo bash scripts/start-infra.sh"
    echo ""
    echo "Permanent fix (then log out/in):"
    echo "  sudo usermod -aG docker \"\$USER\""
    exit 1
  fi
fi

NEO4J_PASSWORD="password"
if [[ -f .env ]]; then
  val="$(grep -E '^NEO4J_PASSWORD=' .env | head -1 | cut -d= -f2- || true)"
  if [[ -n "$val" ]]; then
    NEO4J_PASSWORD="$val"
  fi
fi

start_or_create() {
  local name="$1"
  shift
  if "${DOCKER[@]}" ps -a --format '{{.Names}}' | grep -qx "$name"; then
    "${DOCKER[@]}" start "$name" >/dev/null
    echo "Started existing container: $name"
  else
    "${DOCKER[@]}" run -d --name "$name" "$@" >/dev/null
    echo "Created container: $name"
  fi
}

start_or_create statathon-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e "NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}" \
  neo4j:5

start_or_create statathon-redis \
  -p 6379:6379 \
  redis:7-alpine

echo ""
echo "Infrastructure ready:"
echo "  Neo4j browser: http://localhost:7474  (user: neo4j, password from .env)"
echo "  Neo4j bolt:    bolt://localhost:7687"
echo "  Redis:         redis://localhost:6379/0"
echo ""
echo "Restart the API so Neo4j schema bootstrap reconnects."
