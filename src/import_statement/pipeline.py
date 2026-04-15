"""Orchestrates the ETL pipeline for importing credit card statements to Splitwise."""

# Standard library
import argparse
import os
from datetime import datetime as dt

# Third-party
import pandas as pd

# Load environment variables
from src.common.env import load_project_env

load_project_env()

# Local application
from src.constants.config import PROCESSED_DIR
from src.constants.splitwise import SplitwiseUserId
from src.import_statement.bank_config import BankConfig
from src.import_statement.parse_statement import parse_statement
from src.import_statement.process_refunds import RefundProcessor
from src.common.sheets_sync import write_to_sheets
from src.common.splitwise_client import SplitwiseClient
from src.database import DatabaseManager
from src.database.models import Transaction
from src.common.utils import (
    LOG,
    clean_merchant_name,
    infer_category,
    mkdir_p,
    now_iso,
)


def process_statement(
    path,
    dry_run=True,
    limit=None,
    sheet_key: str = None,
    worksheet_name: str = None,
    no_sheet: bool = False,
    start_date: str = None,
    end_date: str = None,
    append_to_sheet: bool = False,
    offset: int = 0,
    merchant_filter: str = None,
):
    # Use defaults from env vars if not provided
    if worksheet_name is None:
        worksheet_name = os.getenv("DRY_RUN_WORKSHEET_NAME", "Statement Imports")
    if start_date is None:
        start_date = os.getenv("START_DATE", f"{dt.now().year}-01-01")
    if end_date is None:
        end_date = os.getenv("END_DATE", f"{dt.now().year}-12-31")

    LOG.info("Processing statement %s (dry_run=%s)", path, dry_run)
    df = parse_statement(path)
    if df is None or df.empty:
        LOG.info("No transactions parsed from %s", path)
        return

    # Determine bank from file path
    bank_config = BankConfig()
    try:
        bank_config.detect_bank_from_path(path)
    except ValueError as e:
        LOG.error("Error determining bank from path: %s", e)

    mkdir_p(PROCESSED_DIR)
    db = DatabaseManager()  # Initialize database manager

    # Initialize client for duplicate detection (both dry-run and live mode)
    # In dry-run, we still need to check Splitwise to see what would/wouldn't be added
    client = SplitwiseClient()

    if not dry_run:
        # Pre-fetch expenses for the specified date range to build disk cache
        # This ensures we can detect duplicates across the entire period
        LOG.info(
            f"Pre-fetching expenses from {start_date} to {end_date} to build disk cache..."
        )
        client.fetch_expenses_with_details(start_date, end_date, use_cache=True)
        LOG.info("Disk cache ready for duplicate detection")

    results = []
    added = 0
    attempted = 0
    skipped = 0
    for _, row in df.reset_index(drop=True).iterrows():
        # Skip transactions before offset
        if skipped < offset:
            skipped += 1
            continue

        if limit and attempted >= limit:
            LOG.info(f"Reached limit of {limit} transactions, stopping")
            break
        attempted += 1
        date = row.get("date")
        desc = row.get("description")
        amount = row.get("amount")
        detail = row.get("detail")
        merchant = row.get("description") or ""

        # Determine if this is a credit/refund early so we can allow missing
        # cc_reference_id for credits (these often lack a transaction id).
        try:
            is_credit_flag = bool(row.get("is_credit", False)) or float(amount) < 0
        except Exception:
            is_credit_flag = bool(row.get("is_credit", False))

        # Check merchant filter if specified
        if merchant_filter:
            if merchant_filter.lower() not in merchant.lower():
                LOG.debug(
                    f"Skipping transaction (merchant filter '{merchant_filter}' not in '{merchant}')"
                )
                continue

        # Check date filter if specified (filter transactions by date range)
        if date:
            txn_date = (
                dt.strptime(date, "%Y-%m-%d").date() if isinstance(date, str) else date
            )
            start_date_obj = dt.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = dt.strptime(end_date, "%Y-%m-%d").date()
            if txn_date < start_date_obj or txn_date > end_date_obj:
                LOG.debug(
                    f"Skipping transaction outside date range: {date} (range: {start_date} to {end_date})"
                )
                continue

        # Clean description for Splitwise posting (keep raw for sheets)
        desc_clean = clean_merchant_name(desc)
        desc_raw = desc

        # Prefer the parsed `cc_reference_id` produced by `parse_statement()`.
        cc_reference_id = None
        parsed_cc = row.get("cc_reference_id")
        if parsed_cc is not None and str(parsed_cc).strip().lower() not in [
            "",
            "nan",
            "none",
        ]:
            cc_reference_id = str(parsed_cc).strip()

        # Fallback: use raw detail only when it looks like an ID (contains digits
        # or is a short single-line token). Avoid using verbose/multiline detail
        # text as the cc_reference_id.
        if not cc_reference_id and detail is not None:
            s = str(detail).strip()
            if s and s.lower() != "nan":
                is_multiline = "\n" in s or "\\n" in s
                has_digit = any(ch.isdigit() for ch in s)
                if has_digit or (not is_multiline and len(s) < 40):
                    cc_reference_id = s

        if not cc_reference_id:
            # Allow missing cc_reference_id for credit/refund transactions
            if is_credit_flag:
                cc_reference_id = None
            else:
                error_msg = f"Transaction is missing required cc_reference_id (date={date}, amount={amount}, description='{desc}')"
                raise ValueError(error_msg)

        # Detect if this is a refund/credit (negative amount OR explicit is_credit flag)
        is_credit = row.get("is_credit", False) or float(amount) < 0

        # For refunds, use absolute value for amount
        amount_abs = abs(float(amount))

        entry = {
            "date": date,
            "description": desc_clean,  # Clean version for Splitwise
            "description_raw": desc_raw,  # Raw version for debugging in sheets
            "amount": amount_abs,
            "detail": cc_reference_id,
            "cc_reference_id": cc_reference_id,
            "is_credit": is_credit,
        }

        # Clean cc_reference_id by stripping quotes (Amex CSV wraps in single quotes)
        if cc_reference_id:
            cc_reference_id = str(cc_reference_id).strip().strip("'\"")
            entry["cc_reference_id"] = cc_reference_id

        # Infer category for ALL transactions (needed for sheet reporting even if duplicate)
        is_credit = row.get("is_credit", False)
        if is_credit:
            # All credits should be categorized as Uncategorized > General
            category_info = {
                "category_id": 2,
                "category_name": "Uncategorized",
                "subcategory_id": 18,
                "subcategory_name": "General",
                "confidence": "credit_override",
            }
        else:
            category_info = infer_category(
                {
                    "description": desc,
                    "merchant": merchant,
                    "amount": amount,
                    "category": row.get("category"),  # Pass Amex category if available
                }
            )

        # Add category info to the entry
        entry.update(
            {
                "category_id": category_info.get("category_id"),
                "category_name": category_info.get("category_name"),
                "subcategory_id": category_info.get("subcategory_id"),
                "subcategory_name": category_info.get("subcategory_name"),
                "confidence": category_info.get("confidence"),
            }
        )

        # Check database for duplicate by cc_reference_id ONLY
        # Do NOT use fuzzy matching (date/merchant/amount) because legitimate separate
        # transactions can have identical details (e.g., 2 plane tickets on same day)
        db_found = None

        # Check by cc_reference_id column - this is the ONLY reliable duplicate detection
        if cc_reference_id:
            # Strip quotes that might be in the CSV (Amex wraps in single quotes)
            cc_ref_clean = str(cc_reference_id).strip().strip("'\"")
            db_found = db.get_transaction_by_cc_reference(cc_ref_clean)
            if db_found:
                LOG.info(
                    "Found existing transaction by cc_reference_id in DB: %s (SW ID: %s)",
                    cc_ref_clean,
                    db_found.splitwise_id,
                )

        if db_found:
            entry["status"] = "db_exists"
            entry["db_id"] = db_found.id
            entry["splitwise_id"] = db_found.splitwise_id
            results.append(entry)
            continue

        # check remote (only if not dry_run and client exists)
        remote_found = None
        if client:
            try:
                remote_found = client.find_expense_by_cc_reference(
                    cc_reference_id,
                    amount=amount,
                    date=date,
                    merchant=merchant,
                    use_detailed_search=True,
                    start_date=start_date,
                    end_date=end_date,
                )
            except (RuntimeError, ValueError) as e:
                LOG.warning(
                    "Error searching remote for cc_reference_id %s: %s",
                    cc_reference_id,
                    str(e),
                )
                remote_found = None

        # If found in remote, skip adding to Splitwise
        if remote_found:
            entry["status"] = "remote_exists"
            entry["splitwise_id"] = remote_found.get(
                "id"
            )  # Use splitwise_id for consistency
            entry["remote_id"] = remote_found.get(
                "id"
            )  # Keep remote_id for backward compatibility
            LOG.info(
                "Found existing Splitwise expense for txn %s -> id %s",
                cc_reference_id,
                remote_found.get("id"),
            )
            results.append(entry)
            continue

        # create expense (unless dry_run)
        if dry_run:
            entry["status"] = "would_add"
            results.append(entry)
            continue

        # Skip creating expense for refunds/credits here - they'll be handled by refund processor
        is_credit = entry.get("is_credit", False)
        if is_credit:
            entry["status"] = "added"
            entry["splitwise_id"] = None  # Will be set by refund processor

            # Save to database
            txn = Transaction(
                date=date,
                merchant=merchant,
                amount=-float(amount),  # Store as negative for refunds
                source="amex",  # TODO: Make this configurable based on statement source
                imported_at=now_iso(),
                cc_reference_id=cc_reference_id,
                notes=f"cc_reference_id: {cc_reference_id}",
                description=desc_clean,
                is_refund=True,
                category_id=entry.get("category_id"),
                subcategory_id=entry.get("subcategory_id"),
            )

            txn_id = db.insert_transaction(txn)
            entry["status"] = "added"
            entry["db_id"] = txn_id
            entry["splitwise_id"] = None  # Will be set by refund processor
            LOG.info(
                "Saved CREDIT transaction to database with ID %d (pending refund processing)",
                txn_id,
            )
            results.append(entry)
            continue

        try:
            # Get current user ID
            current_user_id = client.get_current_user_id()

            # Regular expense: SELF_EXPENSE paid, user owes
            users = [
                {
                    "user_id": SplitwiseUserId.SELF_EXPENSE,
                    "paid_share": float(amount),
                    "owed_share": 0.0,
                },
                {
                    "user_id": current_user_id,
                    "paid_share": 0.0,
                    "owed_share": float(amount),
                },
            ]

            # Build transaction dict with category info
            txn_dict = {
                "date": date,
                "amount": amount,
                "description": desc_clean,  # Use clean description for Splitwise
                "merchant": merchant,
                "detail": cc_reference_id,
                "category_id": entry.get("category_id"),
                "subcategory_id": entry.get("subcategory_id"),
                "category_name": entry.get("category_name"),
                "subcategory_name": entry.get("subcategory_name"),
            }

            sid = client.add_expense_from_txn(
                txn_dict,
                cc_reference_id,
                users=users,
            )
            entry["status"] = "added"
            entry["splitwise_id"] = sid
            LOG.info(
                "Added expense to Splitwise id=%s for txn %s (%s/%s)",
                sid,
                cc_reference_id,
                category_info.get("category_name", "Unknown"),
                category_info.get("subcategory_name", "Unknown"),
            )

            # Save to database after successful Splitwise creation
            try:
                db_txn = Transaction(
                    date=date,
                    merchant=merchant,
                    description=desc_clean,
                    raw_description=desc_raw,
                    amount=amount_abs,
                    raw_amount=float(amount),  # Store original signed amount
                    statement_date=date,
                    cc_reference_id=cc_reference_id,
                    source="amex",  # TODO: Make this configurable based on statement source
                    source_file=os.path.basename(path),
                    category=entry.get("category_name"),
                    subcategory=entry.get("subcategory_name"),
                    category_id=entry.get("category_id"),
                    subcategory_id=entry.get("subcategory_id"),
                    is_refund=is_credit,
                    is_shared=True,
                    splitwise_id=sid,
                    imported_at=now_iso(),
                    notes=f"cc_reference_id: {cc_reference_id}",
                )
                db_txn_id = db.insert_transaction(db_txn)
                entry["db_id"] = db_txn_id
                LOG.info(
                    "Saved transaction to database with ID %s (Splitwise ID: %s)",
                    db_txn_id,
                    sid,
                )
            except Exception as db_error:
                LOG.warning(
                    "Failed to save transaction to database: %s (Splitwise ID: %s)",
                    str(db_error),
                    sid,
                )
                entry["db_error"] = str(db_error)

            added += 1
        except (RuntimeError, ValueError) as e:
            entry["status"] = "error"
            entry["error"] = str(e)
            LOG.exception("Failed to add txn %s: %s", cc_reference_id, str(e))
        results.append(entry)

    # Collect refund transaction IDs from this batch that need Splitwise processing
    # Include: newly added ("added") OR already in DB but not yet in Splitwise ("db_exists" with no splitwise_id)
    imported_refund_ids = [
        entry.get("db_id")
        for entry in results
        if entry.get("db_id")
        and entry.get("is_credit")
        and (
            entry.get("status") == "added"
            or (entry.get("status") == "db_exists" and not entry.get("splitwise_id"))
        )
    ]

    LOG.info(
        "Found %d refund transactions in this batch that need Splitwise processing",
        len(imported_refund_ids),
    )

    # write processed CSV (with statuses)
    out_df = pd.DataFrame(results)
    base = os.path.basename(path)
    out_path = os.path.join(PROCESSED_DIR, base + ".processed.csv")
    out_df.to_csv(out_path, index=False)
    LOG.info("Wrote processed output to %s", out_path)

    # Process refunds (match to originals and create in Splitwise if needed)
    # Only process refunds that were imported in THIS batch (not all pending refunds)
    if not dry_run and client and imported_refund_ids:
        LOG.info("=" * 60)
        LOG.info(
            "Processing %d refunds from this import batch...", len(imported_refund_ids)
        )
        LOG.info("=" * 60)

        refund_processor = RefundProcessor(db=db, client=client)

        # Process only the refunds imported in this batch
        refund_summary = {
            "total": len(imported_refund_ids),
            "created": 0,
            "errors": 0,
            "results": [],
        }

        for refund_id in imported_refund_ids:
            # Get the transaction from database
            refund_txn = db.get_transaction_by_id(refund_id)
            if not refund_txn:
                LOG.warning(
                    "Could not find refund transaction ID %s in database", refund_id
                )
                continue

            result = refund_processor.process_refund(refund_txn, dry_run=False)
            refund_summary["results"].append(result)

            if result["status"] == "created":
                refund_summary["created"] += 1
            elif result["status"] == "error":
                refund_summary["errors"] += 1

        LOG.info("Refund processing summary:")
        LOG.info("  Total refunds from this batch: %d", refund_summary["total"])
        LOG.info("  Successfully created: %d", refund_summary["created"])
        LOG.info("  Errors: %d", refund_summary["errors"])
    elif dry_run and len(imported_refund_ids) > 0:
        LOG.info("=" * 60)
        LOG.info("Refund processing (would run in live mode):")
        LOG.info(
            "  %d refunds from this batch would be processed", len(imported_refund_ids)
        )
        LOG.info("=" * 60)

    # If requested, push the processed output to Google Sheets
    if sheet_key and not no_sheet:
        try:
            # If appending, only include non-cached entries (new additions from this batch)
            sheet_df = out_df
            if append_to_sheet:
                sheet_df = out_df[out_df["status"] != "cached"].copy()
                if sheet_df.empty:
                    LOG.info("No new transactions to append to sheet (all were cached)")
                else:
                    LOG.info(
                        "Appending %d new transactions to sheet (filtered out %d cached)",
                        len(sheet_df),
                        len(out_df) - len(sheet_df),
                    )

            if not sheet_df.empty or not append_to_sheet:
                LOG.info(
                    "Pushing processed output to Google Sheets (key=%s)",
                    sheet_key,
                )
                url = write_to_sheets(
                    sheet_df,
                    worksheet_name=worksheet_name,
                    spreadsheet_key=sheet_key,
                    append=append_to_sheet,
                )
                LOG.info("Wrote processed output to sheet: %s", url)
        except (RuntimeError, ValueError) as e:
            LOG.exception(
                "Failed to write processed output to Google Sheets: %s", str(e)
            )

    return out_df


