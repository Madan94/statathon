"""Resolve Poppler bin directory for pdf2image (Windows/local dev)."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_UNSET = object()
_CACHED: str | None | object = _UNSET


def _has_pdftoppm(directory: Path) -> bool:
    return (directory / "pdftoppm.exe").is_file() or (directory / "pdftoppm").is_file()


def _normalize_bin(path: Path) -> Path | None:
    path = path.expanduser().resolve()
    if path.is_file():
        path = path.parent
    if path.is_dir() and _has_pdftoppm(path):
        return path
    return None


def _winget_poppler_bins() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    packages = Path(local) / "Microsoft" / "WinGet" / "Packages"
    if not packages.is_dir():
        return []
    bins: list[Path] = []
    for pkg in packages.glob("oschwartz10612.Poppler*"):
        for candidate in pkg.glob("poppler-*/Library/bin"):
            if _has_pdftoppm(candidate):
                bins.append(candidate)
    return bins


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []

    env_path = os.getenv("POPPLER_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path))

    which = shutil.which("pdftoppm")
    if which:
        candidates.append(Path(which))

    for fixed in (
        Path(r"C:\poppler\Library\bin"),
        Path(r"C:\poppler\bin"),
    ):
        candidates.append(fixed)

    candidates.extend(_winget_poppler_bins())
    return candidates


def resolve_poppler_path(*, refresh: bool = False) -> str | None:
    """Return Poppler bin directory, or None when running in Docker/Linux PATH."""
    global _CACHED
    if not refresh and _CACHED is not _UNSET:
        return _CACHED  # type: ignore[return-value]

    resolved: str | None = None
    for candidate in _candidate_paths():
        normalized = _normalize_bin(candidate)
        if normalized is None:
            continue
        resolved = str(normalized)
        break

    if resolved:
        current = os.getenv("POPPLER_PATH", "").strip()
        if current != resolved:
            os.environ["POPPLER_PATH"] = resolved
            if current and current != resolved:
                logger.warning(
                    "POPPLER_PATH was invalid (%s); using %s",
                    current,
                    resolved,
                )
            else:
                logger.info("Resolved Poppler bin: %s", resolved)
    elif os.getenv("POPPLER_PATH"):
        logger.warning(
            "POPPLER_PATH=%s is invalid and Poppler was not found on PATH",
            os.getenv("POPPLER_PATH"),
        )

    _CACHED = resolved
    return resolved
