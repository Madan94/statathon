"""R1.2 — deterministic SVG chart kit for the render layer.

Single source of truth for static charts (used by HTML and, later, PDF). Reads
only the §0 ``chartAST`` contract and never invents data: empty series degrade to
an ``empty-slot`` placeholder. Output is deterministic (no randomness, fixed
rounding) so golden snapshots are stable.

Supported ``chartType`` values::

    bar / simple_bar     vertical bars (1 series)
    grouped_bar          clustered bars (N series share x categories)
    stacked_bar          stacked bars (absolute)
    stacked_100          stacked to 100% (distribution)
    line                 time-series / trend (N series)
    pie                  pie slices (1 series)
    donut                pie with a hole

Density rule: when a categorical chart has > ``max_categories`` (12) categories,
bar/grouped/stacked charts flip to **horizontal** orientation and the output
carries a ``data-orientation="horizontal"`` marker.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from .numbers import esc, format_value
from .theme import Theme, get_theme

# Canvas geometry (kept identical to the legacy single-bar chart for snapshot
# continuity on the gold report).
_W, _H = 640, 280
_PAD_L, _PAD_B, _PAD_T, _PAD_R = 48, 40, 16, 16
_PLOT_W = _W - _PAD_L - _PAD_R
_PLOT_H = _H - _PAD_T - _PAD_B
_MAX_CATEGORIES = 12

# Wider canvas + bigger left gutter for horizontal (dense) charts.
_HW, _HH = 640, 420
_H_PAD_L, _H_PAD_R, _H_PAD_T, _H_PAD_B = 150, 56, 16, 28


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _series(chart: dict[str, Any]) -> list[dict[str, Any]]:
    return chart.get("series") or []


def _categories(series: Sequence[dict[str, Any]]) -> list[Any]:
    """Ordered x categories taken from the first non-empty series."""
    for s in series:
        pts = s.get("points") or []
        if pts:
            return [p.get("x") for p in pts]
    return []


def _color_for(point: dict[str, Any], series_idx: int, theme: Theme) -> str:
    return point.get("color") or theme.palette[series_idx % len(theme.palette)]


def _unit(chart: dict[str, Any]) -> str | None:
    return (chart.get("yAxis") or {}).get("unit")


def _empty(msg: str = "[chart has no data]") -> str:
    return f'<div class="empty-slot">{esc(msg)}</div>'


def _svg_open(width: int, height: int, *, title: str | None,
              orientation: str = "vertical", chart_type: str = "") -> str:
    t = f"<title>{esc(title)}</title>" if title else ""
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'xmlns="http://www.w3.org/2000/svg" class="chart" '
        f'data-orientation="{orientation}" data-charttype="{esc(chart_type)}">{t}'
    )


def _legend(series: Sequence[dict[str, Any]], theme: Theme, *, y: int) -> str:
    """Inline legend swatches+labels across the top; returns '' for single series."""
    if len(series) < 2:
        return ""
    parts: list[str] = []
    x = _PAD_L
    for i, s in enumerate(series):
        label = s.get("label") or f"Series {i + 1}"
        color = theme.palette[i % len(theme.palette)]
        parts.append(
            f'<rect x="{x}" y="{y - 9}" width="11" height="11" fill="{color}" rx="2"/>'
        )
        parts.append(
            f'<text x="{x + 16}" y="{y}" font-size="11" fill="{theme.ink}">{esc(label)}</text>'
        )
        x += 22 + 7 * len(str(label))
    return "".join(parts)


def _gridlines_v(vmax: float, unit: str | None, theme: Theme,
                 *, base_y: float) -> list[str]:
    parts: list[str] = []
    for frac in (0.5, 1.0):
        gv = vmax * frac
        gy = base_y - _PLOT_H * frac
        parts.append(
            f'<line x1="{_PAD_L}" y1="{gy:.1f}" x2="{_W - _PAD_R}" y2="{gy:.1f}" '
            f'stroke="{theme.line}" stroke-width="1" opacity="0.5"/>'
        )
        parts.append(
            f'<text x="{_PAD_L - 6}" y="{gy + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="{theme.muted}">'
            f'{format_value(round(gv, 1), unit=unit)}</text>'
        )
    return parts


# ─────────────────────────────────────────────────────────────────────────────
# Vertical bar family
# ─────────────────────────────────────────────────────────────────────────────


def _render_bar_vertical(chart: dict[str, Any], theme: Theme) -> str:
    series = _series(chart)
    points = series[0].get("points") if series else []
    if not points:
        return _empty()
    unit = _unit(chart)
    values = [p.get("y") or 0 for p in points]
    vmax = (max(values) or 1.0) * 1.15
    n = len(points)
    band = _PLOT_W / n
    bar_w = band * 0.65
    base_y = _PAD_T + _PLOT_H

    parts = [_svg_open(_W, _H, title=chart.get("title"), chart_type="bar")]
    parts.append(
        f'<line x1="{_PAD_L}" y1="{base_y}" x2="{_W - _PAD_R}" y2="{base_y}" '
        f'stroke="#999" stroke-width="1"/>'
    )
    parts += _gridlines_v(vmax, unit, theme, base_y=base_y)
    show_labels = n <= 24
    for i, p in enumerate(points):
        v = p.get("y") or 0
        color = _color_for(p, 0, theme)
        bh = (v / vmax) * _PLOT_H if vmax else 0
        bx = _PAD_L + band * i + (band - bar_w) / 2
        by = base_y - bh
        parts.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" '
            f'fill="{color}" rx="2"/>'
        )
        if show_labels:
            parts.append(
                f'<text x="{bx + bar_w / 2:.1f}" y="{by - 5:.1f}" text-anchor="middle" '
                f'font-size="12" fill="{theme.ink}">{format_value(v, unit=unit)}</text>'
            )
            parts.append(
                f'<text x="{bx + bar_w / 2:.1f}" y="{base_y + 16:.1f}" text-anchor="middle" '
                f'font-size="12" fill="{theme.ink}">{esc(p.get("x"))}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _render_grouped_bar(chart: dict[str, Any], theme: Theme) -> str:
    series = _series(chart)
    if not series:
        return _empty()
    cats = _categories(series)
    if not cats:
        return _empty()
    unit = _unit(chart)
    all_vals = [pt.get("y") or 0 for s in series for pt in (s.get("points") or [])]
    vmax = (max(all_vals) or 1.0) * 1.15
    n_cat = len(cats)
    n_ser = len(series)
    band = _PLOT_W / n_cat
    group_w = band * 0.8
    bar_w = group_w / n_ser
    base_y = _PAD_T + _PLOT_H

    parts = [_svg_open(_W, _H, title=chart.get("title"), chart_type="grouped_bar")]
    parts.append(
        f'<line x1="{_PAD_L}" y1="{base_y}" x2="{_W - _PAD_R}" y2="{base_y}" '
        f'stroke="#999" stroke-width="1"/>'
    )
    parts += _gridlines_v(vmax, unit, theme, base_y=base_y)
    parts.append(_legend(series, theme, y=_PAD_T + 4))
    show_labels = n_cat * n_ser <= 16
    for ci in range(n_cat):
        gx = _PAD_L + band * ci + (band - group_w) / 2
        for si, s in enumerate(series):
            pts = s.get("points") or []
            p = pts[ci] if ci < len(pts) else {}
            v = p.get("y") or 0
            color = _color_for(p, si, theme)
            bh = (v / vmax) * _PLOT_H if vmax else 0
            bx = gx + bar_w * si
            by = base_y - bh
            parts.append(
                f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" '
                f'fill="{color}" rx="2"/>'
            )
            if show_labels:
                parts.append(
                    f'<text x="{bx + bar_w / 2:.1f}" y="{by - 4:.1f}" text-anchor="middle" '
                    f'font-size="10" fill="{theme.ink}">{format_value(v, unit=unit)}</text>'
                )
        parts.append(
            f'<text x="{gx + group_w / 2:.1f}" y="{base_y + 16:.1f}" text-anchor="middle" '
            f'font-size="12" fill="{theme.ink}">{esc(cats[ci])}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _render_stacked_bar(chart: dict[str, Any], theme: Theme,
                        *, normalize: bool = False) -> str:
    series = _series(chart)
    if not series:
        return _empty()
    cats = _categories(series)
    if not cats:
        return _empty()
    unit = "percent" if normalize else _unit(chart)
    n_cat = len(cats)
    # Column totals (for headroom / normalization).
    totals = []
    for ci in range(n_cat):
        tot = 0.0
        for s in series:
            pts = s.get("points") or []
            if ci < len(pts):
                tot += pts[ci].get("y") or 0
        totals.append(tot or 1.0)
    vmax = 100.0 if normalize else (max(totals) or 1.0) * 1.10
    band = _PLOT_W / n_cat
    bar_w = band * 0.6
    base_y = _PAD_T + _PLOT_H
    ctype = "stacked_100" if normalize else "stacked_bar"

    parts = [_svg_open(_W, _H, title=chart.get("title"), chart_type=ctype)]
    parts.append(
        f'<line x1="{_PAD_L}" y1="{base_y}" x2="{_W - _PAD_R}" y2="{base_y}" '
        f'stroke="#999" stroke-width="1"/>'
    )
    parts += _gridlines_v(vmax, unit, theme, base_y=base_y)
    parts.append(_legend(series, theme, y=_PAD_T + 4))
    for ci in range(n_cat):
        bx = _PAD_L + band * ci + (band - bar_w) / 2
        cursor = base_y
        col_total = totals[ci]
        for si, s in enumerate(series):
            pts = s.get("points") or []
            p = pts[ci] if ci < len(pts) else {}
            raw = p.get("y") or 0
            v = (raw / col_total * 100.0) if normalize else raw
            color = _color_for(p, si, theme)
            sh = (v / vmax) * _PLOT_H if vmax else 0
            top = cursor - sh
            parts.append(
                f'<rect x="{bx:.1f}" y="{top:.1f}" width="{bar_w:.1f}" height="{sh:.1f}" '
                f'fill="{color}"/>'
            )
            if sh >= 16:
                parts.append(
                    f'<text x="{bx + bar_w / 2:.1f}" y="{top + sh / 2 + 4:.1f}" '
                    f'text-anchor="middle" font-size="10" fill="#fff">'
                    f'{format_value(round(v, 1), unit=unit)}</text>'
                )
            cursor = top
        parts.append(
            f'<text x="{bx + bar_w / 2:.1f}" y="{base_y + 16:.1f}" text-anchor="middle" '
            f'font-size="12" fill="{theme.ink}">{esc(cats[ci])}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Horizontal bar (density fallback)
# ─────────────────────────────────────────────────────────────────────────────


def _render_bar_horizontal(chart: dict[str, Any], theme: Theme) -> str:
    """Single-series horizontal bars; used when categories exceed the limit."""
    series = _series(chart)
    points = series[0].get("points") if series else []
    if not points:
        return _empty()
    unit = _unit(chart)
    values = [p.get("y") or 0 for p in points]
    vmax = (max(values) or 1.0) * 1.15
    n = len(points)
    plot_w = _HW - _H_PAD_L - _H_PAD_R
    plot_h = _HH - _H_PAD_T - _H_PAD_B
    band = plot_h / n
    bar_h = band * 0.7
    base_x = _H_PAD_L

    parts = [_svg_open(_HW, _HH, title=chart.get("title"),
                       orientation="horizontal", chart_type="bar")]
    parts.append(
        f'<line x1="{base_x}" y1="{_H_PAD_T}" x2="{base_x}" y2="{_H_PAD_T + plot_h}" '
        f'stroke="#999" stroke-width="1"/>'
    )
    for frac in (0.5, 1.0):
        gx = base_x + plot_w * frac
        parts.append(
            f'<line x1="{gx:.1f}" y1="{_H_PAD_T}" x2="{gx:.1f}" y2="{_H_PAD_T + plot_h}" '
            f'stroke="{theme.line}" stroke-width="1" opacity="0.5"/>'
        )
        parts.append(
            f'<text x="{gx:.1f}" y="{_H_PAD_T + plot_h + 16:.1f}" text-anchor="middle" '
            f'font-size="11" fill="{theme.muted}">'
            f'{format_value(round(vmax * frac, 1), unit=unit)}</text>'
        )
    for i, p in enumerate(points):
        v = p.get("y") or 0
        color = _color_for(p, 0, theme)
        bw = (v / vmax) * plot_w if vmax else 0
        by = _H_PAD_T + band * i + (band - bar_h) / 2
        parts.append(
            f'<rect x="{base_x:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bar_h:.1f}" '
            f'fill="{color}" rx="2"/>'
        )
        parts.append(
            f'<text x="{base_x - 6:.1f}" y="{by + bar_h / 2 + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="{theme.ink}">{esc(p.get("x"))}</text>'
        )
        parts.append(
            f'<text x="{base_x + bw + 4:.1f}" y="{by + bar_h / 2 + 4:.1f}" text-anchor="start" '
            f'font-size="11" fill="{theme.ink}">{format_value(v, unit=unit)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Line (time-series)
# ─────────────────────────────────────────────────────────────────────────────


def _render_line(chart: dict[str, Any], theme: Theme) -> str:
    series = _series(chart)
    if not series:
        return _empty()
    cats = _categories(series)
    if not cats:
        return _empty()
    unit = _unit(chart)
    all_vals = [pt.get("y") or 0 for s in series for pt in (s.get("points") or [])]
    vmin = min(all_vals + [0])
    vmax = (max(all_vals) or 1.0) * 1.10
    span = (vmax - vmin) or 1.0
    n_cat = len(cats)
    base_y = _PAD_T + _PLOT_H
    step = _PLOT_W / max(n_cat - 1, 1)

    def _x(i: int) -> float:
        return _PAD_L + step * i

    def _y(v: float) -> float:
        return base_y - ((v - vmin) / span) * _PLOT_H

    parts = [_svg_open(_W, _H, title=chart.get("title"), chart_type="line")]
    parts.append(
        f'<line x1="{_PAD_L}" y1="{base_y}" x2="{_W - _PAD_R}" y2="{base_y}" '
        f'stroke="#999" stroke-width="1"/>'
    )
    parts += _gridlines_v(vmax, unit, theme, base_y=base_y)
    parts.append(_legend(series, theme, y=_PAD_T + 4))
    for si, s in enumerate(series):
        pts = s.get("points") or []
        color = theme.palette[si % len(theme.palette)]
        coords = [(_x(i), _y(p.get("y") or 0)) for i, p in enumerate(pts)]
        if coords:
            d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords)
            parts.append(
                f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"/>'
            )
            for x, y in coords:
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>')
    show_x = n_cat <= 16
    if show_x:
        for i, c in enumerate(cats):
            parts.append(
                f'<text x="{_x(i):.1f}" y="{base_y + 16:.1f}" text-anchor="middle" '
                f'font-size="11" fill="{theme.ink}">{esc(c)}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Pie / donut
# ─────────────────────────────────────────────────────────────────────────────


def _render_pie(chart: dict[str, Any], theme: Theme, *, donut: bool = False) -> str:
    series = _series(chart)
    points = series[0].get("points") if series else []
    if not points:
        return _empty()
    values = [(p.get("y") or 0) for p in points]
    total = sum(values) or 1.0
    cx, cy, r = 200.0, _H / 2, 110.0
    inner = r * 0.55 if donut else 0.0
    ctype = "donut" if donut else "pie"

    parts = [_svg_open(_W, _H, title=chart.get("title"), chart_type=ctype)]
    angle = -math.pi / 2  # start at top
    for i, p in enumerate(points):
        v = p.get("y") or 0
        frac = v / total
        sweep = frac * 2 * math.pi
        a0, a1 = angle, angle + sweep
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        large = 1 if sweep > math.pi else 0
        color = _color_for(p, i, theme)
        if donut:
            xi0, yi0 = cx + inner * math.cos(a0), cy + inner * math.sin(a0)
            xi1, yi1 = cx + inner * math.cos(a1), cy + inner * math.sin(a1)
            d = (f"M{x0:.1f},{y0:.1f} A{r:.1f},{r:.1f} 0 {large} 1 {x1:.1f},{y1:.1f} "
                 f"L{xi1:.1f},{yi1:.1f} A{inner:.1f},{inner:.1f} 0 {large} 0 "
                 f"{xi0:.1f},{yi0:.1f} Z")
        else:
            d = (f"M{cx:.1f},{cy:.1f} L{x0:.1f},{y0:.1f} "
                 f"A{r:.1f},{r:.1f} 0 {large} 1 {x1:.1f},{y1:.1f} Z")
        parts.append(f'<path d="{d}" fill="{color}" stroke="#fff" stroke-width="1"/>')
        # Slice label at the mid-angle.
        amid = (a0 + a1) / 2
        lr = r * (0.78 if donut else 0.62)
        lx, ly = cx + lr * math.cos(amid), cy + lr * math.sin(amid)
        if frac >= 0.05:
            parts.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                f'font-size="11" fill="#fff">{format_value(round(frac * 100, 1), unit="percent")}</text>'
            )
        angle = a1
    # Legend on the right.
    lx = 360
    ly = int(cy - len(points) * 9)
    for i, p in enumerate(points):
        color = _color_for(p, i, theme)
        parts.append(f'<rect x="{lx}" y="{ly - 9}" width="11" height="11" fill="{color}" rx="2"/>')
        parts.append(
            f'<text x="{lx + 16}" y="{ly}" font-size="11" fill="{theme.ink}">'
            f'{esc(p.get("x"))}</text>'
        )
        ly += 20
    parts.append("</svg>")
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Public dispatch
# ─────────────────────────────────────────────────────────────────────────────

_DENSE_FALLBACK = {"bar", "simple_bar"}


def render_chart_svg(chart: dict[str, Any] | None, theme: Theme | str | None = None) -> str:
    """Render a ``chartAST`` chart to a deterministic SVG string.

    Unknown/empty charts degrade to an ``empty-slot`` placeholder. Dense
    single-series bar charts (> 12 categories) flip to horizontal.
    """
    if not chart:
        return _empty("[missing chart]")
    th = get_theme(theme)
    ctype = (chart.get("chartType") or "bar").lower()

    if ctype in {"bar", "simple_bar"}:
        cats = _categories(_series(chart))
        if len(cats) > _MAX_CATEGORIES:
            return _render_bar_horizontal(chart, th)
        return _render_bar_vertical(chart, th)
    if ctype == "grouped_bar":
        return _render_grouped_bar(chart, th)
    if ctype == "stacked_bar":
        return _render_stacked_bar(chart, th, normalize=False)
    if ctype in {"stacked_100", "stacked_percent", "distribution"}:
        return _render_stacked_bar(chart, th, normalize=True)
    if ctype in {"line", "time_series", "trend"}:
        return _render_line(chart, th)
    if ctype == "pie":
        return _render_pie(chart, th, donut=False)
    if ctype == "donut":
        return _render_pie(chart, th, donut=True)

    # Unknown type → best-effort vertical bar (graceful, never raises).
    return _render_bar_vertical(chart, th)
