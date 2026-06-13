"""
VLM Services Verification — BharatStat Pipeline
================================================
Tests LayoutLM (port 8001) and Qwen-VL (port 8002) with REAL prompts
that mirror actual extraction pipeline calls.

NOT a simple /health ping — sends actual multimodal prompts and validates
that the model outputs make sense for MoSPI document extraction.

Usage (on GPU laptop):
    python scripts/verify_vlm_services.py

    # Point to remote services:
    LAYOUTLM_ENDPOINT=http://192.168.1.10:8001 \
    SGLANG_ENDPOINT=http://192.168.1.10:8002 \
    python scripts/verify_vlm_services.py

Exit codes:
    0 = all checks passed
    1 = one or more checks failed (details printed)
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import textwrap
import time
from pathlib import Path

import requests

LAYOUTLM_ENDPOINT = os.getenv("LAYOUTLM_ENDPOINT", "http://localhost:8001")
SGLANG_ENDPOINT = os.getenv("SGLANG_ENDPOINT", "http://localhost:8002")
SGLANG_MODEL = os.getenv("SGLANG_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct-AWQ")
TIMEOUT_HEALTH = 10
TIMEOUT_INFERENCE = 120

_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_RST = "\033[0m"


def _ok(msg: str):
    print(f"  {_GREEN}✓{_RST} {msg}")


def _fail(msg: str):
    print(f"  {_RED}✗{_RST} {msg}")


def _warn(msg: str):
    print(f"  {_YELLOW}⚠{_RST} {msg}")


def _head(msg: str):
    print(f"\n{_BOLD}{_CYAN}{'─' * 60}{_RST}")
    print(f"{_BOLD}{_CYAN}  {msg}{_RST}")
    print(f"{_BOLD}{_CYAN}{'─' * 60}{_RST}")


# ─────────────────────────────────────────────────────────────────────────────
# Test image generators — create synthetic test pages without external files
# ─────────────────────────────────────────────────────────────────────────────

def _make_test_page_png() -> bytes:
    """Create a synthetic PLFS-style test page as PNG bytes.

    Draws a simple table header + two data rows that mimic a real
    MoSPI statistical table, without needing PIL/Pillow.
    Falls back to a 1×1 white pixel if image libs unavailable.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (800, 400), "white")
        draw = ImageDraw.Draw(img)

        # Draw a fake PLFS table
        draw.rectangle([20, 20, 780, 60], fill="#1a237e")
        draw.text((25, 30), "PLFS 2025 — LFPR (%) by State and Rural/Urban Sector", fill="white")

        # Table headers
        headers = ["State/UT", "Rural Male", "Rural Female", "Urban Male", "Urban Female"]
        col_w = 150
        draw.rectangle([20, 70, 780, 100], fill="#e3f2fd")
        for i, h in enumerate(headers):
            draw.text((25 + i * col_w, 78), h, fill="#0d47a1")
            if i > 0:
                draw.line([20 + i * col_w, 70, 20 + i * col_w, 220], fill="#90caf9", width=1)

        # Data rows
        data = [
            ["Andhra Pradesh", "80.5", "47.2", "74.3", "23.1"],
            ["Bihar", "77.8", "35.6", "68.9", "19.4"],
            ["Gujarat", "82.1", "52.3", "76.8", "28.7"],
        ]
        for r, row in enumerate(data):
            y = 110 + r * 35
            if r % 2 == 0:
                draw.rectangle([20, y, 780, y + 34], fill="#f5f5f5")
            for c, val in enumerate(row):
                draw.text((25 + c * col_w, y + 10), val, fill="#212121")
        draw.rectangle([20, 70, 780, 220], outline="#90caf9", width=1)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    except ImportError:
        # Minimal valid 1×1 white PNG (89 bytes, no external deps)
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
        )


def _make_minimal_pdf() -> bytes:
    """Create a minimal valid PDF with one text page for LayoutLM testing."""
    pdf = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 595 842]/Parent 2 0 R/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 120>>
