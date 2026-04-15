#!/usr/bin/env python3
"""Monthly export pipeline - Sync DB, import statement, sync again, export to sheets.

This pipeline automates the Phase 3 workflow:
1. Sync database with latest Splitwise data
2. Import CSV statement to Splitwise (optional)
3. Sync database again to capture newly created expenses
4. Export from database to Google Sheets
5. Generate budget summaries

Usage examples:
  # Full pipeline with statement import
  python src/export/monthly_export_pipeline.py --statement data/bank_statements/jan2026.csv --year 2026 --start-date 2026-01-01 --end-date 2026-01-31

  # Sync and export only (no new statement)
  python src/export/monthly_export_pipeline.py --year 2026 --sync-only

  # Dry run to preview changes
  python src/export/monthly_export_pipeline.py --statement data/bank_statements/jan2026.csv --year 2026 --dry-run
"""

import argparse
import sys
from pathlib import Path

from src.common.env import load_project_env
from src.common.utils import LOG
from src.import_statement.pipeline import main as import_main
from src.db_sync.sync_from_splitwise import sync_from_splitwise
from src.export.splitwise_export import main as export_main
from src.export.generate_summaries import main as summaries_main

# Load environment variables
load_project_env()

# Pipeline constants
PIPELINE_NAME = "Monthly Export Pipeline"
DEFAULT_WORKSHEET_TEMPLATE = "Expenses {year}"


def run_import_statement(
    statement_path: str, start_date: str, end_date: str, dry_run: bool = False
) -> bool:
    """Run statement import pipeline.

    Args:
        statement_path: Path to CSV statement file
        start_date: Start date for filtering (YYYY-MM-DD)
        end_date: End date for filtering (YYYY-MM-DD)
        dry_run: If True, preview without making changes

    Returns:
        True if successful, False otherwise
    """
    LOG.info("=" * 60)
    LOG.info("STEP 2: Import statement to Splitwise")
    LOG.info("=" * 60)

    # Build args for import pipeline
    sys.argv = [
        "pipeline.py",
        "--statement",
        statement_path,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
    ]

    if dry_run:
        sys.argv.append("--dry-run")

    result = import_main()
    if result == 0:
        LOG.info("✓ Statement import completed successfully\n")
        return True
    else:
        LOG.error("✗ Statement import failed\n")
        return False


def run_sync_database(
    year: int, dry_run: bool = False, verbose: bool = False, step_number: int = 1
) -> bool:
    """Run database sync with Splitwise.

    Args:
        year: Year to sync
        dry_run: If True, preview without making changes
        verbose: If True, show detailed output
        step_number: Step number for logging

    Returns:
        True if successful, False otherwise
    """
    LOG.info("=" * 60)
    LOG.info(f"STEP {step_number}: Sync database with Splitwise")
    LOG.info("=" * 60)

    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    stats = sync_from_splitwise(
        start_date=start_date, end_date=end_date, dry_run=dry_run, verbose=verbose
    )

    LOG.info("✓ Database sync completed successfully")
    LOG.info(
        f"  Updated: {stats['updated']}, Inserted: {stats['inserted']}, Deleted: {stats['marked_deleted']}\n"
    )
    return True


def run_export_to_sheets(
    year: int,
    worksheet_name: str = None,
    dry_run: bool = False,
    append_only: bool = False,
) -> bool:
    """Run export from database to Google Sheets.

    Args:
        year: Year to export
        worksheet_name: Name of worksheet to export to
        dry_run: If True, preview without making changes
        append_only: If True, only export unwritten transactions

    Returns:
        True if successful, False otherwise
    """
    LOG.info("=" * 60)
    LOG.info("STEP 3: Export to Google Sheets")
    LOG.info("=" * 60)

    # Default worksheet name
    if not worksheet_name:
        worksheet_name = DEFAULT_WORKSHEET_TEMPLATE.format(year=year)

    # Build args for export
    sys.argv = [
        "splitwise_export.py",
        "--source",
        "database",
        "--year",
        str(year),
        "--worksheet",
        worksheet_name,
    ]

    # Add mode flags
    if append_only:
        # Append-only mode: only export unwritten, use append
        sys.argv.append("--append-only")
    else:
        # Default: overwrite mode (full refresh)
        sys.argv.append("--overwrite")

    if dry_run:
        sys.argv.append("--dry-run")

    result = export_main()
    if result == 0:
        LOG.info("✓ Export to sheets completed successfully\n")
        return True
    else:
        LOG.error("✗ Export to sheets failed\n")
        return False


