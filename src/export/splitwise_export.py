#!/usr/bin/env python3
"""Export expenses to Google Sheets from Splitwise API.

Key features:
- Dedupe and append support for Splitwise API source
- Overwrite mode for full refresh
- Year-specific filtering
"""
# Standard library
import argparse
import json
import os
import re
from datetime import datetime, date
from typing import List, Optional, Union

# Third-party
import pandas as pd

# Local application
from src.common.env import load_project_env, get_env
from src.constants.config import STATE_PATH
from src.constants.gsheets import DEFAULT_WORKSHEET_NAME

# Load environment variables
load_project_env()

from src.common.sheets_sync import write_to_sheets, read_from_sheets
from src.common.splitwise_client import SplitwiseClient
from src.common.transaction_filters import extract_participant_names
from src.common.utils import (
    load_state,
    save_state_atomic,
    LOG,
    generate_fingerprint,
    parse_date,
)
from src.constants.splitwise import (
    ExcludedSplitwiseDescriptions,
    SPLIT_TYPE_SELF,
    SPLIT_TYPE_SPLIT,
    REFUND_KEYWORDS,
)
from src.constants.export_columns import ExportColumns


def get_current_user_name() -> str:
    """Get current user's first name from Splitwise API."""
    client = SplitwiseClient()
    current_user = client.get_current_user()
    return current_user.getFirstName() if current_user else ""


# Data source constants
SOURCE_SPLITWISE = "splitwise"

# Worksheet name template for year-based exports
WORKSHEET_NAME_TEMPLATE = "Expenses {year}"

# Error messages
ERROR_START_DATE_REQUIRED = (
    "--start-date is required for Splitwise source (or set START_DATE env var)"
)
ERROR_END_DATE_REQUIRED = (
    "--end-date is required for Splitwise source (or set END_DATE env var)"
)
ERROR_DATE_RANGE_INVALID = (
    "Start date ({start_date}) cannot be after end date ({end_date})"
)
ERROR_SHEET_KEY_REQUIRED = (
    "--sheet-key must be provided (or set SPREADSHEET_KEY env var)"
)

# Log messages
LOG_NO_EXPENSES_FOUND = "No expenses found for the date range %s to %s"
LOG_FETCHING_FROM_API = "Fetching expenses from Splitwise API..."
LOG_EXPORTING_FROM = "Exporting from Splitwise API: %s to %s"
LOG_EXPORT_CATEGORIES = "Exporting categories due to --export-categories flag"
LOG_FILTERED_SETTLE = "Filtered out %d Splitwise 'Settle all balances' exact-match transactions from API export"
LOG_FILTERED_PAYMENT = (
    "Filtered out %d Splitwise 'Payment' transactions from API export"
)
LOG_FILTERED_NO_PARTICIPATION = "Filtered out %d expenses where my_paid and my_owed were both zero (no participation)"

# User messages
MSG_NO_NEW_EXPENSES = "No new Splitwise expenses to export (all rows already exported or no participation)."
MSG_PROCESSED_SUCCESS = "Successfully processed {count} expenses"
MSG_NO_EXPENSES_PROCESSED = "No expenses found or processed"


