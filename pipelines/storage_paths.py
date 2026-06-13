"""Resolve upload/report paths against repo root (not process cwd)."""
from __future__ import annotations

import os
from pathlib import Path

from pipelines.model_path import repo_root


def _resolve_dir(raw: str) -> Path:
    p = Path(raw.strip() or ".")
    if not p.is_absolute():
        p = repo_root() / p
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def normalize_storage_env() -> None:
    """Pin storage env vars to absolute repo-root paths for the API process."""
    os.environ["UPLOAD_STORAGE_PATH"] = str(
        _resolve_dir(os.getenv("UPLOAD_STORAGE_PATH", "./storage/uploads"))
    )
    os.environ["REPORT_STORAGE_PATH"] = str(
        _resolve_dir(os.getenv("REPORT_STORAGE_PATH", "./storage/reports"))
    )


def upload_storage_dir() -> Path:
    return _resolve_dir(os.getenv("UPLOAD_STORAGE_PATH", "./storage/uploads"))


def report_storage_dir() -> Path:
    return _resolve_dir(os.getenv("REPORT_STORAGE_PATH", "./storage/reports"))


def resolve_dataset_storage_path(storage_path: str | None) -> str | None:
    """Locate a dataset file saved with a relative or legacy path."""
    if not storage_path:
        return None

    p = Path(storage_path)
    if p.is_file():
        return str(p.resolve())

    root = repo_root()
    upload_dir = upload_storage_dir()
    candidates: list[Path] = []

    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.extend(
            [
                Path.cwd() / p,
                root / p,
                root / "api" / p,
                upload_dir / p.name,
                upload_dir / p,
            ]
        )

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return str(resolved)

    if p.is_absolute():
        return str(p)
    return str((root / p).resolve())
