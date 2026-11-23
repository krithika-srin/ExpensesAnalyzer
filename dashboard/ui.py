"""Shared bits for the dashboard pages: settings, nav bar, KPI tiles, formatting."""

import html
import os

from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, "config", ".env"))  # local runs; Render uses real env vars

EXPENSES_KEY = os.getenv("EXPENSES_SPREADSHEET_KEY") or os.getenv("SPREADSHEET_KEY", "")
NET_WORTH_KEY = os.getenv("NET_WORTH_SPREADSHEET_KEY", "")

GROUP_COLORS = {
    "Investment": "#4C78A8", "Savings": "#54A24B", "Retirement": "#F58518",
    "Health Savings": "#B279A2",
}

_PAGES = [("spending", "Spending", "/"), ("net_worth", "Net Worth", "/net-worth")]

STYLE = """
<style>
  .d-nav { display:flex; gap:1.6rem; padding:.7rem 0 .9rem; border-bottom:1px solid #e3e6ec; margin-bottom:1rem;
           font-size:.85rem; letter-spacing:.08em; text-transform:uppercase; }
  .d-nav a { color:#6b7280; text-decoration:none; padding-bottom:.2rem; }
  .d-nav a.active { color:#111827; border-bottom:2px solid #2563eb; font-weight:600; }
  .d-kpis { display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:.8rem; }
  .d-kpi { border:1px solid #e3e6ec; border-radius:8px; padding:.8rem 1rem; background:#fff; }
  .d-kpi-label { font-size:.75rem; color:#6b7280; text-transform:uppercase; letter-spacing:.06em; }
  .d-kpi-value { font-size:1.45rem; font-weight:600; color:#111827; margin-top:.2rem; }
  .d-kpi-sub { font-size:.8rem; color:#6b7280; margin-top:.15rem; }
  .pos { color:#15803d; } .neg { color:#b91c1c; }
</style>
"""


def nav(active: str) -> str:
    links = "".join(
        f'<a href="{path}"{" class=active" if key == active else ""}>{label}</a>'
        for key, label, path in _PAGES
    )
    return STYLE + f'<div class="d-nav">{links}</div>'


def money(value: float, signed: bool = False) -> str:
    sign = "+" if signed and value > 0 else ("-" if value < 0 else "")
    return f"{sign}${abs(value):,.0f}"


def kpi(label: str, value: str, sub: str = "", tone: str = "") -> str:
    return (f'<div class="d-kpi"><div class="d-kpi-label">{html.escape(label)}</div>'
            f'<div class="d-kpi-value {tone}">{value}</div>'
            f'<div class="d-kpi-sub">{sub}</div></div>')


def kpi_row(*tiles: str) -> str:
    return f'<div class="d-kpis">{"".join(tiles)}</div>'


def tone(value: float, good_when_positive: bool = True) -> str:
    if value == 0:
        return ""
    return "pos" if (value > 0) == good_when_positive else "neg"