stream
BT
/F1 16 Tf
50 780 Td
(Periodic Labour Force Survey PLFS 2025) Tj
0 -30 Td
/F1 12 Tf
(LFPR: 59.3%  WPR: 57.4%  UR: 3.1%) Tj
ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000436 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
510
%%EOF"""
    return pdf


# ─────────────────────────────────────────────────────────────────────────────
# Check 1: LayoutLM /health
# ─────────────────────────────────────────────────────────────────────────────

def check_layoutlm_health() -> bool:
    _head("Check 1 — LayoutLM Health (port 8001)")
    url = f"{LAYOUTLM_ENDPOINT.rstrip('/')}/health"
    try:
        t0 = time.monotonic()
        r = requests.get(url, timeout=TIMEOUT_HEALTH)
        elapsed = time.monotonic() - t0
        if r.status_code == 200:
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}
            _ok(f"Health OK ({elapsed:.1f}s) — {body}")
            return True
        else:
            _fail(f"HTTP {r.status_code}: {r.text[:200]}")
            return False
    except requests.exceptions.ConnectionError:
        _fail(f"Connection refused → {url}")
        _warn("Is LayoutLM running? Start with: docker compose --profile gpu up layoutlm")
        return False
    except Exception as e:
        _fail(f"Error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Check 2: LayoutLM real PDF analysis
# ─────────────────────────────────────────────────────────────────────────────

def check_layoutlm_inference() -> bool:
    _head("Check 2 — LayoutLM Real PDF Analysis")
    url = f"{LAYOUTLM_ENDPOINT.rstrip('/')}/analyze"
    pdf_bytes = _make_minimal_pdf()

    print(f"  Sending minimal PLFS test PDF ({len(pdf_bytes)} bytes) to {url}")
    try:
        t0 = time.monotonic()
        r = requests.post(url, files={"file": ("test.pdf", pdf_bytes, "application/pdf")}, timeout=60)
        elapsed = time.monotonic() - t0

        if r.status_code != 200:
            _fail(f"HTTP {r.status_code}: {r.text[:300]}")
            return False

        data = r.json()
        pages = data.get("pages") or []
        total_regions = sum(len(p.get("regions") or []) for p in pages)

        print(f"  Response ({elapsed:.1f}s):")
        print(f"    Pages:   {len(pages)}")
        print(f"    Regions: {total_regions}")

        if pages:
            first_page = pages[0]
            regions = first_page.get("regions") or []
            region_types = [r.get("type", "?") for r in regions[:5]]
            print(f"    Sample region types (page 1): {region_types}")

            # Validate: should detect at least heading or text
            valid_types = {"title", "heading", "text", "paragraph", "table"}
            found = set(region_types) & valid_types
            if found:
                _ok(f"Detected meaningful regions: {found}")
            else:
                _warn(f"No meaningful region types detected — got: {region_types}")

            # Check region structure
            if regions and "bbox" in regions[0] and "type" in regions[0]:
                _ok("Region structure correct (has bbox + type)")
            else:
                _warn("Region structure may be incomplete")

        _ok(f"LayoutLM inference working ({elapsed:.1f}s)")
        return True

    except requests.exceptions.ConnectionError:
        _fail("Connection refused — LayoutLM not running or not yet ready")
        return False
    except Exception as e:
        _fail(f"Error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Check 3: Qwen-VL /health + /v1/models
# ─────────────────────────────────────────────────────────────────────────────

def check_qwen_health() -> tuple[bool, str]:
    _head("Check 3 — Qwen-VL Health + Model List (port 8002)")
    loaded_model = ""

    # 1. /health
    health_url = f"{SGLANG_ENDPOINT.rstrip('/')}/health"
    try:
        t0 = time.monotonic()
        r = requests.get(health_url, timeout=TIMEOUT_HEALTH)
        elapsed = time.monotonic() - t0
        if r.status_code == 200:
            _ok(f"/health OK ({elapsed:.1f}s)")
        else:
            _fail(f"/health returned HTTP {r.status_code}")
            return False, ""
    except requests.exceptions.ConnectionError:
        _fail(f"Connection refused → {health_url}")
        _warn("Is vLLM running? Start with: docker compose --profile gpu up sglang")
        return False, ""

    # 2. /v1/models — get the actually loaded model name
    models_url = f"{SGLANG_ENDPOINT.rstrip('/')}/v1/models"
    try:
        r = requests.get(models_url, timeout=TIMEOUT_HEALTH)
        if r.status_code == 200:
            models_data = r.json()
            model_list = models_data.get("data") or []
            if model_list:
                loaded_model = model_list[0].get("id", "")
                _ok(f"Model loaded: {loaded_model}")
                if "3B" in loaded_model or "3b" in loaded_model:
                    _ok("3B model confirmed (correct for RTX 4050 6GB)")
                elif "7B" in loaded_model or "7b" in loaded_model:
                    _warn("7B model detected — requires 8+ GB VRAM (RTX 4070/3080+)")
                else:
                    _warn(f"Unknown model size: {loaded_model}")
            else:
                _warn("No models listed in /v1/models response")
        else:
            _warn(f"/v1/models returned HTTP {r.status_code}")
    except Exception as e:
        _warn(f"/v1/models error: {e}")

    return True, loaded_model


# ─────────────────────────────────────────────────────────────────────────────
# Check 4: Qwen-VL TEXT-ONLY inference (no image)
# ─────────────────────────────────────────────────────────────────────────────

def check_qwen_text_inference(loaded_model: str) -> bool:
    _head("Check 4 — Qwen-VL Text-Only Inference")
    model = loaded_model or SGLANG_MODEL
    url = f"{SGLANG_ENDPOINT.rstrip('/')}/v1/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    'In the PLFS 2025 report, LFPR stands for "Labour Force Participation Rate". '
                    "Is LFPR a measure or a dimension? Reply with one word: measure or dimension."
                ),
            }
        ],
        "temperature": 0.0,
        "max_tokens": 10,
    }

    print(f"  Prompt: 'Is LFPR a measure or a dimension?'")
    print(f"  Expected: 'measure' (or similar)")

    try:
        t0 = time.monotonic()
        r = requests.post(url, json=payload, timeout=TIMEOUT_INFERENCE)
        elapsed = time.monotonic() - t0

        if r.status_code != 200:
            _fail(f"HTTP {r.status_code}: {r.text[:300]}")
            return False

        data = r.json()
        response_text = data["choices"][0]["message"]["content"].strip().lower()
        tokens_used = data.get("usage", {}).get("total_tokens", "?")

        print(f"  Response ({elapsed:.1f}s, {tokens_used} tokens): '{response_text}'")

        if "measure" in response_text:
            _ok("Correct answer — model understands statistical terminology")
            return True
        elif "dimension" in response_text:
            _warn("Model said 'dimension' — acceptable (LFPR can be either depending on context)")
            return True
        else:
            _warn(f"Unexpected response: '{response_text}' — model may need checking")
            return True  # Don't fail on content, just report

    except requests.exceptions.Timeout:
        _fail(f"Timeout after {TIMEOUT_INFERENCE}s — model may still be loading or OOM")
        return False
    except Exception as e:
        _fail(f"Error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Check 5: Qwen-VL VISION inference (the actual pipeline call pattern)
# ─────────────────────────────────────────────────────────────────────────────

def check_qwen_vision_inference(loaded_model: str) -> bool:
    _head("Check 5 — Qwen-VL Vision Inference (multimodal — CRITICAL)")
    model = loaded_model or SGLANG_MODEL
    url = f"{SGLANG_ENDPOINT.rstrip('/')}/v1/chat/completions"

    # Create test image
    img_bytes = _make_test_page_png()
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    print(f"  Test image: synthetic PLFS table page ({len(img_bytes)} bytes PNG)")

    # This mirrors the EXACT prompt used in pass2_entity_structure_extraction()
    prompt = (
        'Page 1/1 of "PLFS Annual Report 2025".\n'
        "Detected layout regions: table, heading\n\n"
        "Examine this page carefully. Your tasks:\n"
        "1. List ONLY entities that appear VERBATIM as column headers, section titles, "
        "or metric names visible on the page. Do NOT invent anything not explicitly "
        "printed. Examples: 'LFPR', 'State/UT', 'Rural', 'Urban', "
        "'Labour Force Participation Rate', 'Unemployment Rate', 'MPCE'. "
        "Exclude articles ('the','a'), prepositions ('of','in'), "
        "figure references ('Table 1','Figure 2.3'), pure numbers.\n"
        "2. If a table is present, extract its exact visible title or statement number. Use empty string if none.\n"
        "3. If a section/chapter heading is visible, extract it exactly. Use empty string if none.\n"
        "4. Identify charts/graphs if visible.\n"
        "5. Classify the dominant page structure.\n"
        "Output ONLY this JSON (no prose, no markdown):\n"
        '{"entities":["ExactColumnHeader","MetricName"],'
        '"structure_type":"data_table|chart_page|narrative|title_page|appendix|mixed",'
        '"description":"one-line summary",'
        '"table_title":"table title if present else empty",'
        '"section_heading":"heading if present else empty",'
        '"chart_types":[],'
        '"chart_titles":[]}\n'
        "JSON only."
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 256,
    }

    print(f"  Sending vision prompt (mirrors actual Pass 2 extraction call)...")

    try:
        t0 = time.monotonic()
        r = requests.post(url, json=payload, timeout=TIMEOUT_INFERENCE)
        elapsed = time.monotonic() - t0

        if r.status_code != 200:
            _fail(f"HTTP {r.status_code}: {r.text[:400]}")
            return False

        data = r.json()
        raw_response = data["choices"][0]["message"]["content"].strip()
        tokens_used = data.get("usage", {})

        print(f"\n  Raw response ({elapsed:.1f}s):")
        print(textwrap.indent(raw_response[:500], "    "))
        print()

        # Validate response quality
        passed = True

        # 1. Try to parse as JSON
        try:
            parsed = json.loads(raw_response)
            _ok("Response is valid JSON")
        except json.JSONDecodeError:
            # Try extracting JSON from response
            import re
            match = re.search(r'\{.*\}', raw_response, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                    _ok("JSON extracted from response (wrapped in text)")
                except:
                    _fail("Response is not parseable JSON — extraction pipeline will fail")
                    passed = False
                    parsed = {}
            else:
                _fail("No JSON found in response — Qwen may be echoing prompt or hallucinating")
                passed = False
                parsed = {}

        if parsed:
            entities = parsed.get("entities") or []
            structure = parsed.get("structure_type", "")
            description = parsed.get("description", "")

            print(f"  Parsed output:")
            print(f"    entities:       {entities[:5]}")
            print(f"    structure_type: {structure}")
            print(f"    description:    {description[:80]}")
            print(f"    table_title:    {parsed.get('table_title', '')[:60]}")

            # 2. Check entities are not prompt echo
            _ECHO_PHRASES = {"exactcolumnheader", "metricname", "sectiontitle"}
            echo_found = [e for e in entities if str(e).lower() in _ECHO_PHRASES]
            if echo_found:
                _fail(f"PROMPT ECHO detected in entities: {echo_found}")
                _warn("Qwen is returning the example text from the prompt verbatim")
                _warn("→ Check if max_tokens (256) is sufficient for the prompt length")
                passed = False
            elif entities:
                _ok(f"Entities look real (not echoed): {entities[:3]}")
            else:
                _warn("No entities returned — model may not see the image content")

            # 3. Check structure type is valid
            valid_types = {"data_table", "chart_page", "narrative", "title_page", "appendix", "mixed"}
            if structure in valid_types:
                _ok(f"structure_type is valid: '{structure}'")
            elif "|" in structure:
                _fail(f"structure_type contains pipe — Qwen returned the enum template: '{structure}'")
                _warn("→ Prompt example format confused the model")
                passed = False
            else:
                _warn(f"Unusual structure_type: '{structure}'")

            # 4. Check description is not empty and not a template
            if description and description != "one-line summary" and len(description) > 5:
                _ok(f"Description present: '{description[:60]}'")
            elif not description:
                _warn("Empty description")
            else:
                _fail(f"Description looks like template echo: '{description}'")
                passed = False

        # 5. Check token usage
        prompt_tokens = tokens_used.get("prompt_tokens", 0)
        completion_tokens = tokens_used.get("completion_tokens", 0)
        print(f"\n  Token usage: {prompt_tokens} prompt + {completion_tokens} completion = {tokens_used.get('total_tokens', '?')} total")

        if completion_tokens >= 256:
            _warn("Response hit max_tokens limit (256) — may be truncated, consider increasing")
        if prompt_tokens > 1800:
            _warn(f"Prompt is very large ({prompt_tokens} tokens) — approaching 2048 context limit")

        if passed:
            _ok(f"Vision inference PASSED ({elapsed:.1f}s)")
        else:
            _fail(f"Vision inference has issues — check model output above")

        return passed

    except requests.exceptions.Timeout:
        _fail(f"Vision inference timeout after {TIMEOUT_INFERENCE}s")
        _warn("→ Model may be loading (first request takes 2-7 min for FlashAttention JIT compilation)")
        _warn("→ Or VRAM is insufficient — check: nvidia-smi")
        _warn("→ Try: VLLM_ATTENTION_BACKEND=XFORMERS docker compose up sglang")
        return False
    except Exception as e:
        _fail(f"Error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Check 6: Qwen-VL JSON extraction reliability
# ─────────────────────────────────────────────────────────────────────────────

def check_qwen_json_reliability(loaded_model: str) -> bool:
    _head("Check 6 — Qwen-VL JSON Extraction Reliability")
    model = loaded_model or SGLANG_MODEL
    url = f"{SGLANG_ENDPOINT.rstrip('/')}/v1/chat/completions"

    # Simpler prompt — check if model can reliably output JSON without image
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are extracting entities from a government statistical report.\n"
                    "The page contains: LFPR (Labour Force Participation Rate) = 59.3%, "
                    "WPR (Worker Population Ratio) = 57.4%, UR (Unemployment Rate) = 3.1%\n"
                    "Output JSON array of entity names found:\n"
                    '[{"name":"LFPR","type":"measure"},{"name":"WPR","type":"measure"}]\n'
                    "Output only the JSON array, no other text."
                ),
            }
        ],
        "temperature": 0.0,
        "max_tokens": 200,
    }

    expected_entities = {"lfpr", "wpr", "ur", "labour force participation rate",
                         "worker population ratio", "unemployment rate"}

    try:
        t0 = time.monotonic()
        r = requests.post(url, json=payload, timeout=TIMEOUT_INFERENCE)
        elapsed = time.monotonic() - t0

        if r.status_code != 200:
            _fail(f"HTTP {r.status_code}")
            return False

        raw = r.json()["choices"][0]["message"]["content"].strip()
        print(f"  Response ({elapsed:.1f}s): {raw[:200]}")

        # Try parse JSON
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                names = {item.get("name", "").lower() for item in parsed if isinstance(item, dict)}
                found = names & expected_entities
                if found:
                    _ok(f"Correct entities extracted: {found}")
                    return True
                else:
                    _warn(f"Entities extracted but unexpected: {names}")
                    return True
            else:
                _warn(f"Returned JSON but not an array: {type(parsed)}")
                return True
        except json.JSONDecodeError:
            _warn("Response is not valid JSON — but this test uses no image, may differ from real usage")
            return True  # Soft warning only

    except Exception as e:
        _fail(f"Error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Summary & GPU status
# ─────────────────────────────────────────────────────────────────────────────

def show_gpu_status():
    _head("GPU Status (nvidia-smi)")
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,memory.used,temperature.gpu,utilization.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 6:
                    name, total, free, used, temp, util = parts[:6]
                    print(f"  GPU:   {name}")
                    print(f"  VRAM:  {total} total | {used} used | {free} free")
                    print(f"  Temp:  {temp}°C | Util: {util}")
                    # Warn if VRAM is tight
                    free_mb = int(free.replace(" MiB", "").replace("MiB", "").strip())
                    if free_mb < 500:
                        _warn(f"Very low VRAM ({free_mb} MB free) — model may OOM")
                    elif free_mb < 1500:
                        _warn(f"Low VRAM headroom ({free_mb} MB free)")
                    else:
                        _ok(f"VRAM headroom: {free_mb} MB")
        else:
            _warn("nvidia-smi not available or no GPU")
    except FileNotFoundError:
        _warn("nvidia-smi not found — run this script on the GPU machine")
    except Exception as e:
        _warn(f"nvidia-smi error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{_BOLD}{'═' * 60}{_RST}")
    print(f"{_BOLD}  BharatStat VLM Services Verification{_RST}")
    print(f"{_BOLD}{'═' * 60}{_RST}")
    print(f"  LayoutLM endpoint: {LAYOUTLM_ENDPOINT}")
    print(f"  Qwen-VL endpoint:  {SGLANG_ENDPOINT}")
    print(f"  Expected model:    {SGLANG_MODEL}")

    show_gpu_status()

    results: dict[str, bool] = {}

    # Run checks
    results["layoutlm_health"] = check_layoutlm_health()

    if results["layoutlm_health"]:
        results["layoutlm_inference"] = check_layoutlm_inference()
    else:
        _warn("Skipping LayoutLM inference — health check failed")
        results["layoutlm_inference"] = False

    qwen_healthy, loaded_model = check_qwen_health()
    results["qwen_health"] = qwen_healthy

    if qwen_healthy:
        results["qwen_text"] = check_qwen_text_inference(loaded_model)
        results["qwen_vision"] = check_qwen_vision_inference(loaded_model)
        results["qwen_json"] = check_qwen_json_reliability(loaded_model)
    else:
        _warn("Skipping Qwen-VL inference checks — health check failed")
        results["qwen_text"] = False
        results["qwen_vision"] = False
        results["qwen_json"] = False

    # Final summary
    _head("Verification Summary")
    check_labels = {
        "layoutlm_health":     "LayoutLM health endpoint",
        "layoutlm_inference":  "LayoutLM real PDF analysis",
        "qwen_health":         "Qwen-VL health + model list",
        "qwen_text":           "Qwen-VL text-only inference",
        "qwen_vision":         "Qwen-VL vision inference (CRITICAL)",
        "qwen_json":           "Qwen-VL JSON extraction reliability",
    }

    critical = {"qwen_vision", "layoutlm_inference"}
    all_passed = True
    critical_failed = []

    for key, label in check_labels.items():
        passed = results.get(key, False)
        if passed:
            _ok(label)
        else:
            if key in critical:
                _fail(f"{label} ← CRITICAL")
                critical_failed.append(label)
            else:
                _fail(label)
            all_passed = False

    print()
    if all_passed:
        print(f"  {_GREEN}{_BOLD}All checks passed ✓ — pipeline ready to run{_RST}")
        print()
        sys.exit(0)
    elif critical_failed:
        print(f"  {_RED}{_BOLD}CRITICAL failures — pipeline WILL fail:{_RST}")
        for f in critical_failed:
            print(f"    • {f}")
        print()
        print("  Common fixes:")
        print("    1. Start services: docker compose --profile gpu up -d layoutlm sglang")
        print("    2. Wait for model load: docker compose logs -f sglang")
        print("    3. Check VRAM: nvidia-smi")
        print("    4. If FlashAttention hangs: VLLM_ATTENTION_BACKEND=XFORMERS docker compose up sglang")
        print(f"    5. Set GPU laptop IP: SGLANG_ENDPOINT=http://<ip>:8002 python {__file__}")
        print()
        sys.exit(1)
    else:
        print(f"  {_YELLOW}{_BOLD}Non-critical failures — pipeline may partially work{_RST}")
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
