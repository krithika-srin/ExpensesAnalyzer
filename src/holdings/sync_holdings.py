#!/usr/bin/env python3
"""Sync account balances from the Money sheet into the local DB and build a Net Worth tab.

Pipeline:
    Money sheet ("Holdings YYYY" tabs)  ->  holdings table (SQLite)
    holdings table + transactions table ->  "Net Worth" tab in the Money sheet

The Money sheet stays the place you type balances each month; this script
only reads those tabs and writes a separate "Net Worth" tab.

Examples:
    # Preview what would be synced for every Holdings tab found
    python src/holdings/sync_holdings.py --dry-run

    # Sync 2026 only and rewrite the Net Worth tab (with spending + runway)
    python src/holdings/sync_holdings.py --years 2026 --write-summary

    # Sync without joining expense data
    python src/holdings/sync_holdings.py --write-summary --no-spending
"""

# Standard library
import argparse
import re
import sys
from typing import Dict, List

# Third-party
import pandas as pd
import pygsheets

# Local application
from src.common.env import get_env
from src.common.sheets_sync import _colnum_to_a1, write_to_sheets
from src.common.utils import LOG
from src.constants.gsheets import CURRENCY_FORMAT_PATTERN, SHEETS_AUTHENTICATION_FILE
from src.constants.holdings import (
    HOLDINGS_SPREADSHEET_KEY_ENV,
    HOLDINGS_WORKSHEET_PREFIX,
    WORKSHEET_NET_WORTH,
    NetWorthColumns as C,
)
from src.database import DatabaseManager
from src.export.generate_summaries import fetch_transactions_for_analysis
from src.holdings.holdings_parser import parse_holdings_grid
from src.holdings.net_worth import build_net_worth_table, monthly_spending_from_transactions

_HOLDINGS_TAB_PATTERN = re.compile(rf"^{re.escape(HOLDINGS_WORKSHEET_PREFIX)}(\d{{4}})$")
_PERCENT_FORMAT_PATTERN = "0.00%"
_DECIMAL_FORMAT_PATTERN = "0.0"


def _open_spreadsheet(spreadsheet_key: str):
    gc = pygsheets.authorize(service_account_file=SHEETS_AUTHENTICATION_FILE)
    return gc.open_by_key(spreadsheet_key)


def find_holdings_tabs(sheet) -> Dict[int, object]:
    """Map year -> worksheet for every 'Holdings YYYY' tab."""
    tabs = {}
    for ws in sheet.worksheets():
        match = _HOLDINGS_TAB_PATTERN.match(ws.title.strip())
        if match:
            tabs[int(match.group(1))] = ws
    return dict(sorted(tabs.items()))


def read_year(worksheet, year: int) -> List[Dict]:
    """Read and parse one Holdings tab using the displayed (formatted) values."""
    values = worksheet.get_all_values(
        include_tailing_empty=False,
        include_tailing_empty_rows=False,
        value_render=pygsheets.ValueRenderOption.FORMATTED_VALUE,
    )
    snapshots = parse_holdings_grid(values, year)
    LOG.info(
        "Holdings %d: %d snapshots across %d months",
        year,
        len(snapshots),
        len({s.year_month for s in snapshots}),
    )
    return [s.to_dict() for s in snapshots]


def sync_years(db: DatabaseManager, tabs: Dict[int, object], dry_run: bool) -> List[Dict]:
    """Parse each year and replace that year's rows in the DB (so deletions in the sheet stick)."""
    all_rows: List[Dict] = []
    for year, ws in tabs.items():
        rows = read_year(ws, year)
        all_rows.extend(rows)
        if dry_run:
            continue
        year_months = [f"{year}-{m:02d}" for m in range(1, 13)]
        db.delete_holdings_for_months(year_months)
        written = db.upsert_holdings(rows)
        LOG.info("Holdings %d: wrote %d rows to DB", year, written)
    return all_rows


def _format_net_worth_tab(sheet, df: pd.DataFrame) -> None:
    ws = sheet.worksheet_by_title(WORKSHEET_NET_WORTH)
    currency = {"numberFormat": {"type": "CURRENCY", "pattern": CURRENCY_FORMAT_PATTERN}}
    percent = {"numberFormat": {"type": "PERCENT", "pattern": _PERCENT_FORMAT_PATTERN}}
    decimal = {"numberFormat": {"type": "NUMBER", "pattern": _DECIMAL_FORMAT_PATTERN}}
    for idx, col in enumerate(df.columns, start=1):
        letter = _colnum_to_a1(idx)
        if col in C.CURRENCY:
            ws.apply_format(f"{letter}2:{letter}", currency)
        elif col == C.MOM_CHANGE_PCT:
            ws.apply_format(f"{letter}2:{letter}", percent)
        elif col == C.RUNWAY_MONTHS:
            ws.apply_format(f"{letter}2:{letter}", decimal)


def build_summary(db: DatabaseManager, include_spending: bool) -> pd.DataFrame:
    holdings = db.get_holdings()
    spending = None
    if include_spending:
        spending = monthly_spending_from_transactions(fetch_transactions_for_analysis(None))
    return build_net_worth_table(holdings, spending)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync Money sheet holdings into the DB and build a Net Worth tab",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--sheet-key",
        default=get_env(HOLDINGS_SPREADSHEET_KEY_ENV),
        help=f"Money spreadsheet key (default: {HOLDINGS_SPREADSHEET_KEY_ENV} env var)",
    )
    parser.add_argument("--years", type=int, nargs="*", help="Only sync these years")
    parser.add_argument(
        "--write-summary",
        action="store_true",
        help=f"Rewrite the '{WORKSHEET_NET_WORTH}' tab in the Money sheet",
    )
    parser.add_argument(
        "--no-spending",
        action="store_true",
        help="Do not join monthly spending from the transactions DB",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and preview only")
    args = parser.parse_args()

    if not args.sheet_key:
        parser.error(f"--sheet-key is required (or set {HOLDINGS_SPREADSHEET_KEY_ENV})")

    sheet = _open_spreadsheet(args.sheet_key)
    tabs = find_holdings_tabs(sheet)
    if args.years:
        missing = sorted(set(args.years) - set(tabs))
        if missing:
            parser.error(f"No Holdings tab for: {missing}. Found: {sorted(tabs)}")
        tabs = {y: tabs[y] for y in args.years}

    db = DatabaseManager()
    parsed = sync_years(db, tabs, args.dry_run)

    if args.dry_run:
        summary = build_net_worth_table(parsed)
        print(summary.to_string(index=False))
        return 0

    summary = build_summary(db, include_spending=not args.no_spending)
    print(summary.tail(12).to_string(index=False))

    if args.write_summary:
        # Newest month first, matching the Monthly Summary tab convention
        to_write = summary.sort_values(C.MONTH, ascending=False)
        write_to_sheets(
            to_write,
            worksheet_name=WORKSHEET_NET_WORTH,
            spreadsheet_key=args.sheet_key,
            skip_formatting=True,
        )
        _format_net_worth_tab(sheet, to_write)
    return 0


if __name__ == "__main__":
    sys.exit(main())
