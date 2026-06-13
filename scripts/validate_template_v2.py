"""Validate energy_enterprise_v2 template package integrity."""
import json
import sys

BASE = "report_builder/gold_standard/energy_enterprise_v2"

bp = json.load(open(f"{BASE}/energy_enterprise_v2.template.blueprint.json"))
ast_data = json.load(open(f"{BASE}/energy_enterprise_v2.template.ast.json"))
ssg = json.load(open(f"{BASE}/energy_enterprise_v2.semantic_slot_graph.json"))

errors = []
warnings = []

# 1. Entities
entity_ids = {e["entityId"] for e in bp["entities"]}
print(f"Entities defined: {len(entity_ids)}")

# 2. Blueprint hierarchy + entity reference checks
topic_ids = set()
chapter_ids = set()
section_ids = set()
question_ids = set()
component_ids = set()
all_referenced = set()

for topic in bp["topics"]:
    tid = topic["topicId"]
    topic_ids.add(tid)
    for ent in topic.get("ownEntities", []):
        eid = ent["entityId"]
        all_referenced.add(eid)
        if eid not in entity_ids:
            errors.append(f"Topic '{tid}' refs unknown entity: {eid}")

    for chapter in topic.get("chapters", []):
        cid = chapter["chapterId"]
        chapter_ids.add(cid)
        for ent in chapter.get("ownEntities", []):
            eid = ent["entityId"]
            all_referenced.add(eid)
            if eid not in entity_ids:
                errors.append(f"Chapter '{cid}' refs unknown entity: {eid}")
        for ent in chapter.get("inheritedEntities", []):
            eid = ent["entityId"]
            all_referenced.add(eid)
            if eid not in entity_ids:
                errors.append(f"Chapter '{cid}' inherits unknown entity: {eid}")

        for section in chapter.get("sections", []):
            sid = section["sectionId"]
            section_ids.add(sid)
            for ent in section.get("ownEntities", []):
                eid = ent["entityId"]
                all_referenced.add(eid)
                if eid not in entity_ids:
                    errors.append(f"Section '{sid}' refs unknown entity: {eid}")
            for ent in section.get("inheritedEntities", []):
                eid = ent["entityId"]
                all_referenced.add(eid)
                if eid not in entity_ids:
                    errors.append(f"Section '{sid}' inherits unknown entity: {eid}")

            for question in section.get("questions", []):
                qid = question["questionId"]
                question_ids.add(qid)
                for ent in question.get("requiredEntities", []):
                    eid = ent["entityId"]
                    all_referenced.add(eid)
                    if eid not in entity_ids:
                        errors.append(f"Question '{qid}' refs unknown entity: {eid}")

                for comp in question.get("answerStructure", {}).get("components", []):
                    comp_id = comp["componentId"]
                    component_ids.add(comp_id)
                    for eid in comp.get("requiredEntities", []):
                        all_referenced.add(eid)
                        if eid not in entity_ids:
                            errors.append(f"Component '{comp_id}' refs unknown entity: {eid}")

print(f"Topics: {len(topic_ids)}, Chapters: {len(chapter_ids)}, Sections: {len(section_ids)}, Questions: {len(question_ids)}, Components: {len(component_ids)}")

# 3. Formula catalog
formula_ids = {f["formulaId"] for f in bp.get("formulaCatalog", [])}
for f in bp.get("formulaCatalog", []):
    if f["numerator"] not in entity_ids:
        errors.append(f"Formula '{f['formulaId']}' numerator '{f['numerator']}' not in entities")
    if f["denominator"] not in entity_ids:
        errors.append(f"Formula '{f['formulaId']}' denominator '{f['denominator']}' not in entities")
print(f"Formulas: {len(formula_ids)}")

# 4. Unused entities
unused = entity_ids - all_referenced
if unused:
    warnings.append(f"Unused entities (never referenced in hierarchy): {unused}")

# 5. AST documentMap vs blueprint
def collect_ast_nodes(nodes, result=None):
    if result is None:
        result = set()
    for n in nodes:
        result.add(n["nodeId"])
        collect_ast_nodes(n.get("children", []), result)
    return result

