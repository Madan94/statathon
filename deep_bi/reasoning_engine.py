"""Multi-hop ReasoningEngine.

Given a list of concepts from the IntentParser and a graph of column-level
relationships (schema_graph from the existing KG), build a *reasoning path*:
a sequence of concepts that connects the question's anchors via the most
trustworthy chain in the graph.

Example: concepts = ["education", "income", "employment"]
   Path: education -> income -> employment
   Each hop carries a weight (the edge weight between corresponding columns).

Falls back gracefully when no KG edges connect the concepts — the path is
then just the concept list in order with hop weight = 0.5.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from .column_synonym_kg import ColumnSynonymKG


@dataclass
class ReasoningHop:
    from_concept: str
    to_concept: str
    via_columns: tuple[str, str]
    weight: float
    relationship: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"from_concept": self.from_concept,
                "to_concept": self.to_concept,
                "via_columns": list(self.via_columns),
                "weight": round(self.weight, 4),
                "relationship": self.relationship}


@dataclass
class ReasoningPath:
    concepts: list[str] = field(default_factory=list)
    hops: list[ReasoningHop] = field(default_factory=list)
    total_weight: float = 0.0
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"concepts": self.concepts,
                "hops": [h.to_dict() for h in self.hops],
                "total_weight": round(self.total_weight, 4),
                "rationale": self.rationale}


class ReasoningEngine:
    """Build reasoning paths over a (column-level) schema graph."""

    def __init__(self, *, schema_graph: dict[str, Any] | None,
                  column_kg: ColumnSynonymKG):
        self._edges = list((schema_graph or {}).get("edges") or [])
        self._adj: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
        for e in self._edges:
            if not isinstance(e, dict):
                continue
            s = str(e.get("source") or "")
            t = str(e.get("target") or "")
            w = float(e.get("weight") or 0.5)
            rtype = str(e.get("relationship_type") or "RELATED")
            if s and t:
                self._adj[s].append((t, w, rtype))
                self._adj[t].append((s, w, rtype))
        self.column_kg = column_kg

    # ---------------- Public ----------------

    def build_path(self, concepts: list[str]) -> ReasoningPath:
        if not concepts:
            return ReasoningPath()
        # Resolve each concept to its best column
        col_by_concept: dict[str, str] = {}
        for c in concepts:
            matches = self.column_kg.resolve(c, top_k=1)
            if matches:
                col_by_concept[c] = matches[0].column

        hops: list[ReasoningHop] = []
        total = 0.0
        for i in range(len(concepts) - 1):
            a, b = concepts[i], concepts[i + 1]
            ca = col_by_concept.get(a)
            cb = col_by_concept.get(b)
            if ca and cb and ca != cb:
                path_cols, w, rtype = self._shortest_path(ca, cb)
                if path_cols:
                    hops.append(ReasoningHop(
                        from_concept=a, to_concept=b,
                        via_columns=(ca, cb), weight=w, relationship=rtype,
                    ))
                    total += w
                    continue
            hops.append(ReasoningHop(
                from_concept=a, to_concept=b,
                via_columns=(ca or "", cb or ""),
                weight=0.50, relationship="implicit",
            ))
            total += 0.50

        return ReasoningPath(
            concepts=list(concepts),
            hops=hops,
            total_weight=total,
            rationale=self._rationale(concepts, hops),
        )

    # ---------------- Internals ----------------

    def _shortest_path(self, src: str, tgt: str
                        ) -> tuple[list[str], float, str]:
        """BFS shortest path with edge weights summed."""
        if src not in self._adj or tgt not in self._adj:
            return [], 0.0, ""
        prev: dict[str, tuple[str, float, str] | None] = {src: None}
        q = deque([src])
        while q:
            cur = q.popleft()
            if cur == tgt:
                break
            for nxt, w, rtype in self._adj.get(cur, []):
                if nxt not in prev:
                    prev[nxt] = (cur, w, rtype)
                    q.append(nxt)
        if tgt not in prev:
            return [], 0.0, ""
        # Reconstruct
        path: list[str] = [tgt]
        total_w = 0.0
        last_rtype = ""
        cur = tgt
        while prev[cur] is not None:
            parent, w, rtype = prev[cur]   # type: ignore[misc]
            total_w += w
            last_rtype = last_rtype or rtype
            path.append(parent)
            cur = parent
        path.reverse()
        # Normalise weight to [0, 1] by averaging
        avg_w = total_w / max(len(path) - 1, 1)
        return path, avg_w, last_rtype

    @staticmethod
    def _rationale(concepts: list[str], hops: list[ReasoningHop]) -> str:
        if not concepts:
            return "no concepts to reason about"
        chain = " -> ".join(concepts)
        if not hops:
            return f"{chain} (single hop)"
        bits: list[str] = [f"reasoning chain: {chain}"]
        for h in hops:
            if h.relationship == "implicit":
                bits.append(f"{h.from_concept}-{h.to_concept}: implicit (no KG edge)")
            else:
                bits.append(f"{h.from_concept}-{h.to_concept}: "
                             f"via {h.via_columns[0]}<->{h.via_columns[1]} "
                             f"({h.relationship}, w={h.weight:.2f})")
        return " | ".join(bits)
