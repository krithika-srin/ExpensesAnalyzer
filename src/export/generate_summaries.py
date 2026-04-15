#!/usr/bin/env python3
"""Generate spending summary and analysis sheets from transaction data.

Creates multiple analysis tabs:
1. Monthly Summary - Total spending by month with trends
"""

import argparse
import json
import os
import re
from typing import Dict

import pandas as pd

# Load environment variables
from src.common.env import load_project_env

load_project_env()

from src.common.sheets_sync import write_to_sheets, read_from_sheets
from src.common.splitwise_client import SplitwiseClient
from src.common.transaction_filters import is_user_participant
from src.common.utils import LOG
from src.constants.gsheets import (
    WORKSHEET_MONTHLY_SUMMARY,
)
from src.constants.splitwise import REFUND_KEYWORDS
from src.database import DatabaseManager

# Constants


def fetch_transactions_for_analysis(year: int = None) -> pd.DataFrame:
    """Fetch transactions for the specified year (or all time if None) from database.

    Args:
        year: Year to analyze, or None for all time

    Returns:
        DataFrame with transaction data
    """
    db = DatabaseManager()
    client = SplitwiseClient()

    # Get current user's name to filter for relevant transactions
    current_user = client.get_current_user()
    current_user_name = current_user.getFirstName() if current_user else ""

    if year:
        LOG.info(f"Fetching transactions for {year}...")
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        transactions = db.get_transactions_with_splitwise_ids(
            start_date=start_date, end_date=end_date
        )
    else:
        LOG.info("Fetching transactions for ALL TIME...")
        transactions = db.get_transactions_with_splitwise_ids()

    if not transactions:
        LOG.warning(f"No transactions found for {year if year else 'all time'}")
        return pd.DataFrame()

    # Convert to DataFrame
    data = []
    filtered_count = 0
    for txn in transactions:
        # Skip transactions where current user is not a participant
        # (matches filter in splitwise_export.py fetch_from_database())
        if not is_user_participant(txn, current_user_name):
            filtered_count += 1
            continue

        # Parse notes field to extract payment info
        my_paid = 0.0
        my_owed = 0.0

        if txn.notes:
            paid_match = re.search(r"Paid: \$?([\d,]+\.?\d*)", txn.notes)
            owe_match = re.search(r"Owe: \$?([\d,]+\.?\d*)", txn.notes)

            if paid_match:
                my_paid = float(paid_match.group(1).replace(",", ""))
            if owe_match:
                my_owed = float(owe_match.group(1).replace(",", ""))

        # Check if this is a refund (either flagged in DB or detected by description)
        description = txn.description or ""
        is_refund_by_description = any(
            keyword in description.lower() for keyword in REFUND_KEYWORDS
        )

        # For refunds, negate my_owed and my_paid to show as credits
        if txn.is_refund or is_refund_by_description:
            my_owed = -my_owed
            my_paid = -my_paid

        my_net = my_paid - my_owed

        data.append(
            {
                "date": txn.date,
                "amount": txn.amount,
                "category": txn.category or "Uncategorized",
                "description": txn.description,
                "my_paid": my_paid,
                "my_owed": my_owed,
                "my_net": my_net,
                "is_shared": txn.is_shared,
                "is_deleted": bool(txn.splitwise_deleted_at),
            }
        )

    df = pd.DataFrame(data)

    # Filter out deleted and payment transactions
    df = df[~df["is_deleted"]]
    df = df[
        ~((df["description"].str.lower() == "payment") & (df["category"] == "General"))
    ]

    # Convert date to datetime
    df["date"] = pd.to_datetime(df["date"])
    df["year_month"] = df["date"].dt.to_period("M")
    df["month"] = df["date"].dt.month
    df["month_name"] = df["date"].dt.strftime("%B")

    LOG.info(f"Found {len(df)} transactions for analysis")
    return df


