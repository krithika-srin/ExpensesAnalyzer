"""Shared bits for the dashboard pages: settings, styling, nav bar and HTML/SVG helpers.

The look (dark "terminal" theme, IBM Plex fonts, orange labels, hand-drawn SVG
charts) follows bsundar2/RobinhoodToSheets' finance_ui.py and
SplitwiseToSheets' spending dashboard, so the household's dashboards match.
marimo's own widgets get the dark theme from .marimo.toml at the repo root.

Each section is one complete HTML string: marimo sanitizes every mo.Html()
call on its own, so a tag opened in one call never wraps another call's output.
"""

import html
import os

from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, "config", ".env"))  # local runs; Render uses real env vars

EXPENSES_KEY = os.getenv("EXPENSES_SPREADSHEET_KEY") or os.getenv("SPREADSHEET_KEY", "")
NET_WORTH_KEY = os.getenv("NET_WORTH_SPREADSHEET_KEY", "")

PALETTE = ["#E8890C", "#00d17a", "#4da3ff", "#c77dff", "#ff4d6a", "#f5d90a", "#5ce1e6", "#8a93a6"]
OTHER_COLOR = "#4a5064"
GROUP_COLORS = {
    "Investment": "#4da3ff", "Savings": "#00d17a", "Retirement": "#E8890C",
    "Health Savings": "#c77dff",
}

_PAGES = [("spending", "Spending", "/"), ("net_worth", "Net Worth", "/net-worth")]

