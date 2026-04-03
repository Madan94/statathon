import json
from pathlib import Path

def write_ingestion_report(path: str, health: dict, schema: dict) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"layout": "one_shot", "health": health, "schema": schema}
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(p)