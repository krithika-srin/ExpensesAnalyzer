"""Database manager for transaction storage and retrieval."""

import sqlite3
import os
from datetime import datetime, timezone
from functools import cache
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

from .schema import init_database
from .models import Transaction, ImportLog

# SQL query constants
DELETED_FILTER_CLAUSE = "(splitwise_deleted_at IS NULL OR splitwise_deleted_at = '')"


class DatabaseManager:
    """Manages SQLite database operations for transactions."""

    def __init__(self, db_path: str = None):
        """Initialize database manager.

        Args:
            db_path: Path to SQLite database file. Defaults to data/transactions.db
        """
        if db_path is None:
            # Default to data/transactions.db in project root
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            db_path = os.path.join(project_root, "data", "transactions.db")

        self.db_path = db_path
        self._ensure_db_exists()

    def _ensure_db_exists(self):
        """Ensure database file and directory exist, initialize schema if new."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        is_new = not os.path.exists(self.db_path)
        conn = self.get_connection()

        if is_new:
            print(f"Initializing new database at {self.db_path}")
            init_database(conn)

        conn.close()

    def get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        return conn

    @contextmanager
    def transaction(self):
        """Context manager for database transactions."""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    @staticmethod
    def _append_deleted_filter(query: str, include_deleted: bool = False) -> str:
        """Append deleted transaction filter to SQL query if needed.

        Args:
            query: Base SQL query string
            include_deleted: If False, append filter to exclude deleted transactions

        Returns:
            Query string with optional deletion filter appended
        """
        if not include_deleted:
            return f"{query} AND {DELETED_FILTER_CLAUSE}"
        return query

    # ==================== Transaction CRUD ====================

    def insert_transaction(self, txn: Transaction) -> int:
        """Insert a new transaction, return its ID.

        Args:
            txn: Transaction object to insert

        Returns:
            Database ID of inserted transaction
        """
        with self.transaction() as conn:
            cursor = conn.cursor()
            data = txn.to_dict()

            # Remove id if present (auto-increment)
            data.pop("id", None)

            columns = ", ".join(data.keys())
            placeholders = ", ".join(["?"] * len(data))
            query = f"INSERT INTO transactions ({columns}) VALUES ({placeholders})"

            cursor.execute(query, list(data.values()))
            return cursor.lastrowid

    def insert_transactions_batch(self, transactions: List[Transaction]) -> List[int]:
        """Insert multiple transactions efficiently.

        Args:
            transactions: List of Transaction objects

        Returns:
            List of inserted IDs
        """
        if not transactions:
            return []

        ids = []
        with self.transaction() as conn:
            cursor = conn.cursor()

            for txn in transactions:
                data = txn.to_dict()
                data.pop("id", None)

                columns = ", ".join(data.keys())
                placeholders = ", ".join(["?"] * len(data))
                query = f"INSERT INTO transactions ({columns}) VALUES ({placeholders})"

                cursor.execute(query, list(data.values()))
                ids.append(cursor.lastrowid)

        return ids

    def get_transaction_by_id(self, txn_id: int) -> Optional[Transaction]:
        """Retrieve transaction by ID."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return Transaction.from_row(dict(row))
        return None

    def get_transaction_by_splitwise_id(
        self, splitwise_id: int
    ) -> Optional[Transaction]:
        """Retrieve transaction by Splitwise expense ID."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM transactions WHERE splitwise_id = ?", (splitwise_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            return Transaction.from_row(dict(row))
        return None

    def update_transaction(self, txn_id: int, updates: Dict[str, Any]) -> bool:
        """Update transaction fields.

        Args:
            txn_id: Transaction ID
            updates: Dictionary of field:value pairs to update

        Returns:
            True if updated, False if not found
        """
        if not updates:
            return False

        # Always update updated_at timestamp
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()

        with self.transaction() as conn:
            cursor = conn.cursor()

            set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
            query = f"UPDATE transactions SET {set_clause} WHERE id = ?"

            cursor.execute(query, list(updates.values()) + [txn_id])
            return cursor.rowcount > 0

    def mark_written_to_sheet(self, txn_ids: List[int], year: int):
        """Mark transactions as written to Google Sheets.

        Args:
            txn_ids: List of transaction IDs
            year: Year of the sheet tab
        """
        if not txn_ids:
            return

        with self.transaction() as conn:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(txn_ids))
            query = f"""
                UPDATE transactions 
                SET written_to_sheet = 1,
                    sheet_year = ?,
                    updated_at = ?
                WHERE id IN ({placeholders})
            """
            cursor.execute(query, [year, datetime.now(timezone.utc).isoformat()] + txn_ids)

    # ==================== Queries ====================

    def get_transactions_by_date_range(
        self, start_date: str, end_date: str, include_deleted: bool = False
    ) -> List[Transaction]:
        """Get transactions within date range.

        Args:
            start_date: ISO date (YYYY-MM-DD)
            end_date: ISO date (YYYY-MM-DD)
            include_deleted: Whether to include Splitwise-deleted transactions

        Returns:
            List of Transaction objects
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM transactions WHERE date >= ? AND date <= ?"
        params = [start_date, end_date]
        query = self._append_deleted_filter(query, include_deleted)
        query += " ORDER BY date, merchant"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [Transaction.from_row(dict(row)) for row in rows]

    def get_transaction_by_cc_reference(
        self, cc_reference_id: str
    ) -> Optional[Transaction]:
        """Get transaction by credit card reference ID.

        Args:
            cc_reference_id: Credit card reference/transaction ID

        Returns:
            Transaction object if found, None otherwise
        """
        if not cc_reference_id:
            return None

        conn = self.get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM transactions WHERE cc_reference_id = ? LIMIT 1"
        cursor.execute(query, [cc_reference_id])
        row = cursor.fetchone()
        conn.close()

        return Transaction.from_row(dict(row)) if row else None

    def get_unwritten_transactions(
        self, year: Optional[int] = None
    ) -> List[Transaction]:
        """Get transactions not yet written to Google Sheets.

        Args:
            year: Optional year filter

        Returns:
            List of Transaction objects
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        query = """
            SELECT * FROM transactions
            WHERE written_to_sheet = 0
        """
        query = self._append_deleted_filter(query.strip())
        params = []

        if year:
            query += " AND strftime('%Y', date) = ?"
            params.append(str(year))

        query += " ORDER BY date, merchant"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [Transaction.from_row(dict(row)) for row in rows]

    def find_potential_duplicates(
        self,
        date: str,
        merchant: str,
        amount: float,
        tolerance_days: int = 3,
        amount_tolerance: float = 0.01,
    ) -> List[Transaction]:
        """Find potential duplicate transactions.

        Args:
            date: Transaction date
            merchant: Merchant name
            amount: Transaction amount
            tolerance_days: Days before/after to check
            amount_tolerance: Amount difference tolerance

        Returns:
            List of potential duplicate Transaction objects
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        query = """
            SELECT * FROM transactions
            WHERE merchant = ?
            AND ABS(julianday(date) - julianday(?)) <= ?
            AND ABS(amount - ?) <= ?
        """
        query = self._append_deleted_filter(query.strip())

        cursor.execute(
            query, [merchant, date, tolerance_days, amount, amount_tolerance]
        )
        rows = cursor.fetchall()
        conn.close()

        return [Transaction.from_row(dict(row)) for row in rows]

    def get_transactions_by_source(self, source: str) -> List[Transaction]:
        """Get all transactions from a specific source.

        Args:
            source: Source identifier (amex, visa, splitwise, etc.)

        Returns:
            List of Transaction objects
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM transactions WHERE source = ? ORDER BY date", (source,)
        )
        rows = cursor.fetchall()
        conn.close()

        return [Transaction.from_row(dict(row)) for row in rows]

    # ==================== Refund Matching ====================

    def find_original_for_refund(
        self,
        refund_amount: float,
        refund_date: str,
        merchant: str,
        cc_reference_id: Optional[str] = None,
        date_window_days: int = 90,
        allow_partial: bool = True,
    ) -> Optional[Transaction]:
        """Find the original transaction for a refund.

        Uses a waterfall matching strategy:
        1. cc_reference_id match (most reliable) - allows partial refunds
        2. merchant + date window + amount range (fallback)

        Args:
            refund_amount: Absolute amount of the refund
            refund_date: Date of the refund transaction
            merchant: Merchant name
            cc_reference_id: Credit card reference ID (if available)
            date_window_days: Maximum days before refund to search for original
            allow_partial: If True, match even when refund < original amount

        Returns:
            Original Transaction object if found, None otherwise
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        # Strategy 1: Match by cc_reference_id (preferred)
        # For partial refunds, refund amount must be <= original amount
        if cc_reference_id:
            if allow_partial:
                query = """
                    SELECT * FROM transactions
                    WHERE cc_reference_id = ?
                    AND is_refund = 0
                    AND amount >= ?
                """
                query = self._append_deleted_filter(query.strip())
                query += " ORDER BY date DESC LIMIT 1"
                cursor.execute(query, (cc_reference_id, refund_amount - 0.01))
            else:
                # Exact match only
                query = """
                    SELECT * FROM transactions
                    WHERE cc_reference_id = ?
                    AND is_refund = 0
                    AND ABS(amount - ?) <= 0.01
                """
                query = self._append_deleted_filter(query.strip())
                query += " ORDER BY date DESC LIMIT 1"
                cursor.execute(query, (cc_reference_id, refund_amount))

            row = cursor.fetchone()

            if row:
                conn.close()
                return Transaction.from_row(dict(row))

        # Strategy 2: Match by merchant + date window + amount range (fallback)
        # Look for transactions where original amount >= refund amount (partial refund support)
        if allow_partial:
            query = """
                SELECT * FROM transactions
                WHERE merchant = ?
                AND is_refund = 0
                AND amount >= ?
                AND date <= ?
                AND julianday(?) - julianday(date) <= ?
            """
            query = self._append_deleted_filter(query.strip())
            query += " ORDER BY date DESC, ABS(amount - ?) ASC LIMIT 1"
            cursor.execute(
                query,
                (
                    merchant,
                    refund_amount - 0.01,
                    refund_date,
                    refund_date,
                    date_window_days,
                    refund_amount,
                ),
            )
        else:
            # Exact match only
            query = """
                SELECT * FROM transactions
                WHERE merchant = ?
                AND is_refund = 0
                AND ABS(amount - ?) <= 0.01
                AND date <= ?
                AND julianday(?) - julianday(date) <= ?
            """
            query = self._append_deleted_filter(query.strip())
            query += " ORDER BY date DESC LIMIT 1"
            cursor.execute(
                query,
                (merchant, refund_amount, refund_date, refund_date, date_window_days),
            )

        row = cursor.fetchone()
        conn.close()

        if row:
            return Transaction.from_row(dict(row))

        return None

    def get_pending_refunds(self) -> List[Transaction]:
        """Get all refund transactions that haven't been added to Splitwise yet.

        Returns:
            List of pending refund Transaction objects
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        query = """
            SELECT * FROM transactions
            WHERE is_refund = 1
            AND splitwise_id IS NULL
        """
        query = self._append_deleted_filter(query.strip())
        query += " ORDER BY date"
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        return [Transaction.from_row(dict(row)) for row in rows]

    # ==================== Import Logging ====================

    def log_import(self, log: ImportLog) -> int:
        """Log an import operation.

        Args:
            log: ImportLog object

        Returns:
            Log entry ID
        """
        with self.transaction() as conn:
            cursor = conn.cursor()
            data = log.to_dict()
            data.pop("id", None)

            columns = ", ".join(data.keys())
            placeholders = ", ".join(["?"] * len(data))
            query = f"INSERT INTO import_log ({columns}) VALUES ({placeholders})"

            cursor.execute(query, list(data.values()))
            return cursor.lastrowid

    def get_import_history(self, source_type: Optional[str] = None) -> List[dict]:
        """Get import history.

        Args:
            source_type: Optional filter by source type

        Returns:
            List of import log entries as dictionaries
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        if source_type:
            cursor.execute(
                "SELECT * FROM import_log WHERE source_type = ? ORDER BY timestamp DESC",
                (source_type,),
            )
        else:
            cursor.execute("SELECT * FROM import_log ORDER BY timestamp DESC")

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    # ==================== Statistics ====================

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics.

        Returns:
            Dictionary with various stats
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        stats = {}

        # Total transactions
        cursor.execute("SELECT COUNT(*) FROM transactions")
        stats["total_transactions"] = cursor.fetchone()[0]

        # Transactions by source
        cursor.execute(
            """
            SELECT source, COUNT(*) as count 
            FROM transactions 
            GROUP BY source
        """
        )
        stats["by_source"] = {row["source"]: row["count"] for row in cursor.fetchall()}

        # Written vs unwritten
        cursor.execute(
            "SELECT written_to_sheet, COUNT(*) FROM transactions GROUP BY written_to_sheet"
        )
        written_counts = {row[0]: row[1] for row in cursor.fetchall()}
        stats["written_to_sheet"] = written_counts.get(1, 0)
        stats["not_written_to_sheet"] = written_counts.get(0, 0)

        # Splitwise integration
        cursor.execute(
            "SELECT COUNT(*) FROM transactions WHERE splitwise_id IS NOT NULL"
        )
        stats["in_splitwise"] = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM transactions WHERE splitwise_deleted_at IS NOT NULL"
        )
        stats["deleted_in_splitwise"] = cursor.fetchone()[0]

        # Date range
        cursor.execute("SELECT MIN(date), MAX(date) FROM transactions")
        min_date, max_date = cursor.fetchone()
        stats["date_range"] = {"min": min_date, "max": max_date}

        conn.close()
        return stats

    # ==================== Splitwise Sync Methods ====================

    def update_splitwise_id(self, txn_id: int, splitwise_id: int) -> bool:
        """Update transaction with Splitwise expense ID.

        Args:
            txn_id: Database transaction ID
            splitwise_id: Splitwise expense ID

        Returns:
            True if updated successfully
        """
        return self.update_transaction(
            txn_id, {"splitwise_id": splitwise_id, "is_shared": True}
        )

    def update_transaction_from_splitwise(
        self, splitwise_id: int, expense_data: Dict[str, Any]
    ) -> bool:
        """Update transaction fields based on Splitwise expense data.

        Args:
            splitwise_id: Splitwise expense ID
            expense_data: Dictionary with updated expense fields

        Returns:
            True if transaction found and updated
        """
        # Find transaction by splitwise_id
        txn = self.get_transaction_by_splitwise_id(splitwise_id)
        if not txn:
            return False

        # Build update dictionary from expense_data
        updates = {}

        if "cost" in expense_data:
            updates["amount"] = float(expense_data["cost"])

        if "description" in expense_data:
            updates["description"] = expense_data["description"]

        if "date" in expense_data:
            updates["date"] = expense_data["date"]

        if "category" in expense_data and expense_data["category"]:
            updates["category"] = expense_data["category"].get("name")
            updates["category_id"] = expense_data["category"].get("id")

        if "subcategory" in expense_data and expense_data["subcategory"]:
            updates["subcategory"] = expense_data["subcategory"].get("name")
            updates["subcategory_id"] = expense_data["subcategory"].get("id")

        # If deleted_at is set, mark as deleted
        if "deleted_at" in expense_data and expense_data["deleted_at"]:
            updates["splitwise_deleted_at"] = expense_data["deleted_at"]

        if updates:
            return self.update_transaction(txn.id, updates)

        return False

    def mark_deleted_by_splitwise_id(self, splitwise_id: int) -> bool:
        """Mark transaction as deleted in Splitwise.

        Args:
            splitwise_id: Splitwise expense ID

        Returns:
            True if transaction found and marked deleted
        """
        txn = self.get_transaction_by_splitwise_id(splitwise_id)
        if not txn:
            return False

        return self.update_transaction(
            txn.id, {"splitwise_deleted_at": datetime.now(timezone.utc).isoformat()}
        )

    def get_transactions_with_splitwise_ids(
        self, start_date: str = None, end_date: str = None
    ) -> List[Transaction]:
        """Get all transactions that have Splitwise IDs.

        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            List of Transaction objects
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM transactions WHERE splitwise_id IS NOT NULL"
        params = []

        if start_date:
            query += " AND date >= ?"
            params.append(start_date)

        if end_date:
            query += " AND date <= ?"
            params.append(end_date)

        query += " ORDER BY date"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [Transaction.from_row(dict(row)) for row in rows]

    def save_monthly_summary(
        self,
        year_month: str,
        total_spent_net: float,
        avg_transaction: float,
        transaction_count: int,
        total_paid: float,
        total_owed: float,
        cumulative_spending: float,
        mom_change: float,
        written_to_sheet: bool = False,
    ) -> None:
        """Save or update monthly summary data.

        Args:
            year_month: Month in YYYY-MM format
            total_spent_net: Net spending for the month
            avg_transaction: Average transaction amount
            transaction_count: Number of transactions
            total_paid: Total amount paid
            total_owed: Total amount owed
            cumulative_spending: Cumulative spending YTD
            mom_change: Month-over-month % change
            written_to_sheet: Whether this has been written to sheets
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        now = datetime.now(timezone.utc).isoformat()

        cursor.execute(
            """
            INSERT INTO monthly_summaries (
                year_month, total_spent_net, avg_transaction, transaction_count,
                total_paid, total_owed, cumulative_spending, mom_change,
                written_to_sheet, calculated_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(year_month) DO UPDATE SET
                total_spent_net = excluded.total_spent_net,
                avg_transaction = excluded.avg_transaction,
                transaction_count = excluded.transaction_count,
                total_paid = excluded.total_paid,
                total_owed = excluded.total_owed,
                cumulative_spending = excluded.cumulative_spending,
                mom_change = excluded.mom_change,
                written_to_sheet = excluded.written_to_sheet,
                updated_at = excluded.updated_at
            """,
            (
                year_month,
                total_spent_net,
                avg_transaction,
                transaction_count,
                total_paid,
                total_owed,
                cumulative_spending,
                mom_change,
                written_to_sheet,
                now,
                now,
            ),
        )

        conn.commit()
        conn.close()

    def get_monthly_summary(self, year_month: str) -> Optional[Dict[str, Any]]:
        """Get monthly summary for a specific month.

        Args:
            year_month: Month in YYYY-MM format

        Returns:
            Dictionary with summary data or None if not found
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM monthly_summaries WHERE year_month = ?", (year_month,)
        )
        row = cursor.fetchone()
        conn.close()

        return dict(row) if row else None

    def get_all_monthly_summaries(self, year: int = None) -> List[Dict[str, Any]]:
        """Get all monthly summaries, optionally filtered by year.

        Args:
            year: Optional year filter

        Returns:
            List of dictionaries with summary data
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        if year:
            cursor.execute(
                "SELECT * FROM monthly_summaries WHERE year_month LIKE ? ORDER BY year_month",
                (f"{year}-%",),
            )
        else:
            cursor.execute("SELECT * FROM monthly_summaries ORDER BY year_month")

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def mark_monthly_summary_written(self, year_month: str) -> None:
        """Mark a monthly summary as written to sheets.

        Args:
            year_month: Month in YYYY-MM format
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE monthly_summaries SET written_to_sheet = 1, updated_at = ? WHERE year_month = ?",
            (datetime.now(timezone.utc).isoformat(), year_month),
        )

        conn.commit()
        conn.close()


@cache
def get_database() -> DatabaseManager:
    """Get singleton DatabaseManager instance.

    Uses @cache decorator for automatic memoization - creates instance once,
    subsequent calls return the same instance. Thread-safe and simple.

    Note: Uses default database path. For custom paths, instantiate
    DatabaseManager directly.

    Returns:
        Shared DatabaseManager instance
    """
    return DatabaseManager()
