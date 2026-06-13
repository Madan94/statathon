"""Rich console logging for the BharatStat API.

Produces structured, color-coded, easy-to-scan logs with icons for pipeline events.
Falls back to plain logging when `rich` is unavailable (e.g. CI environments).

Usage:
    from logging_setup import configure_rich_logging
    configure_rich_logging()  # call once, at process startup

Conventions for log message prefixes (parsed and colored by RichHandler):
    [req_xxxxxxxx]   per-request id   (cyan)
    [job N]          background job   (magenta)
    [pdf_loader]     PDF cascade      (yellow)
    [blueprint.*]    AST compile      (green)
    [db]             database         (red on error)

Emoji legend (use sparingly, only at decisive moments):
    ▶  start              ✓  success            ✗  failure
    ⏱  timing             ⚠  warning            🔁 fallback
    📥  upload received   📤  artifact written  💾 db write
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any


def configure_rich_logging(level: int | str = logging.INFO) -> None:
    """Replace root handlers with a rich console handler.

    Idempotent: safe to call multiple times.
    """
    level = logging.getLevelName(level) if isinstance(level, str) else level
    root = logging.getLogger()
    # Remove existing handlers so basicConfig from libraries does not double-log
    for h in list(root.handlers):
        root.removeHandler(h)

    use_plain = os.getenv("LOG_PLAIN", "false").strip().lower() in ("1", "true", "yes")
    width = int(os.getenv("LOG_WIDTH", "0") or "0") or None

    if use_plain:
        _configure_plain(level)
        return

    try:
        from rich.console import Console
        from rich.logging import RichHandler
        from rich.theme import Theme
    except ImportError:
        _configure_plain(level)
        logging.warning("rich not installed — using plain logging (pip install rich)")
        return

    theme = Theme({
        "logging.level.debug": "dim cyan",
        "logging.level.info": "bold cyan",
        "logging.level.warning": "bold yellow",
        "logging.level.error": "bold red",
        "logging.level.critical": "bold white on red",
        # Custom highlighters
        "log.time": "dim white",
        "log.path": "dim",
        "repr.tag_start": "bold magenta",
        "repr.tag_end": "bold magenta",
    })

    console = Console(
        theme=theme,
        force_terminal=True,
        width=width,
        # Honor user's $NO_COLOR; otherwise force colors so PowerShell shows them
        no_color=os.getenv("NO_COLOR") is not None,
    )

    handler = RichHandler(
        console=console,
        show_time=True,
        show_level=True,
        show_path=False,            # We carry our own prefixes — path noise is distracting
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        tracebacks_word_wrap=False,
        markup=False,                # Avoid accidental markup injection from user data
        omit_repeated_times=False,
        log_time_format="[%H:%M:%S]",
    )
    handler.setLevel(level)

    root.setLevel(level)
    root.addHandler(handler)

    # Quiet down chatty libraries
    for noisy in (
        "watchfiles.main",
        "httpcore",
        "httpx",
        "urllib3.connectionpool",
        "asyncio",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Uvicorn uses its own loggers — re-route them through us
    for uv in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(uv)
        for h in list(lg.handlers):
            lg.removeHandler(h)
        lg.propagate = True

    logging.getLogger(__name__).info(
        "▶ rich logging initialised  level=%s  width=%s",
        logging.getLevelName(level), width or "auto",
    )


def _configure_plain(level: int) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)


def banner(text: str, *, char: str = "─", width: int = 78) -> str:
    """Return a one-line section header. Use sparingly to mark phase changes."""
    pad = max(0, width - len(text) - 4)
    left = char * (pad // 2)
    right = char * (pad - pad // 2)
    return f"{left}  {text}  {right}"
