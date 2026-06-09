"""Number & value formatting for the render layer (R1.1).

Single source of truth for how measured values become display strings, shared by
every server-side renderer (HTML, SVG charts, tables, PDF). The React preview
mirrors this in ``dashboard/lib/report/format.ts``.

Format tokens (from the gold report / blueprint):
    ``percent.1`` → one-decimal percent → ``56.3%``
    ``number.0``  → integer with grouping
    ``unit:"percent"`` (column/axis) → append ``%``
Number systems:
    ``indian``        → ``12,34,567`` (lakh/crore grouping) — DEFAULT for MoSPI
    ``international``  → ``1,234,567`` (thousands grouping)
Empty:
    ``None`` → ``—`` (em dash; the table layer may override per ``emptyPolicy``).
"""
from __future__ import annotations

import html
from typing import Any

EM_DASH = "\u2014"

# Unit → display suffix. Extend as MoSPI units appear (rupee, MW, Mt, …).
_UNIT_SUFFIX = {
    "percent": "%",
    "pct": "%",
    "inr": "\u20b9",          # prefix-handled below
    "rupee": "\u20b9",
    "mw": " MW",
    "million_tonnes": " Mt",
    "mt": " Mt",
}
_PREFIX_UNITS = {"inr", "rupee"}


def parse_format(fmt: str | None) -> tuple[str, int]:
    """Split a format token like ``percent.1`` / ``number.0`` → (kind, decimals).

    Unknown / missing tokens default to ``("number", 1)``.
    """
    if not fmt or not isinstance(fmt, str):
        return ("number", 1)
    kind, _, dec = fmt.partition(".")
    kind = kind.strip().lower() or "number"
    decimals = 1
    if dec:
        try:
            decimals = int(dec)
        except ValueError:
            decimals = 1
    return (kind, decimals)


def _group_indian(int_part: str) -> str:
    """Group an unsigned integer string the Indian way: 12,34,567."""
    if len(int_part) <= 3:
        return int_part
    head, tail = int_part[:-3], int_part[-3:]
    # group the head in pairs from the right
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ",".join(pairs) + "," + tail


def _group_international(int_part: str) -> str:
    return f"{int(int_part):,}"


def _grouped(number: float | int, decimals: int, system: str) -> str:
    neg = number < 0
    n = abs(number)
    if decimals > 0:
        s = f"{n:.{decimals}f}"
        int_part, _, frac = s.partition(".")
    else:
        int_part, frac = f"{round(n):d}", ""
    grouped = _group_indian(int_part) if system == "indian" else _group_international(int_part)
    out = grouped + (("." + frac) if frac else "")
    return ("-" + out) if neg else out


def format_value(
    value: Any,
    *,
    unit: str | None = None,
    fmt: str | None = None,
    system: str = "indian",
    locale: str = "en-IN",
    empty: str = EM_DASH,
) -> str:
    """Format a single value for display.

    - ``None`` → ``empty`` (default em dash).
    - numbers → grouped per ``system`` with decimals from ``fmt``; percent/units
      applied from ``fmt`` kind or ``unit``.
    - non-numbers → HTML-escaped string (passthrough).
    """
    if value is None:
        return empty
    if isinstance(value, bool):  # guard: bool is an int subclass
        return html.escape(str(value))
    if isinstance(value, (int, float)):
        kind, decimals = parse_format(fmt)
        # `number` kind with an int value and no explicit decimals → no forced .0
        if kind == "number" and isinstance(value, int) and (not fmt or "." not in fmt):
            body = _grouped(value, 0, system)
        else:
            body = _grouped(value, decimals, system)
        # percent precedence: format kind first, then column/axis unit
        if kind == "percent" or unit in ("percent", "pct"):
            return f"{body}%"
        u = (unit or "").lower()
        if u in _PREFIX_UNITS:
            return f"{_UNIT_SUFFIX[u]}{body}"
        if u in _UNIT_SUFFIX:
            return f"{body}{_UNIT_SUFFIX[u]}"
        return body
    return html.escape(str(value))


def esc(text: Any) -> str:
    """HTML-escape a value (None → empty string)."""
    return html.escape(str(text if text is not None else ""))
