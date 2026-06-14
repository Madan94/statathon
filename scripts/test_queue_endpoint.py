"""Quick test: call the generation-queue endpoint and display results."""
import requests, json

r = requests.get("http://localhost:8000/report-builder/generate-phase/tpl_energy_enterprise_v2/b7acf2ae375faab7/generation-queue")
q = r.json()
print(f"Status: {r.status_code}, items: {len(q)}")
for item in q[:15]:
    idx = item["index"]
    ct = item["component_type"]
    title = item["title"][:55]
    path = " > ".join(item["section_path"])
    qid = item["question_id"]
    print(f"  [{idx:2d}] {ct:15s}  {title:55s}  q={qid}")
    if path:
        print(f"       path: {path}")
