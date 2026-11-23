"""Read-only loaders for the dashboard: 'Expenses {YEAR}' and the net worth 'Holdings {YEAR}' tabs.

Both return tidy pandas DataFrames. Results are cached for CACHE_SECONDS so
switching pages doesn't hit the Sheets API each time; pass refresh=True to
force a reload.
"""

import functools
import os
import re
import time
from datetime import date

import pandas as pd
import pygsheets

CACHE_SECONDS = 300
DEFAULT_AUTH_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "gsheets_authentication.json")

EXPENSES_TAB = "Expenses {year}"
HOLDINGS_PREFIX = "Holdings "
MONTH_HEADER_ROW = 2  # 'Jan 2026', '', 'Feb 2026', ...
FIRST_ACCOUNT_ROW = 4
TOTALS_LABEL = "Totals"  # account rows stop at this label

# Output columns
DATE, CATEGORY, SUBCATEGORY, DESCRIPTION, AMOUNT, MONTH = "date", "category", "subcategory", "description", "amount", "month"
ACCOUNT, GROUP, BEGIN, END = "account", "group", "beginning", "ending"

_cache: dict = {}


@functools.cache
def _client():
    auth = os.getenv("GSHEETS_AUTH_FILE", DEFAULT_AUTH_FILE)
    return pygsheets.authorize(service_account_file=auth)


def _cached(key: str, loader, refresh: bool):
    hit = _cache.get(key)
    if hit and not refresh and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = loader()
    _cache[key] = (time.time(), value)
    return value


def _to_number(value) -> float:
    """Parse '1,234.50', '$1,234.50', '-$12', '' -> float (blank -> NaN)."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("$", "").replace(",", "").strip()
    if not text:
        return float("nan")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return float(text)
    except ValueError:
        return float("nan")


# ── Expenses ──────────────────────────────────────────────────────────────

def expense_years(sheet_key: str, refresh: bool = False) -> list:
    def load():
        titles = [ws.title for ws in _client().open_by_key(sheet_key).worksheets()]
        return sorted(int(m.group(1)) for t in titles if (m := re.fullmatch(r"Expenses (\d{4})", t)))
    return _cached(f"exp-years:{sheet_key}", load, refresh)


def load_expenses(sheet_key: str, year: int, version: int = 0, refresh: bool = False) -> pd.DataFrame:
    """One row per expense: date, month (1st of month), category, subcategory, description, amount (My Owed)."""
    def load():
        ws = _client().open_by_key(sheet_key).worksheet_by_title(EXPENSES_TAB.format(year=year))
        rows = ws.get_all_values(value_render="UNFORMATTED_VALUE", date_time_render_option="FORMATTED_STRING",
                                 include_tailing_empty_rows=False)
        header, body = rows[0], rows[1:]
        df = pd.DataFrame(body, columns=header)
        out = pd.DataFrame({
            DATE: pd.to_datetime(df["Date"], errors="coerce"),
            CATEGORY: df["Category"].astype(str).str.strip().replace("", "Uncategorized"),
            SUBCATEGORY: df["Subcategory"].astype(str).str.strip().replace("", "General"),
            DESCRIPTION: df["Description"].astype(str).str.strip(),
            AMOUNT: df["My Owed"].map(_to_number).fillna(0.0),
        })
        out = out[out[DATE].notna() & (out[DATE].dt.year == year)].copy()
        out[MONTH] = out[DATE].dt.to_period("M").dt.to_timestamp()
        return out.reset_index(drop=True)
    return _cached(f"exp:{sheet_key}:{year}:{version}", load, refresh)


# ── Net worth ─────────────────────────────────────────────────────────────

def _parse_holdings(values: list) -> pd.DataFrame:
    header = values[MONTH_HEADER_ROW - 1]
    month_cols = {}
    for i, cell in enumerate(header):
        try:
            month_cols[i] = pd.to_datetime(str(cell).strip(), format="%b %Y")
        except ValueError:
            continue
    records, group = [], ""
    for row in values[FIRST_ACCOUNT_ROW - 1:]:
        row = list(row) + [""] * (len(header) + 2 - len(row))
        name = str(row[0]).strip()
        if name == TOTALS_LABEL:
            break
        if not name:
            continue
        if str(row[1]).strip():
            group = str(row[1]).strip()
        sub = str(row[2]).strip()
        account = f"{name} - {sub}" if sub else name
        for col, month in month_cols.items():
            begin, end = _to_number(row[col]), _to_number(row[col + 1])
            if pd.isna(end):
                continue  # month not filled in yet
            records.append({MONTH: month, ACCOUNT: account, GROUP: group,
                            BEGIN: 0.0 if pd.isna(begin) else begin, END: end})
    return pd.DataFrame(records)


def load_net_worth(sheet_key: str, version: int = 0, refresh: bool = False) -> pd.DataFrame:
    """One row per account per month across every 'Holdings {YEAR}' tab: month, account, group, beginning, ending."""
    def load():
        frames = []
        for ws in _client().open_by_key(sheet_key).worksheets():
            if re.fullmatch(r"Holdings \d{4}", ws.title):
                frames.append(_parse_holdings(ws.get_all_values(include_tailing_empty_rows=False)))
        df = pd.concat([f for f in frames if not f.empty], ignore_index=True)
        # A month counts only once every account has an ending balance entered
        # (stops a half-filled current month from showing a fake drop).
        per_month = df.groupby(MONTH)[ACCOUNT].transform("nunique")
        per_year = df.groupby(df[MONTH].dt.year)[ACCOUNT].transform("nunique")
        df = df[per_month == per_year]
        return df.sort_values([MONTH, GROUP, ACCOUNT]).reset_index(drop=True)
    return _cached(f"nw:{sheet_key}:{version}", load, refresh)


def today() -> date:
    return date.today()
