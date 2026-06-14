"""Quick test: verify the fixed _question_meta, _prose_config, _question_registry."""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from api.report_builder_api.generate_phase_api import (
    _question_meta, _prose_config, _question_registry,
)

bp = json.loads(pathlib.Path(
    "report_builder/gold_standard/energy_enterprise_v2/"
    "energy_enterprise_v2.template.blueprint.json"
).read_text(encoding="utf-8"))

qm = _question_meta(bp)
pc = _prose_config(bp)
qr = _question_registry(bp)

print(f"question_meta:    {len(qm)} entries (was 0 before fix)")
print(f"prose_config:     {len(pc)} entries (was 0 before fix)")
print(f"question_registry:{len(qr)} entries")
print()

for k, v in qr.items():
    title = v["title"][:60]
    path = " > ".join(v["sectionPath"])
    types = ", ".join(v["componentTypes"])
    print(f"  {k}: {title}")
    print(f"    path:  {path}")
    print(f"    types: {types}")
    print()

# Verify prose_config has useful data
for k, v in pc.items():
    print(f"  prose[{k}]: measure={v.get('measureLabel','?')}, dim={v.get('dimensionNoun','?')}")
