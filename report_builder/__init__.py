"""Report Builder — 6-phase architecture for tamper-proof, verified statistical reports.

Phases:
  0. blueprint.py     — ColPali vision-spatial extraction + SGLang AST compiler
  1. knowledge_graph  — Dynamic Neo4j ontology with n10s (Neosemantics) RDF export
  2. memory.py        — Redis STM + Qdrant LTM (Reflection Ledger)
  3. kernel.py        — Dockerised Apache Arrow stateful kernel + Semantic Router
  4. firewall.py      — Hallucination Firewall: Scribe + Verifier (ReAct loop)
  5. agui.py          — Block-based reactive canvas with WebSocket transport
  6. exporter.py      — JSON AST -> professional PDF
  7. bi_chat.py       — In-canvas BI chat (drag-and-drop into report)

Each module attempts the production technology first; if the corresponding
service / model is unreachable at runtime the module degrades to a local-only
path so the pipeline still completes. The output schemas are identical either
way, so a deployment with the full stack online produces byte-compatible
artifacts to one running locally.
"""

from .pipeline import generate_report  # re-exported for routes
