from __future__ import annotations

from typing import Any


def neo4j_driver(settings: Any):
    try:
        from neo4j import GraphDatabase
    except ImportError as e:
        raise ImportError(
            "The `neo4j` Python package is required for graph sync (pip install neo4j)."
        ) from e

    return GraphDatabase.driver(settings.uri, auth=(settings.username, settings.password))
