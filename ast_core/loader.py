"""Load / save multi-AST JSON documents."""
from __future__ import annotations

import json
from pathlib import Path

from .schema import MultiAST


def load_multi_ast(path: str | Path) -> MultiAST:
    """Read an Enterprise-style multi-AST JSON file."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw)
    return MultiAST.from_dict(data)


def save_multi_ast(ast: MultiAST, path: str | Path, *, indent: int = 2) -> str:
    """Serialise a MultiAST to JSON. Returns the resolved path string."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ast.to_dict(), indent=indent, default=str),
                 encoding="utf-8")
    return str(p)