STYLE = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500&display=swap');

  /* Dark behind the cells too, so gaps between sections don't show white */
  body { background: #0a0c0f; }

  /* marimo's "running" indicator: a ring mid-screen instead of its hourglass,
     shown only once cells have run for a second */
  [data-testid="loading-indicator"] {
    position: fixed; top: 50%; left: 50%; width: 44px; height: 44px; margin: -22px 0 0 -22px;
    border-radius: 50%; border: 3px solid #1e2330; border-top-color: #00d17a;
    box-shadow: 0 0 0 10px rgba(10, 12, 15, 0.85); background: rgba(10, 12, 15, 0.85);
    animation: t-spin 0.8s linear infinite, t-appear 0.2s ease-out 1s both;
  }
  [data-testid="loading-indicator"] .running-app-icon { display: none; }
  @keyframes t-spin { to { transform: rotate(360deg); } }
  @keyframes t-appear { from { opacity: 0; } to { opacity: 1; } }

  .terminal { background: #0a0c0f; color: #c8d0e0; font-family: 'IBM Plex Sans', sans-serif;
              width: 100%; box-sizing: border-box; }
  .terminal * { box-sizing: border-box; }

  .t-nav { display: flex; flex-wrap: wrap; gap: 0.4rem 1.6rem; padding: 0.8rem 1.8rem;
           background: #0a0c0f; border-bottom: 1px solid #1e2330;
           font-family: 'IBM Plex Mono', monospace; font-size: 0.82rem; letter-spacing: 0.12em;
           text-transform: uppercase; }
  .t-nav a { color: #8a93a6; text-decoration: none; padding-bottom: 0.2rem; white-space: nowrap; }
  .t-nav a:hover { color: #e8edf5; }
  .t-nav a.active { color: #E8890C; border-bottom: 2px solid #E8890C; }

  .t-header { display: flex; align-items: flex-end; justify-content: space-between; flex-wrap: wrap;
              gap: 0.6rem; padding: 2rem 2.5rem 1.5rem; border-bottom: 1px solid #1e2330; }
  .t-title { font-family: 'IBM Plex Mono', monospace; font-size: 1.3rem; font-weight: 500;
             color: #e8edf5; letter-spacing: 0.08em; text-transform: uppercase; }
  .t-subtitle, .t-kpi-sub, .t-kpi-label, .t-section, .t-legend {
    font-family: 'IBM Plex Mono', monospace; color: #E8890C; }
  .t-subtitle { font-size: 0.9rem; letter-spacing: 0.12em; margin-top: 0.3rem; }
  .t-badge { font-family: 'IBM Plex Mono', monospace; font-size: 0.82rem; letter-spacing: 0.1em;
             color: #00d17a; border: 1px solid #00412a; background: rgba(0,209,122,0.05);
             padding: 0.25rem 0.6rem; border-radius: 2px; }

  .t-filter-row { display: flex; align-items: center; flex-wrap: wrap; gap: 1rem 1.5rem;
                  padding: 1rem 1.8rem; border-bottom: 1px solid #1e2330; background: #13161d; }

  .t-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px;
            background: #1e2330; border-bottom: 1px solid #1e2330; }
  .t-kpi { background: #111318; padding: 1.4rem 1.8rem; position: relative; }
  .t-kpi::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; }
  .t-kpi.pos::before { background: #00d17a; }
  .t-kpi.neg::before { background: #ff4d6a; }
  .t-kpi.amb::before { background: #f5a623; }
  .t-kpi.hi::before  { background: #E8890C; }
  .t-kpi-label { font-size: 0.82rem; letter-spacing: 0.15em; text-transform: uppercase; margin-bottom: 0.6rem; }
  .t-kpi-value { font-family: 'IBM Plex Mono', monospace; font-size: 2rem; font-weight: 600;
                 line-height: 1; color: #e8edf5; }
  .t-kpi-value.pos { color: #00d17a; }
  .t-kpi-value.neg { color: #ff4d6a; }
  .t-kpi-sub { font-size: 0.85rem; margin-top: 0.45rem; }

  .t-section { font-size: 0.82rem; letter-spacing: 0.16em; text-transform: uppercase;
               padding: 1.4rem 1.8rem 0.7rem; border-top: 1px solid #1e2330;
               background: #13161d; border-bottom: 1px solid #1e2330; }
  .t-note { font-family: 'IBM Plex Mono', monospace; font-size: 0.8rem; letter-spacing: 0.04em;
            padding: 0.9rem 1.8rem; color: #8a93a6; }
  .t-legend { display: flex; flex-wrap: wrap; gap: 0.4rem 1.5rem; padding: 1rem 1.8rem 0;
              font-size: 0.78rem; letter-spacing: 0.1em; }
  .t-chart { padding: 0.5rem 1.8rem 1.2rem; }

  .t-table-wrap { overflow-x: auto; }
  .t-table { width: 100%; border-collapse: collapse; font-family: 'IBM Plex Mono', monospace; font-size: 0.9rem; }
  .t-table th { text-align: left; font-size: 0.76rem; font-weight: 500; letter-spacing: 0.1em;
                text-transform: uppercase; color: #E8890C; padding: 0.6rem 1.8rem;
                border-bottom: 1px solid #1e2330; background: #0a0c0f; white-space: nowrap; }
  .t-table td { padding: 0.7rem 1.8rem; border-bottom: 1px solid #1a1e28; color: #c8d0e0; white-space: nowrap; }
  .t-table th.num, .t-table td.num { text-align: right; }
  .t-table tr:last-child td { border-bottom: none; }
  .t-table tr:hover td { background: rgba(255,255,255,0.018); }
  .t-table tr.total td { font-weight: 600; color: #e8edf5; border-top: 1px solid #1e2330; }
  .t-table td.tk  { font-weight: 600; color: #e8edf5; }
  .t-table td.pos { color: #00d17a; }
  .t-table td.neg { color: #ff4d6a; }
  .t-table td.dim { color: #7a8296; }

  /* <details>/<summary>: a one-line summary that opens into the table, no JS */
  .t-collapsible summary { cursor: pointer; list-style: none; display: flex; align-items: center;
    justify-content: space-between; gap: 1rem; padding: 0.9rem 1.8rem;
    font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; color: #c8d0e0; }
  .t-collapsible summary::-webkit-details-marker { display: none; }
  .t-collapsible summary::marker { content: ""; }
  .t-collapsible summary:hover { background: rgba(255,255,255,0.02); }
  .t-collapsible summary::after { content: '\\25B8'; color: #E8890C; font-size: 0.8rem; flex-shrink: 0;
                                  transition: transform 0.15s ease; }
  .t-collapsible[open] summary::after { transform: rotate(90deg); }
  .t-collapsible-hint { color: #7a8296; }

  .bar-row { display: flex; align-items: center; gap: 0.9rem; padding: 0.55rem 1.8rem; }
  .bar-label { font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; color: #c8d0e0; width: 190px;
               flex-shrink: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bar-track { flex: 1; height: 14px; background: #1a1e28; border-radius: 2px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 2px; }
  .bar-value { font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; color: #e8edf5;
               width: 150px; text-align: right; flex-shrink: 0; }

  @media (max-width: 640px) {
    .t-header { padding: 1.4rem 1.2rem 1rem; }
    .t-kpis { grid-template-columns: repeat(2, 1fr); }
    .t-kpi { padding: 1rem 1.1rem; }
    .t-kpi-value { font-size: 1.4rem; }
    .t-section { padding: 1.1rem 1.2rem 0.6rem; }
    .t-table th, .t-table td { padding: 0.55rem 1rem; }
    .t-table { font-size: 0.8rem; }
    .t-chart, .t-legend, .t-note, .t-filter-row, .t-nav { padding-left: 1.2rem; padding-right: 1.2rem; }
    .t-collapsible summary, .bar-row { padding-left: 1.2rem; padding-right: 1.2rem; }
    .bar-label { width: 110px; }
    .bar-value { width: 110px; }
  }
</style>
"""

_MONO = "IBM Plex Mono, monospace"


def esc(text) -> str:
    return html.escape(str(text))


def money(value: float, signed: bool = False) -> str:
    sign = "+" if signed and value > 0 else ("-" if value < 0 else "")
    return f"{sign}${abs(value):,.0f}"


def tone(value: float, good_when_positive: bool = True) -> str:
    """'pos' (green) or 'neg' (red) depending on whether the change is good; '' for zero."""
    if value == 0:
        return ""
    return "pos" if (value > 0) == good_when_positive else "neg"


def block(*parts: str) -> str:
    """One self-contained dark section (see module docstring)."""
    return f'<div class="terminal">{"".join(parts)}</div>'


def nav(active: str) -> str:
    """Page styles plus the menu bar; rendered once at the top of each page."""
    links = "".join(
        f'<a href="{path}" target="_top"{" class=active" if key == active else ""}>{label}</a>'
        for key, label, path in _PAGES
    )
    return STYLE + block(f'<nav class="t-nav">{links}</nav>')


def header(title: str, subtitle: str, badge: str = "Google Sheet") -> str:
    return (f'<div class="t-header"><div><div class="t-title">&#9670; {esc(title)}</div>'
            f'<div class="t-subtitle">{esc(subtitle)}</div></div>'
            f'<div class="t-badge">{esc(badge.upper())}</div></div>')


def section(title: str) -> str:
    return f'<div class="t-section">{esc(title)}</div>'


def note(text: str) -> str:
    return f'<div class="t-note">{text}</div>'


def kpi(label: str, value: str, sub: str = "", cls: str = "hi", value_cls: str = "") -> str:
    """A headline tile. cls colors the strip on top (hi/amb/pos/neg); value_cls colors the figure."""
    return (f'<div class="t-kpi {cls}"><div class="t-kpi-label">{esc(label)}</div>'
            f'<div class="t-kpi-value {value_cls}">{value}</div>'
            f'<div class="t-kpi-sub">{sub}</div></div>')


def kpi_row(*tiles: str) -> str:
    return f'<div class="t-kpis">{"".join(tiles)}</div>'


def legend(names, colors) -> str:
    return '<div class="t-legend">' + "".join(
        f'<span style="color:{c}">&#9632; {esc(n)}</span>' for n, c in zip(names, colors)) + "</div>"


def table(headers, rows, num_from: int = 1, total_last: bool = False) -> str:
    """rows are lists of (text, css class). Columns from num_from on are right-aligned numbers."""
    head = "".join(f'<th class="{"num" if i >= num_from else ""}">{esc(h)}</th>' for i, h in enumerate(headers))
    body = []
    for r, row in enumerate(rows):
        row_cls = ' class="total"' if total_last and r == len(rows) - 1 else ""
        cells = "".join(f'<td class="{cls}{" num" if i >= num_from else ""}">{text}</td>'
                        for i, (text, cls) in enumerate(row))
        body.append(f"<tr{row_cls}>{cells}</tr>")
    return (f'<div class="t-table-wrap"><table class="t-table"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def fold(hint: str, headline: str, body: str, open_: bool = False) -> str:
    """A table folded under a one-line summary; closed until clicked unless open_."""
    return (f'<details class="t-collapsible"{" open" if open_ else ""}><summary>'
            f'<span class="t-collapsible-hint">{hint}</span><span>{headline}</span></summary>{body}</details>')


def bar_rows(items) -> str:
    """Horizontal bars: items are (label, value, value text, color), scaled to the largest value."""
    top = max((v for _, v, _, _ in items), default=0) or 1
    return "".join(
        f'<div class="bar-row"><div class="bar-label" title="{esc(label)}">{esc(label)}</div>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{max(v / top * 100, 1):.1f}%;background:{color};"></div></div>'
        f'<div class="bar-value">{text}</div></div>'
        for label, v, text, color in items
    )


def stacked_bars_svg(labels, series, colors, line=None, line_color="#e8edf5") -> str:
    """Bars stacked per label: positive values up from zero, negative ones down.
    series is {name: [value per label]}; line is an optional [value per label]
    drawn over the bars on the same scale. Hover a bar for its value."""
    W, H = 1200, 340
    ML, MR, MT, MB = 80, 20, 20, 40
    PW, PH = W - ML - MR, H - MT - MB
    n = max(len(labels), 1)
    slot = PW / n
    bar_w = slot * 0.6
    every = max(1, -(-n // 14))  # thin the month labels so they don't overlap

    tops = [sum(max(s[i], 0) for s in series.values()) for i in range(len(labels))]
    bottoms = [sum(min(s[i], 0) for s in series.values()) for i in range(len(labels))]
    hi = max(tops + list(line or []) + [0])
    lo = min(bottoms + list(line or []) + [0])
    if hi == lo:
        hi = lo + 1

    def y(v):
        return MT + (hi - v) / (hi - lo) * PH

    parts = [
        f'<line x1="{ML}" y1="{y(0):.1f}" x2="{W - MR}" y2="{y(0):.1f}" stroke="#3a4152" stroke-width="1"/>',
        f'<text x="{ML - 8}" y="{y(hi) + 4:.1f}" fill="#8a93a6" font-size="11" text-anchor="end" font-family="{_MONO}">{money(hi)}</text>',
    ]
    if lo < 0:
        parts.append(f'<text x="{ML - 8}" y="{y(lo) + 4:.1f}" fill="#8a93a6" font-size="11" '
                     f'text-anchor="end" font-family="{_MONO}">{money(lo)}</text>')
    for i, label in enumerate(labels):
        x = ML + i * slot + (slot - bar_w) / 2
        up, down = 0.0, 0.0
        for (name, values), color in zip(series.items(), colors):
            v = values[i]
            if v >= 0:
                y0, y1 = y(up + v), y(up)
                up += v
            else:
                y0, y1 = y(down), y(down + v)
                down += v
            if y1 - y0 > 0.2:
                parts.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" height="{y1 - y0:.1f}" '
                             f'fill="{color}" opacity="0.85"><title>{esc(label)} · {esc(name)}: {money(v)}</title></rect>')
        if i % every == 0:
            parts.append(f'<text x="{ML + i * slot + slot / 2:.1f}" y="{H - MB + 20}" fill="#E8890C" font-size="11" '
                         f'text-anchor="middle" font-family="{_MONO}">{esc(label)}</text>')
    if line:
        pts = [(ML + i * slot + slot / 2, y(v)) for i, v in enumerate(line)]
        parts.append('<polyline points="' + " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
                     + f'" fill="none" stroke="{line_color}" stroke-width="2"/>')
        parts += [f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{line_color}">'
                  f'<title>{esc(labels[i])}: {money(line[i])}</title></circle>'
                  for i, (px, py) in enumerate(pts)]
    return f'<svg viewBox="0 0 {W} {H}" width="100%" style="height:auto;display:block;">{"".join(parts)}</svg>'