def run_generate_summaries(year: int, dry_run: bool = False) -> bool:
    """Run summary generation for budget analysis.

    Args:
        year: Year to generate summaries for
        dry_run: If True, preview without making changes

    Returns:
        True if successful, False otherwise
    """
    LOG.info("=" * 60)
    LOG.info("STEP 4: Generate Budget Summaries")
    LOG.info("=" * 60)

    # Build args for summary generation
    sys.argv = [
        "generate_summaries.py",
        "--year",
        str(year),
        "--all-time",
    ]

    if dry_run:
        sys.argv.append("--dry-run")

    result = summaries_main()
    if result == 0:
        LOG.info("✓ Summary generation completed successfully\n")
        return True
    else:
        LOG.error("✗ Summary generation failed\n")
        return False


def main():
    """Main entry point for the pipeline."""
    parser = argparse.ArgumentParser(
        description="Monthly export pipeline - Import, sync, and export to sheets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline with new statement
  python src/export/monthly_export_pipeline.py \\
    --statement data/bank_statements/jan2026.csv \\
    --year 2026 \\
    --start-date 2026-01-01 \\
    --end-date 2026-01-31
  
  # Sync and export only (no new statement)
  python src/export/monthly_export_pipeline.py --year 2026 --sync-only
  
  # Dry run to preview all changes
  python src/export/monthly_export_pipeline.py \\
    --statement data/bank_statements/jan2026.csv \\
    --year 2026 \\
    --dry-run
        """,
    )

    parser.add_argument(
        "--statement",
        help="Path to CSV statement file to import (optional)",
    )
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="Year for sync and export (e.g., 2026)",
    )
    parser.add_argument(
        "--start-date",
        help="Start date for statement import (YYYY-MM-DD). Required if --statement is provided.",
    )
    parser.add_argument(
        "--end-date",
        help="End date for statement import (YYYY-MM-DD). Required if --statement is provided.",
    )
    parser.add_argument(
        "--worksheet",
        help=f"Worksheet name for export (default: {DEFAULT_WORKSHEET_TEMPLATE})",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Skip statement import, only sync and export",
    )
    parser.add_argument(
        "--append-only",
        action="store_true",
        help="Export only unwritten transactions (tracks written_to_sheet flag)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.statement and not args.sync_only:
        if not args.start_date or not args.end_date:
            parser.error(
                "--start-date and --end-date are required when --statement is provided"
            )
        if not Path(args.statement).exists():
            parser.error(f"Statement file not found: {args.statement}")

    if args.sync_only and args.statement:
        parser.error("Cannot use --sync-only with --statement")

    # Print pipeline header
    print("\n" + "=" * 60)
    print(f"{PIPELINE_NAME}")
    print("=" * 60)
    print(f"Year: {args.year}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    if args.statement:
        print(f"Statement: {args.statement}")
        print(f"Date range: {args.start_date} to {args.end_date}")
    if args.sync_only:
        print("Mode: Sync and export only (no statement import)")
    if args.append_only:
        print("Export mode: Append-only (unwritten transactions only)")
    else:
        print("Export mode: Overwrite (full refresh)")
    print("=" * 60 + "\n")

    success_count = 0
    total_steps = (
        3 if args.sync_only else 5
    )  # sync_only: sync + export + summaries (3 steps), full: sync + import + sync + export + summaries (5 steps)

    # Step 1: Sync database (always first to ensure latest data)
    if run_sync_database(args.year, args.dry_run, args.verbose, step_number=1):
        success_count += 1
    else:
        LOG.error("Pipeline failed at database sync step")
        return 1

    # Step 2: Import statement (optional, now after sync to avoid duplicates)
    if not args.sync_only and args.statement:
        if run_import_statement(
            args.statement, args.start_date, args.end_date, args.dry_run
        ):
            success_count += 1
        else:
            LOG.error("Pipeline failed at statement import step")
            return 1

        # Step 3: Sync database again (to capture newly created expenses from import)
        if run_sync_database(args.year, args.dry_run, args.verbose, step_number=3):
            success_count += 1
        else:
            LOG.error("Pipeline failed at post-import database sync step")
            return 1
    else:
        # When sync_only, export is step 2
        pass

    # Step 4/2: Export to sheets
    if run_export_to_sheets(args.year, args.worksheet, args.dry_run, args.append_only):
        success_count += 1
    else:
        LOG.error("Pipeline failed at export step")
        return 1

    # Step 5/3: Generate budget summaries
    if run_generate_summaries(args.year, args.dry_run):
        success_count += 1
    else:
        LOG.error("Pipeline failed at summary generation step")
        return 1

    # Final summary
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"Completed {success_count}/{total_steps} steps successfully")
    if args.dry_run:
        print("(DRY RUN - No changes were made)")
    print("=" * 60 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
