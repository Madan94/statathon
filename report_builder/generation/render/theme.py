"""Theme registry for the render layer (R1.1).

A ``Theme`` bundles the palette, typography, page setup and chrome colors that the
HTML/SVG/table/PDF renderers consume. Three presets ship; ``mospi_navy`` is the
default and reproduces the original renderer's look so existing snapshots hold.

Bilingual note: ``font_body``/``font_head`` include a Devanagari fallback so the
hi-IN locale renders correctly in both HTML and (later) WeasyPrint PDF.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Categorical fallback palette (mirrors the filler) when a point has no colour.
_MOSPI_PALETTE = ["#1F7A1F", "#0B5394", "#B45F06", "#741B47", "#594F8D", "#0C6E6E"]
_SAFFRON_PALETTE = ["#B45F06", "#1F7A1F", "#0B5394", "#741B47", "#8D5A00", "#0C6E6E"]
_NEUTRAL_PALETTE = ["#374151", "#6B7280", "#9CA3AF", "#4B5563", "#1F2937", "#D1D5DB"]

_FONT_STACK = '"Segoe UI", Roboto, Helvetica, Arial, "Noto Sans Devanagari", sans-serif'


@dataclass
class Theme:
    """A named visual theme."""

    id: str
    name: str
    accent: str
    ink: str = "#1a1a1a"
    muted: str = "#5a5a5a"
    line: str = "#d9d9d9"
    th_bg: str = "#f3f6fa"
    group_bg: str = "#e8eef6"
    palette: list[str] = field(default_factory=lambda: list(_MOSPI_PALETTE))
    font_body: str = _FONT_STACK
    font_head: str = _FONT_STACK
    page_size: str = "A4"
    margins: str = "18mm"
    logo_ref: str | None = None


THEMES: dict[str, Theme] = {
    "mospi_navy": Theme(
        id="mospi_navy", name="MoSPI Navy", accent="#0B5394",
        palette=list(_MOSPI_PALETTE),
    ),
    "mospi_saffron": Theme(
        id="mospi_saffron", name="MoSPI Saffron", accent="#B45F06",
        palette=list(_SAFFRON_PALETTE), group_bg="#f6efe8", th_bg="#faf6f3",
    ),
    "neutral_grey": Theme(
        id="neutral_grey", name="Neutral Grey", accent="#374151",
        palette=list(_NEUTRAL_PALETTE), group_bg="#eef0f2", th_bg="#f5f6f7",
    ),
}

DEFAULT_THEME_ID = "mospi_navy"


def get_theme(theme: "Theme | str | None") -> Theme:
    """Resolve a Theme from an id / Theme / None (→ default navy)."""
    if isinstance(theme, Theme):
        return theme
    if isinstance(theme, str) and theme in THEMES:
        return THEMES[theme]
    return THEMES[DEFAULT_THEME_ID]


def theme_css(theme: "Theme | str | None" = None) -> str:
    """Document CSS for a theme (screen). Print/@page CSS is added in document.py (R1.4)."""
    t = get_theme(theme)
    return f"""
:root {{ --ink:{t.ink}; --muted:{t.muted}; --line:{t.line}; --accent:{t.accent};
        --th-bg:{t.th_bg}; --group-bg:{t.group_bg}; }}
* {{ box-sizing: border-box; }}
body {{ font-family: {t.font_body};
       color: var(--ink); margin: 0; padding: 32px; line-height: 1.5; }}
.report {{ max-width: 820px; margin: 0 auto; }}
.report-header {{ border-bottom: 2px solid var(--accent); padding-bottom: 12px; margin-bottom: 24px; }}
.report-header h1 {{ margin: 0 0 4px; font-size: 22px; font-family: {t.font_head}; }}
.report-meta {{ color: var(--muted); font-size: 13px; }}
section.report-section {{ margin-bottom: 28px; }}
section.report-section > h2 {{ font-size: 18px; border-left: 4px solid var(--accent);
       padding-left: 10px; margin: 0 0 12px; font-family: {t.font_head}; }}
p.block {{ margin: 0 0 12px; text-align: justify; }}
figure {{ margin: 0 0 18px; }}
figure figcaption {{ color: var(--muted); font-size: 13px; margin-top: 6px; font-style: italic; }}
table {{ border-collapse: collapse; width: 100%; margin: 0 0 8px; font-size: 14px; }}
table caption {{ caption-side: top; text-align: left; font-weight: 600; margin-bottom: 6px; }}
th, td {{ border: 1px solid var(--line); padding: 6px 10px; }}
th {{ background: var(--th-bg); text-align: left; }}
td.measure, th.measure {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr.subtotal td {{ font-weight: 700; background: var(--group-bg); }}
.colgroup-head th {{ text-align: center; background: var(--group-bg); }}
.footnotes {{ color: var(--muted); font-size: 12px; margin: 4px 0 0; padding-left: 16px; }}
.empty-slot {{ color: #b00; font-style: italic; }}
"""
