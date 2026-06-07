#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# vLLM entrypoint — runtime diagnostics + VRAM-optimized launch
# RTX 4050 Laptop: SM89, 6GB VRAM, 24GB RAM
#
# Serves OpenAI-compatible API at /v1/chat/completions
# Drop-in replacement for SGLang — same API contract
# ─────────────────────────────────────────────────────────────────────────────
set -e

MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct-AWQ}"
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
echo "  Max model len:  2048 (vision model needs more VRAM for image tokens)"
echo "  GPU mem util:   0.70 (reserves 4.20GB — safe for 6GB cards)"
echo "  Enforce eager:  yes (saves VRAM vs CUDA graphs)"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Launching vLLM server..."
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── Launch vLLM ──────────────────────────────────────────────────────────────
# VRAM Budget (RTX 4050/3050 Laptop, 6GB total):
#   Display driver uses ~1.05GB → only 4.95GB free
#   gpu_memory_utilization is % of TOTAL (6GB), not FREE (4.95GB)
#   So: 0.70 × 6.0 = 4.20GB requested (safe margin for 6GB cards)
#   Qwen2.5-VL-7B-AWQ ~3.5GB weights + KV cache ~0.5GB = 4.0GB
#
#   --gpu-memory-utilization 0.70  → reserve 4.20GB (safe for 6GB GPUs)
#   --max-model-len 2048           → caps KV cache size (prevents 4096 default)
#   --enforce-eager                → disables CUDA graphs (saves ~500MB VRAM)
#   --max-num-seqs 1               → single request (saves KV cache memory)
#   --limit-mm-per-prompt image=1  → one image per request (page-by-page)
#   NOTE: No --quantization flag needed — vLLM auto-detects from model config
exec python3 -m vllm.entrypoints.openai.api_server \
    --model "${MODEL}" \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --gpu-memory-utilization 0.70 \
    --max-model-len 2048 \
    --enforce-eager \
    --max-num-seqs 1 \
    --limit-mm-per-prompt "image=1" \
    --trust-remote-code \
    --download-dir "${HF_HOME}"
