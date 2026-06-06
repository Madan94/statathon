#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# vLLM entrypoint — runtime diagnostics + VRAM-optimized launch
# RTX 4050 Laptop: SM89, 6GB VRAM, 24GB RAM
#
# Serves OpenAI-compatible API at /v1/chat/completions
# Drop-in replacement for SGLang — same API contract
# ─────────────────────────────────────────────────────────────────────────────
set -e

MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-3B-Instruct}"
PORT="${VLLM_PORT:-8002}"

echo "═══════════════════════════════════════════════════════════════"
echo "  vLLM Server — Startup Diagnostics"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── GPU Check ────────────────────────────────────────────────────────────────
echo "▶ GPU Detection:"
if command -v nvidia-smi &>/dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1)
    GPU_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader 2>/dev/null | head -1)
    DRIVER_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
    echo "  ✓ GPU: ${GPU_NAME:-unknown}"
    echo "  ✓ VRAM: ${GPU_MEM:-unknown} (free: ${GPU_FREE:-unknown})"
    echo "  ✓ Driver: ${DRIVER_VER:-unknown}"

    # Warn if GPU already in use (ColPali not stopped?)
    GPU_USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
    if [ "${GPU_USED:-0}" -gt 500 ]; then
        echo "  ⚠ WARNING: ${GPU_USED}MB VRAM already in use!"
        echo "    → Is ColPali still running? Stop it first for sequential mode."
    fi
else
    echo "  ✗ nvidia-smi not found"
    echo "  → Ensure: docker run --gpus all ..."
    echo "  → WSL2 fix: wsl --shutdown → restart Docker Desktop"
    exit 1
fi
echo ""

# ── Model Cache Check ────────────────────────────────────────────────────────
echo "▶ Model Cache:"
MODEL_DIR="${HF_HOME}/hub/models--$(echo $MODEL | tr '/' '--')"
if [ -d "$MODEL_DIR" ]; then
    MODEL_SIZE=$(du -sh "$MODEL_DIR" 2>/dev/null | cut -f1)
    echo "  ✓ Cached: ${MODEL} (${MODEL_SIZE})"
    echo "  → Fast start (no download)"
else
    echo "  ⚠ Not cached: ${MODEL}"
    echo "  → First boot downloads ~3GB. Subsequent boots instant."
    echo "  → Ensure volume: -v ./model/cache:/cache"
fi
echo ""

# ── Configuration ────────────────────────────────────────────────────────────
echo "▶ Configuration:"
echo "  Model:          ${MODEL}"
echo "  Port:           ${PORT}"
echo "  Max model len:  4096 (fits in 6GB VRAM)"
echo "  GPU mem util:   0.85 (leaves 900MB for system)"
echo "  Enforce eager:  yes (saves VRAM vs CUDA graphs)"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Launching vLLM server..."
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── Launch vLLM ──────────────────────────────────────────────────────────────
# Key flags for 6GB VRAM:
#   --gpu-memory-utilization 0.85  → use 85% of 6GB = 5.2GB (leaves headroom)
#   --max-model-len 4096           → limits KV cache size (big context = more VRAM)
#   --enforce-eager                → disables CUDA graphs (saves ~500MB VRAM)
#   --dtype half                   → FP16 (3B model = ~6GB in FP32, ~3GB in FP16)
#   --max-num-seqs 2               → max 2 concurrent requests (prevents OOM)
exec python3 -m vllm.entrypoints.openai.api_server \
    --model "${MODEL}" \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --gpu-memory-utilization 0.85 \
    --max-model-len 4096 \
    --enforce-eager \
    --dtype half \
    --max-num-seqs 2 \
    --trust-remote-code \
    --download-dir "${HF_HOME}"
