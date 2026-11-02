#!/usr/bin/env python3
"""Create a 'Monthly {YEAR}' tab summarising 'Expenses {YEAR}' by month.

Layout: Category / Subcategory rows, Jan-Dec columns, Total row at the top.
Each category row is followed by its subcategory rows, grouped so they can be
collapsed (show categories only) or expanded (show all subcategories) with the
+/- buttons in the sheet.

Every cell is a live SUMIFS on the 'My Owed' column (your share), so amounts
update automatically as rows are appended to 'Expenses {YEAR}'. The row
structure is fixed at build time: re-run this script when a new category or
subcategory appears. Re-running deletes and rebuilds the tab.
"""

import argparse
import os
import sys
from datetime import datetime

import pygsheets

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.common.env import load_project_env
from src.common.sheets_sync import SHEETS_AUTHENTICATION_FILE, read_from_sheets
from src.constants.export_columns import ExportColumns

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# Columns in 'Expenses {YEAR}' (see ExportColumns): A=Date, C=Category, D=Subcategory, J=My Owed
DATE_COL = "A"
CATEGORY_COL = "C"
SUBCATEGORY_COL = "D"
MY_OWED_COL = "J"
HEADER_ROW = 3
TOTAL_ROW = 4
FIRST_DATA_ROW = 5
NUM_COLS = 2 + len(MONTHS)  # Category, Subcategory, Jan..Dec


def _q(text: str) -> str:
    """Quote a value for use inside a Sheets formula string literal."""
    return '"' + str(text).replace('"', '""') + '"'


def _category_tree(sheet_key: str, year: int) -> dict:
    df = read_from_sheets(sheet_key, f"Expenses {year}")
    if df is None or df.empty:
        return {}
    df = df[df[ExportColumns.CATEGORY].astype(str).str.strip() != ""]
    tree = {}
    for cat, sub in sorted(set(zip(df[ExportColumns.CATEGORY].astype(str), df[ExportColumns.SUBCATEGORY].astype(str)))):
        tree.setdefault(cat, []).append(sub)
    return tree


def build_summary(sheet_key: str, year: int) -> None:
    src = f"'Expenses {year}'"
    dates = f"{src}!${DATE_COL}$2:${DATE_COL}"
    cats = f"{src}!${CATEGORY_COL}$2:${CATEGORY_COL}"
    subs = f"{src}!${SUBCATEGORY_COL}$2:${SUBCATEGORY_COL}"
    owed = f"{src}!${MY_OWED_COL}$2:${MY_OWED_COL}"

    def month_cells(extra_criteria: str) -> list:
        return [
            f'=SUMIFS({owed}{extra_criteria}, {dates}, ">="&DATE({year}, {m}, 1), {dates}, "<"&DATE({year}, {m + 1}, 1))'
            for m in range(1, 13)
        ]

    tree = _category_tree(sheet_key, year)
    rows = [
        [f"Monthly Expenses {year} (my share)"] + [""] * (NUM_COLS - 1),
        [""] * NUM_COLS,
        ["Category", "Subcategory"] + MONTHS,
        ["Total", ""] + month_cells(""),
    ]
    category_rows, groups = [], []  # 0-based row indices
    for cat, sub_list in tree.items():
        category_rows.append(len(rows))
        rows.append([cat, ""] + month_cells(f", {cats}, {_q(cat)}"))
        start = len(rows)
        for sub in sub_list:
            rows.append(["", sub] + month_cells(f", {cats}, {_q(cat)}, {subs}, {_q(sub)}"))
        groups.append((start, len(rows)))

    spreadsheet = pygsheets.authorize(service_account_file=SHEETS_AUTHENTICATION_FILE).open_by_key(sheet_key)
    title = f"Monthly {year}"
    if title in [ws.title for ws in spreadsheet.worksheets()]:
        spreadsheet.del_worksheet(spreadsheet.worksheet_by_title(title))
    ws = spreadsheet.add_worksheet(title, rows=len(rows) + 5, cols=NUM_COLS)
    ws.update_values("A1", rows)

    _format(spreadsheet, ws, len(rows), category_rows, groups)
    print(f"Created '{title}': {len(tree)} categories, {sum(len(s) for s in tree.values())} subcategories.")


def _format(spreadsheet, ws, num_rows: int, category_rows: list, groups: list) -> None:
    sid = ws.id

    def rng(r0, r1, c0=0, c1=NUM_COLS):
        return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}

    def bold(r0, r1, bg=None):
        fmt = {"textFormat": {"bold": True}}
        fields = "userEnteredFormat.textFormat.bold"
        if bg:
            fmt["backgroundColor"] = bg
            fields += ",userEnteredFormat.backgroundColor"
        return {"repeatCell": {"range": rng(r0, r1), "cell": {"userEnteredFormat": fmt}, "fields": fields}}

    requests = [
        {"repeatCell": {
            "range": rng(TOTAL_ROW - 1, num_rows, 2, NUM_COLS),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}}},
            "fields": "userEnteredFormat.numberFormat",
        }},
        bold(0, 1),
        bold(HEADER_ROW - 1, HEADER_ROW, {"red": 0.85, "green": 0.88, "blue": 0.95}),
        bold(TOTAL_ROW - 1, TOTAL_ROW, {"red": 0.93, "green": 0.93, "blue": 0.93}),
        {"updateSheetProperties": {
            "properties": {"sheetId": sid, "gridProperties": {
                "frozenRowCount": TOTAL_ROW, "frozenColumnCount": 2, "rowGroupControlAfter": False}},
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount,gridProperties.rowGroupControlAfter",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 2},
            "properties": {"pixelSize": 170}, "fields": "pixelSize",
        }},
    ]
    requests += [bold(r, r + 1) for r in category_rows]
    groups = [(s, e) for s, e in groups if e > s]
    requests += [{"addDimensionGroup": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": s, "endIndex": e}}}
                 for s, e in groups]
    # Start condensed (categories only); click + to expand.
    requests += [{"updateDimensionGroup": {
        "dimensionGroup": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": s, "endIndex": e},
                           "depth": 1, "collapsed": True},
        "fields": "collapsed",
    }} for s, e in groups]

    spreadsheet.client.sheet.batch_update(spreadsheet.id, requests)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a monthly summary tab from 'Expenses {YEAR}'.")
    parser.add_argument("--year", type=int, default=datetime.now().year)
    args = parser.parse_args()
    load_project_env()
    key = os.getenv("SPREADSHEET_KEY")
    if not key:
        sys.exit("Error: SPREADSHEET_KEY not found in .env")
    build_summary(key, args.year)
