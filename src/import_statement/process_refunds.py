"""Process refund transactions and create corresponding Splitwise expenses.

Refunds are created in Splitwise with their original cc_reference_id from the statement.
No matching to original transactions is performed - refunds are standalone expenses.

This module can be used in two ways:
1. Import RefundProcessor class for programmatic use
2. Run as standalone script with CLI arguments

Example usage:
    # As module
    from src.import_statement.process_refunds import RefundProcessor
    processor = RefundProcessor(db, client)
    summary = processor.process_all_pending_refunds()

    # As script
    python -m src.import_statement.process_refunds --dry-run --verbose
"""

import argparse
import uuid
from datetime import datetime
from typing import Dict, Any

from src.common.utils import LOG
from src.common.splitwise_client import SplitwiseClient
from src.database import DatabaseManager
from src.database.models import Transaction
from src.constants.splitwise import SplitwiseUserId


class RefundProcessor:
    """Handles refund detection and Splitwise creation (no matching logic)."""

    def __init__(self, db: DatabaseManager, client: SplitwiseClient = None):
        """Initialize refund processor.

        Args:
            db: DatabaseManager instance
            client: SplitwiseClient instance (optional, for dry-run mode)
        """
        self.db = db
        self.client = client

    def process_refund(
        self,
        refund_txn: Transaction,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Process a single refund transaction.

        Creates a Splitwise expense with the original cc_reference_id from the statement.
        Uses default split: SELF paid 100%, SELF_EXPENSE owes 100%.

        Args:
            refund_txn: Transaction object for the refund (is_refund=True)
            dry_run: If True, don't create Splitwise expense

        Returns:
            Result dictionary with status and details
        """
        result = {
            "refund_txn_id": refund_txn.id,
            "amount": refund_txn.amount,
            "merchant": refund_txn.merchant,
            "date": refund_txn.date,
            "cc_reference_id": refund_txn.cc_reference_id,
        }

        # Create refund with default self-owed split
        if not dry_run:
            try:
                splitwise_id = self._create_refund_in_splitwise(refund_txn)

                LOG.info(
                    "Created refund in Splitwise: ID %s for cc_ref %s",
                    splitwise_id,
                    refund_txn.cc_reference_id,
                )

                # Update refund transaction with Splitwise ID
                self.db.update_transaction(
                    refund_txn.id,
                    {
                        "splitwise_id": splitwise_id,
                        "updated_at": datetime.now().isoformat(),
                    },
                )

                result["status"] = "created"
                result["splitwise_id"] = splitwise_id

            except Exception as e:
                LOG.exception(
                    "Failed to create refund in Splitwise for txn %s: %s",
                    refund_txn.id,
                    str(e),
                )
                result["status"] = "error"
                result["error"] = str(e)
        else:
            result["status"] = "would_create"

        return result

    def _create_refund_in_splitwise(
        self,
        refund_txn: Transaction,
    ) -> int:
        """Create a refund expense in Splitwise.

        Uses a default split where:
        - SELF (current user) paid 100% (received the credit)
        - SELF_EXPENSE account owes 100% (tracks credit as owed back to self)

        Args:
            refund_txn: Refund transaction to create

        Returns:
            Splitwise expense ID of created refund
        """
        if not self.client:
            raise ValueError("SplitwiseClient required for creating refunds")

        # Get current user ID
        current_user_id = self.client.get_current_user_id()

        # Default split (changed based on user request): SELF_EXPENSE paid 100%, SELF owes 100%
        users = [
            {
                "user_id": SplitwiseUserId.SELF_EXPENSE,
                "paid_share": abs(refund_txn.amount),  # Self-account paid
                "owed_share": 0,  # Self-account doesn't owe
            },
            {
                "user_id": current_user_id,
                "paid_share": 0,  # SELF didn't pay
                "owed_share": abs(refund_txn.amount),  # SELF owes it
            },
        ]

        # Use original description from statement
        description = refund_txn.description or refund_txn.merchant

        # Use cc_reference_id if available, otherwise generate a UUID
        ref_id = refund_txn.cc_reference_id or f"CREDIT_{uuid.uuid4().hex[:16]}"

        txn_dict = {
            "date": refund_txn.date,
            "amount": abs(refund_txn.amount),
            "description": description,
            "merchant": refund_txn.merchant,
            "detail": ref_id,  # Store reference ID in detail field
            "category_id": refund_txn.category_id,
            "subcategory_id": refund_txn.subcategory_id,
            "category_name": refund_txn.category,
            "subcategory_name": refund_txn.subcategory,
        }

        # Create expense using client
        splitwise_id = self.client.add_expense_from_txn(
            txn_dict,
            cc_reference_id=ref_id,
            users=users,
        )

        return splitwise_id

    def process_all_pending_refunds(self, dry_run: bool = False) -> Dict[str, Any]:
        """Process all pending refunds that haven't been added to Splitwise yet.

        Args:
            dry_run: If True, don't create Splitwise expenses

        Returns:
            Summary of processing results
        """
        pending_refunds = self.db.get_pending_refunds()

        LOG.info("Found %d pending refunds to process", len(pending_refunds))

        summary = {
            "total": len(pending_refunds),
            "created": 0,
            "errors": 0,
            "would_create": 0,
            "results": [],
        }

        for refund in pending_refunds:
            result = self.process_refund(refund, dry_run=dry_run)
            summary["results"].append(result)

            status = result.get("status")
            if status == "created":
                summary["created"] += 1
            elif status == "error":
                summary["errors"] += 1
            elif status == "would_create":
                summary["would_create"] += 1

        LOG.info(
            "Refund processing complete: %d created, %d errors",
            summary["created"],
            summary["errors"],
        )

        return summary


def main():
    """Main entry point for standalone script execution."""
    parser = argparse.ArgumentParser(
        description="Process pending refunds and create them in Splitwise with their cc_reference_id"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be done without making changes",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Only process refunds from a specific year (e.g., 2026)",
    )

    args = parser.parse_args()

    # Initialize database and client
    db = DatabaseManager()
    client = None if args.dry_run else SplitwiseClient()

    LOG.info("=" * 60)
    LOG.info("Refund Processing Script")
    LOG.info("=" * 60)
    LOG.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    LOG.info("Time: %s", datetime.now().isoformat())
    if args.year:
        LOG.info("Year Filter: %d", args.year)
    LOG.info("=" * 60)

    # Get pending refunds count
    all_pending = db.get_pending_refunds()

    # Filter by year if specified
    if args.year:
        pending_refunds = [
            r for r in all_pending if r.date and r.date.startswith(str(args.year))
        ]
        LOG.info(
            "Found %d refunds from year %d (out of %d total)",
            len(pending_refunds),
            args.year,
            len(all_pending),
        )
    else:
        pending_refunds = all_pending
        LOG.info("Found %d pending refunds to process", len(pending_refunds))

    if not pending_refunds:
        LOG.info("No pending refunds to process")
        return

    # Show sample of pending refunds
    if args.verbose:
        LOG.info("\nPending refunds:")
        for i, refund in enumerate(pending_refunds[:5], 1):
            LOG.info(
                "  %d. ID=%s, Date=%s, Merchant=%s, Amount=$%.2f",
                i,
                refund.id,
                refund.date,
                refund.merchant,
                refund.amount,
            )
        if len(pending_refunds) > 5:
            LOG.info("  ... and %d more", len(pending_refunds) - 5)

    # Process refunds
    LOG.info("\nProcessing refunds...")
    processor = RefundProcessor(db=db, client=client)
    summary = processor.process_all_pending_refunds(dry_run=args.dry_run)

    # Print summary
    LOG.info("\n" + "=" * 60)
    LOG.info("REFUND PROCESSING SUMMARY")
    LOG.info("=" * 60)
    LOG.info("Total pending refunds: %d", summary["total"])

    if args.dry_run:
        LOG.info("Would create in Splitwise: %d", summary["would_create"])
    else:
        LOG.info("Successfully created: %d", summary["created"])

    LOG.info("Errors: %d", summary["errors"])
    LOG.info("=" * 60)

    # Show details of errors
    if summary["errors"] > 0 and args.verbose:
        LOG.info("\nErrors encountered:")
        for result in summary["results"]:
            if result.get("status") == "error":
                LOG.info(
                    "  - ID=%s, Date=%s, Merchant=%s, Amount=$%.2f",
                    result.get("refund_txn_id"),
                    result.get("date"),
                    result.get("merchant"),
                    result.get("amount"),
                )
                LOG.info("    Error: %s", result.get("error"))

    if args.dry_run:
        LOG.info("\nDry run complete - no changes were made")
    else:
        LOG.info("\nRefund processing complete")


if __name__ == "__main__":
    # Load environment variables when run as script
    from src.common.env import load_project_env

    load_project_env()

    main()
