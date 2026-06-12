"""Shared recursive traversal helpers for template blueprints.

Extraction can emit legacy flat topics (``topics[].questions[]``) or the
enterprise outline shape (``topics[].chapters[].sections[].questions[]``).
These helpers keep binder, diagnostics, and emission code on one traversal
contract instead of each module rediscovering the outline differently.
"""
from __future__ import annotations

from typing import Any

_CHILD_KEYS = ("topics", "chapters", "sections", "children", "subtopics", "subsections")


def _as_root(blueprint: dict[str, Any] | list[Any] | None) -> dict[str, Any]:
    if isinstance(blueprint, dict):
        return blueprint
    if isinstance(blueprint, list):
        return {"topics": blueprint}
    return {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _node_id(node: dict[str, Any], node_type: str, index: int) -> str:
    keys = {
        "topic": ("topicId", "id", "nodeId", "slug"),
        "chapter": ("chapterId", "id", "nodeId", "slug"),
        "section": ("sectionId", "id", "nodeId", "slug"),
    }.get(node_type, ("id", "nodeId", "slug"))
    for key in keys:
        value = _text(node.get(key))
        if value:
            return value
    title = _node_title(node, node_type)
    return f"{node_type}_{index + 1}_{title.lower().replace(' ', '_')[:40]}" if title else f"{node_type}_{index + 1}"


def _node_title(node: dict[str, Any], node_type: str) -> str:
    keys = {
        "topic": ("topicTitle", "title", "heading", "name"),
        "chapter": ("chapterTitle", "title", "heading", "name"),
        "section": ("sectionTitle", "title", "heading", "name"),
    }.get(node_type, ("title", "heading", "name"))
    for key in keys:
        value = _text(node.get(key))
        if value:
            return value
    return ""


def _child_type(key: str, child: dict[str, Any]) -> str:
    if child.get("topicId") or key in ("topics", "subtopics"):
        return "topic"
    if child.get("chapterId") or key == "chapters":
        return "chapter"
    return "section"


def _base_context() -> dict[str, Any]:
    return {
        "topicId": None,
        "topicTitle": None,
        "chapterId": None,
        "chapterTitle": None,
        "sectionId": None,
        "sectionTitle": None,
        "path": [],
    }


def _node_context(parent: dict[str, Any], key: str, node: dict[str, Any], index: int) -> dict[str, Any]:
    node_type = _child_type(key, node)
    node_id = _node_id(node, node_type, index)
    title = _node_title(node, node_type)
    ctx = dict(parent)
    ctx["path"] = list(parent.get("path") or []) + [f"{key}[{index}]"]
    if node_type == "topic":
        ctx["topicId"] = node_id
        ctx["topicTitle"] = title
        ctx["chapterId"] = None
        ctx["chapterTitle"] = None
        ctx["sectionId"] = None
        ctx["sectionTitle"] = None
    elif node_type == "chapter":
        ctx["chapterId"] = node_id
        ctx["chapterTitle"] = title
        ctx["sectionId"] = None
        ctx["sectionTitle"] = None
    else:
        ctx["sectionId"] = node_id
        ctx["sectionTitle"] = title
    return ctx


def _walk_nodes(root: dict[str, Any], parent: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in _CHILD_KEYS:
        for index, child in enumerate(_as_list(root.get(key))):
            if not isinstance(child, dict):
                continue
            node_type = _child_type(key, child)
            ctx = _node_context(parent, key, child, index)
            out.append({
                "node": child,
                "nodeType": node_type,
                "nodeId": _node_id(child, node_type, index),
                "nodeTitle": _node_title(child, node_type),
                **ctx,
            })
            out.extend(_walk_nodes(child, ctx))
    return out


def walk_outline_nodes(blueprint: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    """Return all recursive outline node contexts in reading order."""
    return _walk_nodes(_as_root(blueprint), _base_context())


def iter_question_contexts(blueprint: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    """Return recursive question contexts for enterprise and legacy blueprints."""
    root = _as_root(blueprint)
    out: list[dict[str, Any]] = []

    for node_ctx in walk_outline_nodes(root):
        node = node_ctx.get("node") if isinstance(node_ctx, dict) else None
        if not isinstance(node, dict):
            continue
        base = {k: node_ctx.get(k) for k in ("topicId", "topicTitle", "chapterId", "chapterTitle", "sectionId", "sectionTitle")}
        base_path = list(node_ctx.get("path") or [])
        for index, question in enumerate(_as_list(node.get("questions"))):
            if isinstance(question, dict):
                out.append({**base, "question": question, "path": base_path + [f"questions[{index}]"]})

    for index, question in enumerate(_as_list(root.get("questions"))):
        if isinstance(question, dict):
            ctx = _base_context()
            out.append({**ctx, "question": question, "path": [f"questions[{index}]"]})
    return out


def iter_questions(blueprint: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    """Return recursive questions without context."""
    return [ctx["question"] for ctx in iter_question_contexts(blueprint)]


def iter_components(question: dict[str, Any]) -> list[dict[str, Any]]:
    """Return question answer components from current and legacy shapes."""
    if not isinstance(question, dict):
        return []
    ans = question.get("answerStructure") or question.get("outputContract") or {}
    if not isinstance(ans, dict):
        return []
    return [comp for comp in _as_list(ans.get("components")) if isinstance(comp, dict)]
