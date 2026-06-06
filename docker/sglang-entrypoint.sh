#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# SGLang entrypoint — runtime diagnostics + graceful startup
# RTX 4050 Laptop: SM89, 6GB VRAM, 24GB RAM
# ─────────────────────────────────────────────────────────────────────────────
set -e

echo "═══════════════════════════════════════════════════════════════"
echo "  SGLang Server — Startup Diagnostics"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── GPU Check ────────────────────────────────────────────────────────────────
echo "▶ GPU Detection:"
if command -v nvidia-smi &>/dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1)
    GPU_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader 2>/dev/null | head -1)
    CUDA_DRIVER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
    echo "  ✓ GPU: ${GPU_NAME:-unknown}"
    echo "  ✓ VRAM: ${GPU_MEM:-unknown} (free: ${GPU_FREE:-unknown})"
    echo "  ✓ Driver: ${CUDA_DRIVER:-unknown}"
    
    # Check if another process is using GPU (ColPali still running?)
    GPU_USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
    if [ "${GPU_USED:-0}" -gt 500 ]; then
        echo "  ⚠ WARNING: ${GPU_USED}MB VRAM already in use!"
        echo "    → Is ColPali still running? Stop it first."
        echo "    → Continuing anyway (may OOM)..."
    fi
else
    echo "  ✗ nvidia-smi not found — GPU not available"
    echo "  → Ensure: docker run --gpus all ..."
    echo "  → WSL2: run 'wsl --shutdown' then restart Docker if GPU adapter lost"
    exit 1
fi
echo ""

# ── Model Cache Check ────────────────────────────────────────────────────────
echo "▶ Model Cache:"
MODEL_DIR="${HF_HOME}/hub/models--$(echo $SGLANG_MODEL | tr '/' '--')"
if [ -d "$MODEL_DIR" ]; then
    MODEL_SIZE=$(du -sh "$MODEL_DIR" 2>/dev/null | cut -f1)
    echo "  ✓ Cached: ${SGLANG_MODEL} (${MODEL_SIZE})"
    echo "  → Fast start (no download)"
else
    echo "  ⚠ Not cached: ${SGLANG_MODEL}"
    echo "  → First boot downloads ~3-5GB. Subsequent boots instant."
    echo "  → Ensure volume mount: -v ./model/cache:/cache"
fi
echo ""

# ── Configuration ────────────────────────────────────────────────────────────
echo "▶ Configuration:"
echo "  Model:        ${SGLANG_MODEL}"
echo "  Port:         ${SGLANG_PORT}"
echo "  Mem fraction: ${SGLANG_MEM_FRACTION_STATIC}"
echo "  VRAM budget:  ~$((6 * ${SGLANG_MEM_FRACTION_STATIC%.*}))GB of 6GB"
echo ""

# ── Determine launch flags ───────────────────────────────────────────────────
EXTRA_ARGS=""

# For 6GB VRAM: disable features that consume extra memory
EXTRA_ARGS="${EXTRA_ARGS} --disable-cuda-graph"
# Chunked prefill reduces peak VRAM during long prompts
EXTRA_ARGS="${EXTRA_ARGS} --chunked-prefill-size 2048"
# Limit concurrent requests to avoid OOM on 6GB
EXTRA_ARGS="${EXTRA_ARGS} --max-running-requests 2"

echo "▶ Extra flags: ${EXTRA_ARGS}"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Launching SGLang server..."
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── Launch ───────────────────────────────────────────────────────────────────
exec python -m sglang.launch_server \
    --model-path "${SGLANG_MODEL}" \
    --host 0.0.0.0 \
    --port "${SGLANG_PORT}" \
    --mem-fraction-static "${SGLANG_MEM_FRACTION_STATIC}" \
    --tp 1 \
    ${EXTRA_ARGS}
