"""Sync database with Splitwise - handle inserts, updates, and deletions.

This unified script handles both:
1. Initial migration (bulk import of historical data)
2. Ongoing sync (update existing transactions, mark deletions)

It fetches expenses from Splitwise and:
- Inserts new transactions not in DB (migration behavior)
- Updates existing transactions if changed (sync behavior)
- Marks transactions as deleted if removed from Splitwise
"""

import argparse
import sys
from datetime import datetime as dt, timezone
from typing import Dict, Set, Any
import traceback

from src.common.splitwise_client import SplitwiseClient
from src.common.utils import normalize_splitwise_date_to_local
from src.database import DatabaseManager, Transaction
from src.constants.export_columns import ExportColumns
from src.constants.splitwise import SPLIT_TYPE_SELF, REFUND_KEYWORDS


def parse_expense_to_transaction(row: Dict[str, Any]) -> Transaction:
    """Convert Splitwise dataframe row to Transaction object.

    Args:
        row: Row dictionary from SplitwiseClient.get_my_expenses_by_date_range()

    Returns:
        Transaction object
    """
    # Extract fields using ExportColumns constants
    expense_id = row.get(ExportColumns.ID)

    # Date - normalize timezone-aware Splitwise timestamps into local calendar date
    date_val = normalize_splitwise_date_to_local(str(row.get(ExportColumns.DATE, "")))

    description = row.get(ExportColumns.DESCRIPTION, "")
    merchant = description  # Use description as merchant
    details = row.get(ExportColumns.DETAILS, "")

    # Amounts
    total_cost = float(row.get(ExportColumns.AMOUNT, 0))
    my_paid = float(row.get(ExportColumns.MY_PAID, 0))
    my_owed = float(row.get(ExportColumns.MY_OWED, 0))
    my_net = float(
        row.get(ExportColumns.MY_NET, 0)
    )  # This is what we paid minus what we owe

    # Category
    category_name = row.get(ExportColumns.CATEGORY, "Uncategorized")

    # Split type
    split_type = row.get(ExportColumns.SPLIT_TYPE, "unknown")
    is_self = split_type == SPLIT_TYPE_SELF

    # Participants
    participant_names = row.get(ExportColumns.PARTICIPANT_NAMES, "")

    # Determine if refund/payment
    is_refund = total_cost < 0

    # Extract cc_reference_id from details field (Splitwise stores it as the raw value)
    cc_reference_id = None
    if details:
        # Details field contains the cc_reference_id directly (e.g., '320260110295060302')
        # Strip quotes and whitespace
        cc_ref_clean = str(details).strip().strip("'\"")
        if cc_ref_clean and len(cc_ref_clean) > 5:  # Sanity check
            cc_reference_id = cc_ref_clean

    # Build notes
    notes_parts = []
    notes_parts.append("Imported from Splitwise API")

    # For refunds, if my_paid is negative and my_owed is 0, treat abs(my_paid) as the amount owed back
    if is_refund and my_paid < 0 and my_owed == 0:
        notes_parts.append(f"Owe: ${abs(my_paid):.2f}")
    elif my_paid != 0:
        notes_parts.append(f"Paid: ${my_paid:.2f}")
    if my_owed != 0:
        notes_parts.append(f"Owe: ${my_owed:.2f}")
    if participant_names:
        notes_parts.append(f"With: {participant_names}")
    notes = " | ".join(notes_parts)

    txn = Transaction(
        date=date_val,
        merchant=merchant,
        description=description,
        raw_description=f"{description} | {details}".strip(" |"),
        amount=my_net,  # Net: what you paid minus what you owe
        raw_amount=total_cost,  # Total expense cost
        source="splitwise",
        category=category_name,
        is_refund=is_refund,
        is_shared=not is_self,
        split_type=split_type,
        currency="USD",
        splitwise_id=expense_id,
        cc_reference_id=cc_reference_id,
        imported_at=dt.now(timezone.utc).isoformat(),
        notes=notes,
    )

    return txn


