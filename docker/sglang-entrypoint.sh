#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# vLLM entrypoint — runtime diagnostics + VRAM-optimized launch
# Target: RTX 4050 Laptop (SM89, 6GB VRAM, 24GB RAM)
#
# VRAM BUDGET ANALYSIS (validated for 6GB laptop GPUs):
#   Total VRAM:           6144 MB
#   WSL2 display driver:  ~500 MB (less than native Windows desktop)
#   Available for vLLM:   ~5644 MB
#
#   Qwen2.5-VL-7B-AWQ breakdown:
#     Vision encoder (ViT, NOT quantized, fp16):  ~1200 MB
#     Language model (AWQ 4-bit Marlin):          ~3500 MB
#     KV cache (1024 tokens, 28 layers):          ~150 MB
#     Activation memory:                          ~200 MB
#     TOTAL:                                      ~5050 MB
#
#   gpu_memory_utilization = 0.88 → 6144 × 0.88 = 5407 MB
#   Headroom: 5407 - 5050 = ~357 MB (safe margin)
#   swap-space = 4 GB (overflow KV blocks → host RAM, user has 24GB)
#
# Serves OpenAI-compatible API at /v1/chat/completions
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
    GPU_MEM_TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
    GPU_MEM_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
    GPU_MEM_USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
    DRIVER_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
    echo "  GPU:     ${GPU_NAME:-unknown}"
    echo "  VRAM:    ${GPU_MEM_TOTAL:-?} MB total, ${GPU_MEM_FREE:-?} MB free, ${GPU_MEM_USED:-?} MB used"
    echo "  Driver:  ${DRIVER_VER:-unknown}"

    # FAIL FAST: if less than 4500MB free, model won't fit
    if [ "${GPU_MEM_FREE:-0}" -lt 4500 ]; then
        echo ""
        echo "  ✗ FATAL: Only ${GPU_MEM_FREE}MB free VRAM — need at least 4500MB"
        echo "    → Close GPU-heavy apps (browsers with HW accel, games, other models)"
        echo "    → Run: nvidia-smi on host to see what's using VRAM"
        echo "    → WSL2 fix: wsl --shutdown → restart Docker Desktop"
        exit 1
    fi
    echo "  ✓ Sufficient VRAM (${GPU_MEM_FREE}MB free, need ~5000MB)"
else
    echo "  ✗ nvidia-smi not found — no GPU access!"
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
    echo "  → Fast start (no download needed)"
else
    echo "  ⚠ Not cached: ${MODEL}"
    echo "  → First boot downloads ~4GB. Subsequent boots instant."
    echo "  → Volume: ./model/cache:/cache"
fi
echo ""

# ── Configuration ────────────────────────────────────────────────────────────
echo "▶ Launch Configuration:"
echo "  Model:            ${MODEL}"
echo "  Port:             ${PORT}"
echo "  GPU mem util:     0.88 (5407 MB of ${GPU_MEM_TOTAL:-6144} MB)"
echo "  Max model len:    1024 tokens (minimal KV cache for page-by-page)"
echo "  Max num seqs:     1 (sequential processing)"
echo "  Swap space:       4 GB (KV overflow → host RAM)"
echo "  Enforce eager:    yes (saves ~500MB vs CUDA graphs)"
echo "  MM limit:         1 image per prompt"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Launching vLLM server..."
echo "  If it hangs here >120s: reduce --gpu-memory-utilization to 0.85"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── Launch vLLM ──────────────────────────────────────────────────────────────
# Key flags explained:
#   --gpu-memory-utilization 0.88  → use 88% of 6GB = 5.4GB (fits weights + minimal KV)
#   --max-model-len 1024           → tiny KV cache (we process 1 page at a time)
#   --enforce-eager                → no CUDA graphs (saves ~500MB)
#   --max-num-seqs 1               → only 1 concurrent request (saves KV slots)
#   --swap-space 4                 → 4GB host RAM for KV cache overflow
#   --limit-mm-per-prompt JSON     → 1 image per request (page-by-page extraction)
#   --dtype half                   → force fp16 (some configs default to bf16 which can be slower)
#   --trust-remote-code            → needed for Qwen2.5-VL processor
#   --download-dir                 → persistent cache volume
exec python3 -m vllm.entrypoints.openai.api_server \
    --model "${MODEL}" \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --gpu-memory-utilization 0.88 \
    --max-model-len 1024 \
    --enforce-eager \
    --max-num-seqs 1 \
    --swap-space 4 \
    --limit-mm-per-prompt '{"image": 1}' \
    --dtype half \
    --trust-remote-code \
    --download-dir "${HF_HOME}"
