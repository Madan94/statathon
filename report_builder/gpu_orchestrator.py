"""Sequential GPU Orchestrator — manages Docker containers for 6GB VRAM constraint.

On a 6GB GPU, ColPali (~4GB) and SGLang (~5GB) CANNOT coexist.
This module starts/stops them sequentially during extraction:

    1. Ensure ColPali is up (warm) → extract PDF pages → stop ColPali
    2. Ensure SGLang is up (warm) → compile AST from pages → stop SGLang
    3. Return final TemplateAST

This runs when PIPELINE_GPU_MODE=sequential (default on GPU laptops).
When PIPELINE_GPU_MODE=concurrent (big GPU) or PIPELINE_GPU_MODE=gemini_only,
the old behavior (ColPali + Gemini fallback) is used.

Environment variables:
    PIPELINE_GPU_MODE        = sequential | concurrent | gemini_only (default: gemini_only)
    GPU_COMPOSE_FILE         = path to docker-compose.gpu.yml (default: ./docker-compose.gpu.yml)
    COLPALI_ENDPOINT         = http://localhost:8001
    SGLANG_ENDPOINT          = http://localhost:8002
    COLPALI_WARMUP_TIMEOUT   = seconds to wait for ColPali health (default: 180)
    SGLANG_WARMUP_TIMEOUT    = seconds to wait for SGLang health (default: 240)
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

_COMPOSE_FILE = os.getenv("GPU_COMPOSE_FILE", "./docker-compose.gpu.yml")
_COLPALI_ENDPOINT = os.getenv("COLPALI_ENDPOINT", "http://localhost:8001")
_SGLANG_ENDPOINT = os.getenv("SGLANG_ENDPOINT", "http://localhost:8002")


class GPUServiceError(RuntimeError):
    """Raised when a GPU Docker service fails to start or respond."""
    pass


def _compose_cmd(*args: str) -> list[str]:
    """Build docker compose command list."""
    return ["docker", "compose", "-f", _COMPOSE_FILE, "--profile", "gpu", *args]


def _run_compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a docker compose command, log it."""
    cmd = _compose_cmd(*args)
    logger.info("[gpu-orch] ▶ %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0 and check:
        logger.error("[gpu-orch] ✗ command failed: %s", result.stderr.strip()[:500])
    return result


def _wait_for_health(url: str, service_name: str, timeout_s: int) -> bool:
    """Poll health endpoint until OK or timeout."""
    health_url = url.rstrip("/") + "/health"
    deadline = time.monotonic() + timeout_s
    attempt = 0
    logger.info(
        "[gpu-orch] ⏱ waiting for %s health at %s   timeout=%ds",
        service_name, health_url, timeout_s,
    )
    while time.monotonic() < deadline:
        attempt += 1
        try:
            r = requests.get(health_url, timeout=5)
            if r.status_code == 200:
                elapsed = timeout_s - (deadline - time.monotonic())
                logger.info(
                    "[gpu-orch] ✓ %s healthy   attempt=%d   elapsed=%.1fs",
                    service_name, attempt, elapsed,
                )
                return True
        except Exception:
            pass
        time.sleep(3)
    logger.error("[gpu-orch] ✗ %s failed to become healthy within %ds", service_name, timeout_s)
    return False


def _is_service_healthy(endpoint: str) -> bool:
    """Quick check if service is already responding."""
    try:
        r = requests.get(endpoint.rstrip("/") + "/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def ensure_colpali_up() -> bool:
    """Start ColPali container and wait for health. Returns True if healthy."""
    if _is_service_healthy(_COLPALI_ENDPOINT):
        logger.info("[gpu-orch] ✓ ColPali already healthy")
        return True
    _run_compose("up", "-d", "colpali", check=False)
    timeout = int(os.getenv("COLPALI_WARMUP_TIMEOUT", "180"))
    return _wait_for_health(_COLPALI_ENDPOINT, "ColPali", timeout)


def stop_colpali() -> None:
    """Stop ColPali container to free VRAM."""
    logger.info("[gpu-orch] ▶ stopping ColPali (freeing VRAM)")
    _run_compose("stop", "colpali", check=False)
    time.sleep(2)  # brief pause for GPU memory release


def ensure_sglang_up() -> bool:
    """Start SGLang container and wait for health. Returns True if healthy."""
    if _is_service_healthy(_SGLANG_ENDPOINT):
        logger.info("[gpu-orch] ✓ SGLang already healthy")
        return True
    _run_compose("up", "-d", "sglang", check=False)
    timeout = int(os.getenv("SGLANG_WARMUP_TIMEOUT", "240"))
    return _wait_for_health(_SGLANG_ENDPOINT, "SGLang", timeout)


def stop_sglang() -> None:
    """Stop SGLang container to free VRAM."""
    logger.info("[gpu-orch] ▶ stopping SGLang (freeing VRAM)")
    _run_compose("stop", "sglang", check=False)


def extract_with_colpali(pdf_path: str | Path) -> list[dict[str, Any]] | None:
    """Start ColPali → POST PDF → return pages → stop ColPali.

    Returns page summaries list or None on failure.
    """
    path = Path(pdf_path)
    if not path.exists():
        logger.error("[gpu-orch] PDF not found: %s", path)
        return None

    file_size_kb = path.stat().st_size / 1024
    logger.info(
        "[gpu-orch] ───────────────────────────────────────────────────────"
    )
    logger.info(
        "[gpu-orch] ▶ PHASE 1: ColPali Vision Extraction"
    )
    logger.info(
        "[gpu-orch]   file=%s   size=%.1f KB", path.name, file_size_kb
    )

    if not ensure_colpali_up():
        logger.error("[gpu-orch] ✗ ColPali failed to start — aborting extraction")
        return None

    # Send the PDF
    colpali_url = _COLPALI_ENDPOINT.rstrip("/") + "/extract"
    timeout = int(os.getenv("COLPALI_TIMEOUT", "300"))
    t0 = time.monotonic()
    try:
        with open(path, "rb") as f:
            r = requests.post(colpali_url, files={"file": f}, timeout=timeout)
        r.raise_for_status()
        body = r.json()
        pages = body.get("pages") or []
        vision_ok = body.get("vision_pass")
        elapsed = time.monotonic() - t0

        if vision_ok is False:
            logger.warning(
                "[gpu-orch] ⚠ ColPali returned pages BUT vision_pass=false: %s",
                body.get("vision_error", "unknown"),
            )
        logger.info(
            "[gpu-orch] ✓ ColPali extracted   pages=%d   vision=%s   elapsed=%.1fs",
            len(pages), "✓" if vision_ok else "✗" if vision_ok is False else "?", elapsed,
        )
        return pages if pages else None
    except Exception as exc:
        elapsed = time.monotonic() - t0
        logger.error("[gpu-orch] ✗ ColPali extraction failed: %s   elapsed=%.1fs", exc, elapsed)
        return None
    finally:
        stop_colpali()


def compile_with_sglang(page_summaries: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Start SGLang → compile AST → return blocks → stop SGLang.

    Returns list of raw block dicts or None on failure.
    """
    import json as _json
    import re

    logger.info(
        "[gpu-orch] ───────────────────────────────────────────────────────"
    )
    logger.info(
        "[gpu-orch] ▶ PHASE 2: SGLang AST Compilation"
    )
    logger.info(
        "[gpu-orch]   pages=%d", len(page_summaries)
    )

    if not ensure_sglang_up():
        logger.error("[gpu-orch] ✗ SGLang failed to start — will fall back to Gemini")
        return None

    endpoint = _SGLANG_ENDPOINT
    model = os.getenv("SGLANG_MODEL", "Qwen/Qwen2.5-3B-Instruct")
    prompt = (
        "You compile statistical-report PDFs into structured block ASTs.\n"
        "Output ONLY a JSON array. Each item must have: "
        "block_id (slug), kind (narrative|table|chart|metric|heading), "
        "title (short string), section (slug), required (bool), "
        "hints (object with at least page_index).\n\n"
        f"PAGES:\n{_json.dumps(page_summaries)[:8000]}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You compile statistical-report PDFs into block ASTs."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }
    timeout = int(os.getenv("SGLANG_TIMEOUT", "180"))
    t0 = time.monotonic()
    try:
        logger.info(
            "[gpu-orch] ▶ SGLang POST   model=%s   timeout=%ds", model, timeout
        )
        r = requests.post(
            f"{endpoint.rstrip('/')}/v1/chat/completions",
            json=payload,
            timeout=timeout,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
        data = _json.loads(content)
        if isinstance(data, dict):
            data = data.get("blocks") or data.get("items") or []
        elapsed = time.monotonic() - t0
        logger.info(
            "[gpu-orch] ✓ SGLang compiled   blocks=%d   elapsed=%.1fs",
            len(data) if isinstance(data, list) else 0, elapsed,
        )
        return data if isinstance(data, list) and data else None
    except Exception as exc:
        elapsed = time.monotonic() - t0
        logger.error("[gpu-orch] ✗ SGLang compilation failed: %s   elapsed=%.1fs", exc, elapsed)
        return None
    finally:
        stop_sglang()


def get_pipeline_mode() -> str:
    """Return current pipeline GPU mode from env."""
    return os.getenv("PIPELINE_GPU_MODE", "gemini_only").strip().lower()
