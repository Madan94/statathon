"""Freeze Store — file-backed immutable bundle persistence.

Implements versioned freeze semantics:
- Same confirmed binding version → same bindingAstId → same frozen artifact
- Repeated calls with same identity return the SAME frozen bundle (not fresh)
- New confirmations → new version number → new frozen artifact

Storage layout:
    storage/bindings/{template_id}__{signature}/
        v{N}.bundle.json      — frozen ExecutionBundle
        v{N}.binding.json     — frozen BindingAST
        latest.json           — pointer: {"version": N, "bindingAstId": "...", "frozenAt": "..."}

This ensures S4/S5/S6 reproducibility and evidence audit.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from report_builder.binding.execution_contracts import ExecutionBundle

logger = logging.getLogger(__name__)

# Base directory for frozen bundles
FREEZE_DIR = Path("storage/bindings")


def _bundle_dir(template_id: str, signature: str) -> Path:
    """Get the directory for a specific template+signature pair."""
    safe_id = template_id.replace("/", "_").replace("\\", "_")
    safe_sig = signature[:16] if len(signature) > 16 else signature
    return FREEZE_DIR / f"{safe_id}__{safe_sig}"


def _compute_content_hash(bundle: ExecutionBundle) -> str:
    """Compute a deterministic hash of the bundle's semantic content.

    Used to detect whether a new freeze actually differs from the latest.
    Ignores frozenAt (timestamp) since that's metadata, not content.
    """
    d = bundle.to_dict()
    d.pop("frozenAt", None)
    # Sort keys for determinism
    raw = json.dumps(d, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _read_latest(bundle_dir: Path) -> dict[str, Any] | None:
    """Read the latest.json pointer file."""
    latest_path = bundle_dir / "latest.json"
    if latest_path.exists():
        try:
            return json.loads(latest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _write_latest(bundle_dir: Path, version: int, binding_ast_id: str, frozen_at: str, content_hash: str) -> None:
    """Write latest.json pointer."""
    bundle_dir.mkdir(parents=True, exist_ok=True)
    latest = {
        "version": version,
        "bindingAstId": binding_ast_id,
        "frozenAt": frozen_at,
        "contentHash": content_hash,
    }
    (bundle_dir / "latest.json").write_text(
        json.dumps(latest, indent=2), encoding="utf-8"
    )


def freeze_bundle(bundle: ExecutionBundle) -> dict[str, Any]:
    """Persist an ExecutionBundle as an immutable versioned artifact.

    If the bundle content is identical to the latest frozen version,
    returns the existing frozen artifact (no new version created).

    Returns:
        {"version": N, "bindingAstId": "...", "frozenAt": "...", "path": "...", "isNew": bool}
    """
    template_id = bundle.templateId
    # Freeze key MUST be the dataset signature so consumers can reload via
    # load_frozen_bundle(template_id, BindingAST.datasetSignature). The signature
    # lives on BindingAST.datasetSignature (DatasetAST has no `signature` field).
    # Fall back to datasetId for legacy bundles that carry no signature, then "unknown".
    signature = bundle.bindingAst.datasetSignature or bundle.datasetId or "unknown"
    bundle_dir = _bundle_dir(template_id, signature)
    content_hash = _compute_content_hash(bundle)

    # Check if latest version has same content (idempotent freeze)
    latest = _read_latest(bundle_dir)
    if latest and latest.get("contentHash") == content_hash:
        version = latest["version"]
        bundle_path = bundle_dir / f"v{version}.bundle.json"
        logger.info(
            "[freeze_store] Bundle unchanged — returning existing v%d (hash=%s)",
            version, content_hash,
        )
        return {
            "version": version,
            "bindingAstId": latest["bindingAstId"],
            "frozenAt": latest["frozenAt"],
            "path": str(bundle_path),
            "isNew": False,
        }

    # New version
    version = (latest["version"] + 1) if latest else 1
    frozen_at = datetime.now(timezone.utc).isoformat()

    # Update bundle with freeze metadata
    bundle.frozenAt = frozen_at

    # Write files
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"v{version}.bundle.json"
    binding_path = bundle_dir / f"v{version}.binding.json"

    bundle_dict = bundle.to_dict()
    bundle_path.write_text(
        json.dumps(bundle_dict, indent=2, default=str), encoding="utf-8"
    )

    binding_dict = bundle.bindingAst.to_dict()
    binding_path.write_text(
        json.dumps(binding_dict, indent=2, default=str), encoding="utf-8"
    )

    # Update latest pointer
    _write_latest(bundle_dir, version, bundle.bindingAstId, frozen_at, content_hash)

    logger.info(
        "[freeze_store] Frozen v%d → %s (hash=%s, status=%s)",
        version, bundle_path, content_hash, bundle.status,
    )

    return {
        "version": version,
        "bindingAstId": bundle.bindingAstId,
        "frozenAt": frozen_at,
        "path": str(bundle_path),
        "isNew": True,
    }


def load_frozen_bundle(template_id: str, signature: str, version: int | None = None) -> ExecutionBundle | None:
    """Load a frozen bundle by template+signature (optionally at a specific version).

    If version is None, loads the latest version.

    Returns:
        ExecutionBundle or None if not found.
    """
    bundle_dir = _bundle_dir(template_id, signature)

    if version is None:
        latest = _read_latest(bundle_dir)
        if not latest:
            return None
        version = latest["version"]

    bundle_path = bundle_dir / f"v{version}.bundle.json"
    if not bundle_path.exists():
        return None

    try:
        data = json.loads(bundle_path.read_text(encoding="utf-8"))
        return ExecutionBundle.from_dict(data)
    except (json.JSONDecodeError, OSError, KeyError) as e:
        logger.error("[freeze_store] Failed to load v%d from %s: %s", version, bundle_path, e)
        return None


def get_freeze_info(template_id: str, signature: str) -> dict[str, Any] | None:
    """Get freeze metadata without loading the full bundle."""
    bundle_dir = _bundle_dir(template_id, signature)
    return _read_latest(bundle_dir)
