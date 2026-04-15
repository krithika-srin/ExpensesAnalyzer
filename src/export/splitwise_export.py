#!/usr/bin/env python3
"""Export expenses to Google Sheets from Splitwise API or local database.

Supports two data sources:
1. Splitwise API (live data) - default behavior
2. Local database (synced data) - Phase 3 database-first approach

Key features:
- Dedupe and append support for Splitwise API source
- Database source exports unwritten transactions with write tracking
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
from src.common.transaction_filters import extract_participant_names, is_user_participant
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
from src.database import DatabaseManager


def get_current_user_name() -> str:
    """Get current user's first name from Splitwise API."""
    client = SplitwiseClient()
    current_user = client.get_current_user()
    return current_user.getFirstName() if current_user else ""


# Data source constants
SOURCE_SPLITWISE = "splitwise"
SOURCE_DATABASE = "database"

# Worksheet name template for year-based exports
WORKSHEET_NAME_TEMPLATE = "Expenses {year}"

# Error messages
ERROR_START_DATE_REQUIRED = (
    "--start-date is required for Splitwise source (or set START_DATE env var)"
)
ERROR_END_DATE_REQUIRED = (
    "--end-date is required for Splitwise source (or set END_DATE env var)"
)
ERROR_DATABASE_FILTER_REQUIRED = (
    "Database source requires either --year or both --start-date and --end-date"
)
ERROR_DATE_RANGE_INVALID = (
    "Start date ({start_date}) cannot be after end date ({end_date})"
)
ERROR_SHEET_KEY_REQUIRED = (
    "--sheet-key must be provided (or set SPREADSHEET_KEY env var)"
)

# Log messages
LOG_NO_TRANSACTIONS_DB = "No transactions found in database for the specified filters"
LOG_NO_EXPENSES_FOUND = "No expenses found for the date range %s to %s"
LOG_FETCHED_FROM_DB = "Fetched %d transactions from database"
LOG_FETCHING_FROM_DB = "Fetching expenses from local database..."
LOG_FETCHING_FROM_API = "Fetching expenses from Splitwise API..."
LOG_EXPORTING_FROM = "Exporting from %s source: %s to %s"
LOG_MARKED_WRITTEN = "Marked %d transactions as written to sheet"
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


