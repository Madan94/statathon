"""Template package manifest and loader.

The extraction pipeline emits two primary value-free JSON files:
``template.ast.json`` and ``template.blueprint.json``. The binder should present
them as one versioned Template Package while still preserving the internal split.
This module is the additive contract layer for that package.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PACKAGE_SCHEMA = "bharatstat/template-package/v1"


def stable_json_hash(value: Any) -> str:
    """Return a deterministic short hash for JSON-serializable content."""
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class TemplatePackageManifest:
    """Versioned manifest tying AST, blueprint, diagnostics, and slot graph."""

    templateId: str
    version: str = "1.0.0"
    name: str = "Document"
    status: str = "UNKNOWN"
    schema: str = PACKAGE_SCHEMA
    astPath: str = "template.ast.json"
    blueprintPath: str = "template.blueprint.json"
    semanticSlotGraphPath: str | None = "semantic_slot_graph.json"
    diagnosticsPath: str | None = "template.diagnostics.json"
    astHash: str = ""
    blueprintHash: str = ""
    semanticSlotGraphHash: str | None = None
    diagnosticsHash: str | None = None
    extractionScore: float | None = None
    sourceDocument: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "$schema": self.schema,
            "templateId": self.templateId,
            "version": self.version,
            "name": self.name,
            "status": self.status,
            "artifacts": {
                "templateAst": {"path": self.astPath, "hash": self.astHash},
                "templateBlueprint": {"path": self.blueprintPath, "hash": self.blueprintHash},
            },
            "metadata": dict(self.metadata),
        }
        if self.semanticSlotGraphPath:
            d["artifacts"]["semanticSlotGraph"] = {
                "path": self.semanticSlotGraphPath,
                "hash": self.semanticSlotGraphHash,
            }
        if self.diagnosticsPath:
            d["artifacts"]["diagnostics"] = {
                "path": self.diagnosticsPath,
                "hash": self.diagnosticsHash,
            }
        if self.extractionScore is not None:
            d["extractionScore"] = self.extractionScore
        if self.sourceDocument:
            d["sourceDocument"] = self.sourceDocument
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TemplatePackageManifest":
        artifacts = d.get("artifacts") or {}
        ast = artifacts.get("templateAst") or {}
        blueprint = artifacts.get("templateBlueprint") or {}
        graph = artifacts.get("semanticSlotGraph") or {}
        diagnostics = artifacts.get("diagnostics") or {}
        return cls(
            templateId=str(d.get("templateId") or ""),
            version=str(d.get("version") or "1.0.0"),
            name=str(d.get("name") or "Document"),
            status=str(d.get("status") or "UNKNOWN"),
            schema=str(d.get("$schema") or d.get("schema") or PACKAGE_SCHEMA),
            astPath=str(ast.get("path") or "template.ast.json"),
            blueprintPath=str(blueprint.get("path") or "template.blueprint.json"),
            semanticSlotGraphPath=graph.get("path"),
            diagnosticsPath=diagnostics.get("path"),
            astHash=str(ast.get("hash") or ""),
            blueprintHash=str(blueprint.get("hash") or ""),
            semanticSlotGraphHash=graph.get("hash"),
            diagnosticsHash=diagnostics.get("hash"),
            extractionScore=d.get("extractionScore"),
            sourceDocument=str(d.get("sourceDocument") or ""),
            metadata=dict(d.get("metadata") or {}),
        )


@dataclass
class TemplatePackage:
    """Loaded package content used by binder/review."""

    manifest: TemplatePackageManifest
    templateAst: dict[str, Any]
    templateBlueprint: dict[str, Any]
    semanticSlotGraph: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None


def build_template_package_manifest(
    *,
    template_ast: dict[str, Any],
    template_blueprint: dict[str, Any],
    semantic_slot_graph: dict[str, Any] | None = None,
    diagnostics: Any | None = None,
    ast_path: str = "template.ast.json",
    blueprint_path: str = "template.blueprint.json",
    semantic_slot_graph_path: str | None = "semantic_slot_graph.json",
    diagnostics_path: str | None = "template.diagnostics.json",
) -> TemplatePackageManifest:
    """Create a manifest from in-memory artifacts without writing files."""
    ast_meta = template_ast.get("metadata") or {}
    bp_meta = template_blueprint.get("templateMeta") or {}
    diagnostics_dict = diagnostics.to_dict() if hasattr(diagnostics, "to_dict") else diagnostics
    template_id = str(bp_meta.get("templateId") or ast_meta.get("templateId") or "template")
    status = str((diagnostics_dict or {}).get("status") or "VALID")
    score = (diagnostics_dict or {}).get("binderReadinessScore")
    return TemplatePackageManifest(
        templateId=template_id,
        version=str(bp_meta.get("version") or ast_meta.get("version") or "1.0.0"),
        name=str(bp_meta.get("name") or ast_meta.get("name") or "Document"),
        status=status,
        astPath=ast_path,
        blueprintPath=blueprint_path,
        semanticSlotGraphPath=semantic_slot_graph_path if semantic_slot_graph is not None else None,
        diagnosticsPath=diagnostics_path if diagnostics_dict is not None else None,
        astHash=stable_json_hash(template_ast),
        blueprintHash=stable_json_hash(template_blueprint),
        semanticSlotGraphHash=stable_json_hash(semantic_slot_graph) if semantic_slot_graph is not None else None,
        diagnosticsHash=stable_json_hash(diagnostics_dict) if diagnostics_dict is not None else None,
        extractionScore=float(score) if score is not None else None,
        sourceDocument=str(bp_meta.get("sourceDocument") or ast_meta.get("generatedFrom") or ""),
        metadata={
            "domain": bp_meta.get("domain"),
            "locale": bp_meta.get("locale") or ast_meta.get("locale"),
            "valueFree": bool(bp_meta.get("valueFree") or ast_meta.get("valueFree")),
        },
    )


def write_template_package(
    directory: str | Path,
    *,
    template_ast: dict[str, Any],
    template_blueprint: dict[str, Any],
    semantic_slot_graph: dict[str, Any] | None = None,
    diagnostics: Any | None = None,
) -> TemplatePackageManifest:
    """Write package artifacts and ``template.package.json`` to a directory."""
    base = Path(directory)
    base.mkdir(parents=True, exist_ok=True)
    diagnostics_dict = diagnostics.to_dict() if hasattr(diagnostics, "to_dict") else diagnostics
    manifest = build_template_package_manifest(
        template_ast=template_ast,
        template_blueprint=template_blueprint,
        semantic_slot_graph=semantic_slot_graph,
        diagnostics=diagnostics_dict,
    )
    (base / manifest.astPath).write_text(json.dumps(template_ast, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (base / manifest.blueprintPath).write_text(json.dumps(template_blueprint, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if semantic_slot_graph is not None and manifest.semanticSlotGraphPath:
        (base / manifest.semanticSlotGraphPath).write_text(json.dumps(semantic_slot_graph, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if diagnostics_dict is not None and manifest.diagnosticsPath:
        (base / manifest.diagnosticsPath).write_text(json.dumps(diagnostics_dict, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (base / "template.package.json").write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def load_template_package(directory: str | Path) -> TemplatePackage:
    """Load a package directory produced by ``write_template_package``."""
    base = Path(directory)
    manifest_path = base / "template.package.json"
    if manifest_path.exists():
        manifest = TemplatePackageManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
    else:
        ast_path = base / "template.ast.json"
        bp_path = base / "template.blueprint.json"
        template_ast = json.loads(ast_path.read_text(encoding="utf-8"))
        template_blueprint = json.loads(bp_path.read_text(encoding="utf-8"))
        manifest = build_template_package_manifest(template_ast=template_ast, template_blueprint=template_blueprint)

    template_ast = json.loads((base / manifest.astPath).read_text(encoding="utf-8"))
    template_blueprint = json.loads((base / manifest.blueprintPath).read_text(encoding="utf-8"))
    semantic_slot_graph = None
    diagnostics = None
    if manifest.semanticSlotGraphPath and (base / manifest.semanticSlotGraphPath).exists():
        semantic_slot_graph = json.loads((base / manifest.semanticSlotGraphPath).read_text(encoding="utf-8"))
    if manifest.diagnosticsPath and (base / manifest.diagnosticsPath).exists():
        diagnostics = json.loads((base / manifest.diagnosticsPath).read_text(encoding="utf-8"))
    return TemplatePackage(
        manifest=manifest,
        templateAst=template_ast,
        templateBlueprint=template_blueprint,
        semanticSlotGraph=semantic_slot_graph,
        diagnostics=diagnostics,
    )