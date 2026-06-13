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

# Lazy re-export (PEP 562). Importing a leaf subpackage such as
# ``report_builder.binding`` or ``report_builder.generation`` must NOT drag in the
# heavy extraction/agent pipeline (pandas + Neo4j/Redis/Qdrant + agents/firewall/
# exporter), which previously added ~3 s and import-time service coupling to every
# ``report_builder.*`` import. ``generate_report`` is resolved on first access, so
# ``from report_builder import generate_report`` still works for the routes that
# need it while the generate-phase API stays light.
def __getattr__(name: str):
    if name == "generate_report":
        from .pipeline import generate_report as _generate_report

        return _generate_report
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
