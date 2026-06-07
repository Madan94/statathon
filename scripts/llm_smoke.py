"""Quick Gemini + Groq fallback smoke test."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "model"))

try:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
except Exception:
    pass

from semantic_mapping_v2.llm_client import generate_json, generate_text, llm_status


def main() -> int:
    print("LLM status:", llm_status())
    try:
        text = generate_text('Reply with exactly: {"ok": true}', system="Return JSON only.")
        print("generate_text OK:", text[:120])
        data = generate_json('Return {"provider_working": true}')
        print("generate_json OK:", data)
        return 0
    except Exception as exc:
        print("LLM FAILED:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
