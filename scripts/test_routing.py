"""Quick test script to verify routing: LayoutLM + Groq + OpenRouter vision."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(override=True)

import requests
from report_builder.llm_router import llm_text_call, llm_vision_call, is_provider_available

print("=" * 60)
print("ROUTING VALIDATION")
print("=" * 60)

# 1. LayoutLM
print("\n[1] LayoutLM Health Check")
endpoint = os.getenv("LAYOUTLM_ENDPOINT", "http://localhost:8001")
try:
    r = requests.get(f"{endpoint}/health", timeout=10)
    print(f"    Endpoint: {endpoint}")
    print(f"    Status: {r.status_code} — {r.json()}")
except Exception as e:
    print(f"    FAILED: {e}")

# 2. Groq (reasoning)
print("\n[2] Groq Reasoning (key rotation)")
result = llm_text_call(
    'Return ONLY: {"ok": true}',
    task="gap_fill",
    max_tokens=30,
    temperature=0.0,
)
print(f"    Result: {result}")

# 3. OpenRouter Vision (check availability)
print("\n[3] OpenRouter Vision Provider")
print(f"    Available: {is_provider_available('openai', vision=True)}")
print(f"    OPENAI_BASE_URL: {os.getenv('OPENAI_BASE_URL')}")
print(f"    OPENAI_VISION_MODEL: {os.getenv('OPENAI_VISION_MODEL')}")
key = os.getenv("OPENAI_API_KEY", "")
masked = f"...{key[-8:]}" if len(key) > 8 else "(NOT SET)"
print(f"    OPENAI_API_KEY: {masked}")

# 4. Provider summary
print("\n[4] Provider Availability")
for prov in ["openai", "groq", "qwen", "gemini"]:
    print(f"    {prov:8s}: {'YES' if is_provider_available(prov) else 'NO'}")

# 5. Config summary
print("\n[5] RuntimeConfig")
from report_builder.model_runtime.config import build_runtime_config
config = build_runtime_config()
print(f"    Profile: {config.modelProfile}")
print(f"    VLM: {config.vlmProvider}")
print(f"    Reasoning: {config.reasoningProvider}")
print(f"    Keys: {config.keyPool.validSlots} ({config.keyPool.byProvider})")

print("\n" + "=" * 60)
print("DONE — All checks complete")
print("=" * 60)
