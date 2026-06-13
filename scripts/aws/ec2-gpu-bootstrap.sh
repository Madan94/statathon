#!/usr/bin/env bash
# Bootstrap g5.xlarge (or any NVIDIA GPU EC2) for ColPali + SGLang sidecars.
# Run on the EC2 instance after cloning the repo (via SSM Session Manager).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

export GPU_MODEL_CACHE="${GPU_MODEL_CACHE:-/data/model/cache}"
sudo mkdir -p "$GPU_MODEL_CACHE" ./data
sudo chown -R "$(whoami):$(whoami)" "$GPU_MODEL_CACHE" 2>/dev/null || true

echo "==> Checking NVIDIA driver"
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi not found. Use Deep Learning AMI or install NVIDIA drivers."
  exit 1
fi
nvidia-smi

echo "==> Checking Docker + NVIDIA Container Toolkit"
if ! docker info 2>/dev/null | grep -qi nvidia; then
  echo "Install NVIDIA Container Toolkit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
fi

echo "==> Building GPU images (first run may take 20+ minutes)"
docker compose -f docker-compose.gpu.yml --profile gpu build colpali sglang

echo "==> Starting ColPali + SGLang"
docker compose -f docker-compose.gpu.yml --profile gpu up -d colpali sglang

echo "==> Waiting for health (up to 30 min on first model download)"
deadline=$((SECONDS + 1800))
until [ "$SECONDS" -ge "$deadline" ]; do
  col_ok=0
  sg_ok=0
  curl -sf http://localhost:8100/health >/dev/null 2>&1 && col_ok=1
  curl -sf http://localhost:30000/health >/dev/null 2>&1 && sg_ok=1
  if [ "$col_ok" -eq 1 ] && [ "$sg_ok" -eq 1 ]; then
    echo "Both services healthy."
    curl -s http://localhost:8100/health
    curl -s http://localhost:30000/health
    nvidia-smi
    exit 0
  fi
  echo "  waiting... colpali=$col_ok sglang=$sg_ok ($(date -Iseconds))"
  sleep 30
done

echo "Health check timed out. Logs:"
docker compose -f docker-compose.gpu.yml --profile gpu logs --tail 40 colpali sglang
exit 1
