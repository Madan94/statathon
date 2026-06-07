#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# vLLM entrypoint — RTX 4050 Laptop (SM89, 6GB VRAM, 24GB RAM)
#
# WHY Qwen2.5-VL-3B-Instruct-AWQ:
#   7B-AWQ (4.65GB) → Marlin repacking peak (2×) exceeds 6GB. Impossible.
#   3B-AWQ (~2.5GB) → Marlin repacking peak (~5GB) fits in 5.7GB free.
#   After load: 2.5GB weights + 3.2GB headroom for KV + activations.
#
# VRAM budget (RTX 4050):
#   Total: 6.0 GiB | Free after driver: ~5.7 GiB
#   AWQ 3B weights (post-repack): ~2.5 GiB
#   KV cache (2048 tok × 1 seq): ~150 MB
#   Vision encoder (fp16 ViT): ~600 MB
#   Activations: ~200 MB
#   Total: ~3.5 GiB → 2.2 GiB headroom ✓
#
# To use 7B on a machine with 8+ GB VRAM:
#   VLLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct-AWQ docker compose ... up sglang
#
# Serves OpenAI-compatible API at /v1/chat/completions
# ─────────────────────────────────────────────────────────────────────────────
set -e

MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-VL-3B-Instruct-AWQ}"
PORT="${VLLM_PORT:-8002}"

echo "═══════════════════════════════════════════════════════════════"
echo "  vLLM Server — Startup Diagnostics"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── GPU Check ────────────────────────────────────────────────────────────────
echo "▶ GPU Detection:"
if ! command -v nvidia-smi &>/dev/null; then
    echo "  ✗ nvidia-smi not found — no GPU access!"
    echo "  → Ensure: docker run --gpus all ..."
    echo "  → WSL2 fix: wsl --shutdown → restart Docker Desktop"
    exit 1
fi

GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
GPU_MEM_TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
GPU_MEM_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
GPU_MEM_USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
DRIVER_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)

echo "  GPU:     ${GPU_NAME:-unknown}"
echo "  VRAM:    ${GPU_MEM_TOTAL:-?} MB total, ${GPU_MEM_FREE:-?} MB free, ${GPU_MEM_USED:-?} MB used"
echo "  Driver:  ${DRIVER_VER:-unknown}"

# FAIL FAST: need at least 5000MB for 3B-AWQ (Marlin repacking spike)
if [ "${GPU_MEM_FREE:-0}" -lt 5000 ]; then
    echo ""
    echo "  ✗ FATAL: Only ${GPU_MEM_FREE}MB free VRAM — need at least 5000MB"
    echo "    → AWQ Marlin repacking needs ~2× weight memory (~5GB peak)"
    echo "    → Close GPU-heavy apps (browsers, games, other models)"
    echo "    → nvidia-smi on host to identify processes"
    echo "    → wsl --shutdown → restart Docker Desktop"
    exit 1
fi
echo "  ✓ OK (${GPU_MEM_FREE}MB free)"
echo ""

# ── Model Cache ──────────────────────────────────────────────────────────────
echo "▶ Model Cache:"
MODEL_DIR="${HF_HOME}/hub/models--$(echo $MODEL | tr '/' '--')"
if [ -d "$MODEL_DIR" ]; then
    MODEL_SIZE=$(du -sh "$MODEL_DIR" 2>/dev/null | cut -f1)
    echo "  ✓ Cached: ${MODEL} (${MODEL_SIZE})"
else
    echo "  ⚠ Not cached — first boot downloads ~2.5GB"
    echo "  → Cached in volume ./model/cache after first run"
fi
echo ""

# ── Launch Config ────────────────────────────────────────────────────────────
echo "▶ Configuration:"
echo "  Model:          ${MODEL}"
echo "  Port:           ${PORT}"
echo "  GPU mem util:   0.90 → $(echo "${GPU_MEM_TOTAL:-6144} * 90 / 100" | bc 2>/dev/null || echo "~5530") MB"
echo "  Max model len:  4096 tokens"
echo "  Max num seqs:   1"
echo "  Enforce eager:  yes"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Launching vLLM..."
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── Launch vLLM ──────────────────────────────────────────────────────────────
# Qwen2.5-VL-3B-Instruct-AWQ (4-bit, ~2.5 GB weights):
#   0.90 × 6.0 = 5.40 GiB budget
#   AWQ weights (post-Marlin repack): ~2.5 GiB
#   Vision encoder (fp16 ViT): ~600 MB
#   KV cache (4096 tok × 1 seq): ~150 MB
#   Activations: ~200 MB
#   Total: ~3.5 GiB → 1.9 GiB headroom ✓
#   Marlin repacking peak (transient): ~5.0 GiB < 5.7 GiB free ✓
#
# ATTENTION BACKEND: FlashAttention JIT-compiles for SM89 on first run (2-7 min).
# If stuck >10min, override with: VLLM_ATTENTION_BACKEND=FLASHINFER or XFORMERS
# e.g.: docker run -e VLLM_ATTENTION_BACKEND=XFORMERS ...
VLLM_ATTENTION_BACKEND="${VLLM_ATTENTION_BACKEND:-}"
EXTRA_ARGS=""
if [ -n "$VLLM_ATTENTION_BACKEND" ]; then
    echo "  ▶ Attention backend override: ${VLLM_ATTENTION_BACKEND}"
    export VLLM_ATTENTION_BACKEND
fi

# SAFE FLAGS (verified on vllm/vllm-openai:latest v0.22.1):
exec python3 -m vllm.entrypoints.openai.api_server \
    --model "${MODEL}" \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --gpu-memory-utilization 0.90 \
    --max-model-len 4096 \
    --enforce-eager \
    --max-num-seqs 1 \
    --limit-mm-per-prompt '{"image": 1}' \
    --trust-remote-code \
    --download-dir "${HF_HOME}"