def fetch_from_database(
    start_date: Union[datetime, date, str],
    end_date: Union[datetime, date, str],
    year: Optional[int] = None,
    include_written: bool = False,
) -> pd.DataFrame:
    """Fetch expenses from local database.

    Args:
        start_date: Start date for filtering
        end_date: End date for filtering
        year: Optional year filter (overrides date range)
        include_written: If True, include already-written transactions

    Returns:
        DataFrame with database transactions matching Splitwise export format
    """
    current_user_name = get_current_user_name()

    db = DatabaseManager()

    # Get transactions based on filters
    if year and not include_written:
        # Get unwritten for specific year (most common Phase 3 use case)
        transactions = db.get_unwritten_transactions(year=year)
    elif year:
        # Get all transactions for year (for overwrite mode)
        transactions = db.get_transactions_by_date_range(
            start_date=f"{year}-01-01", end_date=f"{year}-12-31"
        )
    else:
        # Get by date range
        transactions = db.get_transactions_by_date_range(
            start_date=str(start_date), end_date=str(end_date)
        )

    if not transactions:
        return pd.DataFrame()

    # Convert to DataFrame matching Splitwise export format (all columns)
    rows = []
    for txn in transactions:
        # Skip deleted transactions
        if txn.splitwise_deleted_at:
            continue

        # Parse notes field for payment information
        # Format: "Imported from Splitwise API | Paid: $X.XX | Owe: $Y.YY | With: name1, name2"
        # or: "cc_reference_id: XXX | Imported from Splitwise API | ..."
        my_paid = 0.0
        my_owed = 0.0
        details = ""

        if txn.notes:
            # Extract cc_reference_id for details (just the ID number)
            cc_ref_match = re.search(r"cc_reference_id:\s*(\d+)", txn.notes)
            if cc_ref_match:
                details = cc_ref_match.group(1)

            # Extract MY_PAID
            paid_match = re.search(r"Paid:\s*\$?\s*(-?[\d,]+\.?\d*)", txn.notes)
            if paid_match:
                my_paid = float(paid_match.group(1).replace(",", ""))

            # Extract MY_OWED
            owe_match = re.search(r"Owe:\s*\$?\s*(-?[\d,]+\.?\d*)", txn.notes)
            if owe_match:
                my_owed = float(owe_match.group(1).replace(",", ""))

        # Skip transactions where the current user is not a participant
        if not is_user_participant(txn, current_user_name):
            continue

        # Extract participant names for the row
        participant_names = extract_participant_names(txn.notes)

        # Check if this is a refund (either flagged in DB or detected by description)
        description = txn.description or txn.merchant or ""
        is_refund_by_description = any(
            keyword in description.lower() for keyword in REFUND_KEYWORDS
        )
        is_refund = txn.is_refund or is_refund_by_description

        # Calculate amount: negative for refunds, positive for expenses
        raw_amount = txn.raw_amount if txn.raw_amount else txn.amount
        if is_refund:
            amount = -abs(raw_amount)
        else:
            amount = abs(raw_amount)

        # For refunds, negate both my_owed and my_paid (if extracted)
        if is_refund:
            my_owed = -abs(my_owed)
            my_paid = -abs(my_paid)

        # If payment info not extracted (still 0), set based on split type
        if my_paid == 0.0 and my_owed == 0.0:
            split_type = SPLIT_TYPE_SPLIT if txn.is_shared else SPLIT_TYPE_SELF
            if split_type == SPLIT_TYPE_SELF:
                my_paid = amount
                my_owed = amount
            else:
                # Assume 50/50 split
                my_paid = amount / 2
                my_owed = amount / 2

        # Calculate MY_NET
        my_net = my_paid - my_owed

        # Determine split type
        split_type = txn.split_type or (
            SPLIT_TYPE_SPLIT if txn.is_shared else SPLIT_TYPE_SELF
        )

        # Create row in exact column order to match existing exports
        row = {
            ExportColumns.DATE: txn.date,
            ExportColumns.AMOUNT: amount,
            ExportColumns.CATEGORY: txn.category or "Uncategorized",
            ExportColumns.DESCRIPTION: txn.description or txn.merchant,
            ExportColumns.DETAILS: details,
            ExportColumns.SPLIT_TYPE: split_type,
            ExportColumns.PARTICIPANT_NAMES: participant_names,
            ExportColumns.MY_PAID: my_paid,
            ExportColumns.MY_OWED: my_owed,
            ExportColumns.MY_NET: my_net,
            ExportColumns.ID: txn.splitwise_id or "",
        }

        rows.append(row)

    df = pd.DataFrame(rows)

    # Ensure proper data types
    if not df.empty:
        # Convert numeric columns
        for col in [
            ExportColumns.AMOUNT,
            ExportColumns.MY_PAID,
            ExportColumns.MY_OWED,
            ExportColumns.MY_NET,
        ]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Generate fingerprints for consistency with Splitwise source
        df[ExportColumns.FINGERPRINT] = df.apply(
            lambda r: generate_fingerprint(
                r.get(ExportColumns.DATE),
                r.get(ExportColumns.AMOUNT),
                r.get(ExportColumns.DESCRIPTION, ""),
            ),
            axis=1,
        )

        # Filter out payment/settlement transactions (same as Splitwise API filtering)
        if ExportColumns.DESCRIPTION in df.columns:
            # Filter "Settle all balances" transactions
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

            # Filter "Payment" transactions (General category only)
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

    return df