def load_exported_state() -> tuple[set, set]:
    """Load the set of previously exported Splitwise expense IDs and fingerprints.

    Returns:
        A tuple of (exported_ids, exported_fingerprints) as sets
    """
    try:
        state = load_state(STATE_PATH)
        return set(state.get("exported_ids", [])), set(
            state.get("exported_fingerprints", [])
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return set(), set()


def save_exported_state(exported_ids: set, exported_fps: set) -> None:
    """Save the set of exported Splitwise expense IDs and fingerprints.

    Args:
        exported_ids: Set of exported expense IDs
        exported_fps: Set of exported fingerprints
    """
    state = {
        "exported_ids": list(exported_ids),
        "exported_fingerprints": list(exported_fps),
        "last_updated": datetime.now().isoformat(),
    }
    save_state_atomic(STATE_PATH, state)


def _read_existing_fingerprints(
    sheet_key: Optional[str] = None,
    worksheet_name: Optional[str] = None,
) -> Optional[List[str]]:
    """Read existing fingerprints from a Google Sheet.

    Args:
        sheet_key: Google Sheet key/ID
        worksheet_name: Name of the worksheet to read from

    Returns:
        List of fingerprints or None if the sheet couldn't be read
    """
    if not sheet_key or not worksheet_name:
        return None

    df = read_from_sheets(sheet_key, worksheet_name, numerize=False)
    if df is None or ExportColumns.FINGERPRINT not in df.columns:
        return None

    # Return non-empty fingerprints
    return [fp for fp in df[ExportColumns.FINGERPRINT].dropna() if fp]


def export_categories(sheet_key: str = None) -> Optional[str]:
    """Export all Splitwise categories to a 'Splitwise Categories' worksheet.

    Args:
        sheet_key: Google Sheet key/ID

    Returns:
        URL of the updated sheet or None if no categories found
    """
    client = SplitwiseClient()
    categories = client.get_categories()

    # Create a dictionary to hold categories and their subcategories
    category_dict = {}
    for category in categories:
        category_name = category.getName()
        subcategories = []
        if hasattr(category, "getSubcategories"):
            subcategories = [subcat.getName() for subcat in category.getSubcategories()]
        category_dict[category_name] = subcategories

    if not category_dict:
        LOG.warning("No categories found to export")
        return None

    # Find the maximum number of subcategories for any category
    max_subs = max(len(subs) for subs in category_dict.values())

    # Create a list of dictionaries for the DataFrame
    data = []
    for i in range(max_subs):
        row = {}
        for category, subcategories in category_dict.items():
            # Get the subcategory at index i, or empty string if none
            row[category] = subcategories[i] if i < len(subcategories) else ""
        data.append(row)

    # Create DataFrame from the list of dictionaries
    df = pd.DataFrame(data)

    # Reorder columns to match the original category order
    df = df[list(category_dict.keys())]

    # Write to Google Sheets
    url = write_to_sheets(
        df,
        worksheet_name="Splitwise Categories",
        spreadsheet_key=sheet_key,
        append=False,  # Always overwrite the categories sheet
    )
    LOG.info("Exported %d categories to Google Sheets", len(category_dict))
    return url


def fetch_and_write(
    start_date: Union[datetime, date, str],
    end_date: Union[datetime, date, str],
    sheet_key: Optional[str] = None,
    worksheet_name: str = DEFAULT_WORKSHEET_NAME,
    append: bool = True,
    export_categories_flag: bool = False,
    dry_run: bool = False,
) -> tuple[pd.DataFrame, Optional[str]]:
    """Fetch expenses and write to Google Sheets.

    Args:
        start_date: Start date for date range
        end_date: End date for date range
        sheet_key: Google Sheets spreadsheet key
        worksheet_name: Name of worksheet to write to
        append: If True, append to existing data; if False, overwrite
        export_categories_flag: If True, also export Splitwise categories
        dry_run: If True, preview data without writing to sheets or updating state

    Returns:
        Tuple of (DataFrame with expenses, URL of the updated sheet or None)
    """

    # Parse dates if they are strings
    if isinstance(start_date, str):
        start_date = parse_date(start_date)
    if isinstance(end_date, str):
        end_date = parse_date(end_date)

    # Fetch data from Splitwise API
    LOG.info(LOG_FETCHING_FROM_API)
    client = SplitwiseClient()
    df = client.get_my_expenses_by_date_range(start_date, end_date)

    # Filter out Splitwise-generated "Settle all balances" rows
    if df is not None and not df.empty and ExportColumns.DESCRIPTION in df.columns:
        settle_mask = (
            df[ExportColumns.DESCRIPTION]
            .astype(str)
            .str.strip()
            .str.lower()
            .eq(ExcludedSplitwiseDescriptions.SETTLE_ALL_BALANCES.value.lower())
        )

        num_settle = int(settle_mask.sum())
        if num_settle > 0:
            LOG.info(LOG_FILTERED_SETTLE, num_settle)
            df = df[~settle_mask].reset_index(drop=True)

        # Filter out 'Payment' rows
        desc_series = df[ExportColumns.DESCRIPTION].astype(str).str.strip()
        payment_exact = desc_series.str.lower().eq(
            ExcludedSplitwiseDescriptions.PAYMENT.value.lower()
        )
        payment_word = desc_series.str.contains(
            r"\bpayment\b", case=False, na=False
        )

        if ExportColumns.CATEGORY in df.columns:
            category_general = (
                df[ExportColumns.CATEGORY].astype(str).str.strip().eq("General")
            )
        else:
            category_general = pd.Series(True, index=df.index)

        payment_mask = (payment_exact | payment_word) & category_general
        num_pay = int(payment_mask.sum())
        if num_pay > 0:
            LOG.info(LOG_FILTERED_PAYMENT, num_pay)
            df = df[~payment_mask].reset_index(drop=True)

    if df is None or df.empty:
        LOG.info(LOG_NO_EXPENSES_FOUND, start_date, end_date)
        return pd.DataFrame(), None

    is_overwrite = not append

    # Ensure all columns are strings for consistency
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].astype(str)

    # Generate fingerprints
    df[ExportColumns.FINGERPRINT] = df.apply(
        lambda r: generate_fingerprint(
            r.get(ExportColumns.DATE),
            r.get(ExportColumns.AMOUNT),
            r.get(ExportColumns.DESCRIPTION, ""),
        ),
        axis=1,
    )

    if is_overwrite:
        exported_ids, exported_fps = set(), set()
    else:
        exported_ids, exported_fps = load_exported_state()
        if sheet_key:
            sheet_existing_fps = _read_existing_fingerprints(
                sheet_key, worksheet_name
            )
            if sheet_existing_fps:
                exported_fps = set(exported_fps) | set(sheet_existing_fps)
                save_exported_state(exported_ids, exported_fps)

    # Filter new rows
    if not is_overwrite:
        mask_new = ~(
            (df[ExportColumns.ID].isin(exported_ids))
            | (df[ExportColumns.FINGERPRINT].isin(exported_fps))
        )
        new_df = df[mask_new].reset_index(drop=True)
    else:
        new_df = df

    # Filter out no-participation rows
    if (
        not new_df.empty
        and ExportColumns.MY_PAID in new_df.columns
        and ExportColumns.MY_OWED in new_df.columns
    ):
        new_df = new_df.copy()
        new_df[ExportColumns.MY_PAID] = pd.to_numeric(
            new_df[ExportColumns.MY_PAID], errors="coerce"
        ).fillna(0.0)
        new_df[ExportColumns.MY_OWED] = pd.to_numeric(
            new_df[ExportColumns.MY_OWED], errors="coerce"
        ).fillna(0.0)

        before_count = len(new_df)
        participation_mask = (new_df[ExportColumns.MY_PAID] != 0.0) | (
            new_df[ExportColumns.MY_OWED] != 0.0
        )
        new_df = new_df[participation_mask].reset_index(drop=True)
        filtered_count = before_count - len(new_df)
        if filtered_count > 0:
            LOG.info(LOG_FILTERED_NO_PARTICIPATION, filtered_count)

    if new_df.empty:
        print(MSG_NO_NEW_EXPENSES)
        return new_df, None

    if dry_run:
        print(f"\nDRY RUN MODE - No changes made")
        print(f"Transactions to export: {len(new_df)}")
        print(new_df.head(10).to_string(index=False))
        return new_df, None

    # Reorder columns to ensure Subcategory is after Category
    all_cols = [
        ExportColumns.DATE,
        ExportColumns.AMOUNT,
        ExportColumns.CATEGORY,
        ExportColumns.SUBCATEGORY,
        ExportColumns.DESCRIPTION,
        ExportColumns.DETAILS,
        ExportColumns.SPLIT_TYPE,
        ExportColumns.PARTICIPANT_NAMES,
        ExportColumns.MY_PAID,
        ExportColumns.MY_OWED,
        ExportColumns.MY_NET,
        ExportColumns.ID,
        ExportColumns.FINGERPRINT
    ]
    
    # Only keep columns that exist in the dataframe
    df_cols = [c for c in all_cols if c in new_df.columns]
    new_df = new_df[df_cols]

    # Format for Sheets
    if ExportColumns.DATE in new_df.columns:
        parsed = pd.to_datetime(new_df[ExportColumns.DATE], errors="coerce")
        new_df[ExportColumns.DATE] = parsed.dt.strftime("%Y-%m-%d").where(
            parsed.notna(), new_df[ExportColumns.DATE]
        )

    if ExportColumns.AMOUNT in new_df.columns:
        new_df[ExportColumns.AMOUNT] = pd.to_numeric(
            new_df[ExportColumns.AMOUNT], errors="coerce"
        )

    if ExportColumns.FRIENDS_SPLIT in new_df.columns:
        new_df = new_df.drop(columns=[ExportColumns.FRIENDS_SPLIT])

    # Write
    if sheet_key:
        url = write_to_sheets(
            new_df,
            worksheet_name=worksheet_name,
            spreadsheet_key=sheet_key,
            append=append,
        )
    else:
        url = None

    # Update state
    is_overwrite = not append
    if is_overwrite:
        updated_ids = set(new_df[ExportColumns.ID].tolist())
        updated_fps = set(new_df[ExportColumns.FINGERPRINT].tolist())
    else:
        exported_ids, exported_fps = load_exported_state()
        updated_ids = set(exported_ids) | set(new_df[ExportColumns.ID].tolist())
        updated_fps = set(exported_fps) | set(
            new_df[ExportColumns.FINGERPRINT].tolist()
        )
    save_exported_state(updated_ids, updated_fps)

    if not append and export_categories_flag:
        export_categories(sheet_key=sheet_key)

    return new_df, url


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Export expenses to Google Sheets from Splitwise API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--start-date",
        default=get_env("START_DATE"),
        help="Start date. Defaults to START_DATE env var.",
    )
    parser.add_argument(
        "--end-date",
        default=get_env("END_DATE"),
        help="End date. Defaults to END_DATE env var.",
    )
    parser.add_argument(
        "--worksheet",
        dest="worksheet_name",
        default=get_env("EXPENSES_WORKSHEET_NAME", DEFAULT_WORKSHEET_NAME),
        help="Worksheet name.",
    )
    parser.add_argument(
        "--export-categories",
        dest="export_categories",
        action="store_true",
        help="Export Splitwise categories.",
    )
    parser.add_argument(
        "--sheet-key",
        default=os.getenv("SPREADSHEET_KEY"),
        help="Spreadsheet key.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--no-append",
        dest="append",
        action="store_false",
        help="Overwrite instead of append.",
    )
    group.add_argument(
        "--overwrite",
        dest="append",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes.",
    )

    args = parser.parse_args()

    if not args.start_date:
        args.start_date = f"{datetime.now().year}-01-01"
    if not args.end_date:
        args.end_date = f"{datetime.now().year}-12-31"

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)

    if start_date > end_date:
        raise ValueError(ERROR_DATE_RANGE_INVALID.format(start_date=start_date, end_date=end_date))

    if not args.sheet_key and not args.dry_run:
        raise ValueError(ERROR_SHEET_KEY_REQUIRED)

    new_df, url = fetch_and_write(
        start_date=start_date,
        end_date=end_date,
        sheet_key=args.sheet_key,
        worksheet_name=args.worksheet_name,
        append=args.append if args.append is not None else True,
        export_categories_flag=args.export_categories,
        dry_run=args.dry_run,
    )

    if not new_df.empty:
        print(MSG_PROCESSED_SUCCESS.format(count=len(new_df)))
        if url:
            print(f"Updated sheet: {url}")
    else:
        print(MSG_NO_EXPENSES_PROCESSED)

    return 0


if __name__ == "__main__":
    exit(main())
