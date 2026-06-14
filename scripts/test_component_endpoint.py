"""Test: generate component at index 0, then index 2 — verify different content."""
import requests, json

base = "http://localhost:8000/report-builder/generate-phase/tpl_energy_enterprise_v2/b7acf2ae375faab7"

for idx in [0, 2, 8]:
    print(f"\n{'='*60}")
    print(f"Generating component index={idx}...")
    r = requests.post(f"{base}/generate-component", json={"index": idx, "use_llm": True})
    data = r.json()
    print(f"  Status: {r.status_code}")
    print(f"  Plan:   {data.get('plan_id')}")
    print(f"  Type:   {data.get('component_type')}")
    print(f"  Title:  {data.get('title')}")
    print(f"  Progress: {data.get('progress_pct')}%")
    narrative = data.get("narrative", "")
    if len(narrative) > 150:
        narrative = narrative[:150] + "..."
    print(f"  Narrative: {narrative}")
    content = data.get("content", {})
    if content.get("rows"):
        print(f"  Content rows: {len(content['rows'])}")
    elif content.get("value"):
        print(f"  Content value: {content['value']}")
    else:
        print(f"  Content keys: {list(content.keys())[:5]}")
