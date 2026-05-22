"""Neo4j connection settings from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Neo4jSettings:
    enabled: bool
    uri: str
    username: str
    password: str
    database: str

    @classmethod
    def from_env(cls) -> Neo4jSettings:
        return cls(
            enabled=_truthy(os.getenv("NEO4J_ENABLED")),
            uri=(os.getenv("NEO4J_URI") or "bolt://localhost:7687").strip(),
            username=(os.getenv("NEO4J_USER") or "neo4j").strip(),
            password=(os.getenv("NEO4J_PASSWORD") or "").strip(),
            database=(os.getenv("NEO4J_DATABASE") or "neo4j").strip() or "neo4j",
        )