def sync_from_splitwise(
    start_date: str,
    end_date: str,
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, int]:
    """Sync database with Splitwise expenses.

    Handles both initial migration and ongoing sync:
    - Inserts new expenses not in DB
    - Updates existing expenses if changed
    - Marks deleted expenses

    Args:
        start_date: Start date for sync (YYYY-MM-DD)
        end_date: End date for sync (YYYY-MM-DD)
        dry_run: If True, show changes but don't apply them
        verbose: Print detailed information

    Returns:
        Dictionary with sync statistics
    """
    print(f"\n{'='*60}")
    print(f"Syncing database with Splitwise")
    print(f"Date range: {start_date} to {end_date}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    db = DatabaseManager()
    client = SplitwiseClient()

    # Stats tracking
    stats = {
        "checked": 0,
        "inserted": 0,
        "updated": 0,
        "marked_deleted": 0,
        "unchanged": 0,
        "errors": 0,
    }

    # Get all transactions from DB that have Splitwise IDs in this date range
    print(f"Fetching transactions from database...")
    db_transactions = db.get_transactions_with_splitwise_ids(start_date, end_date)
    print(f"   Found {len(db_transactions)} transactions with Splitwise IDs in DB\n")

    # Build lookup by splitwise_id
    db_by_splitwise_id = {txn.splitwise_id: txn for txn in db_transactions}
    db_splitwise_ids = set(db_by_splitwise_id.keys())

    # Fetch expenses from Splitwise
    print(f"Fetching expenses from Splitwise API...")
    # Convert string dates to datetime objects for the client

    start_date_obj = dt.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj = dt.strptime(end_date, "%Y-%m-%d").date()

    splitwise_df = client.get_my_expenses_by_date_range(
        start_date=start_date_obj,
        end_date=end_date_obj,
    )
    print(f"   Found {len(splitwise_df)} expenses in Splitwise\n")

    if splitwise_df.empty:
        print("WARNING: No expenses found in Splitwise for this date range")
        return stats

    # Get splitwise_ids that exist in Splitwise
    splitwise_ids_in_api: Set[int] = set()
    if ExportColumns.ID in splitwise_df.columns:
        splitwise_ids_in_api = set(splitwise_df[ExportColumns.ID].dropna().astype(int))

    # Convert to list of dicts for easier processing
    expenses = splitwise_df.to_dict("records")

    print(f"Processing {len(expenses)} expenses from Splitwise...\n")

    # Track new transactions to insert
    transactions_to_insert = []

    # Process each Splitwise expense
    for expense in expenses:
        splitwise_id = expense.get(ExportColumns.ID)

        if not splitwise_id:
            continue

        stats["checked"] += 1

        # Check if this expense exists in DB
        if splitwise_id not in db_by_splitwise_id:
            # NEW TRANSACTION - Insert it
            try:
                txn = parse_expense_to_transaction(expense)
                print(
                    f"  NEW: ID {splitwise_id} | {txn.date} | {txn.merchant[:40]} | ${txn.amount:.2f}"
                )

                if not dry_run:
                    transactions_to_insert.append(txn)

                stats["inserted"] += 1

            except Exception as e:
                print(f"  ERROR: Error parsing new expense {splitwise_id}: {e}")
                stats["errors"] += 1

            continue

        # EXISTING TRANSACTION - Check for updates
        txn = db_by_splitwise_id[splitwise_id]

        # Compare and detect changes
        changes = []
        updates = {}

        # Check amount
        sw_amount = float(expense[ExportColumns.MY_NET])
        if abs(sw_amount - txn.amount) > 0.01:
            changes.append(f"amount: ${txn.amount:.2f} → ${sw_amount:.2f}")
            updates["amount"] = sw_amount

        # Check total cost (raw_amount)
        sw_total_cost = float(expense.get(ExportColumns.AMOUNT, 0))
        if txn.raw_amount is not None and abs(sw_total_cost - txn.raw_amount) > 0.01:
            changes.append(f"cost: ${txn.raw_amount:.2f} → ${sw_total_cost:.2f}")
            updates["raw_amount"] = sw_total_cost

        # Check date
        sw_date = normalize_splitwise_date_to_local(
            str(expense[ExportColumns.DATE])
        )
        if sw_date != txn.date:
            changes.append(f"date: {txn.date} → {sw_date}")
            updates["date"] = sw_date

        # Check description/merchant
        sw_desc = expense[ExportColumns.DESCRIPTION]
        if sw_desc != txn.merchant:
            changes.append(f"merchant: '{txn.merchant}' → '{sw_desc}'")
            updates["merchant"] = sw_desc
            updates["description"] = sw_desc

        # Check category
        sw_category = expense.get(ExportColumns.CATEGORY)
        if sw_category and sw_category != txn.category:
            changes.append(f"category: '{txn.category}' → '{sw_category}'")
            updates["category"] = sw_category

        # Check split_type
        sw_split_type = expense.get(ExportColumns.SPLIT_TYPE)
        if sw_split_type and sw_split_type != txn.split_type:
            changes.append(f"split_type: {txn.split_type or 'None'} → {sw_split_type}")
            updates["split_type"] = sw_split_type
            # Also update is_shared for backward compatibility
            is_self = sw_split_type == SPLIT_TYPE_SELF
            updates["is_shared"] = not is_self

        # Check and update cc_reference_id from Splitwise details
        sw_details = expense.get(ExportColumns.DETAILS, "")
        sw_cc_reference_id = None
        if sw_details:
            cc_ref_clean = str(sw_details).strip().strip("'\"")
            if cc_ref_clean and len(cc_ref_clean) > 5:
                sw_cc_reference_id = cc_ref_clean

        # Update cc_reference_id if missing or different
        if sw_cc_reference_id and sw_cc_reference_id != txn.cc_reference_id:
            changes.append(
                f"cc_ref: {txn.cc_reference_id or 'None'} → {sw_cc_reference_id}"
            )
            updates["cc_reference_id"] = sw_cc_reference_id

        # Check and update notes with payment information
        # Rebuild notes from Splitwise data to ensure it has payment info
        sw_my_paid = float(expense.get(ExportColumns.MY_PAID, 0))
        sw_my_owed = float(expense.get(ExportColumns.MY_OWED, 0))
        sw_participant_names = expense.get(ExportColumns.PARTICIPANT_NAMES, "")
        sw_description = expense.get(ExportColumns.DESCRIPTION, "")

        # For notes, use original values (not negated for refunds)
        original_my_paid = sw_my_paid
        original_my_owed = sw_my_owed
        is_refund_desc = any(
            keyword in sw_description.lower() for keyword in REFUND_KEYWORDS
        )

        notes_parts = []
        notes_parts.append("Imported from Splitwise API")

        # For refunds, if my_paid is negative and my_owed is 0, treat abs(my_paid) as the amount owed back
        if is_refund_desc and original_my_paid < 0 and original_my_owed == 0:
            notes_parts.append(f"Owe: ${abs(original_my_paid):.2f}")
        elif original_my_paid != 0:
            notes_parts.append(f"Paid: ${original_my_paid:.2f}")
        if original_my_owed != 0:
            notes_parts.append(f"Owe: ${original_my_owed:.2f}")
        if sw_participant_names:
            notes_parts.append(f"With: {sw_participant_names}")

        sw_notes = " | ".join(notes_parts)

        # Check if notes need updating (payment info missing)
        if txn.notes != sw_notes:
            # Don't log full notes change unless verbose, it's long
            if "Paid:" not in str(txn.notes) or "With:" not in str(txn.notes):
                changes.append("notes: added payment info")
            updates["notes"] = sw_notes

        if changes:
            print(
                f"  UPDATED: ID {splitwise_id} | {txn.merchant[:40]} | {', '.join(changes)}"
            )
            if not dry_run:
                db.update_transaction(txn.id, updates)
            stats["updated"] += 1
        else:
            if verbose:
                print(f"  Unchanged: ID {splitwise_id} | {txn.merchant[:40]}")
            stats["unchanged"] += 1

    # Batch insert new transactions
    if not dry_run and transactions_to_insert:
        print(f"\nInserting {len(transactions_to_insert)} new transactions...")
        db.insert_transactions_batch(transactions_to_insert)
        print(f"   Inserted successfully\n")

    # Check for deletions (transactions in DB but not in Splitwise)
    print(f"\nChecking for deletions...")
    deleted_ids = db_splitwise_ids - splitwise_ids_in_api

    if deleted_ids:
        for splitwise_id in deleted_ids:
            txn = db_by_splitwise_id[splitwise_id]
            if not txn.splitwise_deleted_at:
                print(
                    f"  DELETED: ID {splitwise_id} | {txn.date} | {txn.merchant[:40]} | ${txn.amount:.2f}"
                )
                if not dry_run:
                    db.mark_deleted_by_splitwise_id(splitwise_id)
                stats["marked_deleted"] += 1
            else:
                if verbose:
                    print(
                        f"  Already marked deleted: ID {splitwise_id} | {txn.merchant[:40]}"
                    )
    else:
        print(f"   No deletions detected")

    # Summary
    print(f"\n{'='*60}")
    print(f"Sync Summary {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*60}")
    print(f"  Expenses checked:        {stats['checked']}")
    print(f"  New (inserted):          {stats['inserted']}")
    print(f"  Updated:                 {stats['updated']}")
    print(f"  Marked as deleted:       {stats['marked_deleted']}")
    print(f"  Unchanged:               {stats['unchanged']}")
    print(f"  Errors:                  {stats['errors']}")
    print(f"{'='*60}\n")

    if dry_run:
        print(
            "NOTE: This was a dry run. Use --live to apply changes to the database.\n"
        )

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Sync database with Splitwise (insert new, update existing, mark deleted)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run for specific year (default mode, safe)
  python src/db_sync/sync_from_splitwise.py --year 2026
  
  # Live sync for specific year (applies changes)
  python src/db_sync/sync_from_splitwise.py --year 2026 --live
  
  # Verbose output showing all transactions
  python src/db_sync/sync_from_splitwise.py --year 2026 --verbose
  
  # Sync specific date range
  python src/db_sync/sync_from_splitwise.py --start-date 2026-01-01 --end-date 2026-03-31 --live
  
  # Initial migration for a year (same command, will insert missing expenses)
  python src/db_sync/sync_from_splitwise.py --year 2025 --live
        """,
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date for sync (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date for sync (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show changes without applying them (default)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Apply changes to database (overrides --dry-run)",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Sync specific year (sets start-date and end-date)",
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        help="Sync multiple years (e.g., --years 2025 2026)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show all transactions including unchanged",
    )

    args = parser.parse_args()

    # Determine years to process
    years = []
    if args.year:
        years = [args.year]
    elif args.years:
        years = sorted(args.years)

    # If years specified, process each year
    if years:
        total_stats = {
            "checked": 0,
            "inserted": 0,
            "updated": 0,
            "marked_deleted": 0,
            "unchanged": 0,
            "errors": 0,
        }

        is_live = args.live
        is_dry_run = not is_live

        for year in years:
            start_date = f"{year}-01-01"
            end_date = f"{year}-12-31"

            try:
                stats = sync_from_splitwise(
                    start_date=start_date,
                    end_date=end_date,
                    dry_run=is_dry_run,
                    verbose=args.verbose,
                )

                # Accumulate stats
                for key in total_stats:
                    total_stats[key] += stats[key]

                # Note: ImportLog feature not yet implemented
                # Could add logging here for audit trail if needed

            except Exception as e:
                print(f"\nERROR: Error syncing year {year}: {e}", file=sys.stderr)
                traceback.print_exc()
                total_stats["errors"] += 1

        # Print overall summary if multiple years
        if len(years) > 1:
            print(f"\n{'='*60}")
            print(f"OVERALL SUMMARY (Years: {', '.join(map(str, years))})")
            print(f"{'='*60}")
            print(f"  Total checked:           {total_stats['checked']}")
            print(f"  Total inserted:          {total_stats['inserted']}")
            print(f"  Total updated:           {total_stats['updated']}")
            print(f"  Total marked deleted:    {total_stats['marked_deleted']}")
            print(f"  Total unchanged:         {total_stats['unchanged']}")
            print(f"  Total errors:            {total_stats['errors']}")
            print(f"{'='*60}\n")

        # Exit with error code if there were errors
        if total_stats["errors"] > 0:
            sys.exit(1)

    # Otherwise use provided date range
    else:
        if not args.start_date or not args.end_date:
            parser.error(
                "Must specify either --year/--years OR both --start-date and --end-date"
            )

        # Determine if live mode
        is_live = args.live
        is_dry_run = not is_live

        try:
            stats = sync_from_splitwise(
                start_date=args.start_date,
                end_date=args.end_date,
                dry_run=is_dry_run,
                verbose=args.verbose,
            )

            # Note: ImportLog feature not yet implemented
            # Could add logging here for audit trail if needed

            # Exit with error code if there were errors
            if stats["errors"] > 0:
                sys.exit(1)

        except Exception as e:
            print(f"\nERROR: {e}", file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    main()