def fetch_and_write(
    start_date: Union[datetime, date, str],
    end_date: Union[datetime, date, str],
    sheet_key: Optional[str] = None,
    worksheet_name: str = DEFAULT_WORKSHEET_NAME,
    append: bool = True,
    export_categories_flag: bool = False,
    source: str = SOURCE_SPLITWISE,
    year: Optional[int] = None,
    dry_run: bool = False,
    append_only: bool = False,
) -> tuple[pd.DataFrame, Optional[str]]:
    """Fetch expenses and write to Google Sheets.

    Args:
        start_date: Start date for date range
        end_date: End date for date range
        sheet_key: Google Sheets spreadsheet key
        worksheet_name: Name of worksheet to write to
        append: If True, append to existing data; if False, overwrite
        export_categories_flag: If True, also export Splitwise categories
        source: Data source - 'splitwise' for API or 'database' for local DB
        year: Optional year filter (used with database source)
        dry_run: If True, preview data without writing to sheets or updating state
        append_only: If True (database source only), only export unwritten transactions

    Returns:
        Tuple of (DataFrame with expenses, URL of the updated sheet or None)
    """

    # Fetch data based on source
    if source == SOURCE_DATABASE:
        LOG.info(LOG_FETCHING_FROM_DB)
        is_overwrite = not append

        # Determine whether to include already-written transactions
        # - append_only mode: Only fetch unwritten (include_written=False)
        # - overwrite mode: Fetch all (include_written=True)
        # - normal append mode: Fetch all (include_written=True) for backward compatibility
        if append_only:
            include_written = False
        else:
            include_written = (
                is_overwrite or append
            )  # True in overwrite or normal append

        df = fetch_from_database(
            start_date=start_date,
            end_date=end_date,
            year=year,
            include_written=include_written,
        )

        if df.empty:
            LOG.info(LOG_NO_TRANSACTIONS_DB)
            return pd.DataFrame(), None

        LOG.info(LOG_FETCHED_FROM_DB, len(df))

        # For database source in overwrite mode, skip deduplication
        # Just write everything and mark as written
        new_df = df

    else:
        # Original Splitwise API behavior
        LOG.info(LOG_FETCHING_FROM_API)
        client = SplitwiseClient()
        df = client.get_my_expenses_by_date_range(start_date, end_date)

        # Filter out Splitwise-generated "Settle all balances" rows which are not useful for budgeting.
        # Match the exact phrase (case-insensitive, trimmed) instead of a fuzzy regex.
        if df is not None and not df.empty and ExportColumns.DESCRIPTION in df.columns:
            # explicit exact-match checks using pandas Series.eq for clarity
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

            # Also filter out explicit 'Payment' rows (these are payments/settlements, not expenses).
            # Only target the description field; if a `category` column exists require it to be 'General'
            # to avoid removing other rows accidentally.
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

        # Generate fingerprints using the utility function
        df[ExportColumns.FINGERPRINT] = df.apply(
            lambda r: generate_fingerprint(
                r.get(ExportColumns.DATE),
                r.get(ExportColumns.AMOUNT),
                r.get(ExportColumns.DESCRIPTION, ""),
            ),
            axis=1,
        )

        # In overwrite mode, we want a full refresh of the worksheet.
        # That means we should not filter anything out based on prior exported state.
        if is_overwrite:
            exported_ids, exported_fps = set(), set()
        else:
            # Always load existing exported state when not overwriting
            exported_ids, exported_fps = load_exported_state()
            # If appending to a live sheet, also read existing fingerprints from that worksheet to handle
            # cases where the local state file is missing or inconsistent.
            if sheet_key:
                sheet_existing_fps = _read_existing_fingerprints(
                    sheet_key, worksheet_name
                )
                if sheet_existing_fps:
                    exported_fps = set(exported_fps) | set(sheet_existing_fps)
                    # Persist the discovered fingerprints so future runs don't recompute them each time
                    save_exported_state(exported_ids, exported_fps)

        # Filter new rows: not in exported ids and not in exported fingerprints
        if not is_overwrite:
            mask_new = ~(
                (df[ExportColumns.ID].isin(exported_ids))
                | (df[ExportColumns.FINGERPRINT].isin(exported_fps))
            )
            new_df = df[mask_new].reset_index(drop=True)
        else:
            new_df = df

        # Convert my_paid/my_owed to numeric and filter out expenses where the
        # user has no participation (both my_paid and my_owed are zero).
        # This prevents exporting rows where the current user is not involved.
        if (
            not new_df.empty
            and ExportColumns.MY_PAID in new_df.columns
            and ExportColumns.MY_OWED in new_df.columns
        ):
            # Coerce to numeric (invalid -> 0.0) then filter
            new_df = new_df.copy()
            new_df[ExportColumns.MY_PAID] = pd.to_numeric(
                new_df[ExportColumns.MY_PAID], errors="coerce"
            ).fillna(0.0)
            new_df[ExportColumns.MY_OWED] = pd.to_numeric(
                new_df[ExportColumns.MY_OWED], errors="coerce"
            ).fillna(0.0)

            before_count = len(new_df)
            # Keep rows where either my_paid or my_owed is non-zero
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

    # In dry run mode, show preview and return early
    if dry_run:
        print(f"\n{'='*60}")
        print(f"DRY RUN MODE - No changes will be made")
        print(f"{'='*60}")
        print(f"Source: {source}")
        print(f"Worksheet: {worksheet_name}")
        print(f"Mode: {'Overwrite' if not append else 'Append'}")
        print(f"Transactions to export: {len(new_df)}")
        print(f"\nPreview (first 10 rows):")
        print(new_df.head(10).to_string(index=False))
        print(f"\n{'='*60}")
        return new_df, None

    # Coerce types for better Sheets formatting: date -> datetime objects, amount -> numeric
    if ExportColumns.DATE in new_df.columns:
        # parse and format as 'YYYY-MM-DD' (date-only) strings so Google Sheets will parse them as dates
        # Don't use utc=True to avoid timezone shifts - Splitwise dates are already in the correct format
        parsed = pd.to_datetime(new_df[ExportColumns.DATE], errors="coerce")
        # Format where parse succeeded; otherwise leave the original string
        new_df[ExportColumns.DATE] = parsed.dt.strftime("%Y-%m-%d").where(
            parsed.notna(), new_df[ExportColumns.DATE]
        )

    if ExportColumns.AMOUNT in new_df.columns:
        new_df[ExportColumns.AMOUNT] = pd.to_numeric(
            new_df[ExportColumns.AMOUNT], errors="coerce"
        )

    # Drop FRIENDS_SPLIT column if it exists, as it's not part of the standard export columns
    if ExportColumns.FRIENDS_SPLIT in new_df.columns:
        new_df = new_df.drop(columns=[ExportColumns.FRIENDS_SPLIT])

    # Write to sheets
    if sheet_key:
        url = write_to_sheets(
            new_df,
            worksheet_name=worksheet_name,
            spreadsheet_key=sheet_key,
            append=append,
        )
    else:
        url = None
        print(new_df.head())

    # Update state based on source
    if source == SOURCE_SPLITWISE:
        # Update exported state for Splitwise source
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

    elif source == SOURCE_DATABASE:
        # Mark transactions as written in database
        db = DatabaseManager()
        txn_ids = [
            int(sid) for sid in new_df[ExportColumns.ID].tolist() if sid and sid != ""
        ]

        if txn_ids and sheet_key:
            # Get transaction IDs from database by splitwise_id
            db_txn_ids = []
            for sw_id in txn_ids:
                txn = db.get_transaction_by_splitwise_id(sw_id)
                if txn and txn.id:
                    db_txn_ids.append(txn.id)

            if db_txn_ids:
                mark_year = year if year else datetime.now().year
                db.mark_written_to_sheet(db_txn_ids, year=mark_year)
                LOG.info(LOG_MARKED_WRITTEN, len(db_txn_ids))

    # Export categories only when explicitly requested via flag
    if not append and export_categories_flag:
        LOG.info(LOG_EXPORT_CATEGORIES)
        export_categories(sheet_key=sheet_key)

    return new_df, url


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Export expenses to Google Sheets from Splitwise API or local database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export from Splitwise API (default)
  python src/export/splitwise_export.py --start-date 2026-01-01 --end-date 2026-12-31
  
  # Export from local database for 2026
  python src/export/splitwise_export.py --source database --year 2026
  
  # Overwrite mode (full refresh)
  python src/export/splitwise_export.py --source database --year 2026 --overwrite
  
  # Export to specific worksheet
  python src/export/splitwise_export.py --source database --year 2026 --worksheet "Expenses 2026"
        """,
    )
    parser.add_argument(
        "--source",
        choices=[SOURCE_SPLITWISE, SOURCE_DATABASE],
        default=SOURCE_SPLITWISE,
        help=f"Data source: '{SOURCE_SPLITWISE}' for live API or '{SOURCE_DATABASE}' for local DB (default: {SOURCE_SPLITWISE})",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Year filter (primarily for database source, e.g., 2026)",
    )
    parser.add_argument(
        "--append-only",
        action="store_true",
        help="(Database source only) Export only unwritten transactions, tracking via written_to_sheet flag",
    )
    parser.add_argument(
        "--start-date",
        default=get_env("START_DATE"),
        help="Start date (any parseable date string). Defaults to START_DATE env var or current year start.",
    )
    parser.add_argument(
        "--end-date",
        default=get_env("END_DATE"),
        help="End date (any parseable date string). Defaults to END_DATE env var or current year end.",
    )
    parser.add_argument(
        "--worksheet-name",
        "--worksheet",
        dest="worksheet_name",
        default=get_env("EXPENSES_WORKSHEET_NAME", DEFAULT_WORKSHEET_NAME),
        help=f"Worksheet name (default: EXPENSES_WORKSHEET_NAME env var or {DEFAULT_WORKSHEET_NAME})",
    )
    parser.add_argument(
        "--export-categories",
        dest="export_categories",
        action="store_true",
        help="Also export Splitwise categories to the 'Splitwise Categories' worksheet when using --no-append/--overwrite",
    )
    parser.add_argument(
        "--sheet-key",
        default=os.getenv("SPREADSHEET_KEY"),
        help="Spreadsheet key/ID (default: SPREADSHEET_KEY env var). Find this in your sheet URL.",
    )
    # --overwrite is an alias for --no-append for backward compatibility
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--no-append",
        dest="append",
        action="store_false",
        help="Overwrite the worksheet instead of appending to it (default: %(default)s)",
    )
    group.add_argument(
        "--overwrite",
        dest="append",
        action="store_false",
        help=argparse.SUPPRESS,  # Hidden alias for backward compatibility
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Preview data without writing to sheets or updating state (no changes made)",
    )

    args = parser.parse_args()

    # Determine worksheet name
    worksheet_name = args.worksheet_name
    if (
        args.source == SOURCE_DATABASE
        and args.year
        and worksheet_name == DEFAULT_WORKSHEET_NAME
    ):
        # Default to "Expenses YYYY" for database year exports
        worksheet_name = WORKSHEET_NAME_TEMPLATE.format(year=args.year)

    # Validate required arguments based on source
    if (
        args.source == SOURCE_DATABASE
        and not args.year
        and not (args.start_date and args.end_date)
    ):
        raise ValueError(ERROR_DATABASE_FILTER_REQUIRED)

    if args.source == SOURCE_SPLITWISE:
        if not args.start_date:
            args.start_date = f"{datetime.now().year}-01-01"
            LOG.info("No start date provided, defaulting to %s", args.start_date)
        if not args.end_date:
            args.end_date = f"{datetime.now().year}-12-31"
            LOG.info("No end date provided, defaulting to %s", args.end_date)

    # Parse dates (use shared parse_date in src.utils)
    if args.year:
        # Use year boundaries if year is specified
        start_date = parse_date(f"{args.year}-01-01")
        end_date = parse_date(f"{args.year}-12-31")
    else:
        start_date = parse_date(args.start_date) if args.start_date else None
        end_date = parse_date(args.end_date) if args.end_date else None

    if start_date and end_date and start_date > end_date:
        raise ValueError(
            ERROR_DATE_RANGE_INVALID.format(start_date=start_date, end_date=end_date)
        )

    # Ensure sheet_key is provided for writes unless in dry run mode
    if not args.sheet_key and not args.dry_run:
        raise ValueError(ERROR_SHEET_KEY_REQUIRED)

    LOG.info(LOG_EXPORTING_FROM, args.source, start_date, end_date)
    new_df, url = fetch_and_write(
        start_date=start_date,
        end_date=end_date,
        sheet_key=args.sheet_key,
        worksheet_name=worksheet_name,
        append=args.append,
        export_categories_flag=args.export_categories,
        source=args.source,
        year=args.year,
        dry_run=args.dry_run,
        append_only=args.append_only,
    )

    if new_df is not None and not new_df.empty:
        print(MSG_PROCESSED_SUCCESS.format(count=len(new_df)))
        if url:
            print(f"Updated sheet: {url}")

        if "status" in new_df.columns:
            print("\nSummary:")
            print(new_df["status"].value_counts().to_string())
    else:
        print(MSG_NO_EXPENSES_PROCESSED)

    return 0


if __name__ == "__main__":
    exit(main())