def main():
    """Main entry point for the pipeline script."""
    parser = argparse.ArgumentParser(
        description="Import credit card statements to Splitwise",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/import_statement/pipeline.py --statement data/bank_statements/amex2025.csv --dry-run
  python src/import_statement/pipeline.py --statement data/bank_statements/amex2025.csv --start-date 2025-01-01 --end-date 2025-12-31
        """,
    )
    parser.add_argument(
        "--statement",
        required=True,
        help="Path to CSV statement file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without creating expenses",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of transactions to process",
    )
    parser.add_argument(
        "--sheet-key",
        default=os.getenv("SPREADSHEET_KEY"),
        help="Google Sheets spreadsheet key for logging",
    )
    parser.add_argument(
        "--worksheet-name",
        default=os.getenv("DRY_RUN_WORKSHEET_NAME", "Statement Imports"),
        help="Worksheet name for dry-run logging",
    )
    parser.add_argument(
        "--no-sheet",
        action="store_true",
        help="Skip writing to Google Sheets",
    )
    parser.add_argument(
        "--start-date",
        help="Start date filter (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        help="End date filter (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        dest="append_to_sheet",
        help="Append to existing sheet instead of overwriting",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip first N transactions",
    )
    parser.add_argument(
        "--merchant-filter",
        help="Only process transactions containing this merchant name",
    )

    args = parser.parse_args()

    # Validate sheet_key if we're going to write to sheets
    if not args.no_sheet and not args.sheet_key:
        parser.error(
            "--sheet-key is required (or set SPREADSHEET_KEY env var) unless --no-sheet is used"
        )

    process_statement(
        args.statement,
        dry_run=args.dry_run,
        limit=args.limit,
        sheet_key=args.sheet_key,
        worksheet_name=args.worksheet_name,
        no_sheet=args.no_sheet,
        start_date=args.start_date,
        end_date=args.end_date,
        append_to_sheet=args.append_to_sheet,
        offset=args.offset,
        merchant_filter=args.merchant_filter,
    )
    return 0


if __name__ == "__main__":
    exit(main())