ast_node_ids = collect_ast_nodes(ast_data.get("documentMap", []))
bp_all_ids = topic_ids | chapter_ids | section_ids | question_ids
missing_in_ast = bp_all_ids - ast_node_ids
extra_in_ast = ast_node_ids - bp_all_ids
if missing_in_ast:
    errors.append(f"Blueprint nodes missing from AST documentMap: {missing_in_ast}")
if extra_in_ast:
    warnings.append(f"AST documentMap has extra nodes not in blueprint: {extra_in_ast}")

# 6. AST slot refs vs blueprint components
def collect_ast_slots(nodes):
    slots = set()
    for n in nodes:
        for s in n.get("slots", []):
            slots.add(s.get("componentRef", ""))
        slots.update(collect_ast_slots(n.get("children", [])))
    return slots

ast_slot_component_refs = collect_ast_slots(ast_data.get("documentMap", []))
missing_comp_in_ast = component_ids - ast_slot_component_refs
extra_comp_in_ast = ast_slot_component_refs - component_ids
if missing_comp_in_ast:
    warnings.append(f"Blueprint components without AST slot: {missing_comp_in_ast}")
if extra_comp_in_ast:
    errors.append(f"AST slots reference non-existent components: {extra_comp_in_ast}")

# 7. Semantic slot graph
slot_question_refs = set()
slot_component_refs = set()
for slot in ssg.get("slots", []):
    slot_question_refs.add(slot["questionRef"])
    slot_component_refs.add(slot["componentRef"])
    for eid in slot.get("requiredEntities", []):
        if eid not in entity_ids:
            errors.append(f"Slot '{slot['slotId']}' refs unknown entity: {eid}")
    # Check formula refs
    fref = slot.get("formulaRef")
    if fref and fref not in formula_ids:
        errors.append(f"Slot '{slot['slotId']}' refs unknown formula: {fref}")

missing_q_in_slots = question_ids - slot_question_refs
if missing_q_in_slots:
    warnings.append(f"Questions with no semantic slots: {missing_q_in_slots}")
missing_comp_in_slots = component_ids - slot_component_refs
if missing_comp_in_slots:
    warnings.append(f"Components without a semantic slot: {missing_comp_in_slots}")
extra_comp_in_slots = slot_component_refs - component_ids
if extra_comp_in_slots:
    errors.append(f"Slot graph refs non-existent components: {extra_comp_in_slots}")

actual_slots = len(ssg["slots"])
claimed_slots = ssg["totalSlots"]
if actual_slots != claimed_slots:
    errors.append(f"Slot count mismatch: {actual_slots} actual vs {claimed_slots} claimed")
print(f"Semantic slots: {actual_slots} (claimed {claimed_slots})")

# 8. Execution order references valid slots
slot_ids = {s["slotId"] for s in ssg.get("slots", [])}
for ref in ssg.get("executionOrder", []):
    if ref not in slot_ids:
        errors.append(f"Execution order refs non-existent slot: {ref}")
exec_order_set = set(ssg.get("executionOrder", []))
missing_from_exec = slot_ids - exec_order_set
if missing_from_exec:
    warnings.append(f"Slots missing from execution order: {missing_from_exec}")

# 9. Check entity column mappings against CSV headers
import csv
with open(f"{BASE}/energy_enterprise_v2.dataset.csv") as f:
    reader = csv.reader(f)
    csv_headers = next(reader)
csv_header_set = set(csv_headers)
for ent in bp["entities"]:
    col = ent.get("columnExpr", "")
    if col and col not in csv_header_set:
        errors.append(f"Entity '{ent['entityId']}' columnExpr '{col}' not found in CSV headers")
print(f"CSV columns: {len(csv_headers)} ({', '.join(csv_headers[:5])}...)")

# Report
print(f"\n{'='*50}")
print(f"ERRORS: {len(errors)}")
for e in errors:
    print(f"  ✗ {e}")
print(f"\nWARNINGS: {len(warnings)}")
for w in warnings:
    print(f"  ⚠ {w}")
print(f"\nVERDICT: {'✓ PASS' if not errors else '✗ FAIL'}")
