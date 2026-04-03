import hashlib
import json
from pathlib import Path

def vault_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

def write_math_vault(path: str, stats: dict) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"stats": stats, "integrity": vault_hash({"stats": stats})}
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(p)