def generate_monthly_summary(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Generate monthly spending summary.

    Args:
        df: Transaction DataFrame
        year: Year being analyzed

    Returns:
        DataFrame with monthly summary
    """
    if df.empty:
        return pd.DataFrame()

    # Group by month
    monthly = (
        df.groupby("year_month")
        .agg({"my_owed": ["sum", "mean", "count"], "my_paid": "sum", "my_net": "sum"})
        .reset_index()
    )

    # Flatten column names
    monthly.columns = [
        "year_month",
        "Total Spent (Net)",
        "Avg Transaction",
        "Transaction Count",
        "Total Paid",
        "Total Net",
    ]

    # Format month as "YYYY-MM" for better sorting in sheets
    monthly["Month"] = monthly["year_month"].dt.strftime("%Y-%m")

    # Calculate cumulative spending per year
    monthly["year"] = monthly["year_month"].dt.year
    monthly["Cumulative Spending"] = monthly.groupby("year")[
        "Total Spent (Net)"
    ].cumsum()
    monthly = monthly.drop(columns=["year"])

    # Calculate month-over-month change (leave as raw decimal for Sheets % formatting)
    monthly["MoM Change"] = monthly["Total Spent (Net)"].pct_change()
    monthly["MoM Change"] = monthly["MoM Change"].fillna(0)

    # Round numeric columns
    numeric_cols = [
        "Total Spent (Net)",
        "Avg Transaction",
        "Total Paid",
        "Total Net",
        "Cumulative Spending",
        "MoM Change",
    ]
    for col in numeric_cols:
        monthly[col] = monthly[col].round(2)

    # Reorder and keep only requested columns
    cols_to_keep = [
        "Month",
        "Total Spent (Net)",
        "Avg Transaction",
        "Transaction Count",
        "Total Paid",
        "Total Net",
        "Cumulative Spending",
        "MoM Change",
    ]
    monthly = monthly[cols_to_keep]

    return monthly


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate budget summary and analysis sheets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate all summaries for 2026
  python src/export/generate_summaries.py --year 2026

  # Dry run to preview
  python src/export/generate_summaries.py --year 2026 --dry-run
        """,
    )

    parser.add_argument(
        "--year",
        type=int,
        help="Year to analyze (e.g., 2026). Required unless --all-time is used.",
    )
    parser.add_argument(
        "--all-time",
        action="store_true",
        help="Analyze all time instead of a specific year",
    )
    parser.add_argument(
        "--sheet-key",
        default=os.getenv("SPREADSHEET_KEY"),
        help="Google Sheets spreadsheet key (defaults to SPREADSHEET_KEY env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview summaries without writing to sheets",
    )

    args = parser.parse_args()

    if not args.sheet_key and not args.dry_run:
        raise ValueError(
            "--sheet-key must be provided (or set SPREADSHEET_KEY env var)"
        )

    if not args.year and not args.all_time:
        parser.error("--year or --all-time must be provided")

    analyze_year = None if args.all_time else args.year

    # Fetch transaction data
    df = fetch_transactions_for_analysis(analyze_year)

    if df.empty:
        print(
            f"No transactions found for {analyze_year if analyze_year else 'all time'}"
        )
        return 1

    print(f"\n{'='*60}")
    print(
        f"Generating Budget Summaries for {analyze_year if analyze_year else 'ALL TIME'}"
    )
    print(f"{'='*60}\n")

    # Generate summary
    monthly_summary = generate_monthly_summary(df, analyze_year)


    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN MODE - Preview Only")
        print("=" * 60)

        print(f"\n{WORKSHEET_MONTHLY_SUMMARY}:")
        print(monthly_summary.to_string(index=False))


        print("\n" + "=" * 60)
        return 0

    # Write to Google Sheets (merge with existing data from other years)
    print("Writing summaries to Google Sheets...\n")

    db = DatabaseManager()

    # Always write out all generated summaries for the year to ensure formatting is up-to-date
    if monthly_summary.empty:
        print(f"✓ {WORKSHEET_MONTHLY_SUMMARY}: No summary data to write")
    else:
        # Completely overwrite without merging
        final_df = monthly_summary
        if "Month" in final_df.columns:
            final_df = final_df.sort_values("Month", ascending=False)

        # Write the combined sheet with overwrite instead of append
        write_to_sheets(
            final_df,
            worksheet_name=WORKSHEET_MONTHLY_SUMMARY,
            spreadsheet_key=args.sheet_key,
            append=False,  # Overwrite with merged or new data
            skip_formatting=False,  # Apply format explicitly
        )

        # Save the written rows to database
        for _, row in monthly_summary.iterrows():
            year_month = str(row["Month"])
            db.save_monthly_summary(
                year_month=year_month,
                total_spent_net=row["Total Spent (Net)"],
                avg_transaction=row["Avg Transaction"],
                transaction_count=int(row["Transaction Count"]),
                total_paid=row["Total Paid"],
                total_owed=row["Total Net"],
                cumulative_spending=row["Cumulative Spending"],
                mom_change=row["MoM Change"],
                written_to_sheet=True,
            )

        print(
            f"✓ {WORKSHEET_MONTHLY_SUMMARY}: Merged and wrote {len(monthly_summary)} months for {args.year if args.year else 'all time'}"
        )

    url = f"https://docs.google.com/spreadsheets/d/{args.sheet_key}"
    print(f"   {url}")

    print(f"\n{'='*60}")
    print("Summary generation complete!")
    print(f"{'='*60}\n")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
