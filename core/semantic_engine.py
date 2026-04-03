import networkx as nx
from services.model_service import embed_texts
import numpy as np

DOMAIN_LABELS = [
    "numeric measurement", "identifier", "date time", "category label",
    "financial amount", "medical symptom", "demographic",
]

def map_columns_semantic(column_names: list[str]) -> dict[str, str]:
    if not column_names:
        return {}
    name_emb = np.array(embed_texts(column_names))
    lab_emb = np.array(embed_texts(DOMAIN_LABELS))
    # cosine similarity argmax
    norm = lambda x: x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-9)
    sn, sl = norm(name_emb), norm(lab_emb)
    sim = sn @ sl.T
    idx = sim.argmax(axis=1)
    return {column_names[i]: DOMAIN_LABELS[idx[i]] for i in range(len(column_names))}

def priority_graph(column_names: list[str], priorities: dict[str, float]) -> dict:
    G = nx.DiGraph()
    for c in column_names:
        G.add_node(c, priority=priorities.get(c, 0.0))
    ordered = sorted(column_names, key=lambda x: priorities.get(x, 0.0), reverse=True)
    for i in range(len(ordered) - 1):
        G.add_edge(ordered[i], ordered[i + 1])
    return {"nodes": list(G.nodes(data=True)), "edges": list(G.edges())}