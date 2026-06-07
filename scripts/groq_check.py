"""Quick Groq connectivity + JSON-mode check (no secrets printed)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import truststore

truststore.inject_into_ssl()

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from groq import Groq

key = os.getenv("GROQ_API_KEY")
if not key:
    print("GROQ_API_KEY not found in environment")
    sys.exit(2)

model = os.getenv("GROQ_SEMANTIC_MODEL", "llama-3.3-70b-versatile")
client = Groq(api_key=key)
resp = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "system", "content": "Reply with strict JSON only."},
        {"role": "user", "content": 'Return {"ping": "pong"}'},
    ],
    response_format={"type": "json_object"},
    temperature=0,
)
print("GROQ OK ->", resp.choices[0].message.content)
print("model:", resp.model)
